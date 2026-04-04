# Output Guide

## Generated files

The CLI writes structured JSON bundles into `outputs/` for batch and daily runs.

Common files:

- `pgsh_snapshot_YYYYMMDD_HHMMSS.json`
- `pgsh_execute_YYYYMMDD_HHMMSS.json`
- `pgsh_probe_YYYYMMDD_HHMMSS.json`
- `pgsh_daily_YYYYMMDD_HHMMSS.json`
- `hsh798_snapshot_YYYYMMDD_HHMMSS.json`
- `*_latest.json`
- `*_manifest.json`

## PGSH bundle shape

`pgsh-snapshot`, `pgsh-execute`, and `pgsh-probe` use the same high-level shape:

- `meta`: command metadata, selected channels, account source, schema version, and command-specific parameters
- `summary`: aggregated counts such as valid accounts, planned attempts, successes, failures, and block signals
- `rows`: per-account detailed results including raw API responses and execution details

## HSH798 snapshot shape

`hsh798-snapshot` currently writes a list of per-account rows.

- Each row includes account identity fields plus the favorited device list
- With `--include-status` enabled, each row also includes `device_statuses`
- `summary.available_devices` and `summary.busy_devices` are derived from the best known idle signal `data.device.gene.status == 99`

## Daily contract

`pgsh-daily` writes `outputs/pgsh_daily_latest.json`.

This is the preferred machine-readable contract for OpenClaw or any robot runner.

Read these fields first:

- `automation_summary`: short decision payload with status, fixed schema, recommended action, suggested retry time, and file locations
- `next_run`: retry guidance derived from the latest cooldown state
- `summary`: human-readable aggregated daily result
- `runtime_state`: persisted account state snapshot after the run

## Recommended robot fields

For scheduling and status checks, prefer:

- `automation_summary.schema_version`
- `automation_summary.status`
- `automation_summary.recommended_action`
- `automation_summary.reason_code`
- `automation_summary.should_run_now`
- `automation_summary.suggested_not_before`
- `automation_summary.suggested_command`
- `automation_summary.execute_no_credit_attempts`
- `automation_summary.stall_probe_triggered`
- `summary.execute_successful_attempts`
- `summary.execute_failed_attempts`
- `summary.execute_no_credit_attempts`
- `summary.execute_blocked_rounds`
- `summary.stall_probe_triggered`
- `summary.deferred_channels`

## Design goals

- Keep every run auditable with timestamped snapshots
- Preserve a stable `*_latest.json` path for automations
- Store enough context to compare token validity and channel health over time
- Expose cooldown and retry state without requiring the caller to parse low-level task details
- Distinguish real execution failures from `no_credit` responses where the API itself still succeeded
- Auto-trigger a low-frequency probe after a zero-progress daily run so confirmed task codes can self-heal
- Avoid telling schedulers to rerun immediately when a zero-progress run is followed by a stall probe that still only returns `no_credit`

## Raw payload mode

Batch and daily snapshot bundles now default to `meta.raw_mode = "redacted"`.

- Redacted mode keeps machine-readable summary fields and masks obvious secrets and PII
- Use `--debug-raw` on bundle-producing commands only when you explicitly need full raw API payloads for debugging
- `hsh798-snapshot`, `pgsh-snapshot`, `pgsh-execute`, `pgsh-probe`, and `pgsh-daily` all support this switch
