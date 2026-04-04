# CLI Updates

This repo's CLI was tightened on 2026-04-02 to match the examples and the new persistence flow.

## Highlights

- Token-like inputs are now real options such as `--token`, `--task-code`, `--device-id`, `--phone`, and `--sms-code`.
- `doctor` hides tokens by default. Use `--show-secrets` only when necessary.
- Most direct commands can resolve credentials from `configs/accounts.json` with `--account-index`.
- `hsh798-login` can now save `phone`, `uid`, `eid`, `token`, and `last_login_at` back into `configs/accounts.json`.
- `pgsh-snapshot` and `pgsh-execute` now support `--channel android_app|alipay|all`.
- `pgsh-save-account` can now write or update a PGSH token in `configs/accounts.json`.
- `pgsh-snapshot` and `pgsh-execute` now also support `--token` and `--account-index` for single-account runs.
- `pgsh-execute` now supports `--dry-run` for safe planning.
- `pgsh-probe` can now low-frequency probe pending task codes and optionally export a refreshed whitelist JSON file.
- `pgsh-probe --export-confirmed-whitelist` can merge newly confirmed task codes back into `configs/pgsh_task_whitelist_confirmed.json`.
- `pgsh-execute` now supports `--delay-seconds` so successful attempts can be throttled more gently.
- `pgsh-daily` now writes a machine-friendly daily bundle, tracks cooldown state, can suggest when the next safe run should happen, and auto-triggers a low-frequency probe after zero-progress runs.
- PGSH batch outputs are now returned as `meta` + `summary` + `rows`.
- PGSH execution/probe summaries now distinguish `no_credit_attempts` from transport/API failures so automation can reason about "接口通了但没拿到积分" separately.
- `pgsh-daily` no longer suggests an immediate rerun when a zero-progress execution auto-triggers a stall probe and the probe still only returns `no_credit`.
- Bundle-producing commands now default to redacted raw payloads. Use `--debug-raw` only when you explicitly need full raw API responses in output files.
- PGSH signing values can now be overridden through environment variables such as `PGHSH_PGSH_APP_VERSION`, `PGHSH_PGSH_APP_SECRET`, `PGHSH_PGSH_ALIPAY_APP_SECRET`, `PGHSH_PGSH_AUTH_APP_VERSION`, and `PGHSH_PGSH_AUTH_APP_SECRET`.
- `hsh798-snapshot` can now enrich snapshots with per-device status checks, and `hsh798-safe-start` / `hsh798-safe-stop` provide state-aware control wrappers.

## Examples

```powershell
python -m src.cli doctor --accounts configs/accounts.json
python -m src.cli pgsh-info --account-index 0
python -m src.cli pgsh-tasks --account-index 0 --channel alipay
python -m src.cli pgsh-save-account --token <TOKEN> --phone-brand Xiaomi --account-index 0
python -m src.cli pgsh-snapshot --accounts configs/accounts.json --output-dir outputs --channel all
python -m src.cli pgsh-snapshot --account-index 0 --channel android_app --debug-raw
python -m src.cli pgsh-snapshot --account-index 0 --channel android_app
python -m src.cli pgsh-execute --accounts configs/accounts.json --whitelist configs/pgsh_task_whitelist.json --output-dir outputs --channel all
python -m src.cli pgsh-execute --account-index 0 --channel android_app --dry-run
python -m src.cli pgsh-probe --account-index 0 --channel alipay --max-tasks 5 --delay-seconds 3
python -m src.cli pgsh-probe --account-index 0 --channel alipay --max-tasks 3 --export-confirmed-whitelist
python -m src.cli pgsh-probe --account-index 0 --channel alipay --whitelist configs/pgsh_task_whitelist_confirmed.json --export-whitelist-auto
python -m src.cli pgsh-daily --account-index 0 --channel alipay --no-refresh-whitelist --state-file configs/pgsh_runtime_state.json
python -m src.cli hsh798-login --phone <PHONE> --sms-code <SMS_CODE> --save --account-index 0
python -m src.cli hsh798-devices --account-index 0
python -m src.cli hsh798-status --account-index 0 --device-id <DEVICE_ID>
python -m src.cli hsh798-safe-start --account-index 0 --device-id <DEVICE_ID>
python -m src.cli hsh798-safe-stop --account-index 0 --device-id <DEVICE_ID>
python -m src.cli hsh798-snapshot --accounts configs/accounts.json --output-dir outputs --include-status
```
