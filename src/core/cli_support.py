import json
from pathlib import Path

import typer

from .models import AccountStore, Hsh798AccountEntry, PgshAccountEntry
from .storage import load_accounts


def echo_json(data: object) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


def mask_secret(value: str, keep: int = 4) -> str:
    """Mask a secret while keeping a small prefix/suffix for human inspection."""
    if not value:
        return ""
    keep = max(0, keep)
    if keep == 0:
        return "*" * len(value)
    if len(value) <= keep * 2:
        return "*" * len(value)
    masked_length = max(3, len(value) - keep * 2)
    return f"{value[:keep]}{'*' * masked_length}{value[-keep:]}"


def mask_phone(value: str, keep_prefix: int = 3, keep_suffix: int = 4) -> str:
    """Mask phone numbers using a more readable mobile-friendly pattern."""
    if not value:
        return ""
    keep_prefix = max(0, keep_prefix)
    keep_suffix = max(0, keep_suffix)
    if len(value) <= keep_prefix + keep_suffix:
        return "*" * len(value)
    masked_length = max(3, len(value) - keep_prefix - keep_suffix)
    return f"{value[:keep_prefix]}{'*' * masked_length}{value[-keep_suffix:]}"


def dump_account_store(store: AccountStore, *, reveal_secrets: bool) -> dict:
    """Return account store data with secrets masked by default for safe CLI display."""
    data = store.model_dump()
    if reveal_secrets:
        return data
    for item in data.get("pgsh", []):
        item["token"] = mask_secret(item.get("token", ""))
        phone = item.get("phone")
        if phone:
            item["phone"] = mask_phone(phone)
    for item in data.get("hsh798", []):
        item["token"] = mask_secret(item.get("token", ""))
        phone = item.get("phone")
        if phone:
            item["phone"] = mask_phone(phone)
    return data


def resolve_pgsh_account(
    *,
    token: str | None,
    phone_brand: str | None,
    accounts_file: Path,
    account_index: int | None,
) -> PgshAccountEntry:
    """Resolve a single PGSH account from explicit token input or stored account index.

    Blank token strings are treated the same as an omitted token so CLI callers do not
    accidentally bypass account-index validation with `--token ""`.
    """
    normalized_token = token.strip() if token is not None else None
    if normalized_token == "":
        normalized_token = None

    if normalized_token and account_index is not None:
        raise typer.BadParameter("provide either --token or --account-index, not both")
    if normalized_token:
        return PgshAccountEntry(token=normalized_token, phone_brand=phone_brand or "Xiaomi")
    if account_index is None:
        raise typer.BadParameter("provide --token or --account-index")

    store = load_accounts(accounts_file)
    if account_index < 0:
        raise typer.BadParameter(f"pgsh account index must be >= 0: {account_index}")
    try:
        account = store.pgsh[account_index]
    except IndexError as exc:
        raise typer.BadParameter(
            f"pgsh account index out of range: {account_index} (available: 0..{len(store.pgsh) - 1} / total {len(store.pgsh)})"
        ) from exc
    if not account.token:
        raise typer.BadParameter(f"pgsh account {account_index} has no token")
    if phone_brand:
        account = account.model_copy(update={"phone_brand": phone_brand})
    return account


def resolve_pgsh_batch_selection(
    *,
    token: str | None,
    phone_brand: str | None,
    accounts_file: Path,
    account_index: int | None,
) -> tuple[PgshAccountEntry | None, int | None]:
    """Resolve optional single-account selection for batch-style PGSH commands.

    Returns the resolved account object plus the original configured account index
    when selection came from the account store. Token-based selection has no stable
    store index, so the second item stays None in that case.
    """
    if token is None and account_index is None:
        return None, None
    account = resolve_pgsh_account(
        token=token,
        phone_brand=phone_brand,
        accounts_file=accounts_file,
        account_index=account_index,
    )
    return account, None if token else account_index


def resolve_hsh798_account(
    *,
    token: str | None,
    accounts_file: Path,
    account_index: int | None,
) -> Hsh798AccountEntry:
    """Resolve a single HSH798 account from explicit token input or stored account index.

    Blank token strings are treated the same as an omitted token so CLI callers do not
    accidentally bypass account-index validation with `--token ""`.
    """
    normalized_token = token.strip() if token is not None else None
    if normalized_token == "":
        normalized_token = None

    if normalized_token and account_index is not None:
        raise typer.BadParameter("provide either --token or --account-index, not both")
    if normalized_token:
        return Hsh798AccountEntry(token=normalized_token)
    if account_index is None:
        raise typer.BadParameter("provide --token or --account-index")

    store = load_accounts(accounts_file)
    if account_index < 0:
        raise typer.BadParameter(f"hsh798 account index must be >= 0: {account_index}")
    try:
        account = store.hsh798[account_index]
    except IndexError as exc:
        raise typer.BadParameter(
            f"hsh798 account index out of range: {account_index} (available: 0..{len(store.hsh798) - 1} / total {len(store.hsh798)})"
        ) from exc
    if not account.token:
        raise typer.BadParameter(f"hsh798 account {account_index} has no token")
    return account
