from urllib.parse import urlparse
import hashlib
import time
from typing import Any

import httpx

APP_VERSION = "1.82.1"
APP_SECRET = "nFU9pbG8YQoAe1kFh+E7eyrdlSLglwEJeA0wwHB1j5o="
ALIPAY_APP_SECRET = "Ew+ZSuppXZoA9YzBHgHmRvzt0Bw1CpwlQQtSl49QNhY="
AUTH_APP_VERSION = "1.57.0"
AUTH_APP_SECRET = "xl8v4s/5qpBLvN+8CzFx7vVjy31NgXXcedU7G0QpOMM="
DEFAULT_USER_AGENT = "okhttp/4.12.0"
AUTH_USER_AGENT = "okhttp/3.14.9"
RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}


class PgshClient:
    def __init__(self, token: str, phone_brand: str):
        self.token = token
        self.phone_brand = phone_brand
        self.client = httpx.Client(base_url="https://userapi.qiekj.com", timeout=20.0)
        self._session_warmed = False

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "PgshClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _sign(
        self,
        request_url: str,
        timestamp: str | int,
        channel: str = "android_app",
        *,
        token: str | None = None,
        app_version: str | None = None,
        app_secret: str | None = None,
    ) -> str:
        path = urlparse(str(request_url)).path
        token_value = self.token if token is None else token
        if channel == "android_app":
            version_value = APP_VERSION if app_version is None else app_version
            secret_value = APP_SECRET if app_secret is None else app_secret
            raw = (
                f"appSecret={secret_value}&channel={channel}&timestamp={timestamp}"
                f"&token={token_value}&version={version_value}&{path}"
            )
        else:
            secret_value = ALIPAY_APP_SECRET if app_secret is None else app_secret
            raw = f"appSecret={secret_value}&channel={channel}&timestamp={timestamp}&token={token_value}&{path}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _headers(
        self,
        path: str,
        channel: str = "android_app",
        *,
        token: str | None = None,
        app_version: str | None = None,
        app_secret: str | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        phone_brand: str | None = None,
    ) -> dict[str, str]:
        ts = str(int(time.time() * 1000))
        token_value = self.token if token is None else token
        brand_value = self.phone_brand if phone_brand is None else phone_brand
        headers = {
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip",
            "Authorization": token_value,
            "timestamp": ts,
            "channel": channel,
            "sign": self._sign(
                path,
                ts,
                channel,
                token=token_value,
                app_version=app_version,
                app_secret=app_secret,
            ),
        }
        if channel == "android_app":
            headers["Version"] = APP_VERSION if app_version is None else app_version
            if brand_value:
                headers["phoneBrand"] = brand_value
        return headers

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        channel: str = "android_app",
        data: dict | None = None,
        token: str | None = None,
        app_version: str | None = None,
        app_secret: str | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        phone_brand: str | None = None,
    ) -> dict:
        try:
            response = self.client.request(
                method,
                path,
                data=data,
                headers=self._headers(
                    path,
                    channel,
                    token=token,
                    app_version=app_version,
                    app_secret=app_secret,
                    user_agent=user_agent,
                    phone_brand=phone_brand,
                ),
            )
        except httpx.RequestError as exc:
            return self._request_error_payload(exc)

        parsed_json = True
        try:
            body = response.json()
        except ValueError:
            parsed_json = False
            body = None

        if response.is_error:
            return self._http_error_payload(response, body)
        if not parsed_json:
            return self._invalid_json_payload(response)

        return self._normalize_payload(body, http_status=response.status_code)

    @classmethod
    def _normalize_payload(cls, payload: Any, *, http_status: int | None) -> dict:
        if isinstance(payload, dict):
            normalized = dict(payload)
            api_code = normalized.get("code")
            ok = api_code == 0 if api_code is not None else True
        else:
            normalized = {"data": payload}
            api_code = None
            ok = True

        normalized.setdefault("data", None)
        normalized.setdefault("msg", None)
        return {
            **normalized,
            "ok": ok,
            "api_code": api_code,
            "http_status": http_status,
            "retryable": False,
        }

    @classmethod
    def _http_error_payload(cls, response: httpx.Response, body: Any) -> dict:
        payload = dict(body) if isinstance(body, dict) else {}
        api_code = payload.get("code")
        payload.setdefault("code", response.status_code)
        payload.setdefault("data", None)
        payload["msg"] = str(payload.get("msg") or f"HTTP {response.status_code}")
        payload["ok"] = False
        payload["api_code"] = api_code if api_code is not None else payload.get("code")
        payload["http_status"] = response.status_code
        payload["retryable"] = response.status_code in RETRYABLE_HTTP_STATUS
        payload["error_type"] = "HTTPStatusError"
        payload["response_body"] = body if body is not None else response.text
        return payload

    @staticmethod
    def _invalid_json_payload(response: httpx.Response) -> dict:
        return {
            "code": None,
            "msg": "invalid JSON response",
            "data": None,
            "ok": False,
            "api_code": None,
            "http_status": response.status_code,
            "retryable": False,
            "error_type": "InvalidJSONResponse",
            "response_body": response.text,
        }

    @staticmethod
    def _request_error_payload(exc: httpx.RequestError) -> dict:
        return {
            "code": None,
            "msg": str(exc),
            "data": None,
            "ok": False,
            "api_code": None,
            "http_status": None,
            "retryable": isinstance(exc, (httpx.TimeoutException, httpx.TransportError)),
            "error_type": type(exc).__name__,
            "response_body": None,
        }

    @staticmethod
    def response_ok(data: dict | None) -> bool:
        if not isinstance(data, dict):
            return False
        if isinstance(data.get("ok"), bool):
            return data["ok"]
        return data.get("code") == 0

    def warmup_session(self) -> dict:
        if self._session_warmed:
            return {"warmed": True, "cached": True}
        path = "/slot/get"
        result = self._request_json(
            "POST",
            path,
            data={"slotKey": "android_open_screen_1_35_0", "token": self.token},
        )
        self._session_warmed = True
        return result

    def user_info(self) -> dict:
        path = "/user/info"
        return self._request_json("POST", path, data={"token": self.token})

    def balance(self) -> dict:
        path = "/user/balance"
        return self._request_json("POST", path, data={"token": self.token})

    def send_sms_code(self, phone: str) -> dict:
        path = "/common/sms/sendCode"
        return self._request_json(
            "POST",
            path,
            data={"phone": phone, "template": "reg"},
            token="",
            app_version=AUTH_APP_VERSION,
            app_secret=AUTH_APP_SECRET,
            user_agent=AUTH_USER_AGENT,
        )

    def sms_login(self, phone: str, verify_code: str) -> dict:
        path = "/user/reg"
        return self._request_json(
            "POST",
            path,
            data={"channel": "h5", "phone": phone, "verify": verify_code},
            token="",
            app_version=AUTH_APP_VERSION,
            app_secret=AUTH_APP_SECRET,
            user_agent=AUTH_USER_AGENT,
        )

    def task_list(self, channel: str = "android_app") -> dict:
        path = "/task/list"
        return self._request_json("POST", path, channel=channel, data={"token": self.token})

    def checkin(self) -> dict:
        path = "/signin/doUserSignIn"
        return self._request_json("POST", path, data={"activityId": "600001", "token": self.token})

    def complete_task(self, task_code: str, channel: str = "android_app", subtask_code: str | None = None) -> dict:
        path = "/task/completed"
        data = {"taskCode": task_code, "token": self.token}
        if subtask_code:
            data["subtaskCode"] = subtask_code
        return self._request_json("POST", path, channel=channel, data=data)

    def captcha_status(self) -> dict:
        path = "/integralCaptcha/isCaptcha"
        return self._request_json("POST", path, data={"token": self.token})

    def token_valid(self) -> bool:
        data = self.user_info()
        return self.response_ok(data) and data.get("data") is not None

    @staticmethod
    def extract_login_auth(data: dict) -> dict[str, str]:
        payload = data.get("data") or {}
        token = str(payload.get("token") or "").strip()
        if not token:
            raise ValueError("login response does not include token")
        return {
            "token": token,
            "phone": str(payload.get("phone") or "").strip(),
            "user_name": str(payload.get("userName") or "").strip(),
        }

    @staticmethod
    def is_login_valid(data: dict) -> bool:
        try:
            return bool(PgshClient.extract_login_auth(data)["token"])
        except ValueError:
            return False
