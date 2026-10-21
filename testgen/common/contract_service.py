"""Contract lifecycle: resolving where a write lands, freezing a version, discarding a draft.

Every mutation of a contract's content routes through here so that the version it lands in is
decided in one place. Functions raise stdlib exceptions; the calling surface translates them
into its own user-facing errors.
"""

import copy
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, NamedTuple
from uuid import UUID, uuid4

import yaml
from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.orm.attributes import flag_modified

from testgen.commands.test_generation import (
    ContractGenerationResult,
    reconcile_contract_conformance,
    run_contract_generation,
)
from testgen.common.contract_rules import RuleResolver, document_rules, rule_label
from testgen.common.enums import JobStatus, SuiteType
from testgen.common.generation_set_service import CONTRACT_GENERATION_SET
from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.job_execution import JobExecution
from testgen.common.models.suite_version import ContractState, SuiteVersion, VersionState, version_state
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import MANAGED_TEST_TYPES, TestDefinition
from testgen.common.models.test_run import TestRun, TestRunSummary
from testgen.common.models.test_suite import TestSuite
from testgen.common.odcs import render, serialize
from testgen.common.odcs.quality_rules import (
    is_unverifiable_marker,
    mark_unverifiable,
    property_declaration,
    resolve_unnamed_declarations,
)
from testgen.common.odcs.servers import ODCS_API_VERSION, ODCS_KIND, CustomServerReason, build_server_block
from testgen.common.odcs.validation import schema_violations, validate_document


def resolve_write_target(suite: TestSuite) -> tuple[UUID, dict[UUID, UUID]]:
    """The version this suite's next write lands in, creating a draft when there is none.

    Returns the version id and a map from each copied term's previous id to its new one. The
    map is empty when a draft already existed.
    """
    _assert_contract(suite)
    return TestDefinition.resolve_write_target(suite.id)


def _assert_contract(suite: TestSuite) -> None:
    """Raise unless the suite is a contract, the only kind that keeps versions.

    A version row on any other suite would take its test definitions -- stamped with the
    placeholder -- out of the version its reads and its generation resolve to.
    """
    if suite.suite_type != SuiteType.CONTRACT:
        raise ValueError(f"Test suite {suite.id} is not a contract and keeps no versions.")


class InvalidContractDocumentError(ValueError):
    """Raised when a contract's merged document fails ODCS validation.

    Carries the validator's own messages, so a caller can show the same violations it
    reported rather than a generic refusal.
    """

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def freeze_version(suite: TestSuite, *, label: str | None = None, username: str | None = None) -> SuiteVersion:
    """Freeze the suite's draft, making it the agreement in force, recorded as frozen by ``username``.

    Renders the draft's terms into its stored document and validates the merge before
    anything is written. Raises ``InvalidContractDocumentError``, leaving the draft a draft,
    when the merged document does not validate; terms are not regenerated here, only what
    the draft already holds is rendered.
    """
    draft = SuiteVersion.draft_for(suite.id)
    if draft is None:
        raise ValueError("This contract has no draft to freeze.")

    document = render.render_document(draft)
    problems = validate_document(document)
    if problems:
        raise InvalidContractDocumentError(problems)

    draft.odcs_api_version = document["apiVersion"]
    draft.frozen_document = serialize.serialize_document(document)
    draft.frozen_at = datetime.now(UTC)
    draft.frozen_by = username
    if label is not None:
        draft.label = label
    get_current_session().flush()
    return draft


@dataclass(frozen=True)
class ExportedDocument:
    """A contract version's document as YAML text, alongside whether it still validates."""

    text: str
    problems: list[str]


def version_for_export(suite: TestSuite, version: int | None = None) -> SuiteVersion:
    """The version of ``suite`` an export without further instruction should return.

    With no ``version``, the draft where one exists, otherwise the version in force. With
    one, the version carrying that number. Raises ``ValueError`` when the suite keeps no
    versions, when it holds no version at the number asked for, or when it has neither a
    draft nor a frozen version to fall back on.
    """
    _assert_contract(suite)
    if version is not None:
        numbered = SuiteVersion.for_number(suite.id, version)
        if numbered is None:
            raise ValueError(f"This contract has no version {version}.")
        return numbered

    resolved = SuiteVersion.draft_for(suite.id) or _active_version(suite)
    if resolved is None:
        raise ValueError("This contract has no version to export.")
    return resolved


