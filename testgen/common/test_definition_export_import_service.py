"""Test definition export/import — portable document schemas and import/export logic."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.engine import Row

from testgen import settings
from testgen.common import contract_service
from testgen.common.contract_rules import writable_tables
from testgen.common.database.table_group_service import (
    apply_test_definition_flavor_rules,
    table_group_qualifies_table_refs,
)
from testgen.common.enums import MANAGED_TEST_TYPES, SuiteType, TestScope
from testgen.common.flavors import reports_table_group_schema
from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.data_column import DataColumnChars
from testgen.common.models.data_table import DataTable
from testgen.common.models.suite_version import SuiteVersion, VersionState
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import (
    NON_PUBLIC_TEST_TYPES,
    TestDefinition,
    TestType,
    missing_required_fields,
    test_definition_errors,
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
    managed_test_type = "managed_test_type"
    managed_test = "managed_test"
    invalid_table = "invalid_table"
    undeclared_table = "undeclared_table"
    invalid_column = "invalid_column"
    missing_external_id = "missing_external_id"
    missing_required_field = "missing_required_field"
    invalid_field = "invalid_field"
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
    ImportReason.managed_test_type: "Test type cannot be imported",
    ImportReason.managed_test: "Managed by TestGen",
    ImportReason.invalid_table: "Table not in the data catalog",
    ImportReason.undeclared_table: "Table not declared by the contract",
    ImportReason.invalid_column: "Column not in the data catalog",
    ImportReason.missing_external_id: "Missing external ID (required to match a manual test)",
    ImportReason.missing_required_field: "Missing a required field",
    ImportReason.invalid_field: "Invalid field value",
    ImportReason.absent: "Not in the file",
}


def import_reason_label(reason: ImportReason, errors: dict[str, str] | None = None) -> str:
    """The reason's label, followed by each invalid field and why when there are any."""
    label = IMPORT_REASON_LABELS.get(reason, reason.value)
    if not errors:
        return label
    return f"{label}. " + "; ".join(f"{field}: {why}" for field, why in errors.items())


