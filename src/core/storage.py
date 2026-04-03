import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from .models import AccountStore, Hsh798AccountEntry, PgshAccountEntry


def load_accounts(path: Path) -> AccountStore:
    """Load account store JSON, returning an empty store when the file is absent or blank."""
    if not path.exists():
        logger.warning(f"accounts file not found: {path}")
        return AccountStore()

    raw = path.read_text(encoding="utf-8-sig")
    if not raw.strip():
        logger.warning(f"accounts file is empty: {path}")
        return AccountStore()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid accounts JSON in {path}: {exc.msg} (line {exc.lineno}, column {exc.colno})") from exc

    if data is None:
        logger.warning(f"accounts file contained null JSON; treating as empty store: {path}")
        return AccountStore()

    if not isinstance(data, dict):
        raise ValueError(f"invalid accounts JSON in {path}: top-level value must be an object")

    if "pgsh" not in data and "hsh798" not in data:
        raise ValueError(
            f"invalid accounts JSON in {path}: expected at least one of 'pgsh' or 'hsh798' at top level"
        )

    normalized = dict(data)
    normalized.setdefault("pgsh", [])
    normalized.setdefault("hsh798", [])

    return AccountStore.model_validate(normalized)


def save_accounts(path: Path, store: AccountStore) -> None:
    """Persist the account store in UTF-8 with BOM for round-trip compatibility on Windows editors."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"{store.model_dump_json(indent=2, exclude_none=True)}\n",
        encoding="utf-8-sig",
    )
    logger.debug(f"saved accounts store to {path}")


def write_json(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"{json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)}\n",
        encoding="utf-8",
    )
    return path


def write_snapshot_bundle(output_dir: str | Path, prefix: str, data: Any) -> Path:
    """Write timestamped/latest snapshot files and a lightweight manifest.

    Returns the timestamped snapshot path so callers can keep a stable audit trail
    while still reading the companion `<prefix>_latest.json` file for the newest view.
    """
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    safe_prefix = prefix.strip().replace(" ", "_")
    if not safe_prefix:
        raise ValueError("prefix must not be blank")

    now = datetime.now().astimezone()
    ts = now.strftime("%Y%m%d_%H%M%S")
    stamped_file = output_root / f"{safe_prefix}_{ts}.json"
    latest_file = output_root / f"{safe_prefix}_latest.json"
    manifest_file = output_root / f"{safe_prefix}_manifest.json"

    write_json(stamped_file, data)
    write_json(latest_file, data)
    write_json(
        manifest_file,
        {
            "prefix": safe_prefix,
            "generated_at": now.isoformat(timespec="seconds"),
            "latest_file": latest_file.name,
            "stamped_file": stamped_file.name,
            "rows": _extract_row_count(data),
        },
    )
    return stamped_file


def _extract_row_count(data: Any) -> int | None:
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        rows = data.get("rows")
        if isinstance(rows, list):
            return len(rows)
        meta = data.get("meta")
        if isinstance(meta, dict) and isinstance(meta.get("row_count"), int):
            return meta["row_count"]
    return None


def upsert_pgsh_account(
    path: Path,
    *,
    token: str,
    phone: str | None = None,
    phone_brand: str = "Xiaomi",
    user_name: str | None = None,
    note: str | None = None,
    last_login_at: str | None = None,
    account_index: int | None = None,
) -> tuple[AccountStore, int, PgshAccountEntry]:
    normalized_token = token.strip()
    normalized_phone = phone.strip() if phone is not None else None
    normalized_user_name = user_name.strip() if user_name is not None else None
    if not normalized_token:
        raise ValueError("token must not be blank")
    if normalized_phone is not None and not normalized_phone:
        raise ValueError("phone must not be blank when provided")
    if normalized_user_name is not None and not normalized_user_name:
        normalized_user_name = None

    store = load_accounts(path)

    if account_index is None:
        for index, item in enumerate(store.pgsh):
            if item.token == normalized_token or (normalized_phone and item.phone == normalized_phone):
                account_index = index
                break

    if account_index is not None and account_index < 0:
        raise ValueError("account_index must be >= 0")

    while account_index is not None and len(store.pgsh) <= account_index:
        store.pgsh.append(PgshAccountEntry())

    if account_index is None:
        current = PgshAccountEntry()
        store.pgsh.append(current)
        account_index = len(store.pgsh) - 1
    else:
        current = store.pgsh[account_index]

    updated = current.model_copy(
        update={
            "phone": normalized_phone if normalized_phone is not None else current.phone,
            "token": normalized_token,
            "phone_brand": ((phone_brand or current.phone_brand or "Xiaomi").strip() or "Xiaomi"),
            "user_name": normalized_user_name if normalized_user_name is not None else current.user_name,
            "note": note if note is not None else current.note,
            "last_login_at": last_login_at if last_login_at is not None else current.last_login_at,
        }
    )
    store.pgsh[account_index] = updated
    save_accounts(path, store)
    return store, account_index, updated


def upsert_hsh798_account(
    path: Path,
    *,
    phone: str,
    token: str,
    uid: str | None = None,
    eid: str | None = None,
    note: str | None = None,
    account_index: int | None = None,
) -> tuple[AccountStore, int, Hsh798AccountEntry]:
    normalized_phone = phone.strip()
    normalized_token = token.strip()
    if not normalized_phone:
        raise ValueError("phone must not be blank")
    if not normalized_token:
        raise ValueError("token must not be blank")

    store = load_accounts(path)
    timestamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    if account_index is None:
        for index, item in enumerate(store.hsh798):
            if item.phone == normalized_phone:
                account_index = index
                break

    if account_index is not None and account_index < 0:
        raise ValueError("account_index must be >= 0")

    while account_index is not None and len(store.hsh798) <= account_index:
        store.hsh798.append(Hsh798AccountEntry())

    if account_index is None:
        current = Hsh798AccountEntry()
        store.hsh798.append(current)
        account_index = len(store.hsh798) - 1
    else:
        current = store.hsh798[account_index]

    updated = current.model_copy(
        update={
            "phone": normalized_phone,
            "token": normalized_token,
            "uid": uid if uid is not None else current.uid,
            "eid": eid if eid is not None else current.eid,
            "note": note if note is not None else current.note,
            "last_login_at": timestamp,
        }
    )
    store.hsh798[account_index] = updated
    save_accounts(path, store)
    return store, account_index, updated
