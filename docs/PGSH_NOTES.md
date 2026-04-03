# PGSH 接口笔记

## 基础信息
- Base URL: `https://userapi.qiekj.com`
- 参考来源: `refs/PgshAutoHelper/src/helper.py`

## 关键头
- `Authorization`: token
- `timestamp`: 毫秒时间戳
- `channel`: `android_app` 或 `alipay`
- `sign`: sha256 签名
- `Version`: `1.82.1`（android_app）
- `phoneBrand`: 如 `Xiaomi`（android_app）

## 签名
### android_app
```text
appSecret={APP_SECRET}&channel=android_app&timestamp={timestamp}&token={token}&version={APP_VERSION}&{path}
```

### alipay
```text
appSecret={ALIPAY_APP_SECRET}&channel=alipay&timestamp={timestamp}&token={token}&{path}
```

## 已知接口
- `/user/info`
- `/user/balance`
- `/task/list`
- `/task/completed`
- `/signin/doUserSignIn`
- `/integralCaptcha/isCaptcha`
- `/slot/get`

## 下一步
- 补 `complete_task`
- 补任务代码白名单配置
- 做 token 有效性检查命令