class NotAContractError(ValueError):
    """Raised when a version is asked of a suite that keeps none."""

    def __init__(self, suite: TestSuite) -> None:
        super().__init__(f"Test suite {suite.id} is not a contract and keeps no versions.")
        self.suite = suite


class UnknownVersionError(ValueError):
    """Raised when a contract holds no version with the number asked for."""

    def __init__(self, suite: TestSuite, version: int, highest: int | None) -> None:
        super().__init__(f"Contract {suite.id} has no version {version}.")
        self.suite = suite
        self.version = version
        self.highest = highest


def version_by_number(suite: TestSuite, version: int) -> SuiteVersion:
    """The contract's version carrying ``version``.

    Raises ``NotAContractError`` for a suite that keeps no versions and ``UnknownVersionError``,
    carrying the highest number the contract holds, when it holds no version with that number.
    """
    if suite.suite_type != SuiteType.CONTRACT:
        raise NotAContractError(suite)
    numbered = SuiteVersion.for_number(suite.id, version)
    if numbered is None:
        highest = get_current_session().scalar(
            select(func.max(SuiteVersion.version)).where(SuiteVersion.test_suite_id == suite.id)
        )
        raise UnknownVersionError(suite, version, highest)
    return numbered


class NoActiveTestsError(ValueError):
    """Raised when a run is asked of a contract version that holds no active tests."""

    def __init__(self, suite: TestSuite, version: SuiteVersion, state: VersionState) -> None:
        super().__init__(f"Version {version.version} of contract {suite.id} has no active tests to run.")
        self.suite = suite
        self.version = version
        self.state = state


@dataclass(frozen=True)
class RunTarget:
    """The contract version a run checks, and its state when the run is submitted."""

    version: SuiteVersion
    state: VersionState

    @property
    def note(self) -> str | None:
        """Why the run will not count as the contract's status, judged from the version's state at submission."""
        if self.state == VersionState.DRAFT:
            return (
                "This run checks a version that is not frozen. Unless the version is frozen before the run starts, "
                "the run is a preview and will not count as the contract's status."
            )
        if self.state == VersionState.SUPERSEDED:
            return "This run checks a superseded version, so it will not count as the contract's status."
        return None


def run_target(suite: TestSuite, version: int | None = None) -> RunTarget | None:
    """The contract version a run of ``suite`` checks; ``None`` for a suite that keeps no versions.

    With no ``version``, the version in force, or the draft when nothing is frozen yet. Raises
    ``NotAContractError`` when a version is asked of a suite that keeps none,
    ``UnknownVersionError`` when the contract holds no version with that number, and
    ``NoActiveTestsError`` when the version holds no active tests.
    """
    if version is None and suite.suite_type != SuiteType.CONTRACT:
        return None
    if version is not None:
        target = version_by_number(suite, version)
    else:
        target = SuiteVersion.get(get_current_session().scalar(select(SuiteVersion.for_run(suite.id))))
    state = version_state(target.frozen_at, SuiteVersion.is_active(target.id, suite.id))
    _, active_tests = TestDefinition.list_for_suite(
        suite.id, test_active=True, version_id=target.id, limit=1, suite_types=(SuiteType.CONTRACT,)
    )
    if not active_tests:
        raise NoActiveTestsError(suite, target, state)
    return RunTarget(target, state)


def import_destination(suite: TestSuite, *, preview: bool) -> tuple[int, VersionState]:
    """The number and state of the version an import into ``suite`` lands in.

    The draft where one exists, otherwise the version in force. A preview into a frozen version
    names the draft that applying the import would open.
    """
    version = version_for_export(suite)
    if preview and version.frozen_at is not None:
        return SuiteVersion.next_version_for(suite.id), VersionState.DRAFT
    return version.version, version_state(version.frozen_at, SuiteVersion.is_active(version.id, suite.id))


class VerificationUnavailable(StrEnum):
    nothing_frozen = "nothing_frozen"
    not_run_since_frozen = "not_run_since_frozen"
    latest_run_incomplete = "latest_run_incomplete"


