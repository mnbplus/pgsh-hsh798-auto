from pathlib import Path
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class StrippingModel(BaseModel):
    @field_validator("*", mode="before", check_fields=False)
    @classmethod
    def _strip_string_fields(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value


class NonBlankDefaultsModel(StrippingModel):
    @field_validator("phone_brand", mode="after", check_fields=False)
    @classmethod
    def _normalize_phone_brand(cls, value: object) -> object:
        if isinstance(value, str) and not value:
            return "Xiaomi"
        return value


class PgshAccountEntry(NonBlankDefaultsModel):
    phone: str = ""
    token: str = ""
    phone_brand: str = "Xiaomi"
    note: str = ""
    user_name: str = ""
    last_login_at: str = ""


class Hsh798AccountEntry(StrippingModel):
    phone: str = ""
    token: str = ""
    uid: str = ""
    eid: str = ""
    note: str = ""
    last_login_at: str = ""


class AccountStore(BaseModel):
    pgsh: list[PgshAccountEntry] = Field(default_factory=list)
    hsh798: list[Hsh798AccountEntry] = Field(default_factory=list)


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PGHSH_", extra="ignore")
    accounts_file: Path = Path("configs/accounts.json")
