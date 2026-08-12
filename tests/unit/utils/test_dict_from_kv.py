"""Corner cases for the shared ``input_parameters`` kv parser.

``input_parameters`` is built with ``"; ".join(...)`` in ``execute_tests_query`` and read
back by the monitor series parsers and the dashboard. This is the only parser for that
format, so its edge behavior is pinned here.
"""

import pytest

from testgen.utils import dict_from_kv


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Empty inputs
        (None, {}),
        ("", {}),
        ("   ", {}),
        # Simple pairs, with and without the space the writer emits
        ("a=1;b=2", {"a": "1", "b": "2"}),
        ("a=1; b=2", {"a": "1", "b": "2"}),
        # Whitespace around keys and values is stripped
        ("  a  =  1  ;  b = 2 ", {"a": "1", "b": "2"}),
        # A fragment with no separator is skipped, NOT an IndexError
        ("a=1; garbage; b=2", {"a": "1", "b": "2"}),
        ("garbage", {}),
        # An empty value is KEPT (absent vs blank must stay distinguishable)
        ("a=; b=2", {"a": "", "b": "2"}),
        ("a=", {"a": ""}),
        # An empty key is skipped
        ("=1; b=2", {"b": "2"}),
        # Only the first separator splits — values may contain "="
        ("expr=a=b; b=2", {"expr": "a=b", "b": "2"}),
        # Trailing / doubled pair separators are ignored
        ("a=1;", {"a": "1"}),
        ("a=1;;b=2", {"a": "1", "b": "2"}),
        # Duplicate keys — last one wins
        ("a=1; a=2", {"a": "2"}),
    ],
)
def test_dict_from_kv_edge_cases(raw, expected):
    assert dict_from_kv(raw) == expected


@pytest.mark.unit
def test_dict_from_kv_custom_separators():
    assert dict_from_kv("a:1|b:2", pairs_seprator="|", kv_separator=":") == {"a": "1", "b": "2"}


@pytest.mark.unit
def test_dict_from_kv_realistic_monitor_parameters():
    raw = "lower_tolerance=1000.5; upper_tolerance=2000.0; threshold_value="
    assert dict_from_kv(raw) == {
        "lower_tolerance": "1000.5",
        "upper_tolerance": "2000.0",
        "threshold_value": "",
    }