@dataclass(frozen=True)
class ContractStatus:
    """A contract's versions and the latest run that verified the agreement in force.

    ``latest_verification`` is the latest completed run of the active version that started after
    it was frozen. ``incomplete_run`` is the latest such run when it has not completed. When there
    is no verification, ``unavailable`` says why.
    """

    active: SuiteVersion | None
    draft: SuiteVersion | None
    latest_verification: TestRunSummary | None
    incomplete_run: TestRunSummary | None
    unavailable: VerificationUnavailable | None

    @property
    def counted_from(self) -> SuiteVersion | None:
        """The version the suite's test count reflects: the draft, else the active version."""
        return self.draft or self.active


def contract_status(suite: TestSuite) -> ContractStatus:
    """The contract's active and draft versions and its latest verification."""
    _assert_contract(suite)
    state = SuiteVersion.states_for([suite.id]).get(suite.id) or ContractState(active=None, draft=None)
    active, draft = state.active, state.draft
    if active is None:
        return ContractStatus(active, draft, None, None, VerificationUnavailable.nothing_frozen)

    latest = _run_summary(TestRun.latest_verification(active))
    if latest is None:
        return ContractStatus(active, draft, None, None, VerificationUnavailable.not_run_since_frozen)
    if latest.status == JobStatus.COMPLETED:
        return ContractStatus(active, draft, latest, None, None)

    completed = _run_summary(TestRun.latest_verification(active, JobExecution.status == JobStatus.COMPLETED))
    unavailable = None if completed else VerificationUnavailable.latest_run_incomplete
    return ContractStatus(active, draft, completed, latest, unavailable)


def _run_summary(run: TestRun | None) -> TestRunSummary | None:
    if run is None:
        return None
    summaries, _ = TestRun.select_summary(test_run_ids=[run.id], suite_types=(SuiteType.CONTRACT,))
    return summaries[0] if summaries else None


def export_version(version: SuiteVersion) -> ExportedDocument:
    """The version's document as YAML text, with a fresh check of whether it validates.

    Returns a frozen version's stored bytes unchanged, reading no terms and rendering
    nothing; a draft, which has no stored bytes yet, is rendered and serialized fresh.
    Either way ``problems`` is computed against the returned text rather than assumed, so a
    frozen document that no longer validates -- for instance after a schema pin change --
    is reported rather than presumed clean.
    """
    text = version.frozen_document or serialize.serialize_document(render.render_document(version))
    problems = validate_document(yaml.safe_load(text))
    return ExportedDocument(text, problems)


def discard_draft(suite: TestSuite) -> int:
    """Delete the suite's draft and every term on it. Returns the number of terms removed."""
    draft = SuiteVersion.draft_for(suite.id)
    if draft is None:
        raise ValueError("This contract has no draft to discard.")
    if _active_version(suite) is None:
        raise ValueError(
            "This contract has no frozen version behind its draft; discarding it would leave "
            "the contract with no version at all. Freeze a version first, or keep this draft."
        )

    removed = term_count(draft.id)
    session = get_current_session()
    session.delete(draft)
    session.flush()
    return removed


def term_count(version_id: UUID, *clauses: ColumnElement[bool]) -> int:
    """The number of terms on the version ``version_id`` that match ``clauses``, leaving out the tests
    TestGen manages itself."""
    return get_current_session().scalar(
        select(func.count()).select_from(TestDefinition).where(
            TestDefinition.version_id == version_id,
            TestDefinition.test_type.not_in(MANAGED_TEST_TYPES),
            *clauses,
        )
    ) or 0


class CheckableRuleError(InvalidContractDocumentError):
    """Raised when a metadata document states a quality rule a test type checks.

    Such a rule is a term: stored in the document, it would be exported but never run.
    """


class OwnedFieldError(InvalidContractDocumentError):
    """Raised when a metadata document changes a root field TestGen sets."""


# Root fields TestGen sets on a contract's document rather than taking from the caller.
_OWNED_FIELDS = ("apiVersion", "kind", "id", "version")


@dataclass(frozen=True)
class SavedMetadata:
    """What saving a metadata document did, and what in it no test checks."""

    version_id: UUID
    unverifiable_rules: list[str]
    unresolved_declarations: list[str]
    untested_declarations: list[str]
    overridden_declarations: list[str]
    problems: list[str]


