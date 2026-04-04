from pathlib import Path
import sys

import typer
from loguru import logger

from src.adapters.hsh798.client import Hsh798Client
from src.adapters.hsh798.runner import run_hsh798_login, run_hsh798_safe_action, run_hsh798_snapshot
from src.adapters.pgsh.client import PgshClient
from src.adapters.pgsh.runner import (
    DEFAULT_DAILY_BLOCK_COOLDOWN_SECONDS,
    DEFAULT_DAILY_STATE_FILE,
    DEFAULT_EXECUTE_DELAY_JITTER_SECONDS,
    DEFAULT_EXECUTE_DELAY_SECONDS,
    DEFAULT_EXECUTE_MAX_ATTEMPTS_PER_TASK,
    DEFAULT_EXECUTE_MAX_SUCCESSES_PER_CHANNEL,
    DEFAULT_PROBE_DELAY_SECONDS,
    run_pgsh_daily,
    run_pgsh_execute,
    run_pgsh_login,
    run_pgsh_probe,
    run_pgsh_snapshot,
)
from src.core.cli_support import (
    dump_account_store,
    echo_json,
    mask_secret,
    resolve_hsh798_account,
    resolve_pgsh_account,
    resolve_pgsh_batch_selection,
)
from src.core.storage import load_accounts, upsert_pgsh_account

app = typer.Typer(help="胖乖生活 / 惠生活798 研究工具")


app.info.help = "PGSH / HSH798 local automation toolkit"


@app.command()
def doctor(
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
    show_secrets: bool = typer.Option(False, "--show-secrets/--hide-secrets", help="Reveal tokens in output."),
):
    store = load_accounts(Path(accounts))
    echo_json(
        {
            "summary": {
                "pgsh_accounts": len(store.pgsh),
                "pgsh_tokens": sum(1 for item in store.pgsh if item.token),
                "hsh798_accounts": len(store.hsh798),
                "hsh798_tokens": sum(1 for item in store.hsh798 if item.token),
            },
            "accounts": dump_account_store(store, reveal_secrets=show_secrets),
        }
    )


@app.command(name="pgsh-info")
def pgsh_info(
    token: str | None = typer.Option(None, "--token", help="PGSH token."),
    account_index: int | None = typer.Option(None, "--account-index", help="Use token from configs/accounts.json."),
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
    phone_brand: str | None = typer.Option(None, "--phone-brand", help="Override phoneBrand header."),
):
    account = resolve_pgsh_account(
        token=token,
        phone_brand=phone_brand,
        accounts_file=Path(accounts),
        account_index=account_index,
    )
    with PgshClient(token=account.token, phone_brand=account.phone_brand) as client:
        echo_json(client.user_info())


@app.command(name="pgsh-valid")
def pgsh_valid(
    token: str | None = typer.Option(None, "--token", help="PGSH token."),
    account_index: int | None = typer.Option(None, "--account-index", help="Use token from configs/accounts.json."),
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
    phone_brand: str | None = typer.Option(None, "--phone-brand", help="Override phoneBrand header."),
):
    account = resolve_pgsh_account(
        token=token,
        phone_brand=phone_brand,
        accounts_file=Path(accounts),
        account_index=account_index,
    )
    with PgshClient(token=account.token, phone_brand=account.phone_brand) as client:
        echo_json({"valid": client.token_valid()})


@app.command(name="pgsh-balance")
def pgsh_balance(
    token: str | None = typer.Option(None, "--token", help="PGSH token."),
    account_index: int | None = typer.Option(None, "--account-index", help="Use token from configs/accounts.json."),
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
    phone_brand: str | None = typer.Option(None, "--phone-brand", help="Override phoneBrand header."),
):
    account = resolve_pgsh_account(
        token=token,
        phone_brand=phone_brand,
        accounts_file=Path(accounts),
        account_index=account_index,
    )
    with PgshClient(token=account.token, phone_brand=account.phone_brand) as client:
        echo_json(client.balance())


@app.command(name="pgsh-send-sms")
def pgsh_send_sms(
    phone: str = typer.Option(..., "--phone", help="Mobile number."),
    phone_brand: str = typer.Option("Xiaomi", "--phone-brand", help="phoneBrand header for android_app."),
):
    with PgshClient(token="", phone_brand=phone_brand) as client:
        echo_json(client.send_sms_code(phone=phone))


