---
name: pgsh-project-automation
description: Run and maintain the PGSH automation workflow in this repository, including SMS login, task probing, cooldown-aware daily execution, balance checks, and result interpretation. Use when working inside the pgsh-hsh798-auto workspace and the user wants to onboard a PGSH account, inspect remaining PGSH tasks, refresh confirmed task codes, run the daily PGSH flow, or decide when the next safe run should happen.
homepage: "https://github.com/mnbplus/pgsh-hsh798-auto"
user-invocable: true
metadata: {"openclaw":{"emoji":"🪙","homepage":"https://github.com/mnbplus/pgsh-hsh798-auto","requires":{"bins":["python"]}}}
---

# PGSH Project Automation

Run all commands from the workspace root.

## Preferred workflow

Use `pgsh-daily` as the default entrypoint for real task execution.

Safe default command:

```powershell
python -m src.cli pgsh-daily --account-index <INDEX> --channel alipay --no-refresh-whitelist --state-file configs/pgsh_runtime_state.json
```

This command already:

- checks account validity
- performs sign-in once
- respects persisted cooldown state
- uses confirmed task codes only
- writes a machine-friendly bundle to `outputs/pgsh_daily_latest.json`
- writes/updates runtime state in `configs/pgsh_runtime_state.json`

For recurring automation, this is the safest command to schedule or expose to a robot:

```powershell
python -m src.cli pgsh-daily --account-index <INDEX> --channel alipay --no-refresh-whitelist --state-file configs/pgsh_runtime_state.json
```

## Daily run contract

Treat `pgsh-daily` as the machine-facing entrypoint for this repository.

After each run, inspect:

- `outputs/pgsh_daily_latest.json`
- `configs/pgsh_runtime_state.json`

Read these fields first:

- `automation_summary`
- `summary.execute_successful_attempts`
- `summary.execute_failed_attempts`
- `summary.execute_blocked_rounds`
- `summary.deferred_channels`
- `next_run`
- `runtime_state.channels`

If `next_run.reason` is `channel_cooldown`, do not run again before `next_run.suggested_not_before`.

If `summary.execute_successful_attempts` is positive and no cooldown is active, it is acceptable to schedule another run later.

For robot orchestration, prefer `automation_summary` as the short contract and fall back to `summary`, `next_run`, and `runtime_state` only when more detail is needed.

## Account onboarding

For a new PGSH account:

1. Send SMS code:

```powershell
python -m src.cli pgsh-send-sms --phone <PHONE>
```

2. Log in and save the token:

```powershell
python -m src.cli pgsh-login --phone <PHONE> --sms-code <CODE>
```

3. Verify account slots:

```powershell
python -m src.cli doctor
```

## Task discovery

When a new account has not been profiled yet, or confirmed tasks stop working, probe first:

```powershell
python -m src.cli pgsh-probe --account-index <INDEX> --channel alipay --max-tasks 3 --export-confirmed-whitelist
```

Prefer `alipay` first. Only explore `android_app` when the user explicitly asks or when Alipay discovery is exhausted.

## Cooldown rules

Before rerunning real execution, inspect:

- `outputs/pgsh_daily_latest.json`
- `configs/pgsh_runtime_state.json`

If `summary.deferred_channels` is non-empty, or `next_run.reason` is `channel_cooldown`, do not run real execution before `next_run.suggested_not_before`.

Use these fields when reporting status:

- `summary.execute_successful_attempts`
- `summary.execute_failed_attempts`
- `summary.execute_blocked_rounds`
- `summary.deferred_channels`
- `next_run`
- `runtime_state.channels`

## Operator guidance

- Favor slow, repeatable progress over aggressive completion.
- Do not loop `pgsh-complete` manually in tight bursts.
- Prefer confirmed whitelist execution over probing once a channel is known-good.
- When execution is blocked, stop and report the cooldown rather than pushing harder.
- Favor `alipay` first for long-running automation.
- Prefer fewer successful attempts per run over aggressive saturation.
- Only turn on `--refresh-whitelist` when confirmed tasks stop progressing.
