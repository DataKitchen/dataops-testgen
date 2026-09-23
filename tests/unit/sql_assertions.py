"""Assertions on the shape of the SQL a call emitted, for tests that mock the session."""

from unittest.mock import MagicMock

from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList


def emitted_statements(session: MagicMock) -> list:
    """The statements the call under test passed to the session.

    Covers ``execute`` and ``scalars`` alike, so a read issued through either is seen.
    """
    statements = [
        call.args[0]
        for call in (*session.execute.call_args_list, *session.scalars.call_args_list)
        if call.args
    ]
    assert statements, "the call issued no statement"
    return statements


def conjuncts(clause) -> list:
    """The terms a statement's WHERE clause ANDs together, flattened.

    An OR-ed predicate does not flatten into its branches, so a check built from these terms
    cannot be satisfied by either branch alone the way a substring check on the compiled SQL can.
    """
    if clause is None:
        return []
    if isinstance(clause, BooleanClauseList) and clause.operator is operators.and_:
        return [term for child in clause.clauses for term in conjuncts(child)]
    return [clause]


def equality_conjunct(term, column_key: str, table_name: str, value) -> bool:
    """Whether ``term`` equates the given table's column to ``value``."""
    if not isinstance(term, BinaryExpression) or term.operator is not operators.eq:
        return False
    left = term.left
    return (
        getattr(left, "key", None) == column_key
        and getattr(left.table, "name", None) == table_name
        and getattr(term.right, "value", None) == value
    )


def _is_unary_null_check(term, column_key: str, table_name: str, operator) -> bool:
    if not isinstance(term, BinaryExpression) or term.operator is not operator:
        return False
    left = term.left
    return getattr(left, "key", None) == column_key and getattr(left.table, "name", None) == table_name


def is_null_conjunct(term, column_key: str, table_name: str) -> bool:
    """Whether ``term`` is an ``IS NULL`` check on the given table's column."""
    return _is_unary_null_check(term, column_key, table_name, operators.is_)


def is_not_null_conjunct(term, column_key: str, table_name: str) -> bool:
    """Whether ``term`` is an ``IS NOT NULL`` check on the given table's column."""
    return _is_unary_null_check(term, column_key, table_name, operators.is_not)


def _narrows_to_a_version(clause) -> bool:
    for term in conjuncts(clause):
        if not isinstance(term, BinaryExpression) or term.operator is not operators.eq:
            continue
        left = term.left
        if getattr(left, "key", None) != "version_id" or left.table.name != "test_definitions":
            continue
        if "suite_versions" in str(term.right):
            return True
    return False


def scopes_to_a_version(statement) -> bool:
    """Whether the statement ANDs in an equality between the version column and a resolution.

    Subqueries and CTEs count, so a union or a paginated count reads as scoped when the select
    it wraps is. Substring presence would not be enough: it also holds for an OR-ed predicate
    and for a version column that only appears in the projection.
    """
    seen, pending = set(), [statement]
    while pending:
        element = pending.pop()
        if id(element) in seen:
            continue
        seen.add(id(element))
        if _narrows_to_a_version(getattr(element, "whereclause", None)):
            return True
        pending.extend(element.get_children())
    return False