def save_metadata_document(suite: TestSuite, document: dict[str, Any]) -> SavedMetadata:
    """Write ``document`` as the metadata of the suite's draft, creating the draft when there is none.

    The document is checked against the version the write lands on before anything is written:

    - a quality rule a test type checks is refused (``CheckableRuleError``), unless the version
      already stores the same rule at the same place; every other rule is stored marked unverifiable;
    - a root field TestGen sets (``apiVersion``, ``kind``, ``id``, ``version``) that differs from
      the version's is refused, and one left out is kept;
    - the document merged with the version's terms is validated, and a problem it did not have
      before is refused (``InvalidContractDocumentError``). Problems it already had are returned.

    Commits the session, then reconciles the draft's Schema Conformance tests with the tables the
    document declares. The declaration lists cover only declarations this save adds or changes:
    ``unresolved_declarations`` no test type checks, ``untested_declarations`` a test type checks
    but the contract holds no such test on the column, and ``overridden_declarations`` a test on
    the column declares with a different value, which the rendered document shows instead.
    """
    _assert_contract(suite)
    current = SuiteVersion.draft_for(suite.id) or _active_version(suite)
    if current is None:
        raise ValueError("This contract has no version to write to.")
    document = copy.deepcopy(document)
    # Re-read the stored document, so a caller that edited the loaded one in place is compared
    # against what is saved rather than against its own edits.
    get_current_session().refresh(current, ["metadata_document"])
    stored = current.metadata_document or {}

    if problems := _owned_field_changes(document, stored):
        raise OwnedFieldError(problems)
    for key in _OWNED_FIELDS:
        if key not in document and key in stored:
            document[key] = stored[key]

    table_group = TableGroup.get(suite.table_groups_id)
    resolver = RuleResolver.for_table_group(table_group, Connection.get(table_group.connection_id))
    unverifiable = _mark_unverifiable_rules(document, stored, resolver)

    problems = _document_problems(current, document)
    if introduced := _introduced_problems(_document_problems(current, stored), problems):
        raise InvalidContractDocumentError(introduced)

    declarations = _unchecked_declarations(document, stored, current.id, resolver)

    version_id, _ = resolve_write_target(suite)
    version = SuiteVersion.get(version_id)
    document["version"] = SuiteVersion.document_version(version.version)
    version.metadata_document = document
    flag_modified(version, "metadata_document")
    get_current_session().commit()
    reconcile_contract_conformance(suite.id)
    return SavedMetadata(
        version_id=version_id,
        unverifiable_rules=unverifiable,
        unresolved_declarations=declarations.unresolved,
        untested_declarations=declarations.untested,
        overridden_declarations=declarations.overridden,
        problems=[problem.text for problem in problems.problems],
    )


def _owned_field_changes(document: dict[str, Any], stored: dict[str, Any]) -> list[str]:
    return [
        f"$.{key}: `{key}` cannot be changed. It is `{stored[key]}`."
        for key in _OWNED_FIELDS
        if key in document and key in stored and document[key] != stored[key]
    ]


def _mark_unverifiable_rules(document: dict[str, Any], stored: dict[str, Any], resolver: RuleResolver) -> list[str]:
    """Mark each rule in ``document`` unverifiable in place, and return the labels of those ``stored`` lacks.

    Raises ``CheckableRuleError`` naming every rule a test type checks that ``stored`` does not
    already hold at the same place.
    """
    stored_rules = {
        (rules.label, _comparable_rule(rule)) for rules in document_rules(stored) for rule in rules.rules
    }
    checkable: list[str] = []
    added: list[str] = []
    for rules in document_rules(document):
        for index, rule in enumerate(rules.rules):
            is_stored = (rules.label, _comparable_rule(rule)) in stored_rules
            resolved = None if rules.nested else resolver.resolve(rule, rules.scope, rules.table_name, rules.column_name)
            if resolved is not None and not is_stored:
                test_type = resolver.test_types[resolved.test_type]
                checkable.append(
                    f"{rules.path}[{index}]: {rule_label(rule, index, rules.label)} is checked by the "
                    f"{test_type.test_name_short or test_type.test_type} test type."
                )
                continue
            if isinstance(rule, dict):
                rules.rules[index] = mark_unverifiable(rule)
            if not is_stored:
                added.append(rule_label(rule, index, rules.label))
    if checkable:
        raise CheckableRuleError(checkable)
    return added


def _comparable_rule(rule: Any) -> str:
    if isinstance(rule, dict):
        entries = [entry for entry in rule.get("customProperties") or [] if not is_unverifiable_marker(entry)]
        rule = {**rule, "customProperties": entries} if entries else {
            key: value for key, value in rule.items() if key != "customProperties"
        }
    return json.dumps(rule, sort_keys=True, default=str)


