# pgsh-hsh798-auto

本项目用于研究胖乖生活与惠生活798的自动化能力，当前已经完成第一版本地 CLI 与接口适配器骨架。

## 当前状态

已完成：
- 参考仓库收集与落地
- Python 3.12 环境安装
- 本地包安装（editable）
- 胖乖生活适配器第一版
- 惠生活798适配器第一版
- CLI 命令入口
- 接口分析文档
- PGSH 批量命令的结构化输出与单账号测试入口
- PGSH daily 冷却状态跟踪、自动补探测与 confirmed whitelist 自修复

## 当前命令

提示：多数命令除了直接传 `--token`，也支持通过 `--accounts configs/accounts.json --account-index N` 读取已保存账号，适合批量或多账号场景。

```powershell
python -m src.cli doctor
python -m src.cli pgsh-info --token <TOKEN> --phone-brand Xiaomi
python -m src.cli pgsh-valid --token <TOKEN> --phone-brand Xiaomi
python -m src.cli pgsh-balance --token <TOKEN> --phone-brand Xiaomi
python -m src.cli pgsh-tasks --token <TOKEN> --phone-brand Xiaomi
python -m src.cli pgsh-checkin --token <TOKEN> --phone-brand Xiaomi
python -m src.cli pgsh-complete --token <TOKEN> --task-code <TASK_CODE> --phone-brand Xiaomi
python -m src.cli pgsh-captcha --token <TOKEN> --phone-brand Xiaomi
python -m src.cli pgsh-send-sms --phone <PHONE> --phone-brand Xiaomi
python -m src.cli pgsh-login --phone <PHONE> --sms-code <SMS_CODE> --phone-brand Xiaomi
python -m src.cli pgsh-save-account --token <TOKEN> --phone-brand Xiaomi --note <NOTE>
python -m src.cli pgsh-snapshot --accounts configs/accounts.json --output-dir outputs
python -m src.cli pgsh-snapshot --account-index 0 --channel android_app
python -m src.cli pgsh-execute --accounts configs/accounts.json --whitelist configs/pgsh_task_whitelist.json --output-dir outputs
python -m src.cli pgsh-execute --account-index 0 --channel android_app --dry-run
python -m src.cli pgsh-probe --account-index 0 --channel alipay --max-tasks 5 --delay-seconds 3
python -m src.cli pgsh-probe --account-index 0 --channel alipay --max-tasks 3 --export-confirmed-whitelist
python -m src.cli pgsh-probe --account-index 0 --channel alipay --whitelist configs/pgsh_task_whitelist_confirmed.json --export-whitelist-auto
python -m src.cli pgsh-daily --account-index 0 --channel alipay --no-refresh-whitelist --state-file configs/pgsh_runtime_state.json
python -m src.cli hsh798-captcha --s <S> --r <R>
python -m src.cli hsh798-send-sms --s <S> --auth-code <CAPTCHA_TEXT> --phone <PHONE>
python -m src.cli hsh798-login --phone <PHONE> --sms-code <SMS_CODE>
python -m src.cli hsh798-login --phone <PHONE> --sms-code <SMS_CODE> --note <NOTE>
python -m src.cli hsh798-devices --token <TOKEN>
python -m src.cli hsh798-devices --account-index 0
python -m src.cli hsh798-status --token <TOKEN> --device-id <ID>
python -m src.cli hsh798-status --account-index 0 --device-id <ID>
python -m src.cli hsh798-favo --token <TOKEN> --device-id <ID>
python -m src.cli hsh798-favo --account-index 0 --device-id <ID>
python -m src.cli hsh798-start --token <TOKEN> --device-id <ID>
python -m src.cli hsh798-start --account-index 0 --device-id <ID>
python -m src.cli hsh798-stop --token <TOKEN> --device-id <ID>
python -m src.cli hsh798-stop --account-index 0 --device-id <ID>
python -m src.cli hsh798-snapshot --accounts configs/accounts.json --output-dir outputs
```

## 目录
- `src/` 主源码
- `configs/` 本地账号配置
- `docs/` 接口、计划与输出说明文档
- `outputs/` 运行输出（按需生成，不一定预先存在）
- `skills/` 面向 OpenClaw / Agent 的项目内技能定义

备注：参考仓库/抓包素材不固定纳入此项目目录时，请以 `docs/REFERENCE_ANALYSIS.md` 与相关 notes 为准。

## 下一步
- 继续收口 PGSH 真账号验证与执行策略
- 深挖惠生活798积分/任务相关接口
- 增强批量账号执行与跨账号结果汇总
- 增加更细的日志落盘、失败分类与回退策略