# Non-None defaults must match the ORM column defaults in TestDefinition:
#   test_active=True (YNString default="Y"), lock_refresh=False (YNString default="N"),
#   skip_errors=0 (ZeroIfEmptyInteger), window_days=0 (ZeroIfEmptyInteger),
#   history_lookback=0 (Column default=0).
# On export, fields equal to these defaults are omitted to keep the file compact — any
# serialization of the document must pass ``exclude_defaults=True`` (the REST route does this
# via ``response_model_exclude_defaults=True``). On import, model_fields_set distinguishes
# explicit from defaulted, so a non-compact file would force-write every defaulted field.
class TestDefinitionExport(BaseModel):
    """One test definition in an export document. On import, only the fields present in the file are written: a field
    left out keeps the matched test's value. Fields equal to their default are left out of an export.
    """

    model_config = {"from_attributes": True}

    # Matching / identity
    test_type: str = Field(
        description="The test type, given as its code, e.g. `Alpha_Trunc`. An auto-generated test is matched on "
        "import by its `test_type`, `table_name` and `column_name`. A matched test keeps its stored test type. A new "
        "test cannot use a test type TestGen creates and removes itself, such as schema conformance; the import skips "
        "it with `managed_test_type`. A matched test of such a type is not updated either; the import skips it with "
        "`managed_test`."
    )
    external_id: UUID | None = Field(
        default=None,
        description="Manually created tests only. A UUID that identifies the test across environments, so an import "
        "can match it. An export assigns one to each manual test that has none. A file prepared by hand must set "
        "one, any UUID, on every manual test: an import skips a manual test without one. When a matched test has "
        "none, it takes this value.",
    )
    last_auto_gen_date: datetime | None = Field(
        default=None,
        description="When test generation last created or refreshed the test, in UTC. `null` for a manually created "
        "test. On import, any value marks the test as auto-generated, which decides how it is matched. The value "
        "itself is not kept: a created test is stamped with the import time, and a matched test keeps its own.",
    )

    # Provenance
    profiling_as_of_date: datetime | None = Field(
        default=None,
        description="The as-of date of the profiling results the test was generated from, in UTC: the generation "
        "time less the table group's `profiling_delay_days`. `null` for a manually created test. An import ignores "
        "it.",
    )
    last_manual_update: datetime | None = Field(
        default=None,
        description="When the test was last edited by hand or by an import, in UTC. An import ignores the value and "
        "records its own time.",
    )

    # Definition fields
    table_name: str | None = Field(
        default=None,
        description="The table the test checks. It must be in the target table group's data catalog; an import "
        "skips the test otherwise.",
    )
    column_name: str | None = Field(
        default=None,
        description="What the test focuses on within the table, depending on the test type: the column a column test "
        "checks, the aggregate expression or comma-separated categorical columns a referential test compares, or a "
        "short label describing a custom test, unique within the test suite. Blank for table-level tests. For a "
        "column test, the column must be in the target table group's data catalog; an import skips the test "
        "otherwise.",
    )
    test_description: str | None = Field(
        default=None, description="A description of the test."
    )
    test_active: bool = Field(default=True, description="Run the test. `false` deactivates it, so test runs skip it.")
    severity: str | None = Field(
        default=None,
        description="How a failing result is reported: `Fail`, `Warning`, or `Log`. A `Log` result is recorded "
        "without passing or failing. Omit to use the test suite's default severity, or the test type's when the "
        "suite sets none.",
    )
    lock_refresh: bool = Field(
        default=False,
        description="Protect the test from test generation: a locked test keeps its parameters when tests are "
        "regenerated. On import, `overwrite_unlocked` and `delete_unlocked` leave locked tests alone, and "
        "`create_and_lock` locks the auto-generated tests it creates.",
    )
    export_to_observability: bool | None = Field(
        default=None,
        description="Send the test's results to DataOps Observability. `null` follows the test suite's setting.",
    )
    skip_errors: int = Field(
        default=0,
        description="Custom, duplicate-row, aggregate-comparison, and value-combination tests only. The number of "
        "failing records, groups, or value combinations the test allows before it fails.",
    )

    # Calibration fields
    baseline_ct: str | None = Field(
        default=None,
        description="Tests that compare against a baseline count only. The count expected at baseline, e.g. the "
        "number of null values for `Match_Null_Ct`, or the record count for `Row_Ct_Pct` and `Missing_Pct`.",
    )
    baseline_unique_ct: str | None = Field(
        default=None,
        description="Tests that compare against a baseline distinct count only. The number of distinct values "
        "expected at baseline, e.g. for `Match_Distinct_Ct` and `Unique_Pct`.",
    )
    baseline_value: str | None = Field(
        default=None,
        description="Tests that compare against a baseline value only. The expected value, list, or pattern, "
        "depending on the test type: e.g. the constant for `Constant`, the earliest date for `Match_Min_Date`, the "
        "expected values as a comma-separated list for `LOV_Match` and `LOV_All`, or the pattern for "
        "`Pattern_Match`.",
    )
    baseline_value_ct: str | None = Field(
        default=None,
        description="Tests that compare against a baseline only. The count of values at baseline, e.g. for "
        "`Avg_Shift` and `Missing_Pct`. For `Distinct_Value_Ct`, the count of distinct values.",
    )
    threshold_value: str | None = Field(
        default=None,
        description="The value the test's measure is compared with. Its meaning depends on the test type: for most "
        "tests, the number of failing values the test allows; for others, an expected value or percentage, e.g. the "
        "expected row count for `Match_Row_Ct` or the highest divergence allowed for `Distribution_Shift`.",
    )
    baseline_sum: str | None = Field(
        default=None,
        description="Tests that compare against a baseline sum only. The sum expected at baseline, e.g. the total of "
        "the column's values for `Match_Sum`, or their combined length in characters for `Match_Total_Length`.",
    )
    baseline_avg: str | None = Field(
        default=None,
        description="Tests that compare against a baseline mean only. The mean of the column's values at baseline, "
        "e.g. for `Avg_Shift` and `Outlier_Pct_Above`.",
    )
    baseline_sd: str | None = Field(
        default=None,
        description="Tests that compare against a baseline spread only. The standard deviation of the column's "
        "values at baseline, e.g. for `Avg_Shift` and `Match_Stdev`.",
    )
    lower_tolerance: str | None = Field(
        default=None,
        description="The lower bound of an acceptable range, depending on the test type: an offset added to the "
        "reference measure for `Aggregate_Balance_Percent` (a percent) and `Aggregate_Balance_Range` (a constant), "
        "negative for a bound below the reference (e.g. `-5`), "
        "the minimum result for `SQL_Metric`, or the minimum length for `Text_Length_Range`. Leave blank for no "
        "minimum where the test type allows it. When `history_calculation` is set, the test sets this bound from its "
        "recent results, replacing the value given here.",
    )
    upper_tolerance: str | None = Field(
        default=None,
        description="The upper bound of an acceptable range, depending on the test type: an offset added to the "
        "reference measure for `Aggregate_Balance_Percent` (a percent) and `Aggregate_Balance_Range` (a constant), "
        "the maximum result for `SQL_Metric`, the maximum length for `Text_Length_Range`, or the allowed difference "
        "as a fraction of the baseline for `Match_Sum` and `Match_Stdev` (e.g. `0.001` allows 0.1 percent). When "
        "`history_calculation_upper` is set, the test sets this bound from its recent results, replacing the value "
        "given here.",
    )

    # Subset / grouping
    subset_condition: str | None = Field(
        default=None,
        description="Referential tests and some table-level tests only. A condition selecting the records to test, "
        "written like a SQL `WHERE` clause, e.g. `status = 'SHIPPED'`.",
    )
    groupby_names: str | None = Field(
        default=None,
        description="Columns of the tested table, separated by commas, that the test groups by: the grouping columns "
        "of an aggregate comparison, the columns that define a duplicate record for `Dupe_Rows`, or the key column "
        "that identifies each row for the keyed hash tests.",
    )
    having_condition: str | None = Field(
        default=None,
        description="Aggregate comparison and value-combination tests only. A condition on the grouped records of "
        "the tested table, written like a SQL `HAVING` clause, e.g. `SUM(sales) < 100`.",
    )
    window_date_column: str | None = Field(
        default=None,
        description="Time-window tests only. The date or timestamp column that defines the time windows.",
    )
    window_days: int = Field(
        default=0,
        description="Time-window tests only. The length of each time window, in days. The test compares the most "
        "recent window with the window of the same length before it.",
    )

    # Referential
    match_schema_name: str | None = Field(
        default=None,
        description="Referential tests only. The schema of the second table: the matching or reference table the "
        "test compares with.",
    )
    match_table_name: str | None = Field(
        default=None, description="Referential tests only. The name of the second table."
    )
    match_column_names: str | None = Field(
        default=None,
        description="The aggregate expression to compute in the second table for an aggregate comparison, e.g. "
        "`SUM(amount)`. For a `CUSTOM` test, the comma-separated result columns that hold PII, redacted for callers "
        "without permission to view PII.",
    )
    match_subset_condition: str | None = Field(
        default=None,
        description="Referential tests only. A condition selecting the records of the second table to compare with, "
        "written like a SQL `WHERE` clause, e.g. `status = 'SHIPPED'`.",
    )
    match_groupby_names: str | None = Field(
        default=None,
        description="Referential tests only. Columns of the second table, separated by commas: the grouping columns "
        "of an aggregate comparison, or the columns compared with the tested table's `column_name` for `Combo_Match` "
        "and `Distribution_Shift`.",
    )
    match_having_condition: str | None = Field(
        default=None,
        description="Aggregate comparison and value-combination tests only. A condition on the grouped records of "
        "the second table, written like a SQL `HAVING` clause.",
    )

    # Query / history
    custom_query: str | None = Field(
        default=None,
        description="Custom SQL, depending on the test type: for `CUSTOM`, a query returning the records that fail, "
        "so the test passes when it returns none; for `Condition_Flag`, an expression that is true for a failing "
        "record; for `SQL_Metric`, a query returning one numeric value; for `Table_Freshness`, the expression that "
        "fingerprints the table's state. Rejected on other test types.",
    )
    history_calculation: str | None = Field(
        default=None,
        description="Tests whose lower bound is calculated from their own recent results only, such as "
        "`Table_Freshness`. How the test sets `lower_tolerance` from its last `history_lookback` results: "
        "`Value` (the latest result), `Minimum`, `Maximum`, `Sum`, `Average`, or an expression written `EXPR:[…]` "
        "that references `{VALUE}`, `{MINIMUM}`, `{MAXIMUM}`, `{SUM}`, `{AVERAGE}` and `{STANDARD_DEVIATION}`, e.g. "
        "`EXPR:[1.5 * {AVERAGE}]`.",
    )
    history_calculation_upper: str | None = Field(
        default=None,
        description="Tests whose upper bound is calculated from their own recent results only. How the test sets "
        "`upper_tolerance`, with the same values as `history_calculation`.",
    )
    history_lookback: int = Field(
        default=0,
        description="Tests whose bounds are calculated from their own recent results only. The number of most recent "
        "results the calculation uses. Ignored by `Value`, which uses only the latest result.",
    )

    # URL / metadata
    external_url: str | None = Field(default=None, description="A link stored with the test.")
    custom_metadata: dict[str, Any] | None = Field(
        default=None,
        description="A JSON object of key-value pairs stored with the test, up to 50 keys and 10,240 "
        "bytes. The `odcs` key is reserved for data contract quality-rule fields and must itself be an object.",
    )

    @field_validator("skip_errors", "window_days", "history_lookback", mode="before")
    @classmethod
    def _coerce_none_to_zero(cls, v: int | None) -> int:
        return v if v is not None else 0


