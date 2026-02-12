from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from testgen.common.models.custom_types import (
    EncryptedBytea,
    EncryptedJson,
    NullIfEmptyString,
    UpdateTimestamp,
    YNString,
    ZeroIfEmptyInteger,
)

pytestmark = pytest.mark.unit


# --- NullIfEmptyString ---

@pytest.mark.parametrize(
    "value, expected",
    [
        ("", None),
        ("hello", "hello"),
        (None, None),
    ],
)
def test_null_if_empty_string(value, expected):
    t = NullIfEmptyString()
    assert t.process_bind_param(value, None) == expected


# --- YNString ---

@pytest.mark.parametrize(
    "value, expected",
    [
        (True, "Y"),
        (False, "N"),
        ("Y", "Y"),
        ("N", "N"),
        (None, None),
    ],
)
def test_yn_string_bind(value, expected):
    t = YNString()
    assert t.process_bind_param(value, None) == expected


@pytest.mark.parametrize(
    "value, expected",
    [
        ("Y", True),
        ("N", False),
        (None, None),
    ],
)
def test_yn_string_result(value, expected):
    t = YNString()
    assert t.process_result_value(value, None) == expected


# --- ZeroIfEmptyInteger ---

@pytest.mark.parametrize(
    "value, expected",
    [
        (5, 5),
        (0, 0),
        ("", 0),
        (None, 0),
    ],
)
def test_zero_if_empty_integer(value, expected):
    t = ZeroIfEmptyInteger()
    assert t.process_bind_param(value, None) == expected


# --- UpdateTimestamp ---

def test_update_timestamp():
    t = UpdateTimestamp()
    before = datetime.now(UTC)
    result = t.process_bind_param("ignored", None)
    after = datetime.now(UTC)
    assert before <= result <= after


# --- EncryptedBytea roundtrip ---

@patch("testgen.common.encrypt.settings")
def test_encrypted_bytea_roundtrip(mock_settings):
    mock_settings.APP_ENCRYPTION_SALT = "testsalt12345678"
    mock_settings.APP_ENCRYPTION_SECRET = "testsecret123456"  # noqa: S105

    t = EncryptedBytea()
    original = "sensitive data"

    encrypted = t.process_bind_param(original, None)
    assert encrypted != original.encode()

    decrypted = t.process_result_value(encrypted, None)
    assert decrypted == original


@patch("testgen.common.encrypt.settings")
def test_encrypted_bytea_none(mock_settings):
    t = EncryptedBytea()
    assert t.process_bind_param(None, None) is None
    assert t.process_result_value(None, None) is None


# --- EncryptedJson roundtrip ---

@patch("testgen.common.encrypt.settings")
def test_encrypted_json_roundtrip(mock_settings):
    mock_settings.APP_ENCRYPTION_SALT = "testsalt12345678"
    mock_settings.APP_ENCRYPTION_SECRET = "testsecret123456"  # noqa: S105

    t = EncryptedJson()
    original = {"key": "value", "num": 42, "list": [1, 2, 3]}

    encrypted = t.process_bind_param(original, None)
    decrypted = t.process_result_value(encrypted, None)
    assert decrypted == original


@patch("testgen.common.encrypt.settings")
def test_encrypted_json_none(mock_settings):
    t = EncryptedJson()
    assert t.process_bind_param(None, None) is None
    assert t.process_result_value(None, None) is None
