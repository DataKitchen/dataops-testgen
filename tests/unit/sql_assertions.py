"""Assertions on the shape of the SQL a call emitted, for tests that mock the session."""

from unittest.mock import MagicMock

from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BinaryExpression, BooleanClauseList


def emitted_statements(session: MagicMock) -> list:
    """The statements passed to ``session.execute`` by the call under test."""
    statements = [call.args[0] for call in session.execute.call_args_list]
    assert statements, "the call issued no statement"
    return statements


def _conjuncts(clause) -> list:
    """The terms a statement's WHERE clause ANDs together, flattened."""
    if clause is None:
        return []
    if isinstance(clause, BooleanClauseList) and clause.operator is operators.and_:
        return [term for child in clause.clauses for term in _conjuncts(child)]
    return [clause]


def _narrows_to_a_version(clause) -> bool:
    for term in _conjuncts(clause):
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
