"""Importing an ODCS document as a contract, or as a new draft of one.

A document is the whole agreement. Its quality rules and column declarations that resolve to a
test type become the draft's terms, and everything else becomes the draft's metadata document,
with each rule no test type checks kept and marked unverifiable. Reconciling the incoming terms
against the contract's terms deletes the active terms the document omits, so the delta is always computed
first (``prepare_import``, which writes nothing) and applied only on request (``apply_import``).
"""

import copy
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

import yaml
from sqlalchemy import delete, select, update
from sqlalchemy.orm.attributes import flag_modified

from testgen.commands.test_generation import reconcile_contract_conformance
from testgen.common import contract_document
from testgen.common.clean_sql import parse_value_list
from testgen.common.contract_rules import (
    RuleResolver,
    all_test_types,
    describe_rule,
    nested_properties,
    rule_label,
)
from testgen.common.contract_service import InvalidContractDocumentError, resolve_write_target
from testgen.common.database.table_group_service import (
    apply_test_definition_flavor_rules,
    table_group_qualifies_table_refs,
)
from testgen.common.enums import MANAGED_TEST_TYPES, VALUE_LIST_TEST_TYPES, SuiteType
from testgen.common.flavors import FLAVOR_CODE_TO_FAMILY, FLAVOR_CODE_TO_LABEL, SqlFlavorCode
from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.data_column import DataColumnChars
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import (
    ODCS_RULE_METADATA_KEY,
    TERM_ID_MAX_LENGTH,
    InvalidTestDefinitionFields,
    TestDefinition,
    TestType,
    stored_value_list,
)
from testgen.common.models.test_suite import TestSuite
from testgen.common.odcs.physical_types import TypeMatch, compare_physical_types
from testgen.common.odcs.quality_rules import (
    RuleScope,
    RuleShape,
    drop_field,
    drop_generated_metadata,
    is_declaration_marker,
    is_synthesized_property,
    mark_unverifiable,
    names_one_column,
    resolve_declarations,
    resolve_unnamed_declarations,
    test_type_parameters,
)
from testgen.common.odcs.servers import FLAVOR_TO_SERVER_TYPE, ODCS_API_VERSION, ServerType
from testgen.common.odcs.validation import validate_document
from testgen.common.test_definition_export_import_service import ImportAction

LOG = logging.getLogger("testgen")

# The `testgen` property keeping a column's `physicalType` as the document's author wrote it,
# when import replaces it with the catalog's spelling or sets it aside.
AUTHORED_PHYSICAL_TYPE = "authoredPhysicalType"

# ODCS spellings that name the same server type as one TestGen maps a flavor to.
_SERVER_TYPE_ALIASES: dict[str, ServerType] = {ServerType.POSTGRESQL.value: ServerType.POSTGRES}


class ContractImportMode(StrEnum):
    PREVIEW = "preview"
    APPLY = "apply"


class ContractTermReason(StrEnum):
    MATCHED_BY_ID = "matched_by_id"
    MATCHED_BY_KEY = "matched_by_key"
    UNCHANGED = "unchanged"
    NEW = "new"
    ABSENT = "absent"


class ContractIdTakenError(InvalidContractDocumentError):
    """Raised when a document would create a contract whose ``id`` another contract in the table group holds."""

    def __init__(self, document_id: str, holder: TestSuite):
        self.document_id = document_id
        self.holder_id = holder.id
        self.holder_name = holder.test_suite
        super().__init__([
            f"$.id: contract `{holder.test_suite}` (`{holder.id}`) in this table group already has the contract `id` "
            f"`{document_id}`. To update that contract, import the document into it. To create a separate "
            "contract, change the document's `id`."
        ])


class ContractIdentityError(ValueError):
    """Raised when a document's contract ``id`` differs from the contract it is imported onto."""

    def __init__(self, target_id: str, incoming_id: str):
        self.target_id = target_id
        self.incoming_id = incoming_id
        super().__init__(
            f"The document's contract `id` is `{incoming_id}`, but this contract's is `{target_id}`, so the "
            "document is a different agreement. To import it into this contract, change the document's `id` "
            f"to `{target_id}`. If it is a separate agreement, import it as a new contract."
        )


@dataclass(frozen=True)
class IncomingTerm:
    """One term the document states: a quality rule or a column declaration that resolved.
    ``custom_rule`` is set for a rule of type ``custom``."""

    test_type: str
    table_name: str
    column_name: str | None
    parameters: dict[str, Any]
    contract_term_id: str | None
    metadata: dict[str, Any]
    custom_rule: bool = False


