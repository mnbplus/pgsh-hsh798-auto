from pathlib import Path

from src.adapters.hsh798.client import Hsh798Client
from src.core.storage import load_accounts, upsert_hsh798_account, write_snapshot_bundle


def _summarize_devices(devices: dict) -> dict:
    payload = devices.get("data", {}) or {}
    account = payload.get("account") or {}
    favorites = payload.get("favos") or []
    return {
        "account": account,
        "device_count": len(favorites),
        "device_ids": [str(item.get("id")) for item in favorites if item.get("id") is not None],
        "device_names": [str(item.get("name")) for item in favorites if item.get("name")],
    }


def run_hsh798_login(
    *,
    phone: str,
    sms_code: str,
    accounts_file: str = "configs/accounts.json",
    account_index: int | None = None,
    save: bool = True,
    note: str | None = None,
) -> dict:
    with Hsh798Client() as client:
        response = client.login(phone=phone, sms_code=sms_code)

    result = {
        "phone": phone,
        "response": response,
        "valid": Hsh798Client.is_login_valid(response),
    }
    if not result["valid"]:
        return result

    auth = Hsh798Client.extract_login_auth(response)
    result["auth"] = auth

    if save:
        _, saved_index, saved_account = upsert_hsh798_account(
            Path(accounts_file),
            phone=phone,
            token=auth["token"],
            uid=auth["uid"] or None,
            eid=auth["eid"] or None,
            note=note,
            account_index=account_index,
        )
        result["saved"] = {
            "accounts_file": accounts_file,
            "account_index": saved_index,
            "phone": saved_account.phone,
            "uid": saved_account.uid,
            "eid": saved_account.eid,
        }

    return result


def run_hsh798_snapshot(accounts_file: str = "configs/accounts.json", output_dir: str = "outputs") -> Path:
    store = load_accounts(Path(accounts_file))
    rows = []
    for index, item in enumerate(store.hsh798):
        if not item.token:
            continue
        row = {
            "account_index": index,
            "note": item.note,
            "phone": item.phone,
            "uid": item.uid,
            "eid": item.eid,
            "last_login_at": item.last_login_at,
            "valid": False,
        }
        with Hsh798Client(token=item.token) as client:
            try:
                devices = client.device_list()
                row["devices"] = devices
                row["valid"] = Hsh798Client.is_device_list_valid(devices)
                row["summary"] = _summarize_devices(devices)
            except Exception as e:
                row["devices_error"] = str(e)
        rows.append(row)

    return write_snapshot_bundle(output_dir, "hsh798_snapshot", rows)