class ExportSource(BaseModel):
    """Where a document's test definitions were exported from."""

    project_code: str
    test_suite: str = Field(description="The name of the test suite the definitions were exported from.")
    table_group: str = Field(description="The name of that suite's table group.")
    table_group_schema: str | None = Field(
        default=None,
        description="The table group's schema, or its data space on Salesforce Data 360. Absent on a file connection.",
    )
    exported_at: datetime = Field(description="When the document was exported, in UTC.")
    testgen_version: str | None = Field(default=None, description="The TestGen version that exported the document.")
    contract_version: int | None = Field(
        default=None, description="Contracts only. The number of the contract version the definitions belong to."
    )


_FORMAT_VERSION = (
    "The document format version. `1` is the only version; an import rejects any other with `unsupported_version`."
)
_DEFINITIONS = "The test definitions, in file order. An import refers to each by its position, `idx`."


class ExportDocument(BaseModel):
    """A portable document of test definitions, as exported from a test suite and accepted by an import."""

    # No default: a defaulted version is stripped by default-omitting serialization,
    # leaving exported documents without their schema-version marker.
    version: int = Field(description=_FORMAT_VERSION)
    source: ExportSource = Field(
        description="Where the definitions were exported from. Informational: an import does not apply it."
    )
    definitions: list[TestDefinitionExport] = Field(description=_DEFINITIONS)


