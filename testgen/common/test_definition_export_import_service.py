"""Test definition export/import — portable document schemas and import/export logic."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, field_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import Row

from testgen import settings
from testgen.common.database.table_group_service import (
    apply_test_definition_flavor_rules,
    table_group_qualifies_table_refs,
)
from testgen.common.enums import TestScope
from testgen.common.models import get_current_session
from testgen.common.models.data_column import DataColumnChars
from testgen.common.models.data_table import DataTable
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import (
    MANAGED_TEST_TYPES,
    NON_PUBLIC_TEST_TYPES,
    TestDefinition,
    TestType,
    missing_required_fields,
    validate_custom_metadata,
)
from testgen.common.models.test_suite import TestSuite

EXPORT_FORMAT_VERSION = 1


class Origin(StrEnum):
    manual = "manual"
    auto = "auto"
    both = "both"


class ImportMode(StrEnum):
    preview = "preview"
    apply = "apply"
    apply_strict = "apply_strict"


class OnMatch(StrEnum):
    overwrite_all = "overwrite_all"
    overwrite_unlocked = "overwrite_unlocked"
    skip = "skip"


class OnNew(StrEnum):
    skip = "skip"
    create = "create"
    create_and_lock = "create_and_lock"


class OnAbsence(StrEnum):
    do_nothing = "do_nothing"
    delete_all = "delete_all"
    delete_unlocked = "delete_unlocked"


class ImportAction(StrEnum):
    create = "create"
    update = "update"
    skip = "skip"
    delete = "delete"


class ImportReason(StrEnum):
    matched = "matched"
    no_match = "no_match"
    policy = "policy"
    locked = "locked"
    invalid_test_type = "invalid_test_type"
    non_public_test_type = "non_public_test_type"
    invalid_table = "invalid_table"
    invalid_column = "invalid_column"
    missing_external_id = "missing_external_id"
    missing_required_field = "missing_required_field"
    absent = "absent"


IMPORT_ACTION_LABELS: dict[ImportAction, str] = {
    ImportAction.create: "Create",
    ImportAction.update: "Update",
    ImportAction.skip: "Skip",
    ImportAction.delete: "Delete",
}

IMPORT_REASON_LABELS: dict[ImportReason, str] = {
    ImportReason.matched: "Matches an existing test",
    ImportReason.no_match: "No matching test",
    ImportReason.policy: "Excluded by the selected policy",
    ImportReason.locked: "Existing test is locked",
    ImportReason.invalid_test_type: "Unknown test type",
    ImportReason.non_public_test_type: "Test type cannot be imported",
    ImportReason.invalid_table: "Table not in the data catalog",
    ImportReason.invalid_column: "Column not in the data catalog",
    ImportReason.missing_external_id: "Missing external ID",
    ImportReason.missing_required_field: "Missing a required field",
    ImportReason.absent: "Not in the file",
}


# Non-None defaults must match the ORM column defaults in TestDefinition:
#   test_active=True (YNString default="Y"), lock_refresh=False (YNString default="N"),
#   skip_errors=0 (ZeroIfEmptyInteger), window_days=0 (ZeroIfEmptyInteger),
#   history_lookback=0 (Column default=0).
# On export, fields equal to these defaults are omitted to keep the file compact — any
# serialization of the document must pass ``exclude_defaults=True`` (the REST route does this
# via ``response_model_exclude_defaults=True``). On import, model_fields_set distinguishes
# explicit from defaulted, so a non-compact file would force-write every defaulted field.
class TestDefinitionExport(BaseModel):
    """Test definition fields included in the export/import file."""

    model_config = {"from_attributes": True}

    # Matching / identity
    test_type: str
    external_id: UUID | None = None
    last_auto_gen_date: datetime | None = None

    # Definition fields
    table_name: str | None = None
    column_name: str | None = None
    test_description: str | None = None
    test_active: bool = True
    severity: str | None = None
    lock_refresh: bool = False
    export_to_observability: bool | None = None
    skip_errors: int = 0

    # Calibration fields
    baseline_ct: str | None = None
    baseline_unique_ct: str | None = None
    baseline_value: str | None = None
    baseline_value_ct: str | None = None
    threshold_value: str | None = None
    baseline_sum: str | None = None
    baseline_avg: str | None = None
    baseline_sd: str | None = None
    lower_tolerance: str | None = None
    upper_tolerance: str | None = None

    # Subset / grouping
    subset_condition: str | None = None
    groupby_names: str | None = None
    having_condition: str | None = None
    window_date_column: str | None = None
    window_days: int = 0

    # Referential
    match_schema_name: str | None = None
    match_table_name: str | None = None
    match_column_names: str | None = None
    match_subset_condition: str | None = None
    match_groupby_names: str | None = None
    match_having_condition: str | None = None

    # Query / history
    custom_query: str | None = None
    history_calculation: str | None = None
    history_calculation_upper: str | None = None
    history_lookback: int = 0

    # URL / metadata
    external_url: str | None = None
    custom_metadata: dict[str, Any] | None = None

    @field_validator("skip_errors", "window_days", "history_lookback", mode="before")
    @classmethod
    def _coerce_none_to_zero(cls, v: int | None) -> int:
        return v if v is not None else 0

    @field_validator("custom_metadata")
    @classmethod
    def _check_custom_metadata(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        # The import path does not run TestDefinition.validate(), so this is the only enforcement
        # of the custom_metadata shape/size bound on import. Shares validate_custom_metadata with
        # the model so the rule has a single definition.
        error = validate_custom_metadata(v)
        if error:
            raise ValueError(f"custom_metadata {error}")
        return v


class ExportSource(BaseModel):
    project_code: str
    test_suite: str
    table_group: str
    table_group_schema: str
    exported_at: datetime
    testgen_version: str | None = None


class ExportDocument(BaseModel):
    # No default: a defaulted version is stripped by default-omitting serialization,
    # leaving exported documents without their schema-version marker.
    version: int
    source: ExportSource
    definitions: list[TestDefinitionExport]


class ImportConfig(BaseModel):
    mode: ImportMode
    on_match: OnMatch
    on_new: OnNew
    on_absence: OnAbsence


class ImportPayload(BaseModel):
    """Import payload — same structure as an export document, but definitions are typed."""

    version: int = EXPORT_FORMAT_VERSION
    source: ExportSource | None = None
    definitions: list[TestDefinitionExport]


class ImportItemTD(BaseModel):
    idx: int | None = None
    target_id: UUID | None = None


class ImportItem(BaseModel):
    action: ImportAction
    reason: ImportReason
    tds: list[ImportItemTD]


class ImportSummary(BaseModel):
    created: int = 0
    updated: int = 0
    skipped: int = 0
    deleted: int = 0


class ImportResponse(BaseModel):
    summary: ImportSummary
    items: list[ImportItem]


class ImportErrorCode(StrEnum):
    duplicate_natural_key = "duplicate_natural_key"
    unsupported_version = "unsupported_version"


class InvalidImportPayload(ValueError):
    """Import payload rejected before any matching or persistence."""

    def __init__(self, code: ImportErrorCode, detail: str):
        super().__init__(detail)
        self.code = code


class ImportStrictViolation(Exception):
    """``apply_strict`` import with test definitions that would be skipped; nothing was applied."""

    def __init__(self, result: ImportResponse):
        super().__init__(f"{result.summary.skipped} test definitions would be skipped")
        self.result = result


# Fields that must never be written from the import payload on update.
# These are either identity fields (set once on create) or determined by matching logic.
_UPDATE_EXCLUDE_FIELDS = frozenset({"test_type", "last_auto_gen_date", "external_id"})

# Lightweight projection — only the columns needed for matching and policy decisions.
_EXISTING_TD_COLUMNS = (
    TestDefinition.id,
    TestDefinition.test_type,
    TestDefinition.table_name,
    TestDefinition.column_name,
    TestDefinition.last_auto_gen_date,
    TestDefinition.external_id,
    TestDefinition.lock_refresh,
    TestDefinition.match_table_name,
    TestDefinition.match_schema_name,
)


def export_definitions(
    test_suite: TestSuite,
    origin: Origin,
    table_name: str | None,
    test_type: str | None,
) -> ExportDocument:
    session = get_current_session()
    table_group = TableGroup.get(test_suite.table_groups_id)

    # Assign external_id to manual TDs that don't have one yet (idempotent)
    if origin in (Origin.manual, Origin.both):
        session.execute(
            update(TestDefinition)
            .where(
                TestDefinition.test_suite_id == test_suite.id,
                TestDefinition.version_clause(),
                TestDefinition.last_auto_gen_date.is_(None),
                TestDefinition.external_id.is_(None),
            )
            .values(external_id=func.gen_random_uuid())
        )

    # Build filter clauses
    clauses = [TestDefinition.test_suite_id == test_suite.id, TestDefinition.version_clause()]
    if origin == Origin.auto:
        clauses.append(TestDefinition.last_auto_gen_date.isnot(None))
    elif origin == Origin.manual:
        clauses.append(TestDefinition.last_auto_gen_date.is_(None))
    if table_name is not None:
        clauses.append(TestDefinition.table_name == table_name)
    if test_type is not None:
        clauses.append(TestDefinition.test_type == test_type)

    tds = session.scalars(select(TestDefinition).where(*clauses)).all()

    definitions = [TestDefinitionExport.model_validate(td, from_attributes=True) for td in tds]

    return ExportDocument(
        version=EXPORT_FORMAT_VERSION,
        source=ExportSource(
            project_code=test_suite.project_code,
            test_suite=test_suite.test_suite,
            table_group=table_group.table_groups_name,
            table_group_schema=table_group.table_group_schema,
            exported_at=datetime.now(UTC),
            testgen_version=settings.VERSION,
        ),
        definitions=definitions,
    )


def import_definitions(
    test_suite: TestSuite,
    config: ImportConfig,
    payload: ImportPayload,
) -> ImportResponse:
    incoming = payload.definitions
    test_types = _load_test_types()
    table_group = TableGroup.get(test_suite.table_groups_id)
    profiled_tables = set(DataTable.select_table_names(test_suite.table_groups_id, limit=None))
    profiled_columns = DataColumnChars.select_column_names(test_suite.table_groups_id)

    # --- Phase 1: Upfront validation ---
    if payload.version != EXPORT_FORMAT_VERSION:
        raise InvalidImportPayload(
            ImportErrorCode.unsupported_version,
            f"Unsupported export document version {payload.version}; supported version: {EXPORT_FORMAT_VERSION}",
        )
    _check_duplicate_keys(incoming)

    # --- Phase 2: Matching ---
    session = get_current_session()
    existing_rows = session.execute(
        select(*_EXISTING_TD_COLUMNS).where(
            TestDefinition.test_suite_id == test_suite.id, TestDefinition.version_clause()
        )
    ).all()

    auto_index: dict[tuple[str, str | None, str | None], Row] = {}
    manual_index: dict[UUID, Row] = {}
    for row in existing_rows:
        if row.last_auto_gen_date is not None:
            auto_index[(row.test_type, row.table_name, row.column_name)] = row
        elif row.external_id is not None:
            manual_index[row.external_id] = row

    # Plan actions for each incoming TD
    actions: list[_PlannedAction] = []
    matched_target_ids: set[UUID] = set()

    for idx, td_import in enumerate(incoming):
        # Match first — even if validation fails, the target must be protected from absence-delete
        is_auto = td_import.last_auto_gen_date is not None
        target: Row | None = None

        if is_auto:
            key = (td_import.test_type, td_import.table_name, td_import.column_name)
            target = auto_index.get(key)
        elif td_import.external_id is not None:
            target = manual_index.get(td_import.external_id)

        if target is not None:
            matched_target_ids.add(target.id)

        # Validate after matching
        if not is_auto and td_import.external_id is None:
            actions.append(_PlannedAction(ImportAction.skip, ImportReason.missing_external_id, idx, td_import, target))
            continue

        if td_import.test_type not in test_types:
            actions.append(_PlannedAction(ImportAction.skip, ImportReason.invalid_test_type, idx, td_import, target))
            continue

        # A non-public type is a real row in ``test_types``, so it clears the check above. Only a new
        # definition is refused: an update keeps the stored type, so a matched one stays importable.
        if target is None and td_import.test_type in NON_PUBLIC_TEST_TYPES:
            actions.append(
                _PlannedAction(ImportAction.skip, ImportReason.non_public_test_type, idx, td_import, target)
            )
            continue

        if not _is_profiled(td_import, profiled_tables):
            actions.append(_PlannedAction(ImportAction.skip, ImportReason.invalid_table, idx, td_import, target))
            continue

        if not _is_column_profiled(td_import, test_types[td_import.test_type], profiled_columns):
            actions.append(_PlannedAction(ImportAction.skip, ImportReason.invalid_column, idx, td_import, target))
            continue

        if missing_required_fields(test_types[td_import.test_type], lambda field: getattr(td_import, field, None)):
            actions.append(
                _PlannedAction(ImportAction.skip, ImportReason.missing_required_field, idx, td_import, target)
            )
            continue

        if target is None:
            action, reason = _resolve_new_action(config)
        else:
            action, reason = _resolve_match_action(config, target)

        actions.append(_PlannedAction(action, reason, idx, td_import, target))

    # Plan absence actions for unmatched existing TDs
    if config.on_absence != OnAbsence.do_nothing:
        for row in existing_rows:
            # Managed TDs are created and removed by TestGen, never by an import
            if row.id not in matched_target_ids and row.test_type not in MANAGED_TEST_TYPES:
                if config.on_absence == OnAbsence.delete_all:
                    actions.append(_PlannedAction(ImportAction.delete, ImportReason.absent, None, None, row))
                elif config.on_absence == OnAbsence.delete_unlocked and not row.lock_refresh:
                    actions.append(_PlannedAction(ImportAction.delete, ImportReason.absent, None, None, row))
                # Locked TDs surviving delete_unlocked are omitted entirely (per design)

    # --- Phase 3: Apply ---
    has_skips = any(a.action == ImportAction.skip for a in actions)
    if config.mode == ImportMode.apply_strict and has_skips:
        # Built before apply, so created TDs have no target_id — correct, nothing was persisted.
        # The post-apply build below is NOT redundant: _apply_actions fills planned.target for creates.
        raise ImportStrictViolation(_build_response(actions))

    if config.mode in (ImportMode.apply, ImportMode.apply_strict):
        _apply_actions(actions, test_suite, table_group, config)

    return _build_response(actions)


# --- Helpers ---


@dataclass
class _PlannedAction:
    action: ImportAction
    reason: ImportReason
    idx: int | None  # None for absence deletes (target-only, not in the file)
    td_import: TestDefinitionExport | None  # None for absence deletes
    target: Any  # Row or TestDefinition (after create flush), None for unmatched creates


def _load_test_types() -> dict[str, TestType]:
    session = get_current_session()
    return {tt.test_type: tt for tt in session.scalars(select(TestType).where(TestType.active == "Y")).all()}


def _is_profiled(td_import: TestDefinitionExport, profiled_tables: set[str]) -> bool:
    """Check that the TD's table exists in profiled data."""
    if td_import.table_name is None:
        return True
    return td_import.table_name in profiled_tables


