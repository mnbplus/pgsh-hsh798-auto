from typing import Any

from .cli_support import mask_phone, mask_secret


SUMMARY_REDACT_KEYS = {"raw", "response", "response_body", "devices"}
SECRET_KEYS = {
    "token",
    "authorization",
    "sign",
    "secret",
    "appsecret",
    "accesstoken",
    "refreshtoken",
    "sessiontoken",
}
PHONE_KEYS = {"phone", "mobile", "telephone", "tel"}
NAME_KEYS = {"username", "user_name", "nickname", "nick_name", "realname", "real_name"}
IDENTIFIER_KEYS = {"uid", "eid", "deviceid", "did", "serialnumber", "serialno", "sn"}


def sanitize_output_bundle(data: Any, *, debug_raw: bool) -> Any:
    if debug_raw:
        return data
    return _sanitize_value(data, path=())


def _sanitize_value(value: Any, *, path: tuple[str, ...]) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            key_lower = key_text.lower()

            if key_lower in SUMMARY_REDACT_KEYS:
                sanitized[key_text] = _summarize_redacted_payload(item)
                continue
            if key_lower in SECRET_KEYS:
                sanitized[key_text] = _mask_secret_like(item)
                continue
            if key_lower in PHONE_KEYS:
                sanitized[key_text] = _mask_phone_like(item)
                continue
            if key_lower in NAME_KEYS:
                sanitized[key_text] = _mask_name_like(item)
                continue
            if key_lower in IDENTIFIER_KEYS:
                sanitized[key_text] = _mask_identifier_like(item)
                continue
            if key_lower == "account_state_key" and isinstance(item, str) and item.startswith("phone:"):
                sanitized[key_text] = f"phone:{mask_phone(item.removeprefix('phone:'))}"
                continue

            sanitized[key_text] = _sanitize_value(item, path=path + (key_text,))
        return sanitized

    if isinstance(value, list):
        return [_sanitize_value(item, path=path) for item in value]

    return value


def _summarize_redacted_payload(value: Any) -> dict[str, Any]:
    summary = {"redacted": True, "shape": _shape_summary(value)}
    if isinstance(value, dict):
        for key in ("ok", "code", "status", "api_code", "http_status", "retryable", "msg", "message", "error_type"):
            if key in value:
                summary[key] = value[key]
    return summary


def _shape_summary(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        data = value.get("data")
        summary = {
            "type": "object",
            "keys": sorted(str(key) for key in value.keys()),
        }
        if isinstance(data, dict):
            summary["data_keys"] = sorted(str(key) for key in data.keys())
        elif isinstance(data, list):
            summary["data_items"] = len(data)
        return summary
    if isinstance(value, list):
        return {"type": "array", "items": len(value)}
    if isinstance(value, str):
        return {"type": "string", "length": len(value)}
    return {"type": type(value).__name__}


def _mask_secret_like(value: Any) -> Any:
    if isinstance(value, str):
        return mask_secret(value)
    return value


def _mask_phone_like(value: Any) -> Any:
    if isinstance(value, str):
        return mask_phone(value)
    return value


def _mask_identifier_like(value: Any) -> Any:
    if isinstance(value, str):
        return mask_secret(value, keep=2)
    return value


def _mask_name_like(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    trimmed = value.strip()
    if not trimmed:
        return value
    if len(trimmed) == 1:
        return "*"
    if len(trimmed) == 2:
        return f"{trimmed[0]}*"
    return f"{trimmed[0]}{'*' * (len(trimmed) - 2)}{trimmed[-1]}"