@dataclass(frozen=True)
class TermChange:
    """What reconciling one term does: create, update, skip (unchanged) or delete."""

    action: ImportAction
    reason: ContractTermReason
    test_type: str
    table_name: str
    column_name: str | None
    contract_term_id: str | None
    target_id: UUID | None = None
    incoming: IncomingTerm | None = None
    custom_metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class SplitDocument:
    """A document divided into the terms it states and the metadata document stored beside them."""

    metadata_document: dict[str, Any]
    terms: list[IncomingTerm]
    unverifiable_rules: list[str]
    unresolved_declarations: list[str]


@dataclass
class ContractImportPlan:
    """The full delta an import would make, computed without writing anything."""

    document_id: str | None
    document_name: str | None
    metadata_document: dict[str, Any]
    changes: list[TermChange]
    unverifiable_rules: list[str]
    unresolved_declarations: list[str]
    server_type_warning: str | None = None
    tables_not_in_catalog: list[str] = field(default_factory=list)

    @property
    def resolved_count(self) -> int:
        return sum(1 for change in self.changes if change.incoming is not None)

    def count(self, action: ImportAction) -> int:
        return sum(1 for change in self.changes if change.action is action)


def parse_document(payload: str) -> dict[str, Any]:
    """The ODCS document in ``payload`` (YAML, or JSON, which YAML reads), validated against the
    bundled schema for the version it declares.

    Raises ``InvalidContractDocumentError`` naming every problem.
    """
    try:
        document = yaml.safe_load(payload)
    except yaml.YAMLError as e:
        raise InvalidContractDocumentError([f"The payload is not valid YAML or JSON: {e}"]) from e
    if not isinstance(document, dict):
        raise InvalidContractDocumentError(["The payload must be an ODCS document object."])
    if problems := validate_document(document):
        raise InvalidContractDocumentError(problems)
    return document


