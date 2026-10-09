import pytest
from sqlalchemy import String

from testgen.common.enums import SuiteType
from testgen.common.models.test_suite import TestSuite


def test_suite_type_column_is_not_null_and_defaults_to_regular():
    column = TestSuite.__table__.c.suite_type

    assert column.nullable is False
    assert column.default.arg == SuiteType.REGULAR
    assert "regular" in str(column.server_default.arg)


def test_suite_type_column_is_wide_enough_for_every_member():
    column = TestSuite.__table__.c.suite_type

    assert isinstance(column.type, String)
    assert column.type.length >= max(len(member.value) for member in SuiteType)


def test_the_monitor_flag_is_gone():
    assert "is_monitor" not in TestSuite.__table__.c


def test_deactivate_invalid_tests_column_is_not_null_and_defaults_to_false():
    column = TestSuite.__table__.c.deactivate_invalid_tests

    assert column.nullable is False
    assert column.default.arg is False


@pytest.mark.parametrize(
    ("suite_type", "setting", "expected"),
    [
        (SuiteType.REGULAR, True, True),
        (SuiteType.REGULAR, False, False),
        (SuiteType.MONITOR, False, True),
        (SuiteType.CONTRACT, True, False),
    ],
)
def test_deactivates_invalid_tests_follows_the_setting_for_regular_suites_only(suite_type, setting, expected):
    suite = TestSuite(suite_type=suite_type, deactivate_invalid_tests=setting)

    assert suite.deactivates_invalid_tests is expected
