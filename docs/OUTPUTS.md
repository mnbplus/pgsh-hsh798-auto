# 输出说明

## 输出文件

批量命令会在 `outputs/` 下生成 JSON 文件：

- `pgsh_snapshot_YYYYMMDD_HHMMSS.json`
- `pgsh_execute_YYYYMMDD_HHMMSS.json`
- `hsh798_snapshot_YYYYMMDD_HHMMSS.json`
- 对应的 `*_latest.json`
- 对应的 `*_manifest.json`

## PGSH 文件结构

`pgsh-snapshot` 和 `pgsh-execute` 现已统一为：

- `meta`：命令、schema 版本、账号文件、channel、选择模式等元信息
- `summary`：聚合统计，例如账号数、有效账号数、计划执行次数、dry-run 信息
- `rows`：逐账号明细，包含原始响应、执行结果、错误列表与 channel 级摘要

## 设计目标

- 每次执行保留独立快照
- 便于比较 token 是否失效
- 便于后续做任务结果审计
- 便于排查接口字段变化
- 让空账号、失效 token、API 返回失败时也保留稳定结构

## 后续准备补充

- 错误分类
- 任务执行结果汇总
- 余额变化字段提炼
