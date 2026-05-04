"""Business logic for test definition export/import."""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import Row

from testgen import settings
from testgen.api.deps import api_error
from testgen.api.schemas import (
    ExportDocument,
    ExportSource,
    ImportAction,
    ImportConfig,
    ImportItem,
    ImportItemTD,
    ImportMode,
    ImportPayload,
    ImportReason,
    ImportResponse,
    ImportSummary,
    OnAbsence,
    OnMatch,
    OnNew,
    Origin,
    TestDefinitionExport,
)
from testgen.common.models import get_current_session
from testgen.common.models.data_table import DataTable
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import TestDefinition, TestType
from testgen.common.models.test_suite import TestSuite

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
                TestDefinition.last_auto_gen_date.is_(None),
                TestDefinition.external_id.is_(None),
            )
            .values(external_id=func.gen_random_uuid())
        )

    # Build filter clauses
    clauses = [TestDefinition.test_suite_id == test_suite.id]
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
    valid_test_types = _load_valid_test_types()
    table_group = TableGroup.get(test_suite.table_groups_id)
    profiled_tables = set(DataTable.select_table_names(test_suite.table_groups_id, limit=None))

    # --- Phase 1: Upfront validation ---
    _check_duplicate_keys(incoming)

    # --- Phase 2: Matching ---
    session = get_current_session()
    existing_rows = session.execute(
        select(*_EXISTING_TD_COLUMNS).where(TestDefinition.test_suite_id == test_suite.id)
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

        if td_import.test_type not in valid_test_types:
            actions.append(_PlannedAction(ImportAction.skip, ImportReason.invalid_test_type, idx, td_import, target))
            continue

        if not _is_profiled(td_import, profiled_tables):
            actions.append(_PlannedAction(ImportAction.skip, ImportReason.invalid_table, idx, td_import, target))
            continue

        if target is None:
            action, reason = _resolve_new_action(config)
        else:
            action, reason = _resolve_match_action(config, target)

        actions.append(_PlannedAction(action, reason, idx, td_import, target))

    # Plan absence actions for unmatched existing TDs
    if config.on_absence != OnAbsence.do_nothing:
        for row in existing_rows:
            if row.id not in matched_target_ids:
                if config.on_absence == OnAbsence.delete_all:
                    actions.append(_PlannedAction(ImportAction.delete, ImportReason.absent, None, None, row))
                elif config.on_absence == OnAbsence.delete_unlocked and not row.lock_refresh:
                    actions.append(_PlannedAction(ImportAction.delete, ImportReason.absent, None, None, row))
                # Locked TDs surviving delete_unlocked are omitted entirely (per design)

    # --- Phase 3: Apply ---
    should_apply = config.mode in (ImportMode.apply, ImportMode.apply_strict)
    has_skips = any(a.action == ImportAction.skip for a in actions)

    if should_apply and not (config.mode == ImportMode.apply_strict and has_skips):
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


def _load_valid_test_types() -> set[str]:
    session = get_current_session()
    rows = session.execute(select(TestType.test_type)).all()
    return {row[0] for row in rows}


def _is_profiled(td_import: TestDefinitionExport, profiled_tables: set[str]) -> bool:
    """Check that the TD's table exists in profiled data. Column is not validated
    because some test types use expressions (e.g. SUM(col)) rather than physical column names."""
    if td_import.table_name is None:
        return True
    return td_import.table_name in profiled_tables


def _check_duplicate_keys(incoming: list[TestDefinitionExport]) -> None:
    auto_keys: set[tuple[str, str | None, str | None]] = set()
    manual_keys: set[UUID] = set()

    for idx, td in enumerate(incoming):
        if td.last_auto_gen_date is not None:
            key = (td.test_type, td.table_name, td.column_name)
            if key in auto_keys:
                raise api_error(
                    400,
                    "duplicate_natural_key",
                    f"Duplicate auto-gen key at index {idx}: ({td.test_type}, {td.table_name}, {td.column_name})",
                )
            auto_keys.add(key)
        else:
            if td.external_id is None:
                continue
            if td.external_id in manual_keys:
                raise api_error(
                    400,
                    "duplicate_natural_key",
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

    # Pass 1: build new TDs and register them in the session.
    for planned in actions:
        if planned.action == ImportAction.create and planned.td_import is not None:
            td = _create_td(planned.td_import, test_suite, table_group, config, now)
            session.add(td)
            planned.target = td

    # Single flush emits all INSERTs in one batch (SQLAlchemy uses executemany).
    session.flush()

    # Pass 2: updates and deletes.
    ids_to_delete: list[UUID] = []
    for planned in actions:
        if planned.action == ImportAction.update and planned.target is not None and planned.td_import is not None:
            _update_td(planned.td_import, planned.target)
        elif planned.action == ImportAction.delete and planned.target is not None:
            ids_to_delete.append(planned.target.id)

    if ids_to_delete:
        session.execute(delete(TestDefinition).where(TestDefinition.id.in_(ids_to_delete)))


def _create_td(
    td_import: TestDefinitionExport,
    test_suite: TestSuite,
    table_group: TableGroup,
    config: ImportConfig,
    now: datetime,
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
    td.table_groups_id = test_suite.table_groups_id
    td.schema_name = table_group.table_group_schema

    # Instance-local defaults
    td.profile_run_id = None
    td.profiling_as_of_date = None
    td.prediction = None
    td.check_result = None
    td.test_mode = None
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


def _update_td(td_import: TestDefinitionExport, target: Row) -> None:
    session = get_current_session()

    values = {
        field_name: getattr(td_import, field_name)
        for field_name in td_import.model_fields_set
        if field_name not in _UPDATE_EXCLUDE_FIELDS
    }

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