class _Problem(NamedTuple):
    path: str
    schema_path: str
    unexpected_keys: tuple[str, ...]
    text: str


class _DocumentProblems(NamedTuple):
    rendered: dict[str, Any] | None
    problems: list[_Problem]


def _document_problems(version: SuiteVersion, metadata_document: dict[str, Any]) -> _DocumentProblems:
    """The document rendered with the version's terms, and each problem the rendered document has.

    ``rendered`` is ``None`` when the terms cannot be rendered into the document, and the one
    problem names why.
    """
    try:
        rendered = render.render_document(version, metadata_document)
    except ValueError as e:
        return _DocumentProblems(None, [_Problem(str(e), "", (), str(e))])
    return _DocumentProblems(
        rendered,
        [
            _Problem(violation.path, violation.schema_path, violation.unexpected_keys, str(violation))
            for violation in schema_violations(rendered)
        ],
    )


def _introduced_problems(before: _DocumentProblems, after: _DocumentProblems) -> list[str]:
    """The problems ``after`` has that ``before`` does not.

    A problem is matched by the schema keyword it fails and where it is, not by the validator's
    message, which quotes the offending value and so changes with any edit to it; a problem
    naming keys an object may not have is matched once per key. Where it is names each list item
    by its ``name`` or ``id`` rather than its position, so a problem keeps its place when an item
    is inserted ahead of it. A problem also matches the place ``before`` gives the item at the
    same position, so it keeps its place when the item gains a name or is renamed, unless
    ``after`` still has a problem at that place, which means that item moved.
    """
    known = {key for problem in before.problems for key in _problem_keys(before.rendered, problem)}
    after_keys = {key for problem in after.problems for key in _problem_keys(after.rendered, problem)}
    introduced = []
    for problem in after.problems:
        pairs = zip(_problem_keys(after.rendered, problem), _problem_keys(before.rendered, problem), strict=True)
        if not all(key in known or (key_before in known and key_before not in after_keys) for key, key_before in pairs):
            introduced.append(problem.text)
    return introduced


def _problem_keys(rendered: dict[str, Any] | None, problem: _Problem) -> list[tuple[str, str, str]]:
    place = _problem_place(rendered, problem.path)
    return [(place, problem.schema_path, key) for key in problem.unexpected_keys or ("",)]


def _problem_place(rendered: dict[str, Any] | None, path: str) -> str:
    return path if rendered is None else _named_path(rendered, path)


_PATH_STEP = re.compile(r"\.([^.\[]+)|\[(\d+)\]")


def _named_path(document: dict[str, Any], path: str) -> str:
    """``path`` (``$.schema[1].properties[0]``) with each list position replaced by the item's
    ``name`` or ``id`` where it has one (``$.schema[orders].properties[amount]``)."""
    node: Any = document
    named = "$"
    for key, index in _PATH_STEP.findall(path.removeprefix("$")):
        if key:
            named += f".{key}"
            node = node.get(key) if isinstance(node, dict) else None
            continue
        item = node[int(index)] if isinstance(node, list) and int(index) < len(node) else None
        label = next(
            (item[field] for field in ("name", "id") if isinstance(item, dict) and isinstance(item.get(field), str)),
            index,
        )
        named += f"[{label}]"
        node = item
    return named


@dataclass(frozen=True)
class _Declarations:
    unresolved: list[str]
    untested: list[str]
    overridden: list[str]


def _unchecked_declarations(
    document: dict[str, Any], stored: dict[str, Any], version_id: UUID, resolver: RuleResolver
) -> _Declarations:
    before = _properties(stored)
    terms: dict[tuple[str, str, str], list[TestDefinition]] = {}
    for term in get_current_session().scalars(
        select(TestDefinition)
        .where(TestDefinition.version_id == version_id, TestDefinition.test_active == True)
        .order_by(*render.TERM_ORDER)
    ):
        terms.setdefault((term.table_name, term.column_name, term.test_type), []).append(term)
    found = _Declarations(unresolved=[], untested=[], overridden=[])
    for (table_name, column_name), prop in _properties(document).items():
        before_prop = before.get((table_name, column_name)) or {}
        if before_prop == prop:
            continue
        label = f"{table_name}.{column_name}"
        declared_before = resolve_unnamed_declarations(before_prop, resolver.known_test_types)
        declared = resolve_unnamed_declarations(prop, resolver.known_test_types)
        found.unresolved.extend(
            f"{label}: {path}" for path in declared.unresolved if path not in declared_before.unresolved
        )
        parameters_before = {term.test_type: term.parameters for term in declared_before.terms}
        for declaration in declared.terms:
            if parameters_before.get(declaration.test_type) == declaration.parameters:
                continue
            test_type = resolver.test_types[declaration.test_type]
            name = test_type.test_name_short or declaration.test_type
            candidates = terms.get((table_name, column_name, declaration.test_type))
            if not candidates:
                found.untested.append(f"{label}: {name}")
            elif _rendered_declaration_differs(candidates, prop):
                found.overridden.append(f"{label}: {name}")
    return found