def _is_column_profiled(
    td_import: TestDefinitionExport, test_type: TestType, profiled_columns: set[tuple[str, str]]
) -> bool:
    """Check that the TD's column exists in profiled data. Only column-scope test types are validated:
    the other scopes can hold an expression (e.g. SUM(col)) rather than a physical column name."""
    if test_type.test_scope != TestScope.COLUMN or not td_import.table_name or not td_import.column_name:
        return True
    return (td_import.table_name, td_import.column_name) in profiled_columns


def _check_duplicate_keys(incoming: list[TestDefinitionExport]) -> None:
    auto_keys: set[tuple[str, str | None, str | None]] = set()
    manual_keys: set[UUID] = set()

    for idx, td in enumerate(incoming):
        if td.last_auto_gen_date is not None:
            key = (td.test_type, td.table_name, td.column_name)
            if key in auto_keys:
                raise InvalidImportPayload(
                    ImportErrorCode.duplicate_natural_key,
                    f"Duplicate auto-gen key at index {idx}: ({td.test_type}, {td.table_name}, {td.column_name})",
                )
            auto_keys.add(key)
        else:
            if td.external_id is None:
                continue
            if td.external_id in manual_keys:
                raise InvalidImportPayload(
                    ImportErrorCode.duplicate_natural_key,
                    f"Duplicate external_id at index {idx}: {td.external_id}",
                )
            manual_keys.add(td.external_id)


