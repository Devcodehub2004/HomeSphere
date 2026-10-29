import re
import unicodedata
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


def safe_filename(value: str) -> str:
    value = unicodedata.normalize("NFC", value).strip()
    if (
        not value or value in {".", ".."} or value.startswith(".")
        or len(value.encode("utf-8")) > 255
        or any(c in '/\\<>:"|?*' or unicodedata.category(c).startswith("C") for c in value)
        or value.endswith(".")
        or re.fullmatch(r"(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", value, re.I)
    ):
        raise ValueError("Use a plain filename of 1–255 UTF-8 bytes without paths or control characters")
    return value


class FileRename(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return safe_filename(value)


class FileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    size_bytes: int
    content_type: str
    sha256: str
    created_at: datetime
    folder_id: str | None
    deleted_at: datetime | None