def _rendered_declaration_differs(terms: list[TestDefinition], prop: dict[str, Any]) -> bool:
    """Whether the first of ``terms`` that renders as a declaration on ``prop`` declares a value
    ``prop`` does not hold. ``terms`` are in render order."""
    logical_type = prop.get("logicalType")
    declaration = next(
        (found for term in terms if (found := property_declaration(term, logical_type)) is not None), {}
    )
    for key, value in declaration.items():
        if isinstance(value, dict):
            options = prop.get(key) if isinstance(prop.get(key), dict) else {}
            if any(options.get(option) != option_value for option, option_value in value.items()):
                return True
        elif prop.get(key) != value:
            return True
    return False


def _properties(document: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (table["name"], prop["name"]): prop
        for table in document.get("schema") or []
        if isinstance(table, dict) and table.get("name")
        for prop in table.get("properties") or []
        if isinstance(prop, dict) and prop.get("name")
    }


def _active_version(suite: TestSuite) -> SuiteVersion | None:
    return SuiteVersion.in_force_for(suite.id)


@dataclass(frozen=True)
class InitializedContract:
    """A contract's first draft, and why its server entry is ``custom`` when it is."""

    draft: SuiteVersion
    custom_server_reason: CustomServerReason | None


def initialize_contract(
    suite: TestSuite, table_group: TableGroup, connection: Connection, username: str | None = None
) -> InitializedContract:
    """Give a newly created contract its first draft, generation set and prefilled document."""
    _assert_contract(suite)
    session = get_current_session()
    server = build_server_block(connection, table_group)
    version = SuiteVersion.next_version_for(suite.id)
    draft = SuiteVersion(
        id=uuid4(),
        test_suite_id=suite.id,
        version=version,
        metadata_document={
            "apiVersion": ODCS_API_VERSION,
            "kind": ODCS_KIND,
            "id": str(suite.id),
            "version": SuiteVersion.document_version(version),
            "name": suite.test_suite,
            "servers": [server.entry],
            "schema": [],
        },
        odcs_api_version=ODCS_API_VERSION,
        created_by=username,
    )
    session.add(draft)
    suite.generation_sets = [CONTRACT_GENERATION_SET]
    session.flush()
    return InitializedContract(draft=draft, custom_server_reason=server.custom_reason)


def add_table(suite: TestSuite, table_name: str) -> ContractGenerationResult:
    """Declare a table on the contract's draft and generate it as ``run_contract_generation`` does,
    merging into any earlier descriptor for it. The contract's own description and tags are left as
    they are. Returns what the generation did."""
    return run_contract_generation(suite.id, table_names=[table_name], refresh_identity=False)


def remove_table(suite: TestSuite, table_name: str) -> dict:
    """Remove a table's descriptor from the contract's draft and delete its terms.

    Returns a report with the number of terms removed.
    """
    version_id, _ = resolve_write_target(suite)
    draft = SuiteVersion.get(version_id)
    document = draft.metadata_document if draft.metadata_document is not None else {}
    document["schema"] = [
        descriptor
        for descriptor in document.get("schema", [])
        if descriptor["name"] != table_name
    ]
    draft.metadata_document = document
    flag_modified(draft, "metadata_document")

    session = get_current_session()
    removed_types = session.execute(
        delete(TestDefinition).where(
            TestDefinition.version_id == version_id,
            TestDefinition.table_name == table_name,
        ).returning(TestDefinition.test_type)
    ).scalars().all()
    session.flush()
    return {"terms_removed": sum(1 for test_type in removed_types if test_type not in MANAGED_TEST_TYPES)}


