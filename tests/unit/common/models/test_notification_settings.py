"""Tests for ``NotificationSettings`` query semantics.

The listing surface (``list_for_test_suite`` / ``list_for_table_group`` /
``list_for_score_definition``) must use strict equality on the scope column —
no ``IS NULL`` wildcard. The firing-pipeline surface (``_base_select_query``)
must keep the ``IS NULL`` wildcard so a project-wide notification matches
events on any child entity.
"""

from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from testgen.common.models.notification_settings import NotificationSettings, is_valid_email

pytestmark = pytest.mark.unit


# ─── Shared email validation helper ───────────────────────────────────


@pytest.mark.parametrize("addr", [
    "alice@example.com",
    "a.b+tag@sub.domain.co",
    "x_y%z@host-name.io",
])
def test_is_valid_email_accepts_well_formed(addr):
    assert is_valid_email(addr) is True


@pytest.mark.parametrize("addr", [
    "no-at-sign",
    "spaces in@here.com",
    "nodot@nope",
    "@nodomain.com",
    "trailing@dot.",
    "",
])
def test_is_valid_email_rejects_malformed(addr):
    assert is_valid_email(addr) is False


def _captured_list_sql(method_name: str, *args, **kwargs) -> str:
    """Invoke a ``list_for_*`` classmethod and compile the query it passes to ``_paginate``."""
    with patch.object(NotificationSettings, "_paginate", return_value=([], 0)) as mock_paginate:
        getattr(NotificationSettings, method_name)(*args, **kwargs)
    query = mock_paginate.call_args.args[0]
    return str(query.compile(compile_kwargs={"literal_binds": True}))


def _uuid_in_sql(value: UUID, sql: str) -> bool:
    """SQLAlchemy literal_binds compiles UUIDs as 32-char hex (no dashes); accept either."""
    return str(value) in sql or value.hex in sql


# ─── Listing surface — strict equality, no IS NULL ────────────────────


def test_list_for_test_suite_filters_by_strict_equality_only():
    suite_id = uuid4()
    sql = _captured_list_sql("list_for_test_suite", suite_id)

    assert "IS NULL" not in sql.upper(), (
        "list_for_test_suite must not surface rows where test_suite_id IS NULL — "
        "they may be unrelated event types whose scope column happens to be null."
    )
    assert "test_suite_id" in sql
    assert _uuid_in_sql(suite_id, sql)


def test_list_for_table_group_filters_by_strict_equality_only():
    table_group_id = uuid4()
    sql = _captured_list_sql("list_for_table_group", table_group_id)

    assert "IS NULL" not in sql.upper(), (
        "list_for_table_group must not surface rows where table_group_id IS NULL — "
        "they may be unrelated event types whose scope column happens to be null."
    )
    assert "table_group_id" in sql
    assert _uuid_in_sql(table_group_id, sql)


def test_list_for_score_definition_filters_by_strict_equality_only():
    score_definition_id = uuid4()
    sql = _captured_list_sql("list_for_score_definition", score_definition_id)

    assert "IS NULL" not in sql.upper(), (
        "list_for_score_definition must not surface rows where score_definition_id IS NULL — "
        "they may be unrelated event types whose scope column happens to be null."
    )
    assert "score_definition_id" in sql
    assert _uuid_in_sql(score_definition_id, sql)


# ─── Firing pipeline — IS NULL preserved (regression guard) ───────────
#
# `_base_select_query` is consumed by the notification firing pipeline, where
# a notification with `<scope>_id IS NULL` legitimately means "fires for any
# child of that type in the same project." Leaving this branch alone is the
# whole reason the listing-side fix is scoped to the `list_for_*` helpers.


def _firing_query_sql(**kwargs) -> str:
    query = NotificationSettings._base_select_query(**kwargs)
    return str(query.compile(compile_kwargs={"literal_binds": True}))


def test_base_select_query_test_suite_keeps_null_wildcard():
    suite_id = uuid4()
    sql = _firing_query_sql(test_suite_id=suite_id)

    assert "IS NULL" in sql.upper(), (
        "_base_select_query is used by the firing pipeline, which needs "
        "test_suite_id IS NULL to mean 'fires for any suite in the project'."
    )
    assert _uuid_in_sql(suite_id, sql)


def test_base_select_query_table_group_keeps_null_wildcard():
    table_group_id = uuid4()
    sql = _firing_query_sql(table_group_id=table_group_id)

    assert "IS NULL" in sql.upper(), (
        "_base_select_query is used by the firing pipeline, which needs "
        "table_group_id IS NULL to mean 'fires for any table group in the project'."
    )
    assert _uuid_in_sql(table_group_id, sql)


def test_base_select_query_score_definition_keeps_null_wildcard():
    score_definition_id = uuid4()
    sql = _firing_query_sql(score_definition_id=score_definition_id)

    assert "IS NULL" in sql.upper(), (
        "_base_select_query is used by the firing pipeline, which needs "
        "score_definition_id IS NULL to mean 'fires for any scorecard in the project'."
    )
    assert _uuid_in_sql(score_definition_id, sql)
