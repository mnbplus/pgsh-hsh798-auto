import json
import hashlib
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time

from src.adapters.pgsh.client import PgshClient
from src.core.models import PgshAccountEntry
from src.core.output_sanitizer import sanitize_output_bundle
from src.core.storage import load_accounts, upsert_pgsh_account, write_json, write_snapshot_bundle


VALID_CHANNELS = ("android_app", "alipay")
BLOCKLIKE_HTTP_STATUS = {401, 403, 429}
SCHEMA_VERSION = 1


def _response_indicates_block(response: dict) -> bool:
    http_status = _to_int(response.get("http_status"))
    if http_status in BLOCKLIKE_HTTP_STATUS:
        return True
    api_code = _to_int(response.get("api_code"))
    return api_code in BLOCKLIKE_HTTP_STATUS


DEFAULT_EXECUTE_DELAY_SECONDS = 6.0
DEFAULT_EXECUTE_DELAY_JITTER_SECONDS = 3.0
DEFAULT_EXECUTE_MAX_ATTEMPTS_PER_TASK = 3
DEFAULT_EXECUTE_MAX_SUCCESSES_PER_CHANNEL = 4
DEFAULT_PROBE_DELAY_SECONDS = 5.0
DEFAULT_PROBE_MAX_ATTEMPTS_PER_TASK = 1
DEFAULT_DAILY_CONFIRMED_WHITELIST_FILE = "configs/pgsh_task_whitelist_confirmed.json"
DEFAULT_DAILY_STATE_FILE = "configs/pgsh_runtime_state.json"
DEFAULT_DAILY_BLOCK_COOLDOWN_SECONDS = 600.0
DEFAULT_DAILY_NO_CREDIT_BACKOFF_SECONDS = 21600.0


def run_pgsh_login(
    *,
    phone: str,
    sms_code: str,
    phone_brand: str = "Xiaomi",
    accounts_file: str = "configs/accounts.json",
    account_index: int | None = None,
    save: bool = True,
    note: str | None = None,
) -> dict:
    with PgshClient(token="", phone_brand=phone_brand) as client:
        response = client.sms_login(phone=phone, verify_code=sms_code)

    login_ok = PgshClient.is_login_valid(response)
    result = {
        "phone": phone,
        "phone_brand": phone_brand,
        "response": response,
        "login_ok": login_ok,
        "valid": False,
    }
    if not login_ok:
        return result

    auth = PgshClient.extract_login_auth(response)
    result["auth"] = auth

    verify_payload = None
    verify_error = None
    try:
        with PgshClient(token=auth["token"], phone_brand=phone_brand) as client:
            verify_payload = client.user_info()
    except Exception as exc:
        verify_error = str(exc)

    if verify_payload is not None:
        result["user_info"] = verify_payload
    if verify_error is not None:
        result["verify_error"] = verify_error

    result["valid"] = bool(PgshClient.response_ok(verify_payload) and verify_payload.get("data") is not None)
    if not result["valid"]:
        return result

    user_info = verify_payload.get("data") or {}
    user_name = str(user_info.get("userName") or auth.get("user_name") or "").strip()
    result["auth"]["user_name"] = user_name

    if save:
        login_time = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        _, saved_index, saved_account = upsert_pgsh_account(
            Path(accounts_file),
            token=auth["token"],
            phone=phone,
            phone_brand=phone_brand,
            user_name=user_name or None,
            note=note,
            last_login_at=login_time,
            account_index=account_index,
        )
        result["saved"] = {
            "accounts_file": accounts_file,
            "account_index": saved_index,
            "phone": saved_account.phone,
            "phone_brand": saved_account.phone_brand,
            "user_name": saved_account.user_name,
            "last_login_at": saved_account.last_login_at,
        }

    return result


def _load_task_whitelist_payload(path: str | None = "configs/pgsh_task_whitelist.json") -> object:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8-sig"))


def load_task_whitelist(path: str = "configs/pgsh_task_whitelist.json") -> set[str]:
    raw = _load_task_whitelist_payload(path)
    if raw is None:
        return set()

    if isinstance(raw, dict):
        for key in ("task_codes", "tasks", "whitelist"):
            if isinstance(raw.get(key), list):
                raw = raw[key]
                break

    if not isinstance(raw, list):
        raise ValueError("pgsh task whitelist must be a JSON array or an object containing a task list")

    return {str(item).strip() for item in raw if str(item).strip()}


def normalize_channels(channel_mode: str) -> tuple[str, ...]:
    mode = channel_mode.strip().lower()
    if mode in {"all", "both"}:
        return VALID_CHANNELS
    if mode in VALID_CHANNELS:
        return (mode,)
    raise ValueError(f"unsupported pgsh channel mode: {channel_mode}")