def split_document(
    document: dict[str, Any],
    test_types: dict[str, TestType],
    *,
    flavor: SqlFlavorCode,
    qualify_tables: bool,
) -> SplitDocument:
    """Divide ``document`` into its terms and its metadata document.

    A quality rule that resolves to a test type becomes a term and leaves the document; one that
    resolves to none stays, marked unverifiable. A column declaration a test type checks exactly
    becomes a term and leaves the document, along with a column's ``enum`` when an ``LOV_Match``
    term resolves on it; one no test type checks stays and is reported. A property TestGen
    synthesized for a rule's subject leaves the document, its rules resolving against that
    subject. A managed, monitor, or inactive test type never comes from a document. The document's
    ``testgenTerm`` entries, which name terms rather than describe the agreement, are dropped. A term
    names its table and column by their ``physical_name``, and the document keeps both names. Raises
    ``InvalidContractDocumentError`` when two rules share an id, or an id is longer than a term
    id can be.
    """
    metadata = copy.deepcopy(document)
    active_types = {code: test_type for code, test_type in test_types.items() if test_type.active != "N"}
    resolver = RuleResolver(test_types=active_types, flavor=flavor, qualify_tables=qualify_tables)
    known = resolver.known_test_types
    terms: list[IncomingTerm] = []
    unverifiable: list[str] = []
    unresolved: list[str] = []

    def resolve_rules(
        rules: list[Any], scope: RuleScope, table_name: str, column_name: str | None, columns: dict[str, str]
    ) -> list[Any]:
        kept = []
        for index, rule in enumerate(rules):
            resolved = resolver.resolve(rule, scope, table_name, column_name, columns)
            if resolved is None:
                kept.append(mark_unverifiable(rule) if isinstance(rule, dict) else rule)
                label = rule_label(rule, index, f"{table_name}.{column_name}" if column_name else table_name)
                unverifiable.append(f"{label} ({describe_rule(rule)})")
                continue
            test_type = test_types[resolved.test_type]
            custom_rule = rule.get("type") == RuleShape.CUSTOM.value
            rule_metadata = drop_generated_metadata(resolved.metadata, test_type, resolved.parameters, custom=custom_rule)
            terms.append(IncomingTerm(
                test_type=resolved.test_type,
                table_name=table_name,
                # A type that does not name one column carries its column_name, if any, in its parameters.
                column_name=column_name if names_one_column(test_type) else resolved.parameters.get("column_name"),
                parameters=resolved.parameters,
                contract_term_id=resolved.contract_term_id,
                metadata=rule_metadata,
                custom_rule=custom_rule,
            ))
        return kept

    def same_claim(term: IncomingTerm, other: IncomingTerm) -> bool:
        return term.test_type == other.test_type and _parameter_values(
            term.test_type, term.parameters, resolver.parameters_by_type
        ) == _parameter_values(other.test_type, other.parameters, resolver.parameters_by_type)

    for table in metadata.get("schema") or []:
        if not isinstance(table, dict) or not table.get("name"):
            continue
        table_name = contract_document.physical_name(table)
        columns = contract_document.physical_column_names(table)
        if isinstance(table.get("quality"), list):
            table["quality"] = resolve_rules(table["quality"], RuleScope.TABLE, table_name, None, columns)
        properties = table.get("properties") if isinstance(table.get("properties"), list) else []
        for prop in [prop for prop in properties if isinstance(prop, dict) and is_synthesized_property(prop)]:
            # It names no column: its rules belong to the subject it stands for, and one that
            # resolves to nothing moves to the table.
            subject = prop.get("transformLogic") or prop.get("name")
            if isinstance(prop.get("quality"), list) and (
                kept := resolve_rules(prop["quality"], RuleScope.COLUMN, table_name, subject, columns)
            ):
                table["quality"] = [*(table.get("quality") or []), *kept]
            properties.remove(prop)
        for prop in table.get("properties") or []:
            if not isinstance(prop, dict) or not prop.get("name"):
                continue
            column_name = contract_document.physical_name(prop)
            first_term = len(terms)
            if isinstance(prop.get("quality"), list):
                prop["quality"] = resolve_rules(prop["quality"], RuleScope.COLUMN, table_name, column_name, columns)
                if not prop["quality"]:
                    del prop["quality"]
            for resolved in resolve_declarations(prop, known):
                terms.append(IncomingTerm(
                    test_type=resolved.test_type, table_name=table_name, column_name=column_name,
                    parameters=resolved.parameters, contract_term_id=resolved.contract_term_id,
                    metadata=drop_generated_metadata(
                        resolved.metadata, test_types[resolved.test_type], resolved.parameters, custom=False
                    ),
                ))
            column_terms = terms[first_term:]
            unnamed = resolve_unnamed_declarations(prop, known)
            for resolved in unnamed.terms:
                term = IncomingTerm(
                    test_type=resolved.test_type, table_name=table_name, column_name=column_name,
                    parameters=resolved.parameters, contract_term_id=None, metadata={},
                )
                # A declaration restating a rule on the same column is that rule's claim, not a second one.
                if not any(same_claim(term, other) for other in column_terms):
                    terms.append(term)
            unresolved += [f"{table_name}.{column_name}: {path}" for path in unnamed.unresolved]
            if prop.get("relationships"):
                unresolved.append(f"{table_name}.{column_name}: relationships")
            # The terms own what they declare: render writes it again from them, so a term edited or
            # deleted later is never contradicted by a stale copy here.
            for path in unnamed.owned:
                drop_field(prop, path.split("."))
            if any(term.test_type == "LOV_Match" for term in terms[first_term:]):
                prop.pop("enum", None)
            if "customProperties" in prop:
                prop["customProperties"] = [
                    entry for entry in prop["customProperties"] if not is_declaration_marker(entry)
                ]
                if not prop["customProperties"]:
                    del prop["customProperties"]
            # Terms check top-level columns only, so a nested rule or declaration resolves to nothing.
            for nested, _, path in nested_properties(prop, "", f"{table_name}.{column_name}"):
                if isinstance(nested.get("quality"), list):
                    nested["quality"] = [
                        mark_unverifiable(rule) if isinstance(rule, dict) else rule for rule in nested["quality"]
                    ]
                    unverifiable += [
                        rule_label(rule, index, path) for index, rule in enumerate(nested["quality"])
                    ]
                unresolved += [
                    f"{path}: {declared}" for declared in resolve_unnamed_declarations(nested, frozenset()).unresolved
                ]

        if table.get("quality") == []:
            del table["quality"]
        if table.get("relationships"):
            unresolved.append(f"{table_name}: relationships")

    _check_term_ids(terms)
    return SplitDocument(
        metadata_document=metadata, terms=terms, unverifiable_rules=unverifiable, unresolved_declarations=unresolved
    )


def _check_term_ids(terms: list[IncomingTerm]) -> None:
    problems = []
    seen: set[str] = set()
    for term in terms:
        term_id = term.contract_term_id
        if term_id is None:
            continue
        if term_id in seen:
            problems.append(f"Rule id `{term_id}` is used by more than one rule.")
        if len(term_id) > TERM_ID_MAX_LENGTH:
            problems.append(f"Rule id `{term_id}` is longer than {TERM_ID_MAX_LENGTH} characters.")
        seen.add(term_id)
    if problems:
        raise InvalidContractDocumentError(problems)