@app.command(name="pgsh-login")
def pgsh_login(
    phone: str = typer.Option(..., "--phone", help="Mobile number."),
    sms_code: str = typer.Option(..., "--sms-code", help="SMS verification code."),
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
    account_index: int | None = typer.Option(None, "--account-index", help="Overwrite or create this account slot."),
    save: bool = typer.Option(True, "--save/--no-save", help="Persist login token into configs/accounts.json."),
    phone_brand: str = typer.Option("Xiaomi", "--phone-brand", help="phoneBrand header for android_app."),
    note: str | None = typer.Option(None, "--note", help="Optional note to store for the account."),
):
    echo_json(
        run_pgsh_login(
            phone=phone,
            sms_code=sms_code,
            phone_brand=phone_brand,
            accounts_file=accounts,
            account_index=account_index,
            save=save,
            note=note,
        )
    )


@app.command(name="pgsh-tasks")
def pgsh_tasks(
    token: str | None = typer.Option(None, "--token", help="PGSH token."),
    account_index: int | None = typer.Option(None, "--account-index", help="Use token from configs/accounts.json."),
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
    phone_brand: str | None = typer.Option(None, "--phone-brand", help="Override phoneBrand header."),
    channel: str = typer.Option("android_app", "--channel", help="android_app or alipay."),
):
    account = resolve_pgsh_account(
        token=token,
        phone_brand=phone_brand,
        accounts_file=Path(accounts),
        account_index=account_index,
    )
    with PgshClient(token=account.token, phone_brand=account.phone_brand) as client:
        echo_json(client.task_list(channel=channel))


@app.command(name="pgsh-checkin")
def pgsh_checkin(
    token: str | None = typer.Option(None, "--token", help="PGSH token."),
    account_index: int | None = typer.Option(None, "--account-index", help="Use token from configs/accounts.json."),
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
    phone_brand: str | None = typer.Option(None, "--phone-brand", help="Override phoneBrand header."),
):
    account = resolve_pgsh_account(
        token=token,
        phone_brand=phone_brand,
        accounts_file=Path(accounts),
        account_index=account_index,
    )
    with PgshClient(token=account.token, phone_brand=account.phone_brand) as client:
        echo_json(client.checkin())


@app.command(name="pgsh-complete")
def pgsh_complete(
    task_code: str = typer.Option(..., "--task-code", help="PGSH task code."),
    token: str | None = typer.Option(None, "--token", help="PGSH token."),
    account_index: int | None = typer.Option(None, "--account-index", help="Use token from configs/accounts.json."),
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
    phone_brand: str | None = typer.Option(None, "--phone-brand", help="Override phoneBrand header."),
    channel: str = typer.Option("android_app", "--channel", help="android_app or alipay."),
):
    account = resolve_pgsh_account(
        token=token,
        phone_brand=phone_brand,
        accounts_file=Path(accounts),
        account_index=account_index,
    )
    with PgshClient(token=account.token, phone_brand=account.phone_brand) as client:
        echo_json(client.complete_task(task_code=task_code, channel=channel))


@app.command(name="pgsh-captcha")
def pgsh_captcha(
    token: str | None = typer.Option(None, "--token", help="PGSH token."),
    account_index: int | None = typer.Option(None, "--account-index", help="Use token from configs/accounts.json."),
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
    phone_brand: str | None = typer.Option(None, "--phone-brand", help="Override phoneBrand header."),
):
    account = resolve_pgsh_account(
        token=token,
        phone_brand=phone_brand,
        accounts_file=Path(accounts),
        account_index=account_index,
    )
    with PgshClient(token=account.token, phone_brand=account.phone_brand) as client:
        echo_json(client.captcha_status())


@app.command(name="pgsh-save-account")
def pgsh_save_account(
    token: str = typer.Option(..., "--token", help="PGSH token to persist."),
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
    account_index: int | None = typer.Option(None, "--account-index", help="Overwrite or create this account slot."),
    phone_brand: str = typer.Option("Xiaomi", "--phone-brand", help="phoneBrand header for android_app."),
    user_name: str | None = typer.Option(None, "--user-name", help="Optional display name for the account."),
    note: str | None = typer.Option(None, "--note", help="Optional note to store for the account."),
):
    _, saved_index, saved_account = upsert_pgsh_account(
        Path(accounts),
        token=token,
        phone_brand=phone_brand,
        user_name=user_name,
        note=note,
        account_index=account_index,
    )
    echo_json(
        {
            "saved": {
                "accounts_file": accounts,
                "account_index": saved_index,
                "phone": saved_account.phone,
                "token": mask_secret(saved_account.token),
                "phone_brand": saved_account.phone_brand,
                "user_name": saved_account.user_name,
                "last_login_at": saved_account.last_login_at,
                "note": saved_account.note,
            }
        }
    )


