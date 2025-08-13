from datetime import UTC, datetime

from sqlalchemy import Integer, String, TypeDecorator
from sqlalchemy.dialects import postgresql

from testgen.common.encrypt import DecryptText, EncryptText


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