def check_identity(target_document: dict[str, Any] | None, incoming_id: str | None) -> None:
    """Raise ``ContractIdentityError`` when the target contract's ``id`` differs from the
    document's. A target with no ``id`` takes the incoming one."""
    target_id = (target_document or {}).get("id")
    if target_id and incoming_id and str(target_id) != str(incoming_id):
        raise ContractIdentityError(str(target_id), str(incoming_id))


def contract_holding_id(table_group_id: UUID, document_id: str) -> TestSuite | None:
    """A contract in the table group with a version whose document ``id`` is ``document_id``, or None."""
    return get_current_session().scalars(
        select(TestSuite)
        .join(SuiteVersion, SuiteVersion.test_suite_id == TestSuite.id)
        .where(
            TestSuite.table_groups_id == table_group_id,
            TestSuite.suite_type == SuiteType.CONTRACT,
            SuiteVersion.metadata_document["id"].astext == document_id,
        )
        .limit(1)
    ).first()


def server_type_warning(document: dict[str, Any], connection: Connection) -> str | None:
    """A warning when the document declares servers, none of them of the connection's type.

    The document's SQL is written for the server it declares and is never translated, so a
    mismatch means its SQL rules may fail when they run. A ``custom`` entry, a document with
    no servers, and a connection whose flavor has no ODCS server type are never warned on.
    """
    connection_type = FLAVOR_TO_SERVER_TYPE.get(SqlFlavorCode(connection.sql_flavor_code))
    if connection_type is None:
        return None
    declared = {
        _SERVER_TYPE_ALIASES.get(str(server.get("type")), str(server.get("type")))
        for server in document.get("servers") or []
        if isinstance(server, dict) and server.get("type")
    }
    declared.discard(ServerType.CUSTOM.value)
    if not declared or connection_type.value in declared:
        return None
    names = ", ".join(f"`{name}`" for name in sorted(declared))
    return (
        f"The document declares a {names} server, but connection `{connection.connection_name}` is "
        f"{FLAVOR_CODE_TO_LABEL[SqlFlavorCode(connection.sql_flavor_code)]} (`{connection_type.value}`). "
        "SQL in its rules is not translated between dialects, so a rule written for another server may fail "
        "when it runs."
    )


@dataclass(frozen=True)
class _BaselineTerm:
    id: UUID
    test_type: str
    schema_name: str | None
    table_name: str | None
    column_name: str | None
    contract_term_id: str | None
    values: dict[str, Any]
    custom_metadata: dict[str, Any] | None = None
    active: bool = True
    test_description: str | None = None


def plan_changes(
    incoming: list[IncomingTerm],
    baseline: list[_BaselineTerm],
    *,
    schema_name: str,
    declared_parameters: dict[str, list[str]],
) -> list[TermChange]:
    """Reconcile ``incoming`` against ``baseline``.

    Every incoming term carrying the id of a baseline term matches it first. Each remaining
    incoming term then matches an unmatched baseline term of the same test type, schema, table
    and column, preferring an active term to a muted one, and is otherwise new. An active baseline
    term nothing matches is deleted. A muted term is left as it is, because the document a contract
    exports states only its active terms.
    """
    by_id = {term.contract_term_id: term for term in baseline if term.contract_term_id}
    targets: dict[int, tuple[_BaselineTerm, ContractTermReason]] = {}
    matched: set[UUID] = set()
    for index, term in enumerate(incoming):
        if term.contract_term_id and (target := by_id.get(term.contract_term_id)):
            targets[index] = (target, ContractTermReason.MATCHED_BY_ID)
            matched.add(target.id)

    unmatched_by_key: dict[tuple, list[_BaselineTerm]] = {}
    for term in baseline:
        if term.id not in matched:
            key = _natural_key(term.test_type, term.schema_name, term.table_name, term.column_name)
            unmatched_by_key.setdefault(key, []).append(term)
    # Terms sharing a key pair by equal parameters first, so their order on either side is irrelevant.
    # Active terms are tried before muted ones: a muted match stays muted while its active twin is deleted.
    for active_only, same_parameters in ((True, True), (True, False), (False, True), (False, False)):
        for index, term in enumerate(incoming):
            if index in targets:
                continue
            key = _natural_key(term.test_type, schema_name, term.table_name, term.column_name)
            candidates = unmatched_by_key.get(key) or []
            incoming_values = _parameter_values(term.test_type, term.parameters, declared_parameters)
            target = next(
                (
                    candidate for candidate in candidates
                    if (candidate.active or not active_only)
                    and (
                        not same_parameters
                        or _parameter_values(candidate.test_type, candidate.values, declared_parameters)
                        == incoming_values
                    )
                ),
                None,
            )
            if target is not None:
                candidates.remove(target)
                targets[index] = (target, ContractTermReason.MATCHED_BY_KEY)
                matched.add(target.id)

    changes: list[TermChange] = []
    for index, term in enumerate(incoming):
        if index not in targets:
            changes.append(TermChange(
                action=ImportAction.create, reason=ContractTermReason.NEW, test_type=term.test_type,
                table_name=term.table_name, column_name=term.column_name, contract_term_id=term.contract_term_id,
                incoming=term, custom_metadata=_custom_metadata(term.metadata, None),
            ))
            continue
        target, reason = targets[index]
        custom_metadata = _custom_metadata(_rule_metadata(term, target), target.custom_metadata)
        unchanged = _is_unchanged(term, target, custom_metadata, schema_name, declared_parameters)
        changes.append(TermChange(
            action=ImportAction.skip if unchanged else ImportAction.update,
            reason=ContractTermReason.UNCHANGED if unchanged else reason,
            test_type=term.test_type,
            table_name=term.table_name,
            column_name=term.column_name,
            contract_term_id=term.contract_term_id or target.contract_term_id,
            target_id=target.id,
            incoming=term,
            custom_metadata=custom_metadata,
        ))

    changes += [
        TermChange(
            action=ImportAction.delete, reason=ContractTermReason.ABSENT, test_type=term.test_type,
            table_name=term.table_name or "", column_name=term.column_name, contract_term_id=term.contract_term_id,
            target_id=term.id,
        )
        for term in baseline
        if term.id not in matched and term.active
    ]
    return changes


