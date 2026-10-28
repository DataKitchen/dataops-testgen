"""Resolving a contract document's quality rules onto test types, walking the rules a document holds, and the
tables a contract's tests may target."""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from testgen.common.contract_document import declared_tables, physical_column_names, physical_name
from testgen.common.database.table_group_service import table_group_qualifies_table_refs
from testgen.common.enums import SuiteType
from testgen.common.flavors import SqlFlavorCode
from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import NON_PUBLIC_TEST_TYPES, TestType
from testgen.common.models.test_suite import TestSuite, TestSuiteMinimal
from testgen.common.odcs.quality_rules import (
    Operator,
    ResolvedTerm,
    RuleScope,
    rename_argument_columns,
    resolve_rule,
    test_type_parameters,
)


class UndeclaredTableError(ValueError):
    """A test on a contract targets a table the contract does not declare."""

    def __init__(self, contract_name: str, table_name: str | None, declared: list[str]) -> None:
        self.contract_name = contract_name
        self.table_name = table_name
        self.declared = declared
        super().__init__(
            f"Contract {contract_name} does not declare table {table_name}."
            if table_name
            else f"A test on contract {contract_name} must name one of its declared tables."
        )


def writable_tables(suite: TestSuite | TestSuiteMinimal) -> list[str] | None:
    """The tables a test on ``suite`` may target: those the contract version its writes land on declares.

    ``None`` when ``suite`` is not a contract, since any table group table is a valid target then.
    """
    if suite.suite_type != SuiteType.CONTRACT:
        return None
    # A write to a contract with no draft opens one from the version in force, copying its document.
    version = SuiteVersion.draft_for(suite.id) or SuiteVersion.in_force_for(suite.id)
    return declared_tables(version.metadata_document if version else None)


def check_table_declared(suite: TestSuite | TestSuiteMinimal, table_name: str | None) -> None:
    """Raise ``UndeclaredTableError`` when ``suite`` is a contract that does not declare ``table_name``."""
    tables = writable_tables(suite)
    if tables is not None and table_name not in tables:
        raise UndeclaredTableError(suite.test_suite, table_name, tables)


def all_test_types() -> dict[str, TestType]:
    return {row.test_type: row for row in get_current_session().scalars(select(TestType))}


@dataclass(frozen=True)
class RuleResolver:
    """Resolves quality rules onto the test types of one connection's flavor."""

    test_types: dict[str, TestType]
    flavor: SqlFlavorCode
    qualify_tables: bool
    known_test_types: frozenset[str] = field(init=False)
    parameters_by_type: dict[str, frozenset[str]] = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "known_test_types", frozenset(self.test_types) - NON_PUBLIC_TEST_TYPES)
        object.__setattr__(
            self,
            "parameters_by_type",
            {code: frozenset(test_type_parameters(test_type)) for code, test_type in self.test_types.items()},
        )

    @classmethod
    def for_table_group(cls, table_group: TableGroup, connection: Connection) -> "RuleResolver":
        return cls(
            test_types=all_test_types(),
            flavor=SqlFlavorCode(connection.sql_flavor_code),
            qualify_tables=table_group_qualifies_table_refs(table_group.id),
        )

    def resolve(
        self,
        rule: Any,
        scope: RuleScope,
        table_name: str,
        column_name: str | None,
        columns: Mapping[str, str] | None = None,
    ) -> ResolvedTerm | None:
        """The term ``rule`` states, or ``None`` when no test type checks it.

        ``columns`` maps the table's property names to the column each names, for a rule whose
        arguments list properties.
        """
        if not isinstance(rule, dict):
            return None
        return resolve_rule(
            rename_argument_columns(rule, columns or {}), scope, self.known_test_types, column_name,
            flavor=self.flavor, table_name=table_name, qualify_tables=self.qualify_tables,
            declared_parameters=self.parameters_by_type,
        )


@dataclass(frozen=True)
class DocumentRules:
    """One ``quality`` list of a document, with the node it sits on.

    ``nested`` marks a list under a nested property, whose rules no term can check. ``columns`` maps
    the table's property names to the column each names.
    """

    rules: list[Any]
    scope: RuleScope
    table_name: str
    column_name: str | None
    path: str
    label: str
    nested: bool = False
    columns: dict[str, str] = field(default_factory=dict)


def document_rules(document: dict[str, Any]) -> Iterator[DocumentRules]:
    """Every ``quality`` list in ``document``: on each table, each column, and each nested property.

    ``path`` is the list's JSON path, and ``label`` names its node as ``table`` or ``table.column``.
    """
    for table_index, table in enumerate(document.get("schema") or []):
        if not isinstance(table, dict) or not table.get("name"):
            continue
        table_name = physical_name(table)
        table_path = f"$.schema[{table_index}]"
        columns = physical_column_names(table)
        if isinstance(table.get("quality"), list):
            yield DocumentRules(
                table["quality"], RuleScope.TABLE, table_name, None, f"{table_path}.quality", table_name,
                columns=columns,
            )
        for prop_index, prop in enumerate(table.get("properties") or []):
            if not isinstance(prop, dict) or not prop.get("name"):
                continue
            column_name = physical_name(prop)
            prop_path = f"{table_path}.properties[{prop_index}]"
            label = f"{table_name}.{column_name}"
            if isinstance(prop.get("quality"), list):
                yield DocumentRules(
                    prop["quality"], RuleScope.COLUMN, table_name, column_name, f"{prop_path}.quality", label,
                    columns=columns,
                )
            for nested, nested_path, nested_label in nested_properties(prop, prop_path, label):
                if isinstance(nested.get("quality"), list):
                    yield DocumentRules(
                        nested["quality"], RuleScope.COLUMN, table_name, column_name, f"{nested_path}.quality",
                        nested_label, nested=True,
                    )


def nested_properties(prop: dict[str, Any], path: str, label: str) -> list[tuple[dict[str, Any], str, str]]:
    """The properties nested under an object or array column, at any depth, each with its JSON path and dotted label."""
    found = []
    children = [
        (child, f"{path}.properties[{index}]", child.get("name"))
        for index, child in enumerate(prop.get("properties") or [])
        if isinstance(child, dict)
    ]
    if isinstance(prop.get("items"), dict):
        children.append((prop["items"], f"{path}.items", prop["items"].get("name") or "items"))
    for node, child_path, name in children:
        child_label = f"{label}.{name}"
        found.append((node, child_path, child_label))
        found += nested_properties(node, child_path, child_label)
    return found


def rule_label(rule: Any, index: int, node_label: str) -> str:
    """``node_label`` and the rule's id or name, or its position when it has neither."""
    if isinstance(rule, dict):
        for key in ("id", "name"):
            if isinstance(rule.get(key), str) and rule[key]:
                return f"{node_label}: {rule[key]}"
    return f"{node_label}: rule {index + 1}"


def describe_rule(rule: Any) -> str:
    """The rule's type, metric, unit, and acceptance operators.

    E.g. ``library nullValues in percent, mustBeLessThan``.
    """
    if not isinstance(rule, dict):
        return "not a rule object"
    rule_type = rule.get("type") or "library"
    shape = str(rule_type)
    if rule_type == "library":
        unit = rule.get("unit", "rows")
        shape += f" {rule.get('metric') or 'without a metric'} in {unit if unit else repr(unit)}"
    elif rule_type == "custom" and rule.get("engine"):
        shape += f" for engine {rule['engine']}"
    operators = [operator.value for operator in Operator if operator.value in rule]
    return f"{shape}, {', '.join(operators)}" if operators else shape
