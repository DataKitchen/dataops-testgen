import logging
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from unittest.mock import patch
from uuid import UUID

import pandas as pd
import pytest

from testgen.utils import (
    chunk_queries,
    friendly_score,
    friendly_score_impact,
    get_exception_message,
    is_uuid4,
    log_and_swallow_exception,
    make_json_safe,
    score,
    str_to_timestamp,
    to_dataframe,
    to_int,
    to_sql_timestamp,
    try_json,
)

pytestmark = pytest.mark.unit


# --- to_int ---

@pytest.mark.parametrize(
    "value, expected",
    [
        (5, 5),
        (3.7, 3),
        (0, 0),
        (0.0, 0),
        (float("nan"), 0),
        (None, 0),
    ],
)
def test_to_int(value, expected):
    assert to_int(value) == expected


# --- to_sql_timestamp ---

def test_to_sql_timestamp():
    dt = datetime(2024, 3, 15, 10, 30, 45)
    assert to_sql_timestamp(dt) == "2024-03-15 10:30:45"


# --- str_to_timestamp ---

@pytest.mark.parametrize(
    "value, expected",
    [
        ("2024-03-15 10:30:45", int(datetime(2024, 3, 15, 10, 30, 45, tzinfo=UTC).timestamp())),
        ("2024-03-15T10:30:45Z", int(datetime(2024, 3, 15, 10, 30, 45, tzinfo=UTC).timestamp())),
        ("not-a-date", None),
    ],
)
def test_str_to_timestamp(value, expected):
    assert str_to_timestamp(value) == expected


# --- is_uuid4 ---

@pytest.mark.parametrize(
    "value, expected",
    [
        ("550e8400-e29b-41d4-a716-446655440000", True),
        (UUID("550e8400-e29b-41d4-a716-446655440000"), True),
        ("not-a-uuid", False),
        ("", False),
        ("550e8400-e29b-41d4-a716-44665544000", False),  # too short
    ],
)
def test_is_uuid4(value, expected):
    assert is_uuid4(value) == expected


# --- try_json ---

@pytest.mark.parametrize(
    "value, default, expected",
    [
        ('{"a": 1}', None, {"a": 1}),
        ("[1, 2, 3]", None, [1, 2, 3]),
        ("invalid", "fallback", "fallback"),
        (None, "default", "default"),
        ("null", None, None),
    ],
)
def test_try_json(value, default, expected):
    assert try_json(value, default) == expected


# --- get_exception_message ---

def test_get_exception_message_string_arg():
    exc = ValueError("something went wrong  ")
    assert get_exception_message(exc) == "something went wrong"


def test_get_exception_message_non_string_arg():
    exc = ValueError(42)
    assert get_exception_message(exc) == "42"


def test_get_exception_message_no_args():
    exc = ValueError()
    assert get_exception_message(exc) == ""


# --- make_json_safe ---

def test_make_json_safe_uuid():
    uid = UUID("550e8400-e29b-41d4-a716-446655440000")
    assert make_json_safe(uid) == "550e8400-e29b-41d4-a716-446655440000"


def test_make_json_safe_datetime():
    dt = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)
    assert make_json_safe(dt) == int(dt.timestamp())


def test_make_json_safe_decimal():
    assert make_json_safe(Decimal("3.14")) == 3.14


def test_make_json_safe_enum():
    class Color(Enum):
        RED = "red"
    assert make_json_safe(Color.RED) == "red"


def test_make_json_safe_list():
    uid = UUID("550e8400-e29b-41d4-a716-446655440000")
    result = make_json_safe([uid, 42])
    assert result == ["550e8400-e29b-41d4-a716-446655440000", 42]


def test_make_json_safe_dict():
    uid = UUID("550e8400-e29b-41d4-a716-446655440000")
    result = make_json_safe({"id": uid, "name": "test"})
    assert result == {"id": "550e8400-e29b-41d4-a716-446655440000", "name": "test"}


def test_make_json_safe_passthrough():
    assert make_json_safe("hello") == "hello"
    assert make_json_safe(42) == 42
    assert make_json_safe(None) is None


# --- chunk_queries ---

def test_chunk_queries_fits_in_one():
    queries = ["SELECT 1", "SELECT 2"]
    result = chunk_queries(queries, " UNION ALL ", 100)
    assert result == ["SELECT 1 UNION ALL SELECT 2"]


def test_chunk_queries_needs_splitting():
    queries = ["SELECT 1", "SELECT 2", "SELECT 3"]
    result = chunk_queries(queries, " UNION ALL ", 30)
    assert len(result) > 1
    for chunk in result:
        assert len(chunk) <= 30


def test_chunk_queries_single_query():
    result = chunk_queries(["SELECT 1"], ";", 100)
    assert result == ["SELECT 1"]


def test_chunk_queries_each_at_limit():
    queries = ["A" * 10, "B" * 10, "C" * 10]
    result = chunk_queries(queries, ";", 11)
    assert result == ["A" * 10, "B" * 10, "C" * 10]


# --- score ---

@pytest.mark.parametrize(
    "profiling, tests, expected",
    [
        (0.9, 0.8, 0.9 * 0.8),
        (0.9, 0.0, 0.9),
        (0.0, 0.8, 0.8),
        (0.0, 0.0, 0.0),
        (float("nan"), 0.8, 0.8),
        (0.9, float("nan"), 0.9),
        (float("nan"), float("nan"), 0.0),
    ],
)
def test_score(profiling, tests, expected):
    assert score(profiling, tests) == pytest.approx(expected)


# --- friendly_score ---

@pytest.mark.parametrize(
    "value, expected",
    [
        (1.0, "100"),
        (0.956, "95.6"),
        (0.0001, "< 0.1"),
        (0.99999, "> 99.9"),
        (0.5, "50.0"),
        (None, None),
        (0, None),
        (float("nan"), None),
    ],
)
def test_friendly_score(value, expected):
    assert friendly_score(value) == expected


# --- friendly_score_impact ---

@pytest.mark.parametrize(
    "value, expected",
    [
        (100, "100"),
        (50.123, "50.12"),
        (0.001, "< 0.01"),
        (99.999, "> 99.99"),
        (None, "-"),
        (0, "-"),
        (float("nan"), "-"),
    ],
)
def test_friendly_score_impact(value, expected):
    assert friendly_score_impact(value) == expected


# --- to_dataframe ---

def test_to_dataframe_with_to_dict():
    class Item:
        def to_dict(self):
            return {"a": 1, "b": 2}

    df = to_dataframe([Item(), Item()])
    assert list(df.columns) == ["a", "b"]
    assert len(df) == 2


def test_to_dataframe_with_dict_attr():
    class Item:
        def __init__(self):
            self.x = 10
            self.y = 20

    df = to_dataframe([Item()])
    assert df.iloc[0]["x"] == 10
    assert df.iloc[0]["y"] == 20


def test_to_dataframe_with_plain_dict():
    df = to_dataframe([{"k": "v"}])
    assert df.iloc[0]["k"] == "v"


def test_to_dataframe_empty():
    df = to_dataframe([])
    assert len(df) == 0


# --- log_and_swallow_exception ---

def test_log_and_swallow_exception_no_error():
    @log_and_swallow_exception
    def good_func():
        return 42

    good_func()  # should not raise


def test_log_and_swallow_exception_swallows(caplog):
    @log_and_swallow_exception
    def bad_func():
        raise RuntimeError("boom")

    with caplog.at_level(logging.ERROR, logger="testgen"):
        bad_func()  # should not raise

    assert "boom" in caplog.text