class ImportConfig(BaseModel):
    """How an import treats matched, new, and absent test definitions, and whether it applies them."""

    mode: ImportMode = Field(
        description="`preview` reports what the import would do and changes nothing. `apply` writes every valid "
        "definition and reports the rest as skipped. `apply_strict` writes only when no definition would be "
        "skipped; otherwise it returns `400` with the projected result and changes nothing."
    )
    on_match: OnMatch = Field(
        description="What to do with a definition that matches an existing test: `overwrite_all` updates it even "
        "when locked, `overwrite_unlocked` updates it unless it is locked, and `skip` leaves it unchanged. An update "
        "writes only the fields present in the file."
    )
    on_new: OnNew = Field(
        description="What to do with a definition that matches no existing test: `create` creates it with the "
        "file's `lock_refresh`, `create_and_lock` creates it and locks it when it is auto-generated, and `skip` "
        "leaves it out."
    )
    on_absence: OnAbsence = Field(
        description="What to do with existing tests that no definition in the file matches: `do_nothing`, "
        "`delete_all` (even locked ones), or `delete_unlocked`. Tests of a type TestGen creates and removes itself, "
        "such as schema conformance tests, are never deleted."
    )


class ImportPayload(BaseModel):
    """A document to import, in the form an export returns."""

    version: int = Field(default=EXPORT_FORMAT_VERSION, description=_FORMAT_VERSION)
    source: ExportSource | None = Field(
        default=None, description="Where the definitions were exported from. Optional, and not applied."
    )
    definitions: list[TestDefinitionExport] = Field(description=_DEFINITIONS)


class ImportItemTD(BaseModel):
    """One test definition an import action applies to: its place in the file and the test it matches."""

    idx: int | None = Field(
        default=None,
        description="The definition's position in the file's `definitions`, starting at 0. `null` for a deletion, "
        "which has no entry in the file.",
    )
    target_id: UUID | None = Field(
        default=None,
        description="The ID of the test the action applies to. `null` for a definition with no match, and for a "
        "creation in a preview.",
    )
    errors: dict[str, str] | None = Field(
        default=None,
        description="For a definition skipped as `missing_required_field` or `invalid_field`, each field at fault "
        "mapped to what is wrong with it.",
    )