def _natural_key(test_type: str, schema_name: str | None, table_name: str | None, column_name: str | None) -> tuple:
    return test_type, schema_name or None, table_name or None, column_name or None


def _parameter_values(test_type: str, parameters: dict[str, Any], declared_parameters: dict[str, list[str]]) -> dict:
    """The comparable value of each parameter ``test_type`` declares. A blank threshold compares as
    the 0 test execution runs it with, which is how the document states it."""
    values: dict[str, Any] = {
        name: _comparable(parameters.get(name), numeric=(test_type, name) not in _TEXT_PARAMETERS)
        for name in declared_parameters.get(test_type, [])
    }
    if "threshold_value" in values and values["threshold_value"] is None:
        values["threshold_value"] = "0"
    if test_type in VALUE_LIST_TEST_TYPES and values.get("baseline_value"):
        # A list compares by the values it holds, so ``a, b`` equals the ``a,b`` the document reads back as.
        values["baseline_value"] = parse_value_list(values["baseline_value"])
    return values


_MIDNIGHT = re.compile(r"^(\d{4}-\d{2}-\d{2})[ T]00:00:00(\.0+)?$")
_DECIMAL = re.compile(r"^-?(0|[1-9]\d*)\.\d+$")
# Parameters whose value is text even when it reads as a decimal number.
_TEXT_PARAMETERS = frozenset({
    ("Pattern_Match", "baseline_value"),
    ("Required_No_Placeholder", "baseline_value"),
    *((test_type, "baseline_value") for test_type in VALUE_LIST_TEST_TYPES),
})


def _comparable(value: Any, numeric: bool = True) -> str | None:
    """``value`` as text to compare a parameter by. A timestamp at midnight compares as its date,
    which is how a date bound renders in the document. When ``numeric``, a decimal number compares
    without the trailing zeros of its fraction, so a whole number compares as an integer."""
    if value is None or value == "":
        return None
    text = str(value).strip()
    if numeric and _DECIMAL.match(text):
        return text.rstrip("0").rstrip(".")
    midnight = _MIDNIGHT.match(text)
    return midnight.group(1) if midnight else text


def _rule_metadata(term: IncomingTerm, target: _BaselineTerm) -> dict[str, Any]:
    """``term``'s rule metadata, without a ``name`` equal to ``target``'s ``test_description``. The export
    renders that description as the rule's name, so it is not a change."""
    if target.test_description and term.metadata.get("name") == target.test_description:
        return {key: value for key, value in term.metadata.items() if key != "name"}
    return term.metadata


