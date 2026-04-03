# 使用说明

## 环境准备

```powershell
python -m pip install -e .
```

## 当前可用命令

```powershell
python -m src.cli doctor
python -m src.cli pgsh-info --token <TOKEN> --phone-brand Xiaomi
python -m src.cli pgsh-valid --token <TOKEN> --phone-brand Xiaomi
python -m src.cli pgsh-balance --token <TOKEN> --phone-brand Xiaomi
python -m src.cli pgsh-tasks --token <TOKEN> --phone-brand Xiaomi --channel android_app
python -m src.cli pgsh-checkin --token <TOKEN> --phone-brand Xiaomi
python -m src.cli pgsh-complete --token <TOKEN> --task-code <TASK_CODE> --phone-brand Xiaomi --channel android_app
python -m src.cli pgsh-captcha --token <TOKEN> --phone-brand Xiaomi
python -m src.cli pgsh-save-account --token <TOKEN> --phone-brand Xiaomi --note <NOTE>
python -m src.cli pgsh-snapshot --accounts configs/accounts.json --output-dir outputs
python -m src.cli pgsh-snapshot --account-index 0 --channel android_app
python -m src.cli pgsh-snapshot --token <TOKEN> --phone-brand Xiaomi --channel alipay
python -m src.cli pgsh-execute --accounts configs/accounts.json --whitelist configs/pgsh_task_whitelist.json --output-dir outputs
python -m src.cli pgsh-execute --account-index 0 --channel android_app --dry-run
python -m src.cli pgsh-execute --account-index 0 --channel android_app --delay-seconds 2
python -m src.cli pgsh-probe --account-index 0 --channel alipay --max-tasks 5 --delay-seconds 3
python -m src.cli pgsh-probe --account-index 0 --channel alipay --max-tasks 3 --export-confirmed-whitelist
python -m src.cli pgsh-probe --account-index 0 --channel alipay --whitelist configs/pgsh_task_whitelist_confirmed.json --export-whitelist-auto
python -m src.cli pgsh-daily --account-index 0 --channel alipay --no-refresh-whitelist --state-file configs/pgsh_runtime_state.json
python -m src.cli hsh798-captcha --s <S> --r <R>
python -m src.cli hsh798-send-sms --s <S> --auth-code <CAPTCHA> --phone <PHONE>
python -m src.cli hsh798-login --phone <PHONE> --sms-code <SMS_CODE>
python -m src.cli hsh798-login --phone <PHONE> --sms-code <SMS_CODE> --note <NOTE>
python -m src.cli hsh798-devices --token <TOKEN>
python -m src.cli hsh798-status --token <TOKEN> --device-id <ID>
python -m src.cli hsh798-favo --token <TOKEN> --device-id <ID>
python -m src.cli hsh798-start --token <TOKEN> --device-id <ID>
python -m src.cli hsh798-stop --token <TOKEN> --device-id <ID>
python -m src.cli hsh798-snapshot --accounts configs/accounts.json --output-dir outputs
```

## 配置文件

- `configs/accounts.json`
- `configs/accounts.example.json`
- `configs/pgsh_task_whitelist.json`

### PGSH 账号使用方式

- 单次直连测试：`--token`，必要时配合 `--phone-brand`
- 使用已保存账号：`--account-index`
- 写入或更新账号：`pgsh-save-account --token <TOKEN> [--account-index N]`

## 输出文件

`pgsh-snapshot`、`pgsh-execute` 和 `hsh798-snapshot` 会在 `--output-dir` 下同时写出：

- 带时间戳的快照文件，例如 `pgsh_snapshot_20260402_211900.json`
- 对应的 `*_latest.json`，方便脚本始终读取最新结果
- 对应的 `*_manifest.json`，记录生成时间、最新文件名、时间戳文件名与行数

其中 `pgsh-snapshot` / `pgsh-execute` 的主 JSON 文件统一包含：

- `meta`：命令、账号文件、channel、schema 版本、选择模式等元信息
- `summary`：账号数、有效账号数、计划执行次数等聚合结果
- `rows`：逐账号的原始返回、错误信息与执行明细

目前先保留为本地调试用途，后续再补批量任务和定时执行。
