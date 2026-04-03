from pathlib import Path

from src.adapters.hsh798.client import Hsh798Client
from src.core.output_sanitizer import sanitize_output_bundle
from src.core.storage import load_accounts, upsert_hsh798_account, write_snapshot_bundle

HSH798_AVAILABLE_GENE_STATUS = 99


def _summarize_devices(devices: dict) -> dict:
    payload = devices.get("data", {}) or {}
    account = payload.get("account") or {}
    favorites = payload.get("favos") or []
    return {
        "account": account,
        "device_count": len(favorites),
        "device_ids": [str(item.get("id")) for item in favorites if item.get("id") is not None],
        "device_names": [str(item.get("name")) for item in favorites if item.get("name")],
    }


def _favorite_devices(devices: dict) -> list[dict]:
    payload = devices.get("data", {}) or {}
    favorites = payload.get("favos") or []
    return favorites if isinstance(favorites, list) else []


def _to_int(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def summarize_hsh798_device_status(device_id: str, payload: dict | None, *, device_name: str | None = None) -> dict:
    payload = payload or {}
    data = payload.get("data") or {}
    device = data.get("device") or {}
    gene = device.get("gene") or {}
    gene_status = _to_int(gene.get("status"))
    available = None if gene_status is None else gene_status == HSH798_AVAILABLE_GENE_STATUS
    return {
        "device_id": device_id,
        "device_name": device_name or device.get("name"),
        "ok": Hsh798Client.response_ok(payload),
        "api_code": payload.get("api_code"),
        "http_status": payload.get("http_status"),
        "msg": payload.get("msg"),
        "available": available,
        "gene_status": gene_status,
        "raw": payload,
    }


def _build_hsh798_safe_action_result(
    *,
    action: str,
    device_id: str,
    verify_after: bool,
    force: bool,
    status_before: dict,
) -> dict:
    return {
        "command": f"hsh798-safe-{action}",
        "device_id": device_id,
        "action": action,
        "force": force,
        "verify_after": verify_after,
        "status_before": status_before,
        "executed": False,
        "success": False,
        "skipped": False,
        "skip_reason": None,
        "recommended_action": None,
        "action_response": None,
        "status_after": None,
        "verified_state_change": None,
    }


def _status_allows_action(action: str, status_before: dict) -> bool:
    available = status_before.get("available")
    if action == "start":
        return available is True
    if action == "stop":
        return available is False
    raise ValueError(f"unsupported action: {action}")


def run_hsh798_safe_action(
    *,
    token: str,
    device_id: str,
    action: str,
    verify_after: bool = True,
    force: bool = False,
) -> dict:
    with Hsh798Client(token=token) as client:
        status_before_payload = client.device_status(device_id)
        status_before = summarize_hsh798_device_status(device_id, status_before_payload)
        result = _build_hsh798_safe_action_result(
            action=action,
            device_id=device_id,
            verify_after=verify_after,
            force=force,
            status_before=status_before,
        )

        if not Hsh798Client.response_ok(status_before_payload) and not force:
            result["skipped"] = True
            result["skip_reason"] = "status_check_failed"
            result["recommended_action"] = "inspect_status"
            return result

        if not force and not _status_allows_action(action, status_before):
            result["skipped"] = True
            result["skip_reason"] = "device_not_ready_for_action" if action == "start" else "device_already_idle"
            result["recommended_action"] = "wait_or_force" if action == "start" else "no_action_needed"
            return result

        action_response = client.start_drinking(device_id) if action == "start" else client.stop_drinking(device_id)
        result["action_response"] = action_response
        result["executed"] = True
        result["success"] = Hsh798Client.response_ok(action_response)

        if verify_after:
            status_after_payload = client.device_status(device_id)
            status_after = summarize_hsh798_device_status(device_id, status_after_payload)
            result["status_after"] = status_after
            if action == "start":
                result["verified_state_change"] = status_after.get("available") is False if status_after.get("ok") else None
            else:
                result["verified_state_change"] = status_after.get("available") is True if status_after.get("ok") else None

        if not result["success"]:
            result["recommended_action"] = "inspect_action_response"
        elif result["verified_state_change"] is False:
            result["recommended_action"] = "recheck_device_status"
        else:
            result["recommended_action"] = "none"

        return result


def run_hsh798_login(
    *,
    phone: str,
    sms_code: str,
    accounts_file: str = "configs/accounts.json",
    account_index: int | None = None,
    save: bool = True,
    note: str | None = None,
) -> dict:
    with Hsh798Client() as client:
        response = client.login(phone=phone, sms_code=sms_code)

    result = {
        "phone": phone,
        "response": response,
        "valid": Hsh798Client.is_login_valid(response),
    }
    if not result["valid"]:
        return result

    auth = Hsh798Client.extract_login_auth(response)
    result["auth"] = auth

    if save:
        _, saved_index, saved_account = upsert_hsh798_account(
            Path(accounts_file),
            phone=phone,
            token=auth["token"],
            uid=auth["uid"] or None,
            eid=auth["eid"] or None,
            note=note,
            account_index=account_index,
        )
        result["saved"] = {
            "accounts_file": accounts_file,
            "account_index": saved_index,
            "phone": saved_account.phone,
            "uid": saved_account.uid,
            "eid": saved_account.eid,
        }

    return result


def run_hsh798_snapshot(
    accounts_file: str = "configs/accounts.json",
    output_dir: str = "outputs",
    *,
    include_status: bool = True,
    debug_raw: bool = False,
) -> Path:
    store = load_accounts(Path(accounts_file))
    rows = []
    for index, item in enumerate(store.hsh798):
        if not item.token:
            continue
        row = {
            "account_index": index,
            "note": item.note,
            "phone": item.phone,
            "uid": item.uid,
            "eid": item.eid,
            "last_login_at": item.last_login_at,
            "valid": False,
        }
        with Hsh798Client(token=item.token) as client:
            try:
                devices = client.device_list()
                row["devices"] = devices
                row["valid"] = Hsh798Client.is_device_list_valid(devices)
                row["summary"] = _summarize_devices(devices)
                if include_status and row["valid"]:
                    statuses = []
                    available_devices = 0
                    busy_devices = 0
                    status_errors = 0
                    for device in _favorite_devices(devices):
                        device_id = str(device.get("id") or "").strip()
                        if not device_id:
                            continue
                        status_payload = client.device_status(device_id)
                        status_summary = summarize_hsh798_device_status(
                            device_id,
                            status_payload,
                            device_name=str(device.get("name") or "").strip() or None,
                        )
                        statuses.append(status_summary)
                        if not status_summary["ok"]:
                            status_errors += 1
                        elif status_summary["available"] is True:
                            available_devices += 1
                        elif status_summary["available"] is False:
                            busy_devices += 1
                    row["device_statuses"] = statuses
                    row["summary"]["available_devices"] = available_devices
                    row["summary"]["busy_devices"] = busy_devices
                    row["summary"]["status_errors"] = status_errors
            except Exception as e:
                row["devices_error"] = str(e)
        rows.append(row)

    rows = sanitize_output_bundle(rows, debug_raw=debug_raw)
    return write_snapshot_bundle(output_dir, "hsh798_snapshot", rows)
