import httpx

RETRYABLE_HTTP_STATUS = {408, 425, 429, 500, 502, 503, 504}


class Hsh798Client:
    BASE_URL = "https://i.ilife798.com/api/v1"

    def __init__(self, token: str = ""):
        self.token = token
        self.client = httpx.Client(base_url=self.BASE_URL, timeout=20.0)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "Hsh798Client":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": self.token} if self.token else {}

    def _request_json(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self.client.request(method, path, **kwargs)
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

    @staticmethod
    def _normalize_payload(payload: object, *, http_status: int | None) -> dict:
        if isinstance(payload, dict):
            normalized = dict(payload)
            api_code = normalized.get("status")
            ok = api_code == 1 if api_code is not None else True
        else:
            normalized = {"data": payload}
            api_code = None
            ok = True

        msg = normalized.get("msg")
        if msg is None and normalized.get("message") is not None:
            msg = normalized.get("message")
        normalized.setdefault("data", None)
        normalized["msg"] = msg
        return {
            **normalized,
            "ok": ok,
            "api_code": api_code,
            "http_status": http_status,
            "retryable": False,
        }

    @staticmethod
    def _http_error_payload(response: httpx.Response, body: object) -> dict:
        payload = dict(body) if isinstance(body, dict) else {}
        api_code = payload.get("status")
        msg = payload.get("msg")
        if msg is None and payload.get("message") is not None:
            msg = payload.get("message")
        payload.setdefault("status", 0)
        payload.setdefault("data", None)
        payload["msg"] = str(msg or f"HTTP {response.status_code}")
        payload["ok"] = False
        payload["api_code"] = api_code if api_code is not None else payload.get("status")
        payload["http_status"] = response.status_code
        payload["retryable"] = response.status_code in RETRYABLE_HTTP_STATUS
        payload["error_type"] = "HTTPStatusError"
        payload["response_body"] = body if body is not None else response.text
        return payload

    @staticmethod
    def _request_error_payload(exc: httpx.RequestError) -> dict:
        return {
            "status": 0,
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
    def _invalid_json_payload(response: httpx.Response) -> dict:
        return {
            "status": 0,
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
    def response_ok(data: dict | None) -> bool:
        if not isinstance(data, dict):
            return False
        if isinstance(data.get("ok"), bool):
            return data["ok"]
        return data.get("status") == 1

    def get_captcha(self, s: str, r: str) -> bytes:
        resp = self.client.get("/captcha/", params={"s": s, "r": r})
        resp.raise_for_status()
        return resp.content

    def send_sms_code(self, s: str, auth_code: str, phone: str) -> dict:
        return self._request_json("POST", "/acc/login/code", json={"s": s, "authCode": auth_code, "un": phone})

    def login(self, phone: str, sms_code: str) -> dict:
        return self._request_json(
            "POST",
            "/acc/login",
            json={"openCode": "", "authCode": sms_code, "un": phone, "cid": "drinkwaterapp123456789"},
        )

    def device_list(self) -> dict:
        return self._request_json("GET", "/ui/app/master", headers=self._headers())

    def device_status(self, device_id: str) -> dict:
        return self._request_json(
            "GET",
            "/ui/app/dev/status",
            params={"did": device_id, "more": True, "promo": False},
            headers=self._headers(),
        )

    def toggle_favorite(self, device_id: str, remove: bool) -> dict:
        return self._request_json(
            "GET",
            "/dev/favo",
            params={"did": device_id, "remove": remove},
            headers=self._headers(),
        )

    def start_drinking(self, device_id: str) -> dict:
        return self._request_json(
            "GET",
            "/dev/start",
            params={"did": device_id, "upgrade": True, "rcp": False, "stype": 5},
            headers=self._headers(),
        )

    def stop_drinking(self, device_id: str) -> dict:
        return self._request_json("GET", "/dev/end", params={"did": device_id}, headers=self._headers())

    @staticmethod
    def extract_login_auth(data: dict) -> dict[str, str]:
        auth = data.get("data", {}).get("al", {}) or {}
        token = str(auth.get("token") or "").strip()
        if not token:
            raise ValueError("login response does not include token")
        return {
            "uid": str(auth.get("uid") or "").strip(),
            "eid": str(auth.get("eid") or "").strip(),
            "token": token,
        }

    @staticmethod
    def is_login_valid(data: dict) -> bool:
        try:
            return bool(Hsh798Client.extract_login_auth(data)["token"])
        except ValueError:
            return False

    @staticmethod
    def is_device_list_valid(data: dict) -> bool:
        return Hsh798Client.response_ok(data) and data.get("data", {}).get("account") is not None