def _resolve_match_action(config: ImportConfig, target: Row) -> tuple[ImportAction, ImportReason]:
    if config.on_match == OnMatch.skip:
        return ImportAction.skip, ImportReason.policy
    elif config.on_match == OnMatch.overwrite_unlocked and target.lock_refresh:
        return ImportAction.skip, ImportReason.locked
    else:
        return ImportAction.update, ImportReason.matched


def _resolve_new_action(config: ImportConfig) -> tuple[ImportAction, ImportReason]:
    if config.on_new == OnNew.skip:
        return ImportAction.skip, ImportReason.no_match
    else:
        return ImportAction.create, ImportReason.no_match


def _apply_actions(
    actions: list[_PlannedAction],
    test_suite: TestSuite,
    table_group: TableGroup,
    config: ImportConfig,
) -> None:
    session = get_current_session()
    now = datetime.now(UTC)
    version_id = session.scalar(select(SuiteVersion.resolved_for(test_suite.id)))
    TestDefinition.assert_version_writable(version_id)
    # Resolved before either loop: a lookup inside pass 1 would autoflush the pending INSERTs.
    qualifies_table_refs = table_group_qualifies_table_refs(table_group.id)

    # Pass 1: build new TDs and register them in the session.
    for planned in actions:
        if planned.action == ImportAction.create and planned.td_import is not None:
            td = _create_td(
                planned.td_import, test_suite, table_group, config, now, version_id, qualifies_table_refs
            )
            session.add(td)
            planned.target = td

    # Single flush emits all INSERTs in one batch (SQLAlchemy uses executemany).
    session.flush()

    # These were registered with `add`, not `save`, so none of them minted a contract identity.
    TestDefinition.assign_missing_term_ids(version_id)

    # Pass 2: updates and deletes.
    ids_to_delete: list[UUID] = []
    for planned in actions:
        if planned.action == ImportAction.update and planned.target is not None and planned.td_import is not None:
            _update_td(planned.td_import, planned.target, table_group, qualifies_table_refs)
        elif planned.action == ImportAction.delete and planned.target is not None:
            ids_to_delete.append(planned.target.id)

    if ids_to_delete:
        session.execute(
            delete(TestDefinition).where(
                TestDefinition.id.in_(ids_to_delete), TestDefinition.version_clause()
            )
        )