class ImportItem(BaseModel):
    """One action and its reason, with the test definitions it applies to. In a preview, what the import would do."""

    action: ImportAction = Field(
        description="`create`, `update`, `skip`, or `delete`. In a preview, what the import would do."
    )
    reason: ImportReason = Field(
        description="Why the action applies: `matched` (matches an existing test), `no_match` (matches none), "
        "`policy` (`on_match` is `skip`), `locked` (the matched test is locked and `on_match` is "
        "`overwrite_unlocked`), `invalid_test_type` (no such test type), `managed_test_type` (a test type TestGen "
        "creates itself), `managed_test` (the matched test is one TestGen manages), `invalid_table` (the table is not in the table group's data catalog), `invalid_column` "
        "(the column is not in its table in the data catalog), `missing_external_id` (a manual test without "
        "`external_id`), `missing_required_field` (a field the test type requires is blank), `invalid_field` (a "
        "field the test type does not use, or a value it does not accept), or `absent` (an existing test the file "
        "does not include)."
    )
    tds: list[ImportItemTD] = Field(description="The test definitions this action and reason apply to.")


class ImportSummary(BaseModel):
    """Counts of test definitions by action. In a preview, what the import would do."""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    deleted: int = 0


class ContractVersion(BaseModel):
    """A contract version, by its number and its state."""

    number: int = Field(description="The version's number, counting from 1.")
    state: VersionState = Field(description="`draft`, `active` (the agreement in force), or `superseded`.")


class ImportResponse(BaseModel):
    """The result of an import. In a preview, what the import would do."""

    summary: ImportSummary = Field(
        description="How many test definitions the import created, updated, skipped, and deleted, or would in a "
        "preview."
    )
    items: list[ImportItem] = Field(description="The test definitions grouped by action and reason.")
    version: ContractVersion | None = Field(
        default=None,
        description=(
            "Contracts only. The version the import writes to, or `null` when it would write nothing. A preview into a "
            "frozen version names the draft that applying the import would open."
        ),
    )


class ImportErrorCode(StrEnum):
    duplicate_natural_key = "duplicate_natural_key"
    unsupported_version = "unsupported_version"


class InvalidImportPayload(ValueError):
    """Import payload rejected before any matching or persistence."""

    def __init__(self, code: ImportErrorCode, detail: str):
        super().__init__(detail)
        self.code = code


class ImportTargetMissing(ValueError):
    """An existing test definition the import matched was deleted before the import wrote to it."""

    def __init__(self, row_id: UUID):
        super().__init__(f"Test definition {row_id} no longer exists.")
        self.row_id = row_id


class ImportStrictViolation(Exception):
    """``apply_strict`` import with test definitions that would be skipped; nothing was applied."""

    def __init__(self, result: ImportResponse):
        super().__init__(f"{result.summary.skipped} test definitions would be skipped")
        self.result = result


# Exported for reference only: import stamps its own values on every definition it writes.
_PROVENANCE_FIELDS = frozenset({"profiling_as_of_date", "last_manual_update"})

# Fields that must never be written from the import payload on update: identity fields (set once on
# create), fields determined by matching logic, and provenance.
_UPDATE_EXCLUDE_FIELDS = frozenset({"test_type", "last_auto_gen_date", "external_id"}) | _PROVENANCE_FIELDS

# The columns needed for matching and policy decisions, plus every field the file can carry, so a
# matched definition is validated as it would be saved.
_EXISTING_TD_COLUMNS = tuple(
    getattr(TestDefinition, name)
    for name in dict.fromkeys((
        "id",
        "test_type",
        "table_name",
        "column_name",
        "last_auto_gen_date",
        "external_id",
        "lock_refresh",
        "match_table_name",
        "match_schema_name",
        *TestDefinitionExport.model_fields,
    ))
)


def _value_as_saved(td_import: TestDefinitionExport, target: Row | None, field: str) -> object:
    """The value ``field`` is saved with: the file's when it carries the field or the definition is new,
    otherwise the matched definition's stored value."""
    if target is None or field in td_import.model_fields_set:
        return getattr(td_import, field, None)
    return getattr(target, field, None)


