# 惠生活798 接口笔记

## 基础信息
- Base URL: `https://i.ilife798.com/api/v1`
- 参考来源: `refs/drink_798/lib/core/services/drink_api_service.dart`

## 已知登录链路
1. 获取图形验证码 `/captcha/`
2. 发送短信验证码 `/acc/login/code`
3. 登录 `/acc/login`
4. 从返回体提取 `uid` / `eid` / `token`

## 已知接口
- `/captcha/`
- `/acc/login/code`
- `/acc/login`
- `/ui/app/master`
- `/ui/app/dev/status`
- `/dev/favo`
- `/dev/start`
- `/dev/end`

## 已知请求特点
- 大部分业务请求使用 `Authorization: <token>`
- 现有第三方客户端已证明这些接口可直接请求

## 下一步
- 继续找与积分/任务相关的接口
- 整理登录返回体结构
- 补设备收藏与登录命令