def _create_td(
    td_import: TestDefinitionExport,
    test_suite: TestSuite,
    table_group: TableGroup,
    config: ImportConfig,
    now: datetime,
    version_id: UUID,
    qualifies_table_refs: bool,
) -> TestDefinition:
    is_auto = td_import.last_auto_gen_date is not None

    td = TestDefinition()

    # Set fields from the payload (only explicitly provided ones)
    for field_name in td_import.model_fields_set:
        if field_name in ("last_auto_gen_date", "external_id", "lock_refresh"):
            continue  # handled specially below
        setattr(td, field_name, getattr(td_import, field_name))

    # Target context
    td.test_suite_id = test_suite.id
    td.version_id = version_id
    td.table_groups_id = test_suite.table_groups_id
    td.schema_name = table_group.table_group_schema
    apply_test_definition_flavor_rules(td, table_group, qualifies_table_refs=qualifies_table_refs)

    # Instance-local defaults
    td.profile_run_id = None
    td.profiling_as_of_date = None
    td.prediction = None
    td.check_result = None
    td.test_definition_status = None
    td.flagged = False

    # Special field handling
    td.last_auto_gen_date = now if is_auto else None
    td.external_id = td_import.external_id
    if config.on_new == OnNew.create_and_lock and is_auto:
        td.lock_refresh = True
    else:
        td.lock_refresh = td_import.lock_refresh
    td.last_manual_update = now

    return td