@app.command(name="pgsh-snapshot")
def pgsh_snapshot(
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
    output_dir: str = typer.Option("outputs", "--output-dir", help="Directory for snapshot files."),
    channel: str = typer.Option("all", "--channel", help="android_app, alipay, or all."),
    token: str | None = typer.Option(None, "--token", help="Run snapshot for one PGSH token only."),
    account_index: int | None = typer.Option(None, "--account-index", help="Run snapshot for one configured account."),
    phone_brand: str | None = typer.Option(None, "--phone-brand", help="Override phoneBrand header."),
    debug_raw: bool = typer.Option(False, "--debug-raw/--redact-raw", help="Include full raw API payloads in output files."),
):
    selected_account, selected_account_index = resolve_pgsh_batch_selection(
        token=token,
        phone_brand=phone_brand,
        accounts_file=Path(accounts),
        account_index=account_index,
    )
    echo_json(
        run_pgsh_snapshot(
            accounts_file=accounts,
            output_dir=output_dir,
            channel_mode=channel,
            selected_account=selected_account,
            selected_account_index=selected_account_index,
            debug_raw=debug_raw,
        )
    )


@app.command(name="pgsh-execute")
def pgsh_execute(
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
    whitelist: str = typer.Option("configs/pgsh_task_whitelist.json", "--whitelist", help="Task whitelist JSON file."),
    output_dir: str = typer.Option("outputs", "--output-dir", help="Directory for execution output files."),
    channel: str = typer.Option("all", "--channel", help="android_app, alipay, or all."),
    token: str | None = typer.Option(None, "--token", help="Run execution for one PGSH token only."),
    account_index: int | None = typer.Option(None, "--account-index", help="Run execution for one configured account."),
    phone_brand: str | None = typer.Option(None, "--phone-brand", help="Override phoneBrand header."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Plan attempts without calling task completion APIs."),
    delay_seconds: float = typer.Option(DEFAULT_EXECUTE_DELAY_SECONDS, "--delay-seconds", help="Delay between successful completion attempts."),
    delay_jitter_seconds: float = typer.Option(DEFAULT_EXECUTE_DELAY_JITTER_SECONDS, "--delay-jitter-seconds", help="Random jitter around the delay between successful attempts."),
    max_attempts_per_task: int | None = typer.Option(DEFAULT_EXECUTE_MAX_ATTEMPTS_PER_TASK, "--max-attempts-per-task", min=1, help="Cap how many times one task can be attempted in a single execution round."),
    max_successful_attempts_per_channel: int | None = typer.Option(DEFAULT_EXECUTE_MAX_SUCCESSES_PER_CHANNEL, "--max-successful-attempts-per-channel", min=1, help="Stop a channel early after this many successful attempts in one round."),
    batch_break_seconds: float = typer.Option(DEFAULT_EXECUTE_BATCH_BREAK_SECONDS, "--batch-break-seconds", help="Rest window inserted after a batch of successful high-frequency tasks such as ad/video tasks."),
    batch_break_jitter_seconds: float = typer.Option(DEFAULT_EXECUTE_BATCH_BREAK_JITTER_SECONDS, "--batch-break-jitter-seconds", help="Random jitter around the batch rest window for high-frequency tasks."),
    batch_min_attempts: int = typer.Option(DEFAULT_EXECUTE_BATCH_MIN_ATTEMPTS, "--batch-min-attempts", min=1, help="Minimum successful ad/video attempts before a batch rest may trigger."),
    batch_max_attempts: int = typer.Option(DEFAULT_EXECUTE_BATCH_MAX_ATTEMPTS, "--batch-max-attempts", min=1, help="Maximum successful ad/video attempts before a batch rest must trigger."),
    debug_raw: bool = typer.Option(False, "--debug-raw/--redact-raw", help="Include full raw API payloads in output files."),
):
    selected_account, selected_account_index = resolve_pgsh_batch_selection(
        token=token,
        phone_brand=phone_brand,
        accounts_file=Path(accounts),
        account_index=account_index,
    )
    echo_json(
        run_pgsh_execute(
            accounts_file=accounts,
            whitelist_file=whitelist,
            output_dir=output_dir,
            channel_mode=channel,
            selected_account=selected_account,
            selected_account_index=selected_account_index,
            dry_run=dry_run,
            delay_seconds=delay_seconds,
            delay_jitter_seconds=delay_jitter_seconds,
            max_attempts_per_task=max_attempts_per_task,
            max_successful_attempts_per_channel=max_successful_attempts_per_channel,
            batch_break_seconds=batch_break_seconds,
            batch_break_jitter_seconds=batch_break_jitter_seconds,
            batch_min_attempts=batch_min_attempts,
            batch_max_attempts=batch_max_attempts,
            debug_raw=debug_raw,
        )
    )


@app.command(name="pgsh-probe")
def pgsh_probe(
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
    output_dir: str = typer.Option("outputs", "--output-dir", help="Directory for probe output files."),
    channel: str = typer.Option("all", "--channel", help="android_app, alipay, or all."),
    whitelist: str | None = typer.Option(None, "--whitelist", help="Optional whitelist file to limit probed task codes."),
    token: str | None = typer.Option(None, "--token", help="Run probe for one PGSH token only."),
    account_index: int | None = typer.Option(None, "--account-index", help="Run probe for one configured account."),
    phone_brand: str | None = typer.Option(None, "--phone-brand", help="Override phoneBrand header."),
    delay_seconds: float = typer.Option(DEFAULT_PROBE_DELAY_SECONDS, "--delay-seconds", help="Delay between successful probe attempts."),
    max_attempts_per_task: int = typer.Option(1, "--max-attempts-per-task", min=1, help="Max completion calls to try per task."),
    max_tasks: int | None = typer.Option(None, "--max-tasks", min=1, help="Limit how many candidate tasks to probe per channel."),
    pending_only: bool = typer.Option(True, "--pending-only/--all-status", help="Probe only pending tasks by default."),
    stop_on_blocked: bool = typer.Option(True, "--stop-on-blocked/--keep-going", help="Stop probing a channel after an HTTP block."),
    export_whitelist: str | None = typer.Option(None, "--export-whitelist", help="Write confirmed task codes to this JSON file."),
    export_confirmed_whitelist: bool = typer.Option(False, "--export-confirmed-whitelist", help="Merge confirmed task codes into configs/pgsh_task_whitelist_confirmed.json."),
    export_whitelist_auto: bool = typer.Option(False, "--export-whitelist-auto", help="Also write a latest confirmed whitelist bundle into outputs/."),
    merge_export: bool = typer.Option(True, "--merge-export/--replace-export", help="Merge exported task codes into an existing whitelist file by default."),
    debug_raw: bool = typer.Option(False, "--debug-raw/--redact-raw", help="Include full raw API payloads in output files."),
):
    selected_account, selected_account_index = resolve_pgsh_batch_selection(
        token=token,
        phone_brand=phone_brand,
        accounts_file=Path(accounts),
        account_index=account_index,
    )
    export_target = export_whitelist
    if export_confirmed_whitelist and export_target is None:
        export_target = "configs/pgsh_task_whitelist_confirmed.json"
    if export_whitelist_auto and export_target is None:
        export_target = "__auto__"
    echo_json(
        run_pgsh_probe(
            accounts_file=accounts,
            output_dir=output_dir,
            channel_mode=channel,
            selected_account=selected_account,
            selected_account_index=selected_account_index,
            whitelist_file=whitelist,
            delay_seconds=delay_seconds,
            max_attempts_per_task=max_attempts_per_task,
            max_tasks=max_tasks,
            pending_only=pending_only,
            stop_on_blocked=stop_on_blocked,
            export_whitelist_file=export_target,
            merge_export=merge_export,
            debug_raw=debug_raw,
        )
    )


@app.command(name="pgsh-daily")
def pgsh_daily(
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
    output_dir: str = typer.Option("outputs", "--output-dir", help="Directory for daily run output files."),
    channel: str = typer.Option("all", "--channel", help="android_app, alipay, or all."),
    confirmed_whitelist: str = typer.Option("configs/pgsh_task_whitelist_confirmed.json", "--confirmed-whitelist", help="Whitelist file for tasks already confirmed as completable."),
    token: str | None = typer.Option(None, "--token", help="Run daily flow for one PGSH token only."),
    account_index: int | None = typer.Option(None, "--account-index", help="Run daily flow for one configured account."),
    phone_brand: str | None = typer.Option(None, "--phone-brand", help="Override phoneBrand header."),
    refresh_whitelist: bool = typer.Option(False, "--refresh-whitelist/--no-refresh-whitelist", help="Probe pending tasks before execution and merge newly confirmed task codes."),
    probe_delay_seconds: float = typer.Option(DEFAULT_PROBE_DELAY_SECONDS, "--probe-delay-seconds", help="Delay between successful probe attempts."),
    probe_max_attempts_per_task: int = typer.Option(1, "--probe-max-attempts-per-task", min=1, help="Max completion calls to try per task during probe."),
    probe_max_tasks: int | None = typer.Option(None, "--probe-max-tasks", min=1, help="Limit how many tasks to probe per channel."),
    execute_delay_seconds: float = typer.Option(DEFAULT_EXECUTE_DELAY_SECONDS, "--execute-delay-seconds", help="Delay between successful execution attempts."),
    execute_delay_jitter_seconds: float = typer.Option(DEFAULT_EXECUTE_DELAY_JITTER_SECONDS, "--execute-delay-jitter-seconds", help="Random jitter around the execution delay."),
    execute_max_attempts_per_task: int | None = typer.Option(DEFAULT_EXECUTE_MAX_ATTEMPTS_PER_TASK, "--execute-max-attempts-per-task", min=1, help="Cap how many times one task can be attempted in a single execution round."),
    execute_max_successful_attempts_per_channel: int | None = typer.Option(DEFAULT_EXECUTE_MAX_SUCCESSES_PER_CHANNEL, "--execute-max-successful-attempts-per-channel", min=1, help="Stop a channel early after this many successful attempts in one daily execution round."),
    execute_batch_break_seconds: float = typer.Option(DEFAULT_EXECUTE_BATCH_BREAK_SECONDS, "--execute-batch-break-seconds", help="Rest window inserted after a batch of successful ad/video tasks during execution."),
    execute_batch_break_jitter_seconds: float = typer.Option(DEFAULT_EXECUTE_BATCH_BREAK_JITTER_SECONDS, "--execute-batch-break-jitter-seconds", help="Random jitter around the execution batch rest window."),
    execute_batch_min_attempts: int = typer.Option(DEFAULT_EXECUTE_BATCH_MIN_ATTEMPTS, "--execute-batch-min-attempts", min=1, help="Minimum successful ad/video attempts before a daily execution batch rest may trigger."),
    execute_batch_max_attempts: int = typer.Option(DEFAULT_EXECUTE_BATCH_MAX_ATTEMPTS, "--execute-batch-max-attempts", min=1, help="Maximum successful ad/video attempts before a daily execution batch rest must trigger."),
    stop_on_blocked: bool = typer.Option(True, "--stop-on-blocked/--keep-going", help="Stop probing a channel after an HTTP block."),
    max_execute_rounds: int = typer.Option(1, "--max-execute-rounds", min=1, help="How many execution rounds to run before stopping."),
    block_cooldown_seconds: float = typer.Option(DEFAULT_DAILY_BLOCK_COOLDOWN_SECONDS, "--block-cooldown-seconds", help="Wait this long before retrying the next execution round after an HTTP block."),
    no_credit_backoff_seconds: float = typer.Option(DEFAULT_DAILY_NO_CREDIT_BACKOFF_SECONDS, "--no-credit-backoff-seconds", help="Backoff window after a zero-progress daily run whose auto stall probe still only returns no_credit."),
    state_file: str = typer.Option(DEFAULT_DAILY_STATE_FILE, "--state-file", help="Persistent runtime state file for cooldowns and learned task results."),
    respect_cooldown: bool = typer.Option(True, "--respect-cooldown/--ignore-cooldown", help="Skip channels still inside a persisted cooldown window."),
    debug_raw: bool = typer.Option(False, "--debug-raw/--redact-raw", help="Include full raw API payloads in output files."),
):
    selected_account, selected_account_index = resolve_pgsh_batch_selection(
        token=token,
        phone_brand=phone_brand,
        accounts_file=Path(accounts),
        account_index=account_index,
    )
    echo_json(
        run_pgsh_daily(
            accounts_file=accounts,
            output_dir=output_dir,
            channel_mode=channel,
            selected_account=selected_account,
            selected_account_index=selected_account_index,
            confirmed_whitelist_file=confirmed_whitelist,
            refresh_whitelist=refresh_whitelist,
            probe_delay_seconds=probe_delay_seconds,
            probe_max_attempts_per_task=probe_max_attempts_per_task,
            probe_max_tasks=probe_max_tasks,
            execute_delay_seconds=execute_delay_seconds,
            execute_delay_jitter_seconds=execute_delay_jitter_seconds,
            execute_max_attempts_per_task=execute_max_attempts_per_task,
            execute_max_successful_attempts_per_channel=execute_max_successful_attempts_per_channel,
            execute_batch_break_seconds=execute_batch_break_seconds,
            execute_batch_break_jitter_seconds=execute_batch_break_jitter_seconds,
            execute_batch_min_attempts=execute_batch_min_attempts,
            execute_batch_max_attempts=execute_batch_max_attempts,
            stop_on_blocked=stop_on_blocked,
            max_execute_rounds=max_execute_rounds,
            block_cooldown_seconds=block_cooldown_seconds,
            no_credit_backoff_seconds=no_credit_backoff_seconds,
            state_file=state_file,
            respect_cooldown=respect_cooldown,
            debug_raw=debug_raw,
        )
    )


@app.command(name="hsh798-captcha")
def hsh798_captcha(
    s: str = typer.Option(..., "--s", help="Captcha session parameter."),
    r: str = typer.Option(..., "--r", help="Captcha timestamp parameter."),
    out: str = typer.Option("outputs/hsh798_captcha.jpg", "--out", help="File path for captcha image."),
):
    with Hsh798Client() as client:
        data = client.get_captcha(s=s, r=r)
    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    echo_json({"output": str(path), "bytes": len(data)})


@app.command(name="hsh798-send-sms")
def hsh798_send_sms(
    s: str = typer.Option(..., "--s", help="Captcha session parameter."),
    auth_code: str = typer.Option(..., "--auth-code", help="Captcha text."),
    phone: str = typer.Option(..., "--phone", help="Mobile number."),
):
    with Hsh798Client() as client:
        echo_json(client.send_sms_code(s=s, auth_code=auth_code, phone=phone))


@app.command(name="hsh798-login")
def hsh798_login(
    phone: str = typer.Option(..., "--phone", help="Mobile number."),
    sms_code: str = typer.Option(..., "--sms-code", help="SMS verification code."),
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
    account_index: int | None = typer.Option(None, "--account-index", help="Overwrite or create this account slot."),
    save: bool = typer.Option(True, "--save/--no-save", help="Persist login token into configs/accounts.json."),
    note: str | None = typer.Option(None, "--note", help="Optional note to store for the account."),
):
    echo_json(
        run_hsh798_login(
            phone=phone,
            sms_code=sms_code,
            accounts_file=accounts,
            account_index=account_index,
            save=save,
            note=note,
        )
    )


@app.command(name="hsh798-devices")
def hsh798_devices(
    token: str | None = typer.Option(None, "--token", help="HSH798 token."),
    account_index: int | None = typer.Option(None, "--account-index", help="Use token from configs/accounts.json."),
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
):
    account = resolve_hsh798_account(token=token, accounts_file=Path(accounts), account_index=account_index)
    with Hsh798Client(token=account.token) as client:
        echo_json(client.device_list())


@app.command(name="hsh798-status")
def hsh798_status(
    device_id: str = typer.Option(..., "--device-id", help="Device ID."),
    token: str | None = typer.Option(None, "--token", help="HSH798 token."),
    account_index: int | None = typer.Option(None, "--account-index", help="Use token from configs/accounts.json."),
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
):
    account = resolve_hsh798_account(token=token, accounts_file=Path(accounts), account_index=account_index)
    with Hsh798Client(token=account.token) as client:
        echo_json(client.device_status(device_id))


@app.command(name="hsh798-favo")
def hsh798_favo(
    device_id: str = typer.Option(..., "--device-id", help="Device ID."),
    token: str | None = typer.Option(None, "--token", help="HSH798 token."),
    account_index: int | None = typer.Option(None, "--account-index", help="Use token from configs/accounts.json."),
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
    remove: bool = typer.Option(False, "--remove", help="Remove favorite instead of adding."),
):
    account = resolve_hsh798_account(token=token, accounts_file=Path(accounts), account_index=account_index)
    with Hsh798Client(token=account.token) as client:
        echo_json(client.toggle_favorite(device_id=device_id, remove=remove))


@app.command(name="hsh798-start")
def hsh798_start(
    device_id: str = typer.Option(..., "--device-id", help="Device ID."),
    token: str | None = typer.Option(None, "--token", help="HSH798 token."),
    account_index: int | None = typer.Option(None, "--account-index", help="Use token from configs/accounts.json."),
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
):
    account = resolve_hsh798_account(token=token, accounts_file=Path(accounts), account_index=account_index)
    with Hsh798Client(token=account.token) as client:
        echo_json(client.start_drinking(device_id))


@app.command(name="hsh798-stop")
def hsh798_stop(
    device_id: str = typer.Option(..., "--device-id", help="Device ID."),
    token: str | None = typer.Option(None, "--token", help="HSH798 token."),
    account_index: int | None = typer.Option(None, "--account-index", help="Use token from configs/accounts.json."),
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
):
    account = resolve_hsh798_account(token=token, accounts_file=Path(accounts), account_index=account_index)
    with Hsh798Client(token=account.token) as client:
        echo_json(client.stop_drinking(device_id))


@app.command(name="hsh798-snapshot")
def hsh798_snapshot(
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
    output_dir: str = typer.Option("outputs", "--output-dir", help="Directory for snapshot files."),
    include_status: bool = typer.Option(True, "--include-status/--skip-status", help="Also fetch per-device status for favorited devices."),
    debug_raw: bool = typer.Option(False, "--debug-raw/--redact-raw", help="Include full raw API payloads in output files."),
):
    out = run_hsh798_snapshot(
        accounts_file=accounts,
        output_dir=output_dir,
        include_status=include_status,
        debug_raw=debug_raw,
    )
    echo_json({"command": "hsh798-snapshot", "output": str(out)})


@app.command(name="hsh798-safe-start")
def hsh798_safe_start(
    device_id: str = typer.Option(..., "--device-id", help="Device ID."),
    token: str | None = typer.Option(None, "--token", help="HSH798 token."),
    account_index: int | None = typer.Option(None, "--account-index", help="Use token from configs/accounts.json."),
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
    verify_after: bool = typer.Option(True, "--verify-after/--no-verify-after", help="Check device status again after sending the action."),
    force: bool = typer.Option(False, "--force", help="Execute even when the device state is unknown or not idle."),
):
    account = resolve_hsh798_account(token=token, accounts_file=Path(accounts), account_index=account_index)
    echo_json(
        run_hsh798_safe_action(
            token=account.token,
            device_id=device_id,
            action="start",
            verify_after=verify_after,
            force=force,
        )
    )


@app.command(name="hsh798-safe-stop")
def hsh798_safe_stop(
    device_id: str = typer.Option(..., "--device-id", help="Device ID."),
    token: str | None = typer.Option(None, "--token", help="HSH798 token."),
    account_index: int | None = typer.Option(None, "--account-index", help="Use token from configs/accounts.json."),
    accounts: str = typer.Option("configs/accounts.json", "--accounts", help="Account store JSON file."),
    verify_after: bool = typer.Option(True, "--verify-after/--no-verify-after", help="Check device status again after sending the action."),
    force: bool = typer.Option(False, "--force", help="Execute even when the device already looks idle or status is unavailable."),
):
    account = resolve_hsh798_account(token=token, accounts_file=Path(accounts), account_index=account_index)
    echo_json(
        run_hsh798_safe_action(
            token=account.token,
            device_id=device_id,
            action="stop",
            verify_after=verify_after,
            force=force,
        )
    )


app.info.help = app.info.help or app.help


def _configure_cli_logging() -> None:
    logger.remove()
    logger.add(sys.stderr)


def main() -> None:
    _configure_cli_logging()
    app()


if __name__ == "__main__":
    main()
