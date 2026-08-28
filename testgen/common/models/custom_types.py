import json
import logging
from datetime import UTC, datetime
from types import NoneType

from sqlalchemy import Integer, String, TypeDecorator
from sqlalchemy.dialects import postgresql

from testgen.common.encrypt import DecryptText, EncryptText

LOG = logging.getLogger("testgen")

JSON_TYPE = str | int | float | list | dict | NoneType


class NullIfEmptyString(TypeDecorator):
    impl = String
    cache_ok = True

    def process_bind_param(self, value: str, _dialect) -> str | None:
        return None if value == "" else value


class YNString(TypeDecorator):
    impl = String
    cache_ok = True

    def process_bind_param(self, value: bool | str | None, _dialect) -> str | None:
        if isinstance(value, bool):
            return "Y" if value else "N"
        return value

    def process_result_value(self, value: str | None, _dialect) -> bool | None:
        if isinstance(value, str):
            return value == "Y"
        return value


class ZeroIfEmptyInteger(TypeDecorator):
    impl = Integer
    cache_ok = True

    def process_bind_param(self, value: str | int, _dialect) -> int:
        return value or 0


class UpdateTimestamp(TypeDecorator):
    impl = postgresql.TIMESTAMP
    cache_ok = True

    def process_bind_param(self, _value, _dialect) -> datetime:
        return datetime.now(UTC)


class EncryptedBytea(TypeDecorator):
    impl = postgresql.BYTEA
    cache_ok = True

    def process_bind_param(self, value: str, _dialect) -> bytes:
        return EncryptText(value).encode("UTF-8") if value is not None else value

    def process_result_value(self, value: bytes, _dialect) -> str:
        return DecryptText(value) if value is not None else value


class EncryptedJson(EncryptedBytea):

    def process_bind_param(self, value: JSON_TYPE, _dialect) -> bytes:
        return None if value is None else super().process_bind_param(json.dumps(value), _dialect)

    def process_result_value(self, value: bytes, _dialect) -> JSON_TYPE:
        return None if value is None else json.loads(super().process_result_value(value, _dialect))


class SafeEncryptedJson(EncryptedJson):
    """``EncryptedJson`` that returns ``None`` (and logs) instead of raising on decrypt failure.

    AES-CBC has no authentication tag, so a rotated or mistyped
    ``TG_DECRYPT_PASSWORD`` returns garbage that ``json.loads`` then rejects.
    Use this for columns loaded in bulk queries where one undecryptable row
    should degrade to a delivery-time failure for that row alone rather than
    500-ing the entire list. Callers must treat ``None`` as "value unavailable"
    -- the model's ``_validate`` still enforces presence at save time.
    """

    def process_result_value(self, value: bytes, _dialect) -> JSON_TYPE:
        if value is None:
            return None
        try:
            return super().process_result_value(value, _dialect)
        except Exception:
            LOG.warning(
                "Failed to decrypt encrypted-JSON column value; returning None. "
                "Likely cause: TG_DECRYPT_PASSWORD rotation without re-encrypting stored rows.",
            )
            return None