def _update_td(
    td_import: TestDefinitionExport, target: Row, table_group: TableGroup, qualifies_table_refs: bool
) -> None:
    session = get_current_session()

    values = {
        field_name: getattr(td_import, field_name)
        for field_name in td_import.model_fields_set
        if field_name not in _UPDATE_EXCLUDE_FIELDS
    }

    # The payload carries the source's reference schema, which names nothing reachable on a target
    # whose flavor has only one. Write the settled value only where it differs from what is stored,
    # so a field the file omits stays untouched.
    settled = TestDefinition(
        schema_name=table_group.table_group_schema,
        match_table_name=values.get("match_table_name", target.match_table_name),
        match_schema_name=values.get("match_schema_name", target.match_schema_name),
    )
    apply_test_definition_flavor_rules(settled, table_group, qualifies_table_refs=qualifies_table_refs)
    if settled.match_schema_name != target.match_schema_name:
        values["match_schema_name"] = settled.match_schema_name

    # Inherit source's external_id if target has none
    if target.external_id is None and td_import.external_id is not None:
        values["external_id"] = td_import.external_id

    values["last_manual_update"] = datetime.now(UTC)

    session.execute(
        update(TestDefinition).where(TestDefinition.id == target.id).values(**values)
    )


def _build_response(actions: list[_PlannedAction]) -> ImportResponse:
    summary = ImportSummary()
    items_by_key: dict[tuple[ImportAction, ImportReason], list[ImportItemTD]] = {}

    for planned in actions:
        if planned.action == ImportAction.create:
            summary.created += 1
        elif planned.action == ImportAction.update:
            summary.updated += 1
        elif planned.action == ImportAction.skip:
            summary.skipped += 1
        elif planned.action == ImportAction.delete:
            summary.deleted += 1

        key = (planned.action, planned.reason)
        td_entry = ImportItemTD(
            idx=planned.idx,
            target_id=planned.target.id if planned.target is not None else None,
        )
        items_by_key.setdefault(key, []).append(td_entry)

    items = [
        ImportItem(action=action, reason=reason, tds=tds)
        for (action, reason), tds in items_by_key.items()
    ]

    return ImportResponse(summary=summary, items=items)