def _custom_metadata(metadata: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, Any] | None:
    """The ``custom_metadata`` a term stores for its resolved rule ``metadata``.

    The rule's metadata goes under the ``odcs`` key, except a ``customProperties`` entry that
    restates one of the ``existing`` top-level keys exactly, as a term's own keys render: that
    stays a top-level key. Top-level keys the rule no longer carries are dropped.
    """
    plain = {key: value for key, value in (existing or {}).items() if key != ODCS_RULE_METADATA_KEY}
    kept: dict[str, Any] = {}
    remaining = []
    for entry in metadata.get("customProperties") or []:
        if (
            isinstance(entry, dict) and entry.keys() == {"property", "value"}
            and entry["property"] in plain and plain[entry["property"]] == entry["value"]
            and entry["property"] not in kept
        ):
            kept[entry["property"]] = entry["value"]
        else:
            remaining.append(entry)
    odcs = {key: value for key, value in metadata.items() if key != "customProperties"}
    if remaining:
        odcs["customProperties"] = remaining
    stored = {**kept, ODCS_RULE_METADATA_KEY: odcs} if odcs else kept
    return stored or None


def _is_unchanged(
    term: IncomingTerm,
    target: _BaselineTerm,
    custom_metadata: dict[str, Any] | None,
    schema_name: str,
    declared_parameters: dict[str, list[str]],
) -> bool:
    return (
        term.test_type == target.test_type
        and _natural_key(term.test_type, schema_name, term.table_name, term.column_name)
        == _natural_key(target.test_type, target.schema_name, target.table_name, target.column_name)
        and (term.contract_term_id is None or term.contract_term_id == target.contract_term_id)
        and _parameter_values(term.test_type, term.parameters, declared_parameters)
        == _parameter_values(target.test_type, target.values, declared_parameters)
        and custom_metadata == (target.custom_metadata or None)
    )


def _baseline_terms(suite: TestSuite, test_types: dict[str, TestType]) -> list[_BaselineTerm]:
    parameter_columns = sorted({name for test_type in test_types.values() for name in test_type_parameters(test_type)})
    rows = get_current_session().scalars(
        select(TestDefinition).where(
            TestDefinition.test_suite_id == suite.id,
            TestDefinition.version_clause(),
            TestDefinition.test_type.not_in(MANAGED_TEST_TYPES),
        ).order_by(TestDefinition.contract_term_id, TestDefinition.id)
    ).all()
    return [
        _BaselineTerm(
            id=row.id,
            test_type=row.test_type,
            schema_name=row.schema_name,
            table_name=row.table_name,
            column_name=row.column_name,
            contract_term_id=row.contract_term_id,
            values={name: getattr(row, name, None) for name in parameter_columns},
            custom_metadata=row.custom_metadata,
            active=bool(row.test_active),
            test_description=row.test_description,
        )
        for row in rows
    ]


def prepare_import(
    payload: str, table_group: TableGroup, connection: Connection, suite: TestSuite | None = None
) -> ContractImportPlan:
    """Everything importing ``payload`` would do, computed without writing anything.

    ``suite`` is the contract whose draft the document is imported into; without one, the plan creates a
    contract in ``table_group``. Raises ``InvalidContractDocumentError`` for a document that is
    not valid ODCS, ``ContractIdentityError`` for one whose ``id`` differs from ``suite``'s, and
    ``ContractIdTakenError`` for a new contract whose ``id`` another contract in ``table_group`` has.
    """
    document = parse_document(payload)
    current = None
    if suite is not None:
        current = SuiteVersion.draft_for(suite.id) or SuiteVersion.in_force_for(suite.id)
        check_identity(current.metadata_document if current else None, document.get("id"))
    elif document.get("id") and (holder := contract_holding_id(table_group.id, str(document["id"]))):
        raise ContractIdTakenError(str(document["id"]), holder)

    flavor = SqlFlavorCode(connection.sql_flavor_code)
    test_types = all_test_types()
    split = split_document(
        document, test_types, flavor=flavor, qualify_tables=table_group_qualifies_table_refs(table_group.id)
    )
    declared_parameters = {code: test_type_parameters(test_type) for code, test_type in test_types.items()}
    baseline = _baseline_terms(suite, test_types) if current is not None else []
    catalog_tables = set(contract_document.catalog_table_names(table_group.id))
    value_list_problems = _normalize_value_lists(split.terms, test_types, table_group.id)
    changes = plan_changes(
        split.terms, baseline, schema_name=table_group.table_group_schema, declared_parameters=declared_parameters
    )
    if problems := value_list_problems + _invalid_terms(changes, test_types, table_group.table_group_schema):
        raise InvalidContractDocumentError(problems)

    return ContractImportPlan(
        document_id=document.get("id"),
        document_name=document.get("name"),
        metadata_document=split.metadata_document,
        changes=changes,
        unverifiable_rules=split.unverifiable_rules,
        unresolved_declarations=split.unresolved_declarations,
        server_type_warning=server_type_warning(document, connection),
        tables_not_in_catalog=[
            name for name in contract_document.declared_tables(split.metadata_document) if name not in catalog_tables
        ],
    )


