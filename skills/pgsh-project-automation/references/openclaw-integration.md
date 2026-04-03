# OpenClaw Integration

Use the repository root as the working directory.

## Primary command

```powershell
python -m src.cli pgsh-daily --account-index <INDEX> --channel alipay --no-refresh-whitelist --state-file configs/pgsh_runtime_state.json
```

## Primary result file

Read:

- `outputs/pgsh_daily_latest.json`

## Machine-facing contract

Prefer the top-level `automation_summary` object.

Important fields:

- `schema_version`
- `status`
- `recommended_action`
- `reason_code`
- `should_run_now`
- `cooldown_active`
- `suggested_not_before`
- `wait_seconds`
- `suggested_command`

## Minimal decision loop

1. Run `pgsh-daily`
2. Parse `automation_summary`
3. If `cooldown_active` is true, wait until `suggested_not_before`
4. If `status` is `progressed`, schedule another run later
5. If `status` is `blocked`, do not retry immediately
6. If `status` is `idle`, inspect whitelist or probe results

## Safety rules

- Prefer `alipay` first
- Do not loop `pgsh-complete` directly
- Do not ignore `cooldown_active`
- Only enable whitelist refresh when confirmed tasks stop making progress
