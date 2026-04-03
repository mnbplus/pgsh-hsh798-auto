---
name: pgsh-daily-runner
description: Run the cooldown-aware PGSH daily execution flow in this repository and decide whether it is safe to retry. Use when the goal is to earn as many PGSH points as safely possible over time, especially for recurring automation, OpenClaw runs, or robot-triggered maintenance on an existing PGSH account.
homepage: "https://github.com/mnbplus/pgsh-hsh798-auto"
user-invocable: true
metadata: {"openclaw":{"emoji":"⏱️","homepage":"https://github.com/mnbplus/pgsh-hsh798-auto","requires":{"bins":["python"]}}}
---

# PGSH Daily Runner

Run from the workspace root.

Use this skill for repeated execution on an already-onboarded PGSH account.

## Default command

```powershell
python -m src.cli pgsh-daily --account-index <INDEX> --channel alipay --no-refresh-whitelist --state-file configs/pgsh_runtime_state.json
```

## Why this skill exists

`pgsh-daily` is the safest project entrypoint because it:

- checks login validity
- signs in once
- reads and writes persistent cooldown state
- avoids channels still inside a cooldown window
- uses the confirmed whitelist instead of probing everything every time
- writes a stable result bundle to `outputs/pgsh_daily_latest.json`

## Use this output contract

After each run, inspect:

- `outputs/pgsh_daily_latest.json`
- `configs/pgsh_runtime_state.json`

Read these fields first:

- `summary.execute_successful_attempts`
- `summary.execute_failed_attempts`
- `summary.execute_blocked_rounds`
- `summary.deferred_channels`
- `next_run`
- `runtime_state.channels`

## Retry rule

If `next_run.reason` is `channel_cooldown`, do not run again before `next_run.suggested_not_before`.

If `summary.execute_successful_attempts` is positive and no cooldown is active, it is acceptable to schedule another run later.

## Conservative execution policy

- Favor `alipay` first.
- Prefer fewer successful attempts per run over aggressive saturation.
- Let the runtime state decide when a channel should be paused.
- Only turn on `--refresh-whitelist` when confirmed tasks stop progressing.