def _term_label(
    table_name: str, column_name: str | None, contract_term_id: str | None, test_type: TestType
) -> str:
    subject = f"{table_name}.{column_name}" if column_name else table_name
    rule = f" rule {contract_term_id}" if contract_term_id else ""
    return f"{subject}{rule} ({test_type.test_name_short})"


def _normalize_value_lists(
    terms: list[IncomingTerm], test_types: dict[str, TestType], table_groups_id: UUID
) -> list[str]:
    """Rewrite each value-list term's list as a test definition stores it, for the general type the
    table group's catalog records for its column.

    Returns each term whose list a test definition could not store, with the reason.
    """
    problems = []
    general_types: dict[tuple[str, str], str | None] | None = None
    for term in terms:
        if term.test_type not in VALUE_LIST_TEST_TYPES or "baseline_value" not in term.parameters:
            continue
        if general_types is None:
            general_types = DataColumnChars.select_general_types(table_groups_id)
        try:
            term.parameters["baseline_value"] = stored_value_list(
                term.test_type,
                term.parameters["baseline_value"],
                general_types.get((term.table_name, term.column_name)),
            )
        except InvalidTestDefinitionFields as e:
            label = _term_label(term.table_name, term.column_name, term.contract_term_id, test_types[term.test_type])
            problems += [f"{label}: {field} {reason}" for field, reason in e.errors.items()]
    return problems


def _invalid_terms(changes: list[TermChange], test_types: dict[str, TestType], schema_name: str) -> list[str]:
    """Each term to create or update that a test definition could not store, with the reason."""
    problems = []
    for change in changes:
        if change.action not in (ImportAction.create, ImportAction.update):
            continue
        test_type = test_types[change.test_type]
        values = _term_values(change.incoming, change.custom_metadata, test_types)
        label = _term_label(change.table_name, change.column_name, change.contract_term_id, test_type)
        try:
            TestDefinition(schema_name=schema_name, **values).validate(test_type)
        except InvalidTestDefinitionFields as e:
            problems += [f"{label}: {field} {reason}" for field, reason in e.errors.items()]
    return problems


@dataclass(frozen=True)
class AppliedImport:
    version_id: UUID
    conformance_failed: bool


def apply_import(
    plan: ContractImportPlan, suite: TestSuite, table_group: TableGroup, flavor: SqlFlavorCode
) -> AppliedImport:
    """Write ``plan`` to ``suite``'s draft, opening one when it has none, then bring its schema
    conformance tests in line with the tables the document declares. Commits the session.

    Returns the draft's version id, and whether bringing schema conformance in line failed after
    the import was saved.
    """
    session = get_current_session()
    version_id, copied = resolve_write_target(suite)
    version = SuiteVersion.get(version_id)

    document = copy.deepcopy(plan.metadata_document)
    # Validated against the version it declares; stored as the pinned version, which accepts every
    # document the earlier bundled versions do and is the one TestGen renders into.
    document["apiVersion"] = ODCS_API_VERSION
    document["version"] = SuiteVersion.document_version(version.version)
    document["name"] = suite.test_suite
    _match_physical_types(document, table_group, FLAVOR_CODE_TO_FAMILY[flavor])
    version.metadata_document = document
    version.odcs_api_version = ODCS_API_VERSION
    flag_modified(version, "metadata_document")

    _write_terms(plan.changes, suite, table_group, version_id, copied)
    session.commit()
    try:
        reconcile_contract_conformance(suite.id)
    except Exception:
        LOG.exception(f"Reconciling schema conformance for contract {suite.id} failed after import")
        return AppliedImport(version_id=version_id, conformance_failed=True)
    return AppliedImport(version_id=version_id, conformance_failed=False)