def export_definitions(
    test_suite: TestSuite,
    origin: Origin,
    table_name: str | None,
    test_type: str | None,
    version_id: UUID | None = None,
) -> ExportDocument:
    session = get_current_session()
    table_group = TableGroup.get(test_suite.table_groups_id)
    version_predicate = TestDefinition.version_id == version_id if version_id else TestDefinition.version_clause()
    exported_version = version_id or session.scalar(select(SuiteVersion.resolved_for(test_suite.id)))

    # Assign external_id to manual TDs that don't have one yet (idempotent)
    if origin in (Origin.manual, Origin.both) and not SuiteVersion.is_frozen_agreement(exported_version):
        session.execute(
            update(TestDefinition)
            .where(
                TestDefinition.test_suite_id == test_suite.id,
                version_predicate,
                TestDefinition.last_auto_gen_date.is_(None),
                TestDefinition.external_id.is_(None),
            )
            .values(external_id=func.gen_random_uuid())
        )

    # Build filter clauses
    clauses = [
        TestDefinition.test_suite_id == test_suite.id,
        version_predicate,
        TestDefinition.test_type.not_in(MANAGED_TEST_TYPES),
    ]
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
    contract_version = SuiteVersion.get(exported_version) if test_suite.suite_type == SuiteType.CONTRACT else None

    return ExportDocument(
        version=EXPORT_FORMAT_VERSION,
        source=ExportSource(
            project_code=test_suite.project_code,
            test_suite=test_suite.test_suite,
            table_group=table_group.table_groups_name,
            table_group_schema=table_group.table_group_schema if _reports_schema(table_group) else None,
            exported_at=datetime.now(UTC),
            testgen_version=settings.VERSION,
            contract_version=contract_version.version if contract_version else None,
        ),
        definitions=definitions,
    )


def _reports_schema(table_group: TableGroup) -> bool:
    connection = Connection.get_by_table_group(table_group.id)
    return reports_table_group_schema(connection.sql_flavor_code if connection else None)


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
    contract_tables = writable_tables(test_suite)

    # --- Phase 1: Upfront validation ---
    if payload.version != EXPORT_FORMAT_VERSION:
        raise InvalidImportPayload(
            ImportErrorCode.unsupported_version,
            f"Unsupported export document version {payload.version}; supported version: {EXPORT_FORMAT_VERSION}",
        )
    _check_duplicate_keys(incoming, test_types)

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

        if target is not None and target.test_type in MANAGED_TEST_TYPES:
            actions.append(_PlannedAction(ImportAction.skip, ImportReason.managed_test, idx, td_import, target))
            continue

        if td_import.test_type not in test_types:
            actions.append(_PlannedAction(ImportAction.skip, ImportReason.invalid_test_type, idx, td_import, target))
            continue

        # A non-public type is a real row in ``test_types``, so it clears the check above. Only a new
        # definition is refused here: an update keeps the stored type, so a matched monitor stays importable.
        if target is None and td_import.test_type in NON_PUBLIC_TEST_TYPES:
            actions.append(
                _PlannedAction(ImportAction.skip, ImportReason.managed_test_type, idx, td_import, target)
            )
            continue

        table_name = _value_as_saved(td_import, target, "table_name")
        column_name = _value_as_saved(td_import, target, "column_name")
        if table_name is not None and table_name not in profiled_tables:
            actions.append(_PlannedAction(ImportAction.skip, ImportReason.invalid_table, idx, td_import, target))
            continue

        if (
            contract_tables is not None
            and table_name not in contract_tables
            and (target is None or table_name != target.table_name)
        ):
            actions.append(_PlannedAction(ImportAction.skip, ImportReason.undeclared_table, idx, td_import, target))
            continue

        if not _is_column_profiled(table_name, column_name, test_types[td_import.test_type], profiled_columns):
            actions.append(_PlannedAction(ImportAction.skip, ImportReason.invalid_column, idx, td_import, target))
            continue

        test_type = test_types[td_import.test_type]
        value_of = partial(_value_as_saved, td_import, target)
        missing = missing_required_fields(test_type, value_of)
        # Generators store values in a non-public type's undeclared parameters, which the full rules reject.
        errors = missing if td_import.test_type in NON_PUBLIC_TEST_TYPES else test_definition_errors(test_type, value_of)
        if errors:
            reason = ImportReason.missing_required_field if missing else ImportReason.invalid_field
            actions.append(_PlannedAction(ImportAction.skip, reason, idx, td_import, target, errors))
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
    has_writes = any(a.action != ImportAction.skip for a in actions)
    if config.mode == ImportMode.apply_strict and has_skips:
        # Built before apply, so created TDs have no target_id — correct, nothing was persisted.
        # The post-apply build below is NOT redundant: _apply_actions fills planned.target for creates.
        version = _contract_version(test_suite, preview=True) if has_writes else None
        raise ImportStrictViolation(_build_response(actions, version))

    if config.mode in (ImportMode.apply, ImportMode.apply_strict):
        _apply_actions(actions, test_suite, table_group, config)

    version = _contract_version(test_suite, preview=config.mode == ImportMode.preview) if has_writes else None
    return _build_response(actions, version)


