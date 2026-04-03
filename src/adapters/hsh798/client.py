import httpx


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
        response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json()

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
        return data.get("status") == 1 and data.get("data", {}).get("account") is not None