def _to_int(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _planned_attempts(task: dict) -> int:
    if task.get("completedStatus") != 0:
        return 0
    daily_limit = _to_int(task.get("dailyTaskLimit"))
    completed_freq = _to_int(task.get("completedFreq")) or 0
    if daily_limit is None:
        return 1
    return max(daily_limit - completed_freq, 0)


def _task_items(payload: dict) -> list[dict]:
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return []
    items = data.get("items") or []
    return items if isinstance(items, list) else []


def _task_summary(task: dict) -> dict:
    code = str(task.get("taskCode") or "").strip()
    return {
        "taskCode": code,
        "title": task.get("title"),
        "completedStatus": task.get("completedStatus"),
        "completedFreq": task.get("completedFreq"),
        "dailyTaskLimit": task.get("dailyTaskLimit"),
        "attemptsRemaining": _planned_attempts(task),
    }


def _task_learning_snapshot(task_profiles: dict[str, dict] | None, task_code: str) -> dict:
    profile = (task_profiles or {}).get(task_code) or {}
    successes = max(_to_int(profile.get("successes")) or 0, 0)
    failures = max(_to_int(profile.get("failures")) or 0, 0)
    no_credit = max(_to_int(profile.get("no_credit")) or 0, 0)
    return {
        "successes": successes,
        "failures": failures,
        "no_credit": no_credit,
        "last_success_at": profile.get("last_success_at"),
        "last_failure_at": profile.get("last_failure_at"),
        "last_http_status": _to_int(profile.get("last_http_status")),
        "last_api_code": _to_int(profile.get("last_api_code")),
        "last_outcome": profile.get("last_outcome"),
    }


def _execute_task_priority(task_meta: dict, task_profiles: dict[str, dict] | None) -> tuple:
    learning = _task_learning_snapshot(task_profiles, task_meta["taskCode"])
    total = learning["successes"] + learning["failures"] + learning["no_credit"]
    success_rate = learning["successes"] / total if total else 0.0
    blocked_penalty = 1 if learning["last_http_status"] in BLOCKLIKE_HTTP_STATUS else 0
    unseen_penalty = 1 if learning["successes"] <= 0 else 0
    return (
        blocked_penalty,
        unseen_penalty,
        learning["no_credit"],
        -success_rate,
        learning["failures"],
        -learning["successes"],
        -int(task_meta.get("attemptsRemaining") or 0),
        task_meta["taskCode"],
    )


def _probe_task_priority(task_meta: dict, task_profiles: dict[str, dict] | None) -> tuple:
    learning = _task_learning_snapshot(task_profiles, task_meta["taskCode"])
    blocked_penalty = 1 if learning["last_http_status"] in BLOCKLIKE_HTTP_STATUS else 0
    return (
        blocked_penalty,
        learning["failures"] > 0,
        learning["no_credit"],
        learning["failures"],
        0 if learning["successes"] > 0 else 1,
        -int(task_meta.get("attemptsRemaining") or 0),
        task_meta["taskCode"],
    )


def _api_ok(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    return PgshClient.response_ok(payload)


def _task_attempt_outcome(response: dict | None) -> str:
    if not isinstance(response, dict):
        return "error"
    if not PgshClient.response_ok(response):
        return "blocked" if _response_indicates_block(response) else "api_error"
    if response.get("data") is True:
        return "success"
    return "no_credit"


def _capture_step(row: dict, key: str, fn):
    try:
        result = fn()
        row[key] = result
        return result
    except Exception as exc:
        row[f"{key}_error"] = str(exc)
        row.setdefault("errors", []).append({"step": key, "error": str(exc)})
        return None


def _snapshot_channel_tasks(client: PgshClient, channel: str) -> dict:
    payload = client.task_list(channel=channel)
    tasks = [_task_summary(item) for item in _task_items(payload)]
    pending_task_codes = [task["taskCode"] for task in tasks if task["completedStatus"] == 0 and task["taskCode"]]
    return {
        "channel": channel,
        "api_ok": _api_ok(payload),
        "api_code": payload.get("code"),
        "message": payload.get("msg"),
        "summary": {
            "api_ok": _api_ok(payload),
            "task_count": len(tasks),
            "pending_count": len(pending_task_codes),
            "planned_attempts": sum(task["attemptsRemaining"] for task in tasks),
            "task_codes": [task["taskCode"] for task in tasks if task["taskCode"]],
            "pending_task_codes": pending_task_codes,
        },
        "tasks": tasks,
        "raw": payload,
    }


def _execute_channel(
    client: PgshClient,
    channel: str,
    whitelist: set[str],
    *,
    task_profiles: dict[str, dict] | None,
    dry_run: bool,
    delay_seconds: float,
    delay_jitter_seconds: float,
    max_attempts_per_task: int | None,
    max_successful_attempts: int | None,
) -> dict:
    payload = client.task_list(channel=channel)
    tasks = _task_items(payload)
    result = {
        "channel": channel,
        "api_ok": _api_ok(payload),
        "api_code": payload.get("code"),
        "message": payload.get("msg"),
        "whitelist_size": len(whitelist),
        "tasks_total": len(tasks),
        "eligible_tasks": 0,
        "planned_attempts": 0,
        "successful_attempts": 0,
        "failed_attempts": 0,
        "no_credit_attempts": 0,
        "dry_run_attempts": 0,
        "blocked": False,
        "blocked_reason": None,
        "soft_stopped": False,
        "soft_stop_reason": None,
        "actions": [],
        "skipped": [],
        "raw": payload,
    }

    eligible_actions: list[dict] = []
    for task in tasks:
        if result["blocked"]:
            result["skipped"].append({"taskCode": None, "title": None, "reason": "channel_blocked"})
            break

        task_meta = _task_summary(task)
        code = task_meta["taskCode"]
        attempts = task_meta["attemptsRemaining"]

        if not code or code not in whitelist:
            result["skipped"].append({**task_meta, "reason": "not_whitelisted"})
            continue
        if attempts <= 0:
            result["skipped"].append({**task_meta, "reason": "no_attempts_remaining"})
            continue

        result["eligible_tasks"] += 1
        attempts_planned = attempts if max_attempts_per_task is None else min(attempts, max_attempts_per_task)
        result["planned_attempts"] += attempts_planned
        action = {
            **task_meta,
            "attempts_planned": attempts_planned,
            "attempts": [],
            "learning": _task_learning_snapshot(task_profiles, code),
        }
        eligible_actions.append(action)

        if dry_run:
            for attempt in range(1, attempts_planned + 1):
                action["attempts"].append({"attempt": attempt, "dry_run": True})
            result["dry_run_attempts"] += attempts_planned
            continue
    if dry_run:
        result["actions"] = eligible_actions
        return result

    eligible_actions.sort(key=lambda action: _execute_task_priority(action, task_profiles))
    remaining_attempts = {action["taskCode"]: action["attempts_planned"] for action in eligible_actions}
    disabled_tasks: set[str] = set()

    while not result["blocked"] and any(count > 0 for count in remaining_attempts.values()):
        if max_successful_attempts is not None and result["successful_attempts"] >= max_successful_attempts:
            result["soft_stopped"] = True
            result["soft_stop_reason"] = f"max_successful_attempts={max_successful_attempts}"
            break
        progressed = False
        for action in eligible_actions:
            if max_successful_attempts is not None and result["successful_attempts"] >= max_successful_attempts:
                result["soft_stopped"] = True
                result["soft_stop_reason"] = f"max_successful_attempts={max_successful_attempts}"
                break
            code = action["taskCode"]
            if code in disabled_tasks:
                continue
            if remaining_attempts.get(code, 0) <= 0:
                continue

            attempt_no = len(action["attempts"]) + 1
            progressed = True
            try:
                response = client.complete_task(task_code=code, channel=channel)
                outcome = _task_attempt_outcome(response)
                success = outcome == "success"
                action["attempts"].append(
                    {"attempt": attempt_no, "success": success, "outcome": outcome, "response": response}
                )
                if success:
                    result["successful_attempts"] += 1
                    remaining_attempts[code] -= 1
                    _sleep_with_jitter(delay_seconds, delay_jitter_seconds)
                    continue

                if outcome == "blocked":
                    blocked_http_status = _to_int(response.get("http_status"))
                    blocked_api_code = _to_int(response.get("api_code"))
                    result["blocked"] = True
                    result["blocked_reason"] = (
                        f"http_status={blocked_http_status}"
                        if blocked_http_status in BLOCKLIKE_HTTP_STATUS
                        else f"api_code={blocked_api_code}"
                    )
                    result["failed_attempts"] += 1
                elif outcome == "no_credit":
                    result["no_credit_attempts"] += 1
                else:
                    result["failed_attempts"] += 1
                disabled_tasks.add(code)
                remaining_attempts[code] = 0
                if result["blocked"]:
                    break
            except Exception as exc:
                action["attempts"].append({"attempt": attempt_no, "success": False, "outcome": "exception", "error": str(exc)})
                result["failed_attempts"] += 1
                disabled_tasks.add(code)
                remaining_attempts[code] = 0

        if not progressed:
            break

    result["actions"] = eligible_actions

    return result


def _probe_channel(
    client: PgshClient,
    channel: str,
    whitelist: set[str] | None,
    *,
    task_profiles: dict[str, dict] | None,
    delay_seconds: float,
    max_attempts_per_task: int,
    max_tasks: int | None,
    pending_only: bool,
    stop_on_blocked: bool,
) -> dict:
    payload = client.task_list(channel=channel)
    tasks = _task_items(payload)
    result = {
        "channel": channel,
        "api_ok": _api_ok(payload),
        "api_code": payload.get("code"),
        "message": payload.get("msg"),
        "whitelist_size": 0 if whitelist is None else len(whitelist),
        "tasks_total": len(tasks),
        "candidate_tasks": 0,
        "probed_tasks": 0,
        "planned_attempts": 0,
        "successful_attempts": 0,
        "failed_attempts": 0,
        "no_credit_attempts": 0,
        "confirmed_task_codes": [],
        "blocked": False,
        "blocked_reason": None,
        "probes": [],
        "skipped": [],
        "raw": payload,
    }

    candidates: list[tuple[dict, dict]] = []
    for task in tasks:
        task_meta = _task_summary(task)
        code = task_meta["taskCode"]

        if not code:
            result["skipped"].append({**task_meta, "reason": "missing_task_code"})
            continue
        if whitelist is not None and code not in whitelist:
            result["skipped"].append({**task_meta, "reason": "not_whitelisted"})
            continue
        if pending_only and task.get("completedStatus") != 0:
            result["skipped"].append({**task_meta, "reason": "not_pending"})
            continue
        if task_meta["attemptsRemaining"] <= 0:
            result["skipped"].append({**task_meta, "reason": "no_attempts_remaining"})
            continue

        candidates.append((task, task_meta))

    candidates.sort(key=lambda item: _probe_task_priority(item[1], task_profiles))
    if max_tasks is not None:
        candidates = candidates[:max_tasks]
    result["candidate_tasks"] = len(candidates)

    for task, task_meta in candidates:
        if result["blocked"] and stop_on_blocked:
            result["skipped"].append({**task_meta, "reason": "channel_blocked"})
            break

        attempts_planned = max(1, min(task_meta["attemptsRemaining"], max_attempts_per_task))
        probe = {
            **task_meta,
            "attempts_planned": attempts_planned,
            "attempts": [],
            "learning": _task_learning_snapshot(task_profiles, task_meta["taskCode"]),
        }
        result["probed_tasks"] += 1
        result["planned_attempts"] += attempts_planned

        for attempt in range(1, attempts_planned + 1):
            response = client.complete_task(task_code=task_meta["taskCode"], channel=channel)
            outcome = _task_attempt_outcome(response)
            success = outcome == "success"
            probe["attempts"].append({"attempt": attempt, "success": success, "outcome": outcome, "response": response})
            if success:
                result["successful_attempts"] += 1
                if task_meta["taskCode"] not in result["confirmed_task_codes"]:
                    result["confirmed_task_codes"].append(task_meta["taskCode"])
                if delay_seconds > 0:
                    time.sleep(delay_seconds)
                continue

            if outcome == "blocked":
                blocked_http_status = _to_int(response.get("http_status"))
                blocked_api_code = _to_int(response.get("api_code"))
                result["blocked"] = True
                result["blocked_reason"] = (
                    f"http_status={blocked_http_status}"
                    if blocked_http_status in BLOCKLIKE_HTTP_STATUS
                    else f"api_code={blocked_api_code}"
                )
                result["failed_attempts"] += 1
            elif outcome == "no_credit":
                result["no_credit_attempts"] += 1
            else:
                result["failed_attempts"] += 1
            break

        result["probes"].append(probe)

    return result


def _selection_mode(selected_account: PgshAccountEntry | None, selected_account_index: int | None) -> str:
    if selected_account is None:
        return "all_accounts"
    if selected_account_index is None:
        return "direct_token"
    return "account_index"


def _collect_target_accounts(
    accounts_file: str,
    *,
    selected_account: PgshAccountEntry | None,
    selected_account_index: int | None,
) -> tuple[int, int, list[tuple[int | None, PgshAccountEntry, str]]]:
    store = load_accounts(Path(accounts_file))
    configured_accounts = len(store.pgsh)
    token_ready_accounts = sum(1 for item in store.pgsh if item.token)

    if selected_account is not None:
        if not selected_account.token:
            raise ValueError("selected pgsh account has no token")
        return configured_accounts, token_ready_accounts, [
            (selected_account_index, selected_account, _selection_mode(selected_account, selected_account_index))
        ]

    targets = []
    for index, item in enumerate(store.pgsh):
        if item.token:
            targets.append((index, item, "accounts_file"))
    return configured_accounts, token_ready_accounts, targets


def _account_row_base(account_index: int | None, item: PgshAccountEntry, source: str, channels: tuple[str, ...]) -> dict:
    return {
        "account_index": account_index,
        "account_source": source,
        "note": item.note,
        "phone_brand": item.phone_brand,
        "user_name": item.user_name,
        "channels": list(channels),
        "valid": False,
        "errors": [],
    }


def _build_snapshot_row(
    client: PgshClient,
    *,
    account_index: int | None,
    item: PgshAccountEntry,
    source: str,
    channels: tuple[str, ...],
) -> dict:
    row = _account_row_base(account_index, item, source, channels)

    _capture_step(row, "warmup", client.warmup_session)
    user_info = _capture_step(row, "user_info", client.user_info)
    row["valid"] = bool(PgshClient.response_ok(user_info) and user_info.get("data") is not None)
    _capture_step(row, "balance", client.balance)
    _capture_step(row, "captcha", client.captcha_status)

    row["tasks"] = {}
    task_count = 0
    pending_count = 0
    planned_attempts = 0
    channels_ok = 0

    for channel in channels:
        try:
            channel_data = _snapshot_channel_tasks(client, channel)
            row["tasks"][channel] = channel_data
            task_count += channel_data["summary"]["task_count"]
            pending_count += channel_data["summary"]["pending_count"]
            planned_attempts += channel_data["summary"]["planned_attempts"]
            if channel_data["api_ok"]:
                channels_ok += 1
            else:
                row["errors"].append(
                    {
                        "step": f"tasks.{channel}",
                        "error": f"task_list api error: code={channel_data['api_code']} msg={channel_data.get('message')}",
                    }
                )
        except Exception as exc:
            row["tasks"][channel] = {"channel": channel, "error": str(exc)}
            row["errors"].append({"step": f"tasks.{channel}", "error": str(exc)})

    row["summary"] = {
        "channels_ok": channels_ok,
        "channels_error": len(channels) - channels_ok,
        "task_count": task_count,
        "pending_count": pending_count,
        "planned_attempts": planned_attempts,
        "error_count": len(row["errors"]),
    }
    return row


def _build_execute_row(
    client: PgshClient,
    *,
    account_index: int | None,
    item: PgshAccountEntry,
    source: str,
    channels: tuple[str, ...],
    whitelist: set[str],
    dry_run: bool,
    delay_seconds: float,
    delay_jitter_seconds: float,
    max_attempts_per_task: int | None,
    max_successful_attempts_per_channel: int | None,
    skip_checkin: bool,
    task_profiles_by_channel: dict[str, dict[str, dict]] | None,
) -> dict:
    row = _account_row_base(account_index, item, source, channels)

    _capture_step(row, "warmup", client.warmup_session)
    user_info = _capture_step(row, "user_info", client.user_info)
    row["valid"] = bool(PgshClient.response_ok(user_info) and user_info.get("data") is not None)
    _capture_step(row, "balance_before", client.balance)
    _capture_step(row, "captcha_before", client.captcha_status)
    checkin = None
    if dry_run:
        row["checkin"] = {"dry_run": True, "skipped": True}
    elif skip_checkin:
        row["checkin"] = {"skipped": True, "reason": "skip_checkin"}
    else:
        checkin = _capture_step(row, "checkin", client.checkin)

    row["execution"] = {}
    summary = {
        "channels_ok": 0,
        "channels_error": 0,
        "blocked_channels": 0,
        "eligible_tasks": 0,
        "planned_attempts": 0,
        "successful_attempts": 0,
        "failed_attempts": 0,
        "no_credit_attempts": 0,
        "dry_run_attempts": 0,
        "checkin_skipped": dry_run or skip_checkin,
        "checkin_success": bool(PgshClient.response_ok(checkin)),
        "error_count": 0,
    }

    for channel in channels:
        try:
            execution = _execute_channel(
                client,
                channel,
                whitelist,
                task_profiles=(task_profiles_by_channel or {}).get(channel),
                dry_run=dry_run,
                delay_seconds=delay_seconds,
                delay_jitter_seconds=delay_jitter_seconds,
                max_attempts_per_task=max_attempts_per_task,
                max_successful_attempts=max_successful_attempts_per_channel,
            )
            row["execution"][channel] = execution
            if execution["api_ok"]:
                summary["channels_ok"] += 1
            else:
                row["errors"].append(
                    {
                        "step": f"execution.{channel}",
                        "error": f"task_list api error: code={execution['api_code']} msg={execution.get('message')}",
                    }
                )
            summary["eligible_tasks"] += execution["eligible_tasks"]
            summary["planned_attempts"] += execution["planned_attempts"]
            summary["successful_attempts"] += execution["successful_attempts"]
            summary["failed_attempts"] += execution["failed_attempts"]
            summary["no_credit_attempts"] += execution.get("no_credit_attempts", 0)
            summary["dry_run_attempts"] += execution["dry_run_attempts"]
            summary["blocked_channels"] += 1 if execution.get("blocked") else 0
        except Exception as exc:
            row["execution"][channel] = {"channel": channel, "error": str(exc)}
            row["errors"].append({"step": f"execution.{channel}", "error": str(exc)})
            summary["channels_error"] += 1

    _capture_step(row, "balance_after", client.balance)
    _capture_step(row, "captcha_after", client.captcha_status)

    summary["channels_error"] = len(channels) - summary["channels_ok"]
    summary["error_count"] = len(row["errors"])
    row["summary"] = summary
    return row


def _build_probe_row(
    client: PgshClient,
    *,
    account_index: int | None,
    item: PgshAccountEntry,
    source: str,
    channels: tuple[str, ...],
    whitelist: set[str] | None,
    delay_seconds: float,
    max_attempts_per_task: int,
    max_tasks: int | None,
    pending_only: bool,
    stop_on_blocked: bool,
    task_profiles_by_channel: dict[str, dict[str, dict]] | None,
) -> dict:
    row = _account_row_base(account_index, item, source, channels)

    _capture_step(row, "warmup", client.warmup_session)
    user_info = _capture_step(row, "user_info", client.user_info)
    row["valid"] = bool(PgshClient.response_ok(user_info) and user_info.get("data") is not None)
    _capture_step(row, "balance_before", client.balance)
    _capture_step(row, "captcha_before", client.captcha_status)

    row["probe"] = {}
    confirmed_task_codes: set[str] = set()
    summary = {
        "channels_ok": 0,
        "channels_error": 0,
        "candidate_tasks": 0,
        "probed_tasks": 0,
        "planned_attempts": 0,
        "successful_attempts": 0,
        "failed_attempts": 0,
        "no_credit_attempts": 0,
        "blocked_channels": 0,
        "confirmed_task_codes": [],
        "error_count": 0,
    }

    for channel in channels:
        try:
            probe_data = _probe_channel(
                client,
                channel,
                whitelist,
                task_profiles=(task_profiles_by_channel or {}).get(channel),
                delay_seconds=delay_seconds,
                max_attempts_per_task=max_attempts_per_task,
                max_tasks=max_tasks,
                pending_only=pending_only,
                stop_on_blocked=stop_on_blocked,
            )
            row["probe"][channel] = probe_data
            if probe_data["api_ok"]:
                summary["channels_ok"] += 1
            else:
                row["errors"].append(
                    {
                        "step": f"probe.{channel}",
                        "error": f"task_list api error: code={probe_data['api_code']} msg={probe_data.get('message')}",
                    }
                )
            summary["candidate_tasks"] += probe_data["candidate_tasks"]
            summary["probed_tasks"] += probe_data["probed_tasks"]
            summary["planned_attempts"] += probe_data["planned_attempts"]
            summary["successful_attempts"] += probe_data["successful_attempts"]
            summary["failed_attempts"] += probe_data["failed_attempts"]
            summary["no_credit_attempts"] += probe_data.get("no_credit_attempts", 0)
            summary["blocked_channels"] += 1 if probe_data["blocked"] else 0
            confirmed_task_codes.update(probe_data["confirmed_task_codes"])
        except Exception as exc:
            row["probe"][channel] = {"channel": channel, "error": str(exc)}
            row["errors"].append({"step": f"probe.{channel}", "error": str(exc)})
            summary["channels_error"] += 1

    _capture_step(row, "balance_after", client.balance)
    _capture_step(row, "captcha_after", client.captcha_status)

    summary["channels_error"] = len(channels) - summary["channels_ok"]
    summary["confirmed_task_codes"] = sorted(confirmed_task_codes)
    summary["error_count"] = len(row["errors"])
    row["summary"] = summary
    return row


def _bundle_meta(
    *,
    command: str,
    accounts_file: str,
    channels: tuple[str, ...],
    configured_accounts: int,
    token_ready_accounts: int,
    row_count: int,
    selected_account: PgshAccountEntry | None,
    selected_account_index: int | None,
    extra: dict | None = None,
) -> dict:
    meta = {
        "command": command,
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "accounts_file": accounts_file,
        "channels": list(channels),
        "configured_accounts": configured_accounts,
        "token_ready_accounts": token_ready_accounts,
        "row_count": row_count,
        "selection_mode": _selection_mode(selected_account, selected_account_index),
        "selected_account_index": selected_account_index,
    }
    if extra:
        meta.update(extra)
    return meta


def _snapshot_bundle_summary(
    rows: list[dict],
    *,
    configured_accounts: int,
    token_ready_accounts: int,
) -> dict:
    return {
        "configured_accounts": configured_accounts,
        "token_ready_accounts": token_ready_accounts,
        "processed_accounts": len(rows),
        "valid_accounts": sum(1 for row in rows if row.get("valid")),
        "accounts_with_errors": sum(1 for row in rows if row.get("errors")),
        "task_count": sum(row.get("summary", {}).get("task_count", 0) for row in rows),
        "pending_count": sum(row.get("summary", {}).get("pending_count", 0) for row in rows),
        "planned_attempts": sum(row.get("summary", {}).get("planned_attempts", 0) for row in rows),
    }


def _execute_bundle_summary(
    rows: list[dict],
    *,
    configured_accounts: int,
    token_ready_accounts: int,
    whitelist_size: int,
    dry_run: bool,
) -> dict:
    return {
        "configured_accounts": configured_accounts,
        "token_ready_accounts": token_ready_accounts,
        "processed_accounts": len(rows),
        "valid_accounts": sum(1 for row in rows if row.get("valid")),
        "accounts_with_errors": sum(1 for row in rows if row.get("errors")),
        "blocked_channels": sum(row.get("summary", {}).get("blocked_channels", 0) for row in rows),
        "checkin_skipped_accounts": sum(1 for row in rows if row.get("summary", {}).get("checkin_skipped")),
        "checkin_success_accounts": sum(1 for row in rows if row.get("summary", {}).get("checkin_success")),
        "eligible_tasks": sum(row.get("summary", {}).get("eligible_tasks", 0) for row in rows),
        "planned_attempts": sum(row.get("summary", {}).get("planned_attempts", 0) for row in rows),
        "successful_attempts": sum(row.get("summary", {}).get("successful_attempts", 0) for row in rows),
        "failed_attempts": sum(row.get("summary", {}).get("failed_attempts", 0) for row in rows),
        "no_credit_attempts": sum(row.get("summary", {}).get("no_credit_attempts", 0) for row in rows),
        "dry_run_attempts": sum(row.get("summary", {}).get("dry_run_attempts", 0) for row in rows),
        "whitelist_size": whitelist_size,
        "dry_run": dry_run,
    }


def _probe_bundle_summary(
    rows: list[dict],
    *,
    configured_accounts: int,
    token_ready_accounts: int,
    whitelist_size: int | None,
    pending_only: bool,
    max_attempts_per_task: int,
    max_tasks: int | None,
) -> dict:
    confirmed_task_codes: set[str] = set()
    for row in rows:
        confirmed_task_codes.update(row.get("summary", {}).get("confirmed_task_codes", []))

    return {
        "configured_accounts": configured_accounts,
        "token_ready_accounts": token_ready_accounts,
        "processed_accounts": len(rows),
        "valid_accounts": sum(1 for row in rows if row.get("valid")),
        "accounts_with_errors": sum(1 for row in rows if row.get("errors")),
        "candidate_tasks": sum(row.get("summary", {}).get("candidate_tasks", 0) for row in rows),
        "probed_tasks": sum(row.get("summary", {}).get("probed_tasks", 0) for row in rows),
        "planned_attempts": sum(row.get("summary", {}).get("planned_attempts", 0) for row in rows),
        "successful_attempts": sum(row.get("summary", {}).get("successful_attempts", 0) for row in rows),
        "failed_attempts": sum(row.get("summary", {}).get("failed_attempts", 0) for row in rows),
        "no_credit_attempts": sum(row.get("summary", {}).get("no_credit_attempts", 0) for row in rows),
        "blocked_channels": sum(row.get("summary", {}).get("blocked_channels", 0) for row in rows),
        "confirmed_task_codes": sorted(confirmed_task_codes),
        "confirmed_task_count": len(confirmed_task_codes),
        "whitelist_size": whitelist_size,
        "pending_only": pending_only,
        "max_attempts_per_task": max_attempts_per_task,
        "max_tasks": max_tasks,
    }


def _probe_export_payload(rows: list[dict], channels: tuple[str, ...]) -> dict:
    by_channel = {channel: set() for channel in channels}
    for row in rows:
        probe = row.get("probe") or {}
        for channel in channels:
            channel_probe = probe.get(channel) or {}
            for code in channel_probe.get("confirmed_task_codes", []):
                if code:
                    by_channel[channel].add(str(code))

    combined = sorted({code for codes in by_channel.values() for code in codes})
    return {
        "task_codes": combined,
        "channels": {channel: sorted(codes) for channel, codes in by_channel.items()},
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }


def _extract_task_codes_from_whitelist_payload(payload: object) -> set[str]:
    if isinstance(payload, list):
        return {str(item).strip() for item in payload if str(item).strip()}
    if not isinstance(payload, dict):
        return set()

    task_codes: set[str] = set()
    for key in ("task_codes", "tasks", "whitelist"):
        value = payload.get(key)
        if isinstance(value, list):
            task_codes.update(str(item).strip() for item in value if str(item).strip())

    channels = payload.get("channels")
    if isinstance(channels, dict):
        for codes in channels.values():
            if isinstance(codes, list):
                task_codes.update(str(item).strip() for item in codes if str(item).strip())
    return task_codes


def _merge_probe_export_payload(existing_payload: object, new_payload: dict) -> dict:
    merged_codes = _extract_task_codes_from_whitelist_payload(existing_payload)
    merged_codes.update(new_payload.get("task_codes", []))

    merged_channels: dict[str, set[str]] = {}
    if isinstance(existing_payload, dict):
        existing_channels = existing_payload.get("channels")
        if isinstance(existing_channels, dict):
            for channel, codes in existing_channels.items():
                if isinstance(codes, list):
                    merged_channels[channel] = {str(item).strip() for item in codes if str(item).strip()}

    for channel, codes in (new_payload.get("channels") or {}).items():
        merged_channels.setdefault(channel, set()).update(str(item).strip() for item in codes if str(item).strip())

    return {
        "task_codes": sorted(code for code in merged_codes if code),
        "channels": {channel: sorted(code for code in codes if code) for channel, codes in sorted(merged_channels.items())},
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }


def load_pgsh_runtime_state(path: str | Path) -> tuple[dict, dict]:
    state_path = Path(path)
    if not state_path.exists():
        return {"accounts": {}}, {"state_recovered": False, "reason": None, "backup_file": None}

    raw = state_path.read_text(encoding="utf-8-sig")
    if not raw.strip():
        return _recover_pgsh_runtime_state(state_path, reason="empty_file")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return _recover_pgsh_runtime_state(state_path, reason="invalid_json")
    if not isinstance(data, dict):
        return _recover_pgsh_runtime_state(state_path, reason="invalid_top_level")
    accounts = data.get("accounts")
    if not isinstance(accounts, dict):
        return _recover_pgsh_runtime_state(state_path, reason="invalid_accounts")
    return data, {"state_recovered": False, "reason": None, "backup_file": None}


def save_pgsh_runtime_state(path: str | Path, state: dict) -> Path:
    return write_json(Path(path), state)


def _recover_pgsh_runtime_state(state_path: Path, *, reason: str) -> tuple[dict, dict]:
    backup_file = _backup_corrupt_pgsh_runtime_state(state_path)
    return {
        "accounts": {},
    }, {
        "state_recovered": True,
        "reason": reason,
        "backup_file": None if backup_file is None else str(backup_file),
    }


def _backup_corrupt_pgsh_runtime_state(state_path: Path) -> Path | None:
    if not state_path.exists():
        return None
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S_%f")
    suffix = state_path.suffix or ".json"
    backup_path = state_path.with_name(f"{state_path.stem}.corrupt.{timestamp}{suffix}")
    try:
        backup_path.write_bytes(state_path.read_bytes())
    except OSError:
        return None
    return backup_path


def _account_state_key(item: PgshAccountEntry, account_index: int | None) -> str:
    if item.phone:
        return f"phone:{item.phone}"
    if account_index is not None:
        return f"account-index:{account_index}"
    if item.token:
        digest = hashlib.sha256(item.token.encode("utf-8")).hexdigest()[:16]
        return f"token:{digest}"
    return "unknown"


def _ensure_runtime_account_state(
    state: dict,
    *,
    item: PgshAccountEntry,
    account_index: int | None,
) -> tuple[str, dict]:
    accounts = state.setdefault("accounts", {})
    key = _account_state_key(item, account_index)
    account_state = accounts.setdefault(
        key,
        {
            "account_index": account_index,
            "phone": item.phone,
            "phone_brand": item.phone_brand,
            "user_name": item.user_name,
            "channels": {},
        },
    )
    account_state["account_index"] = account_index
    account_state["phone"] = item.phone
    account_state["phone_brand"] = item.phone_brand
    account_state["user_name"] = item.user_name
    account_state.setdefault("channels", {})
    return key, account_state


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _channel_mode_from_channels(channels: tuple[str, ...]) -> str:
    if not channels:
        raise ValueError("channels must not be empty")
    if len(channels) == 2 and set(channels) == set(VALID_CHANNELS):
        return "all"
    if len(channels) == 1:
        return channels[0]
    raise ValueError(f"unsupported channel combination: {channels}")


def _filter_channels_by_cooldown(channels: tuple[str, ...], account_state: dict, now: datetime) -> tuple[tuple[str, ...], list[dict]]:
    active: list[str] = []
    deferred: list[dict] = []
    channel_states = account_state.get("channels") or {}

    for channel in channels:
        state = channel_states.get(channel) or {}
        blocked_until = _parse_iso_datetime(state.get("blocked_until"))
        if blocked_until and blocked_until > now:
            remaining_seconds = max(int((blocked_until - now).total_seconds()), 0)
            deferred.append(
                {
                    "channel": channel,
                    "blocked_until": blocked_until.isoformat(timespec="seconds"),
                    "remaining_seconds": remaining_seconds,
                    "reason": state.get("last_blocked_reason"),
                }
            )
            continue
        active.append(channel)
    return tuple(active), deferred


def _suggest_next_daily_run_time(
    deferred_channels: list[dict],
    now: datetime,
    *,
    execute_successful_attempts: int = 0,
    execute_failed_attempts: int = 0,
    execute_no_credit_attempts: int = 0,
    execute_blocked_rounds: int = 0,
    stall_probe_triggered: bool = False,
    no_credit_backoff_seconds: float = DEFAULT_DAILY_NO_CREDIT_BACKOFF_SECONDS,
) -> dict:
    if deferred_channels:
        next_times = [_parse_iso_datetime(item.get("blocked_until")) for item in deferred_channels]
        next_times = [dt for dt in next_times if dt is not None]
        if not next_times:
            return {
                "should_retry": True,
                "reason": "cooldown_present_without_timestamp",
                "suggested_not_before": now.isoformat(timespec="seconds"),
            }
        earliest = min(next_times)
        return {
            "should_retry": True,
            "reason": "channel_cooldown",
            "suggested_not_before": earliest.isoformat(timespec="seconds"),
            "wait_seconds": max(int((earliest - now).total_seconds()), 0),
        }

    if (
        stall_probe_triggered
        and execute_successful_attempts <= 0
        and execute_blocked_rounds <= 0
        and execute_no_credit_attempts > 0
        and execute_failed_attempts <= 0
    ):
        wait_seconds = max(int(no_credit_backoff_seconds), 0)
        suggested_not_before = (now + timedelta(seconds=wait_seconds)).isoformat(timespec="seconds")
        return {
            "should_retry": False,
            "reason": "no_credit_after_stall_probe",
            "suggested_not_before": suggested_not_before,
            "wait_seconds": wait_seconds,
        }

    return {
        "should_retry": True,
        "reason": "no_active_cooldown",
        "suggested_not_before": now.isoformat(timespec="seconds"),
    }


def _build_automation_summary(
    *,
    account_index: int | None,
    channels: tuple[str, ...],
    confirmed_whitelist_file: str,
    state_file: str,
    daily_files: dict | None,
    daily_summary: dict,
    next_run: dict,
) -> dict:
    deferred_channels = daily_summary.get("deferred_channels") or []
    execute_blocked_rounds = int(daily_summary.get("execute_blocked_rounds") or 0)
    execute_successful_attempts = int(daily_summary.get("execute_successful_attempts") or 0)
    execute_failed_attempts = int(daily_summary.get("execute_failed_attempts") or 0)
    execute_no_credit_attempts = int(daily_summary.get("execute_no_credit_attempts") or 0)
    should_retry = bool(next_run.get("should_retry"))

    if deferred_channels:
        status = "cooldown"
        recommended_action = "wait_until_suggested_not_before"
    elif execute_successful_attempts > 0:
        status = "progressed"
        recommended_action = "run_again_later"
    elif execute_blocked_rounds > 0:
        status = "blocked"
        recommended_action = "wait_and_retry"
    elif not should_retry and execute_no_credit_attempts > 0:
        status = "stalled"
        recommended_action = "inspect_probe_or_whitelist"
    else:
        status = "idle"
        recommended_action = "inspect_probe_or_whitelist"

    suggested_command_parts = [
        "python -m src.cli pgsh-daily",
        f"--confirmed-whitelist {confirmed_whitelist_file}",
        f"--state-file {state_file}",
    ]
    if account_index is not None:
        suggested_command_parts.append(f"--account-index {account_index}")
    suggested_command_parts.append(f"--channel {_channel_mode_from_channels(channels)}")
    suggested_command_parts.append("--no-refresh-whitelist")

    return {
        "schema_version": 1,
        "status": status,
        "recommended_action": recommended_action,
        "reason_code": next_run.get("reason"),
        "should_run_now": bool(should_retry and not deferred_channels),
        "cooldown_active": bool(deferred_channels),
        "account_index": account_index,
        "primary_channel": None if not channels else channels[0],
        "channels": list(channels),
        "confirmed_whitelist_file": confirmed_whitelist_file,
        "state_file": state_file,
        "daily_latest_file": None if not daily_files else daily_files.get("latest"),
        "daily_manifest_file": None if not daily_files else daily_files.get("manifest"),
        "checkin_success": bool(daily_summary.get("checkin_success")),
        "execute_successful_attempts": execute_successful_attempts,
        "execute_failed_attempts": execute_failed_attempts,
        "execute_no_credit_attempts": execute_no_credit_attempts,
        "execute_blocked_rounds": execute_blocked_rounds,
        "stall_probe_triggered": bool(daily_summary.get("stall_probe_triggered")),
        "deferred_channels": deferred_channels,
        "suggested_not_before": next_run.get("suggested_not_before"),
        "wait_seconds": next_run.get("wait_seconds"),
        "suggested_command": " ".join(suggested_command_parts),
    }


def _record_channel_attempts(channel_state: dict, *, attempts_payload: list[dict], now_iso: str) -> None:
    task_stats = channel_state.setdefault("task_stats", {})
    for item in attempts_payload:
        task_code = str(item.get("taskCode") or "").strip()
        if not task_code:
            continue
        stats = task_stats.setdefault(task_code, {"successes": 0, "failures": 0, "no_credit": 0})
        for attempt in item.get("attempts", []):
            outcome = attempt.get("outcome")
            response = attempt.get("response") or {}
            if response.get("http_status") is not None:
                stats["last_http_status"] = response["http_status"]
            if response.get("api_code") is not None:
                stats["last_api_code"] = response["api_code"]

            if attempt.get("success"):
                stats["successes"] = int(stats.get("successes", 0)) + 1
                stats["last_success_at"] = now_iso
                stats["last_outcome"] = "success"
                continue

            if outcome == "no_credit":
                stats["no_credit"] = int(stats.get("no_credit", 0)) + 1
                stats["last_failure_at"] = now_iso
                stats["last_outcome"] = "no_credit"
                continue

            stats["failures"] = int(stats.get("failures", 0)) + 1
            stats["last_failure_at"] = now_iso
            stats["last_outcome"] = outcome or "failure"


def _sync_runtime_state_confirmed_whitelist(
    account_state: dict,
    *,
    whitelist_file: str | None,
    channels: tuple[str, ...],
) -> None:
    payload = _load_task_whitelist_payload(whitelist_file)
    combined_codes = sorted(_extract_task_codes_from_whitelist_payload(payload))
    payload_channels = payload.get("channels") if isinstance(payload, dict) else None
    channel_states = account_state.setdefault("channels", {})

    for channel in channels:
        channel_state = channel_states.setdefault(channel, {})
        if isinstance(payload_channels, dict):
            channel_codes = payload_channels.get(channel)
            if isinstance(channel_codes, list):
                codes = sorted({str(item).strip() for item in channel_codes if str(item).strip()})
            else:
                codes = []
        else:
            codes = combined_codes
        channel_state["confirmed_task_codes"] = codes


def _update_runtime_state_from_probe(
    account_state: dict,
    probe_result: dict | None,
    *,
    blocked_cooldown_seconds: float,
    now: datetime,
) -> None:
    if not probe_result:
        return
    rows = probe_result.get("rows") or []
    now_iso = now.isoformat(timespec="seconds")
    account_state["last_probe_at"] = now_iso
    for row in rows:
        probe = row.get("probe") or {}
        for channel, channel_probe in probe.items():
            if not isinstance(channel_probe, dict):
                continue
            channel_state = account_state.setdefault("channels", {}).setdefault(channel, {})
            confirmed = set(channel_state.get("confirmed_task_codes", []))
            confirmed.update(str(code).strip() for code in channel_probe.get("confirmed_task_codes", []) if str(code).strip())
            channel_state["confirmed_task_codes"] = sorted(confirmed)
            channel_state["last_probe_at"] = now_iso
            _record_channel_attempts(channel_state, attempts_payload=channel_probe.get("probes", []), now_iso=now_iso)
            if channel_probe.get("blocked"):
                channel_state["last_blocked_at"] = now_iso
                channel_state["last_blocked_reason"] = channel_probe.get("blocked_reason")
                if blocked_cooldown_seconds > 0:
                    channel_state["blocked_until"] = (now + timedelta(seconds=blocked_cooldown_seconds)).isoformat(timespec="seconds")


def _update_runtime_state_from_execute(
    account_state: dict,
    execute_result: dict | None,
    *,
    blocked_cooldown_seconds: float,
    now: datetime,
) -> None:
    if not execute_result:
        return
    rows = execute_result.get("rows") or []
    now_iso = now.isoformat(timespec="seconds")
    account_state["last_execute_at"] = now_iso
    for row in rows:
        execution = row.get("execution") or {}
        for channel, channel_execution in execution.items():
            if not isinstance(channel_execution, dict):
                continue
            channel_state = account_state.setdefault("channels", {}).setdefault(channel, {})
            channel_state["last_execute_at"] = now_iso
            _record_channel_attempts(channel_state, attempts_payload=channel_execution.get("actions", []), now_iso=now_iso)
            if channel_execution.get("blocked"):
                channel_state["last_blocked_at"] = now_iso
                channel_state["last_blocked_reason"] = channel_execution.get("blocked_reason")
                if blocked_cooldown_seconds > 0:
                    channel_state["blocked_until"] = (now + timedelta(seconds=blocked_cooldown_seconds)).isoformat(timespec="seconds")
            else:
                channel_state["blocked_until"] = None


def _build_skipped_execute_result(
    *,
    accounts_file: str,
    channels: tuple[str, ...],
    configured_accounts: int,
    token_ready_accounts: int,
    selected_account: PgshAccountEntry,
    selected_account_index: int | None,
    whitelist_file: str,
    whitelist_size: int,
    delay_seconds: float,
    delay_jitter_seconds: float,
    max_attempts_per_task: int | None,
    deferred_channels: list[dict],
) -> dict:
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return {
        "command": "pgsh-execute",
        "files": None,
        "meta": {
            "command": "pgsh-execute",
            "schema_version": SCHEMA_VERSION,
            "generated_at": generated_at,
            "accounts_file": accounts_file,
            "channels": list(channels),
            "configured_accounts": configured_accounts,
            "token_ready_accounts": token_ready_accounts,
            "row_count": 0,
            "selection_mode": _selection_mode(selected_account, selected_account_index),
            "selected_account_index": selected_account_index,
            "whitelist_file": whitelist_file,
            "whitelist_size": whitelist_size,
            "dry_run": False,
            "delay_seconds": delay_seconds,
            "delay_jitter_seconds": delay_jitter_seconds,
            "max_attempts_per_task": max_attempts_per_task,
            "skip_checkin": True,
        },
        "summary": {
            "configured_accounts": configured_accounts,
            "token_ready_accounts": token_ready_accounts,
            "processed_accounts": 0,
            "valid_accounts": 0,
            "accounts_with_errors": 0,
            "blocked_channels": len(deferred_channels),
            "checkin_skipped_accounts": 0,
            "checkin_success_accounts": 0,
            "eligible_tasks": 0,
            "planned_attempts": 0,
            "successful_attempts": 0,
            "failed_attempts": 0,
            "dry_run_attempts": 0,
            "whitelist_size": whitelist_size,
            "dry_run": False,
            "deferred_channels": deferred_channels,
        },
        "rows": [],
    }


def _task_profiles_by_channel(account_state: dict | None, channels: tuple[str, ...]) -> dict[str, dict[str, dict]]:
    profiles: dict[str, dict[str, dict]] = {}
    channel_states = (account_state or {}).get("channels") or {}
    for channel in channels:
        task_stats = (channel_states.get(channel) or {}).get("task_stats") or {}
        if isinstance(task_stats, dict):
            profiles[channel] = task_stats
    return profiles


def _output_files(output_dir: str | Path, prefix: str, stamped_file: Path) -> dict:
    base = Path(output_dir)
    return {
        "stamped": str(stamped_file),
        "latest": str(base / f"{prefix}_latest.json"),
        "manifest": str(base / f"{prefix}_manifest.json"),
    }


def _checkin_account(client: PgshClient) -> dict:
    try:
        return client.checkin()
    except Exception as exc:
        return {"code": None, "msg": str(exc), "data": None, "error": True}


def _sleep_with_jitter(base_seconds: float, jitter_seconds: float) -> None:
    if base_seconds <= 0 and jitter_seconds <= 0:
        return
    lower = max(0.0, base_seconds - max(0.0, jitter_seconds))
    upper = max(lower, base_seconds + max(0.0, jitter_seconds))
    time.sleep(random.uniform(lower, upper))


def _execute_result_blocked(execute_result: dict) -> bool:
    summary = execute_result.get("summary") or {}
    if summary.get("blocked_channels", 0):
        return True
    rows = execute_result.get("rows") or []
    for row in rows:
        execution = row.get("execution") or {}
        for channel_result in execution.values():
            if isinstance(channel_result, dict) and channel_result.get("blocked"):
                return True
    return False


def run_pgsh_snapshot(
    accounts_file: str = "configs/accounts.json",
    output_dir: str = "outputs",
    channel_mode: str = "all",
    *,
    selected_account: PgshAccountEntry | None = None,
    selected_account_index: int | None = None,
    debug_raw: bool = False,
) -> dict:
    channels = normalize_channels(channel_mode)
    configured_accounts, token_ready_accounts, targets = _collect_target_accounts(
        accounts_file,
        selected_account=selected_account,
        selected_account_index=selected_account_index,
    )

    rows = []
    for account_index, item, source in targets:
        with PgshClient(token=item.token, phone_brand=item.phone_brand) as client:
            rows.append(
                _build_snapshot_row(
                    client,
                    account_index=account_index,
                    item=item,
                    source=source,
                    channels=channels,
                )
            )

    bundle = {
        "meta": _bundle_meta(
            command="pgsh-snapshot",
            accounts_file=accounts_file,
            channels=channels,
            configured_accounts=configured_accounts,
            token_ready_accounts=token_ready_accounts,
            row_count=len(rows),
            selected_account=selected_account,
            selected_account_index=selected_account_index,
        ),
        "summary": _snapshot_bundle_summary(
            rows,
            configured_accounts=configured_accounts,
            token_ready_accounts=token_ready_accounts,
        ),
        "rows": rows,
    }
    bundle["meta"]["raw_mode"] = "debug" if debug_raw else "redacted"
    bundle = sanitize_output_bundle(bundle, debug_raw=debug_raw)
    stamped_file = write_snapshot_bundle(output_dir, "pgsh_snapshot", bundle)
    return {
        "command": "pgsh-snapshot",
        "files": _output_files(output_dir, "pgsh_snapshot", stamped_file),
        "meta": bundle["meta"],
        "summary": bundle["summary"],
    }


def run_pgsh_execute(
    accounts_file: str = "configs/accounts.json",
    whitelist_file: str = "configs/pgsh_task_whitelist.json",
    output_dir: str = "outputs",
    channel_mode: str = "all",
    *,
    selected_account: PgshAccountEntry | None = None,
    selected_account_index: int | None = None,
    dry_run: bool = False,
    delay_seconds: float = DEFAULT_EXECUTE_DELAY_SECONDS,
    delay_jitter_seconds: float = DEFAULT_EXECUTE_DELAY_JITTER_SECONDS,
    max_attempts_per_task: int | None = DEFAULT_EXECUTE_MAX_ATTEMPTS_PER_TASK,
    max_successful_attempts_per_channel: int | None = DEFAULT_EXECUTE_MAX_SUCCESSES_PER_CHANNEL,
    skip_checkin: bool = False,
    include_rows: bool = False,
    task_profiles_by_channel: dict[str, dict[str, dict]] | None = None,
    debug_raw: bool = False,
) -> dict:
    channels = normalize_channels(channel_mode)
    whitelist = load_task_whitelist(whitelist_file)
    configured_accounts, token_ready_accounts, targets = _collect_target_accounts(
        accounts_file,
        selected_account=selected_account,
        selected_account_index=selected_account_index,
    )

    rows = []
    for account_index, item, source in targets:
        with PgshClient(token=item.token, phone_brand=item.phone_brand) as client:
            rows.append(
                _build_execute_row(
                    client,
                    account_index=account_index,
                    item=item,
                    source=source,
                    channels=channels,
                    whitelist=whitelist,
                    dry_run=dry_run,
                    delay_seconds=delay_seconds,
                    delay_jitter_seconds=delay_jitter_seconds,
                    max_attempts_per_task=max_attempts_per_task,
                    max_successful_attempts_per_channel=max_successful_attempts_per_channel,
                    skip_checkin=skip_checkin,
                    task_profiles_by_channel=task_profiles_by_channel,
                )
            )

    bundle = {
        "meta": _bundle_meta(
            command="pgsh-execute",
            accounts_file=accounts_file,
            channels=channels,
            configured_accounts=configured_accounts,
            token_ready_accounts=token_ready_accounts,
            row_count=len(rows),
            selected_account=selected_account,
            selected_account_index=selected_account_index,
            extra={
                "whitelist_file": whitelist_file,
                "whitelist_size": len(whitelist),
                "dry_run": dry_run,
                "delay_seconds": delay_seconds,
                "delay_jitter_seconds": delay_jitter_seconds,
                "max_attempts_per_task": max_attempts_per_task,
                "max_successful_attempts_per_channel": max_successful_attempts_per_channel,
                "skip_checkin": skip_checkin,
            },
        ),
        "summary": _execute_bundle_summary(
            rows,
            configured_accounts=configured_accounts,
            token_ready_accounts=token_ready_accounts,
            whitelist_size=len(whitelist),
            dry_run=dry_run,
        ),
        "rows": rows,
    }
    bundle["meta"]["raw_mode"] = "debug" if debug_raw else "redacted"
    bundle = sanitize_output_bundle(bundle, debug_raw=debug_raw)
    stamped_file = write_snapshot_bundle(output_dir, "pgsh_execute", bundle)
    result = {
        "command": "pgsh-execute",
        "files": _output_files(output_dir, "pgsh_execute", stamped_file),
        "meta": bundle["meta"],
        "summary": bundle["summary"],
    }
    if include_rows:
        result["rows"] = bundle["rows"]
    return result


def run_pgsh_probe(
    accounts_file: str = "configs/accounts.json",
    output_dir: str = "outputs",
    channel_mode: str = "all",
    *,
    selected_account: PgshAccountEntry | None = None,
    selected_account_index: int | None = None,
    whitelist_file: str | None = None,
    delay_seconds: float = DEFAULT_PROBE_DELAY_SECONDS,
    max_attempts_per_task: int = DEFAULT_PROBE_MAX_ATTEMPTS_PER_TASK,
    max_tasks: int | None = None,
    pending_only: bool = True,
    stop_on_blocked: bool = True,
    export_whitelist_file: str | None = None,
    merge_export: bool = True,
    include_rows: bool = False,
    task_profiles_by_channel: dict[str, dict[str, dict]] | None = None,
    debug_raw: bool = False,
) -> dict:
    channels = normalize_channels(channel_mode)
    whitelist = load_task_whitelist(whitelist_file) if whitelist_file else None
    configured_accounts, token_ready_accounts, targets = _collect_target_accounts(
        accounts_file,
        selected_account=selected_account,
        selected_account_index=selected_account_index,
    )

    rows = []
    for account_index, item, source in targets:
        with PgshClient(token=item.token, phone_brand=item.phone_brand) as client:
            rows.append(
                _build_probe_row(
                    client,
                    account_index=account_index,
                    item=item,
                    source=source,
                    channels=channels,
                    whitelist=whitelist,
                    delay_seconds=delay_seconds,
                    max_attempts_per_task=max(1, max_attempts_per_task),
                    max_tasks=max_tasks,
                    pending_only=pending_only,
                    stop_on_blocked=stop_on_blocked,
                    task_profiles_by_channel=task_profiles_by_channel,
                )
            )

    bundle = {
        "meta": _bundle_meta(
            command="pgsh-probe",
            accounts_file=accounts_file,
            channels=channels,
            configured_accounts=configured_accounts,
            token_ready_accounts=token_ready_accounts,
            row_count=len(rows),
            selected_account=selected_account,
            selected_account_index=selected_account_index,
            extra={
                "whitelist_file": whitelist_file,
                "whitelist_size": None if whitelist is None else len(whitelist),
                "delay_seconds": delay_seconds,
                "max_attempts_per_task": max_attempts_per_task,
                "max_tasks": max_tasks,
                "pending_only": pending_only,
                "stop_on_blocked": stop_on_blocked,
            },
        ),
        "summary": _probe_bundle_summary(
            rows,
            configured_accounts=configured_accounts,
            token_ready_accounts=token_ready_accounts,
            whitelist_size=None if whitelist is None else len(whitelist),
            pending_only=pending_only,
            max_attempts_per_task=max_attempts_per_task,
            max_tasks=max_tasks,
        ),
        "rows": rows,
    }
    bundle["meta"]["raw_mode"] = "debug" if debug_raw else "redacted"
    bundle = sanitize_output_bundle(bundle, debug_raw=debug_raw)
    stamped_file = write_snapshot_bundle(output_dir, "pgsh_probe", bundle)

    export_file = None
    export_summary = None
    if export_whitelist_file:
        export_payload = _probe_export_payload(rows, channels)
        if export_whitelist_file == "__auto__":
            write_snapshot_bundle(output_dir, "pgsh_probe_whitelist", export_payload)
            export_file = str(Path(output_dir) / "pgsh_probe_whitelist_latest.json")
        else:
            export_path = Path(export_whitelist_file)
            merged_from_existing = False
            existing_codes_before = 0
            if merge_export and export_path.exists():
                try:
                    existing_payload = json.loads(export_path.read_text(encoding="utf-8-sig"))
                    existing_codes_before = len(_extract_task_codes_from_whitelist_payload(existing_payload))
                    export_payload = _merge_probe_export_payload(existing_payload, export_payload)
                    merged_from_existing = True
                except Exception:
                    merged_from_existing = False
            export_path = write_json(export_path, export_payload)
            export_file = str(export_path)
            export_summary = {
                "merged": merged_from_existing,
                "task_code_count": len(export_payload.get("task_codes", [])),
                "existing_task_code_count_before": existing_codes_before,
            }

    result = {
        "command": "pgsh-probe",
        "files": _output_files(output_dir, "pgsh_probe", stamped_file),
        "meta": bundle["meta"],
        "summary": bundle["summary"],
    }
    if include_rows:
        result["rows"] = bundle["rows"]
    if export_file:
        result["exported_whitelist_file"] = export_file
    if export_summary:
        result["exported_whitelist_summary"] = export_summary
    return result


def run_pgsh_daily(
    accounts_file: str = "configs/accounts.json",
    output_dir: str = "outputs",
    channel_mode: str = "all",
    *,
    selected_account: PgshAccountEntry | None = None,
    selected_account_index: int | None = None,
    confirmed_whitelist_file: str = DEFAULT_DAILY_CONFIRMED_WHITELIST_FILE,
    refresh_whitelist: bool = False,
    probe_delay_seconds: float = DEFAULT_PROBE_DELAY_SECONDS,
    probe_max_attempts_per_task: int = DEFAULT_PROBE_MAX_ATTEMPTS_PER_TASK,
    probe_max_tasks: int | None = None,
    execute_delay_seconds: float = DEFAULT_EXECUTE_DELAY_SECONDS,
    execute_delay_jitter_seconds: float = DEFAULT_EXECUTE_DELAY_JITTER_SECONDS,
    execute_max_attempts_per_task: int | None = DEFAULT_EXECUTE_MAX_ATTEMPTS_PER_TASK,
    execute_max_successful_attempts_per_channel: int | None = DEFAULT_EXECUTE_MAX_SUCCESSES_PER_CHANNEL,
    stop_on_blocked: bool = True,
    max_execute_rounds: int = 1,
    block_cooldown_seconds: float = DEFAULT_DAILY_BLOCK_COOLDOWN_SECONDS,
    no_credit_backoff_seconds: float = DEFAULT_DAILY_NO_CREDIT_BACKOFF_SECONDS,
    state_file: str = DEFAULT_DAILY_STATE_FILE,
    respect_cooldown: bool = True,
    debug_raw: bool = False,
) -> dict:
    channels = normalize_channels(channel_mode)
    selected_mode = _selection_mode(selected_account, selected_account_index)
    runtime_state, state_load = load_pgsh_runtime_state(state_file)

    daily_started_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    now = datetime.now(timezone.utc).astimezone()
    checkin_payload = None
    valid = False
    balance_before = None
    balance_after = None
    captcha_before = None
    captcha_after = None
    user_info = None
    errors: list[dict] = []

    if selected_account is None:
        raise ValueError("pgsh-daily currently requires a single selected account via --account-index or --token")
    account_state_key, account_state = _ensure_runtime_account_state(
        runtime_state,
        item=selected_account,
        account_index=selected_account_index,
    )
    _sync_runtime_state_confirmed_whitelist(
        account_state,
        whitelist_file=confirmed_whitelist_file,
        channels=channels,
    )
    task_profiles_by_channel = _task_profiles_by_channel(account_state, channels)
    active_channels, deferred_channels = (
        _filter_channels_by_cooldown(channels, account_state, now) if respect_cooldown else (channels, [])
    )

    with PgshClient(token=selected_account.token, phone_brand=selected_account.phone_brand) as client:
        try:
            client.warmup_session()
        except Exception as exc:
            errors.append({"step": "warmup", "error": str(exc)})
        try:
            user_info = client.user_info()
            valid = bool(PgshClient.response_ok(user_info) and user_info.get("data") is not None)
        except Exception as exc:
            errors.append({"step": "user_info", "error": str(exc)})
        try:
            balance_before = client.balance()
        except Exception as exc:
            errors.append({"step": "balance_before", "error": str(exc)})
        try:
            captcha_before = client.captcha_status()
        except Exception as exc:
            errors.append({"step": "captcha_before", "error": str(exc)})

        checkin_payload = _checkin_account(client)
        if checkin_payload.get("error"):
            errors.append({"step": "checkin", "error": checkin_payload.get("msg")})

        try:
            balance_after = client.balance()
        except Exception as exc:
            errors.append({"step": "balance_after", "error": str(exc)})
        try:
            captcha_after = client.captcha_status()
        except Exception as exc:
            errors.append({"step": "captcha_after", "error": str(exc)})

    probe_result = None
    stall_probe_triggered = False
    if refresh_whitelist and active_channels:
        probe_result = run_pgsh_probe(
            accounts_file=accounts_file,
            output_dir=output_dir,
            channel_mode=_channel_mode_from_channels(active_channels),
            selected_account=selected_account,
            selected_account_index=selected_account_index,
            whitelist_file=None,
            delay_seconds=probe_delay_seconds,
            max_attempts_per_task=probe_max_attempts_per_task,
            max_tasks=probe_max_tasks,
            pending_only=True,
            stop_on_blocked=stop_on_blocked,
            export_whitelist_file=confirmed_whitelist_file,
            merge_export=True,
            include_rows=True,
            task_profiles_by_channel=task_profiles_by_channel,
            debug_raw=debug_raw,
        )
        _update_runtime_state_from_probe(
            account_state,
            probe_result,
            blocked_cooldown_seconds=block_cooldown_seconds,
            now=datetime.now(timezone.utc).astimezone(),
        )
        _sync_runtime_state_confirmed_whitelist(
            account_state,
            whitelist_file=confirmed_whitelist_file,
            channels=channels,
        )
        task_profiles_by_channel = _task_profiles_by_channel(account_state, channels)
        active_channels, deferred_channels = _filter_channels_by_cooldown(
            channels,
            account_state,
            datetime.now(timezone.utc).astimezone(),
        )

    execute_rounds: list[dict] = []
    if not active_channels:
        confirmed_whitelist = load_task_whitelist(confirmed_whitelist_file)
        execute_result = _build_skipped_execute_result(
            accounts_file=accounts_file,
            channels=channels,
            configured_accounts=1,
            token_ready_accounts=1,
            selected_account=selected_account,
            selected_account_index=selected_account_index,
            whitelist_file=confirmed_whitelist_file,
            whitelist_size=len(confirmed_whitelist),
            delay_seconds=execute_delay_seconds,
            delay_jitter_seconds=execute_delay_jitter_seconds,
            max_attempts_per_task=execute_max_attempts_per_task,
            deferred_channels=deferred_channels,
        )
        execute_rounds.append(execute_result)

    for round_index in range(1, max(1, max_execute_rounds) + 1):
        if not active_channels:
            break
        execute_result = run_pgsh_execute(
            accounts_file=accounts_file,
            whitelist_file=confirmed_whitelist_file,
            output_dir=output_dir,
            channel_mode=_channel_mode_from_channels(active_channels),
            selected_account=selected_account,
            selected_account_index=selected_account_index,
            dry_run=False,
            delay_seconds=execute_delay_seconds,
            delay_jitter_seconds=execute_delay_jitter_seconds,
            max_attempts_per_task=execute_max_attempts_per_task,
            max_successful_attempts_per_channel=execute_max_successful_attempts_per_channel,
            skip_checkin=True,
            include_rows=True,
            task_profiles_by_channel=task_profiles_by_channel,
            debug_raw=debug_raw,
        )
        execute_rounds.append(execute_result)
        current_now = datetime.now(timezone.utc).astimezone()
        _update_runtime_state_from_execute(
            account_state,
            execute_result,
            blocked_cooldown_seconds=block_cooldown_seconds,
            now=current_now,
        )
        task_profiles_by_channel = _task_profiles_by_channel(account_state, channels)

        blocked = _execute_result_blocked(execute_result)
        if not blocked:
            break
        active_channels, deferred_channels = _filter_channels_by_cooldown(
            channels,
            account_state,
            current_now,
        )
        break

    execute_result = execute_rounds[-1]
    execute_aggregate = {
        "rounds": len(execute_rounds),
        "successful_attempts": sum(item["summary"].get("successful_attempts", 0) for item in execute_rounds),
        "failed_attempts": sum(item["summary"].get("failed_attempts", 0) for item in execute_rounds),
        "no_credit_attempts": sum(item["summary"].get("no_credit_attempts", 0) for item in execute_rounds),
        "blocked_rounds": sum(1 for item in execute_rounds if _execute_result_blocked(item)),
        "final_whitelist_size": execute_result["summary"].get("whitelist_size"),
        "final_dry_run": execute_result["summary"].get("dry_run"),
    }

    if (
        not refresh_whitelist
        and active_channels
        and execute_aggregate["successful_attempts"] <= 0
        and execute_aggregate["blocked_rounds"] <= 0
    ):
        stall_probe_triggered = True
        probe_result = run_pgsh_probe(
            accounts_file=accounts_file,
            output_dir=output_dir,
            channel_mode=_channel_mode_from_channels(active_channels),
            selected_account=selected_account,
            selected_account_index=selected_account_index,
            whitelist_file=None,
            delay_seconds=probe_delay_seconds,
            max_attempts_per_task=probe_max_attempts_per_task,
            max_tasks=probe_max_tasks if probe_max_tasks is not None else 3,
            pending_only=True,
            stop_on_blocked=stop_on_blocked,
            export_whitelist_file=confirmed_whitelist_file,
            merge_export=True,
            include_rows=True,
            task_profiles_by_channel=task_profiles_by_channel,
            debug_raw=debug_raw,
        )
        _update_runtime_state_from_probe(
            account_state,
            probe_result,
            blocked_cooldown_seconds=block_cooldown_seconds,
            now=datetime.now(timezone.utc).astimezone(),
        )
        _sync_runtime_state_confirmed_whitelist(
            account_state,
            whitelist_file=confirmed_whitelist_file,
            channels=channels,
        )
        task_profiles_by_channel = _task_profiles_by_channel(account_state, channels)

    latest_now = datetime.now(timezone.utc).astimezone()
    latest_active_channels, latest_deferred_channels = _filter_channels_by_cooldown(channels, account_state, latest_now)
    next_run = _suggest_next_daily_run_time(
        latest_deferred_channels,
        latest_now,
        execute_successful_attempts=execute_aggregate["successful_attempts"],
        execute_failed_attempts=execute_aggregate["failed_attempts"],
        execute_no_credit_attempts=execute_aggregate["no_credit_attempts"],
        execute_blocked_rounds=execute_aggregate["blocked_rounds"],
        stall_probe_triggered=stall_probe_triggered,
        no_credit_backoff_seconds=no_credit_backoff_seconds,
    )

    daily_summary = {
        "selection_mode": selected_mode,
        "valid": valid,
        "checkin_code": checkin_payload.get("code") if isinstance(checkin_payload, dict) else None,
        "checkin_msg": checkin_payload.get("msg") if isinstance(checkin_payload, dict) else None,
        "checkin_success": bool(PgshClient.response_ok(checkin_payload)),
        "balance_before_integral": None if balance_before is None else (balance_before.get("data") or {}).get("integral"),
        "balance_after_checkin_integral": None if balance_after is None else (balance_after.get("data") or {}).get("integral"),
        "captcha_before": None if captcha_before is None else captcha_before.get("data"),
        "captcha_after": None if captcha_after is None else captcha_after.get("data"),
        "active_channels_after_run": list(latest_active_channels),
        "deferred_channels": latest_deferred_channels,
        "probe_confirmed_task_count": 0 if probe_result is None else probe_result["summary"].get("confirmed_task_count"),
        "execute_rounds": execute_aggregate["rounds"],
        "execute_successful_attempts": execute_aggregate["successful_attempts"],
        "execute_failed_attempts": execute_aggregate["failed_attempts"],
        "execute_no_credit_attempts": execute_aggregate["no_credit_attempts"],
        "execute_blocked_rounds": execute_aggregate["blocked_rounds"],
        "stall_probe_triggered": stall_probe_triggered,
        "execute_checkin_skipped_accounts": execute_result["summary"].get("checkin_skipped_accounts"),
        "state_recovered": bool(state_load.get("state_recovered")),
        "errors": len(errors),
    }
    account_state["last_daily_at"] = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    account_state["last_daily_summary"] = {
        "checkin_code": daily_summary["checkin_code"],
        "checkin_success": daily_summary["checkin_success"],
        "balance_before_integral": daily_summary["balance_before_integral"],
        "balance_after_checkin_integral": daily_summary["balance_after_checkin_integral"],
        "execute_rounds": daily_summary["execute_rounds"],
        "execute_successful_attempts": daily_summary["execute_successful_attempts"],
        "execute_failed_attempts": daily_summary["execute_failed_attempts"],
        "execute_no_credit_attempts": daily_summary["execute_no_credit_attempts"],
        "execute_blocked_rounds": daily_summary["execute_blocked_rounds"],
        "stall_probe_triggered": daily_summary["stall_probe_triggered"],
        "deferred_channels": latest_deferred_channels,
        "next_run": next_run,
    }
    state_saved_to = str(save_pgsh_runtime_state(state_file, runtime_state))

    bundle = {
        "meta": {
            "command": "pgsh-daily",
            "generated_at": daily_started_at,
            "accounts_file": accounts_file,
            "channels": list(channels),
            "confirmed_whitelist_file": confirmed_whitelist_file,
            "refresh_whitelist": refresh_whitelist,
            "probe_delay_seconds": probe_delay_seconds,
            "probe_max_attempts_per_task": probe_max_attempts_per_task,
            "probe_max_tasks": probe_max_tasks,
            "execute_delay_seconds": execute_delay_seconds,
            "execute_delay_jitter_seconds": execute_delay_jitter_seconds,
            "execute_max_attempts_per_task": execute_max_attempts_per_task,
            "execute_max_successful_attempts_per_channel": execute_max_successful_attempts_per_channel,
            "max_execute_rounds": max_execute_rounds,
            "block_cooldown_seconds": block_cooldown_seconds,
            "no_credit_backoff_seconds": no_credit_backoff_seconds,
            "state_file": state_file,
            "state_recovered": bool(state_load.get("state_recovered")),
            "state_recovery_reason": state_load.get("reason"),
            "state_recovery_backup_file": state_load.get("backup_file"),
            "respect_cooldown": respect_cooldown,
            "account_state_key": account_state_key,
            "selection_mode": selected_mode,
            "selected_account_index": selected_account_index,
        },
        "summary": daily_summary,
        "next_run": next_run,
        "checkin": checkin_payload,
        "user_info": user_info,
        "probe": probe_result,
        "execute": execute_result,
        "execute_rounds": execute_rounds,
        "execute_aggregate": execute_aggregate,
        "state_saved_to": state_saved_to,
        "state_load": state_load,
        "runtime_state": runtime_state.get("accounts", {}).get(account_state_key),
        "errors": errors,
    }
    bundle["meta"]["raw_mode"] = "debug" if debug_raw else "redacted"
    bundle = sanitize_output_bundle(bundle, debug_raw=debug_raw)
    files = {
        "stamped": None,
        "latest": str(Path(output_dir) / "pgsh_daily_latest.json"),
        "manifest": str(Path(output_dir) / "pgsh_daily_manifest.json"),
    }
    automation_summary = _build_automation_summary(
        account_index=selected_account_index,
        channels=channels,
        confirmed_whitelist_file=confirmed_whitelist_file,
        state_file=state_file,
        daily_files=files,
        daily_summary=daily_summary,
        next_run=next_run,
    )
    bundle["automation_summary"] = automation_summary
    stamped_file = write_snapshot_bundle(output_dir, "pgsh_daily", bundle)
    files = _output_files(output_dir, "pgsh_daily", stamped_file)
    automation_summary["daily_latest_file"] = files.get("latest")
    automation_summary["daily_manifest_file"] = files.get("manifest")
    automation_summary["daily_stamped_file"] = files.get("stamped")
    write_json(Path(files["stamped"]), bundle)
    write_json(Path(files["latest"]), bundle)

    return {
        "command": "pgsh-daily",
        "files": files,
        "automation_summary": automation_summary,
        **bundle,
    }