def _write_terms(
    changes: list[TermChange], suite: TestSuite, table_group: TableGroup, version_id: UUID, copied: dict[UUID, UUID]
) -> None:
    """Write ``changes`` to the draft ``version_id``. Every term the document states is locked, so
    that a later generation run does not overwrite or delete what the document agreed."""
    session = get_current_session()
    now = datetime.now(UTC)
    qualifies_table_refs = table_group_qualifies_table_refs(table_group.id)
    test_types = all_test_types()

    def target_of(change: TermChange) -> UUID:
        return copied.get(change.target_id, change.target_id)

    if deleted := [target_of(change) for change in changes if change.action is ImportAction.delete]:
        session.execute(
            delete(TestDefinition).where(TestDefinition.id.in_(deleted), TestDefinition.version_id == version_id)
        )

    updates = [change for change in changes if change.action is ImportAction.update]
    if renamed := [target_of(change) for change in updates if change.incoming.contract_term_id]:
        # Cleared first so an id moving between two terms never collides with itself mid-update.
        session.execute(
            update(TestDefinition)
            .where(TestDefinition.id.in_(renamed), TestDefinition.version_id == version_id)
            .values(contract_term_id=None)
        )
    all_parameters = sorted({name for test_type in test_types.values() for name in test_type_parameters(test_type)})
    for change in updates:
        values = {
            **dict.fromkeys(all_parameters),
            **_term_values(change.incoming, change.custom_metadata, test_types),
        }
        settled = TestDefinition(
            schema_name=table_group.table_group_schema,
            match_table_name=values.get("match_table_name"),
            match_schema_name=values.get("match_schema_name"),
        )
        apply_test_definition_flavor_rules(settled, table_group, qualifies_table_refs=qualifies_table_refs)
        if settled.match_table_name:
            values["match_schema_name"] = settled.match_schema_name
        session.execute(
            update(TestDefinition)
            .where(TestDefinition.id == target_of(change), TestDefinition.version_id == version_id)
            .values(**values, lock_refresh=True, last_manual_update=now)
        )
    if unchanged := [target_of(change) for change in changes if change.action is ImportAction.skip]:
        session.execute(
            update(TestDefinition)
            .where(TestDefinition.id.in_(unchanged), TestDefinition.version_id == version_id)
            .values(lock_refresh=True)
        )

    for change in changes:
        if change.action is not ImportAction.create:
            continue
        definition = TestDefinition(
            test_suite_id=suite.id,
            version_id=version_id,
            table_groups_id=suite.table_groups_id,
            schema_name=table_group.table_group_schema,
            lock_refresh=True,
            last_manual_update=now,
            **_term_values(change.incoming, change.custom_metadata, test_types),
        )
        apply_test_definition_flavor_rules(definition, table_group, qualifies_table_refs=qualifies_table_refs)
        session.add(definition)

    session.flush()
    TestDefinition.assign_missing_term_ids(version_id)


def _term_values(
    term: IncomingTerm, custom_metadata: dict[str, Any] | None, test_types: dict[str, TestType]
) -> dict[str, Any]:
    """The columns a term's row takes: its subject, identity and metadata, and a value for every
    parameter its test type declares, NULL where the document states none."""
    values: dict[str, Any] = {
        name: term.parameters.get(name) for name in test_type_parameters(test_types[term.test_type])
    }
    values.update(
        test_type=term.test_type,
        table_name=term.table_name,
        column_name=term.column_name,
        custom_metadata=custom_metadata,
    )
    if term.contract_term_id:
        values["contract_term_id"] = term.contract_term_id
    return values


def _match_physical_types(document: dict[str, Any], table_group: TableGroup, flavor_family: str) -> None:
    """Write each declared ``physicalType`` the catalog records an equivalent of in the catalog's
    spelling, so schema conformance compares like with like.

    The author's spelling is kept in the column's ``authoredPhysicalType`` property. A type that
    cannot be compared with the catalog's is set aside the same way, so conformance compares the
    column's ``logicalType`` instead. A type that differs is left as written, for conformance to
    report.
    """
    for table in document.get("schema") or []:
        if not isinstance(table, dict) or not table.get("name"):
            continue
        recorded = {
            column.column_name: column.db_data_type
            for column in contract_document.catalog_columns(table_group.id, contract_document.physical_name(table))
            if column.db_data_type
        }
        for prop in table.get("properties") or []:
            declared = prop.get("physicalType") if isinstance(prop, dict) else None
            if not isinstance(declared, str) or contract_document.physical_name(prop) not in recorded:
                continue
            catalog_type = recorded[contract_document.physical_name(prop)]
            match = compare_physical_types(declared, catalog_type, flavor_family)
            if match is TypeMatch.MISMATCH or declared == catalog_type:
                continue
            properties = [
                entry for entry in prop.get("customProperties") or [] if entry.get("property") != AUTHORED_PHYSICAL_TYPE
            ]
            prop["customProperties"] = [
                *properties, {"property": AUTHORED_PHYSICAL_TYPE, "value": declared, "vendor": "testgen"},
            ]
            if match is TypeMatch.EQUIVALENT:
                prop["physicalType"] = catalog_type
            else:
                del prop["physicalType"]