# --- Helpers ---


@dataclass
class _PlannedAction:
    action: ImportAction
    reason: ImportReason
    idx: int | None  # None for absence deletes (target-only, not in the file)
    td_import: TestDefinitionExport | None  # None for absence deletes
    target: Any  # Row (re-pointed at the writable version), TestDefinition after create flush, or None
    errors: dict[str, str] | None = None  # Field-level reasons for a definition skipped as missing or invalid


def _test_type_name(test_types: dict[str, TestType], code: str) -> str:
    test_type = test_types.get(code)
    return (test_type.test_name_short if test_type else None) or code


def _load_test_types() -> dict[str, TestType]:
    session = get_current_session()
    return {tt.test_type: tt for tt in session.scalars(select(TestType).where(TestType.active == "Y")).all()}


def _is_column_profiled(
    table_name: str | None, column_name: str | None, test_type: TestType, profiled_columns: set[tuple[str, str]]
) -> bool:
    """Check that the column exists in profiled data. Only column-scope test types are validated:
    the other scopes can hold an expression (e.g. SUM(col)) rather than a physical column name."""
    if test_type.test_scope != TestScope.COLUMN or not table_name or not column_name:
        return True
    return (table_name, column_name) in profiled_columns


def _check_duplicate_keys(incoming: list[TestDefinitionExport], test_types: dict[str, TestType]) -> None:
    auto_keys: set[tuple[str, str | None, str | None]] = set()
    manual_keys: set[UUID] = set()

    for idx, td in enumerate(incoming):
        if td.last_auto_gen_date is not None:
            key = (td.test_type, td.table_name, td.column_name)
            if key in auto_keys:
                raise InvalidImportPayload(
                    ImportErrorCode.duplicate_natural_key,
                    f"Duplicate auto-gen key at index {idx}: "
                    f"({_test_type_name(test_types, td.test_type)}, {td.table_name}, {td.column_name})",
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
    writes = [planned for planned in actions if planned.action != ImportAction.skip]
    if not writes:
        return
    version_id, counterparts = TestDefinition.resolve_writable(
        test_suite.id, [planned.target.id for planned in writes if planned.target is not None]
    )
    for planned in writes:
        if planned.target is None:
            continue
        if planned.target.id not in counterparts:
            raise ImportTargetMissing(planned.target.id)
        if counterparts[planned.target.id] != planned.target.id:
            planned.target = SimpleNamespace(**{**planned.target._asdict(), "id": counterparts[planned.target.id]})

    session = get_current_session()
    now = datetime.now(UTC)
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
        if field_name in _PROVENANCE_FIELDS:
            continue
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
        update(TestDefinition)
        .where(TestDefinition.id == target.id, TestDefinition.version_clause())
        .values(**values)
    )


def _contract_version(test_suite: TestSuite, *, preview: bool) -> ContractVersion | None:
    if test_suite.suite_type != SuiteType.CONTRACT:
        return None
    number, state = contract_service.import_destination(test_suite, preview=preview)
    return ContractVersion(number=number, state=state)


def _build_response(actions: list[_PlannedAction], version: ContractVersion | None) -> ImportResponse:
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
            errors=planned.errors,
        )
        items_by_key.setdefault(key, []).append(td_entry)

    items = [
        ImportItem(action=action, reason=reason, tds=tds)
        for (action, reason), tds in items_by_key.items()
    ]

    return ImportResponse(summary=summary, items=items, version=version)
