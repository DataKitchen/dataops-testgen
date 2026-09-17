"""Contract lifecycle: resolving where a write lands, freezing a version, discarding a draft.

Every mutation of a contract's content routes through here so that the version it lands in is
decided in one place. Functions raise stdlib exceptions; the calling surface translates them
into its own user-facing errors.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import asc, delete, func, select
from sqlalchemy.orm.attributes import flag_modified

from testgen.commands.test_generation import run_test_generation
from testgen.common.enums import SuiteType
from testgen.common.generation_set_service import CONTRACT_GENERATION_SET
from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.data_column import DataColumnChars
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_suite import TestSuite
from testgen.common.odcs_server import build_server_block


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


def freeze_version(suite: TestSuite, *, label: str | None = None) -> SuiteVersion:
    """Freeze the suite's draft, making it the agreement in force."""
    draft = SuiteVersion.draft_for(suite.id)
    if draft is None:
        raise ValueError("This contract has no draft to freeze.")

    draft.frozen_at = datetime.now(UTC)
    if label is not None:
        draft.label = label
    get_current_session().flush()
    return draft


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

    session = get_current_session()
    term_count = session.scalar(
        select(func.count()).select_from(TestDefinition).where(TestDefinition.version_id == draft.id)
    ) or 0
    session.delete(draft)
    session.flush()
    return term_count


def save_metadata_document(suite: TestSuite, document: dict) -> UUID:
    """Write the document to the suite's draft, creating the draft when there is none."""
    version_id, _ = resolve_write_target(suite)
    version = SuiteVersion.get(version_id)
    version.metadata_document = document
    get_current_session().flush()
    return version_id


def _active_version(suite: TestSuite) -> SuiteVersion | None:
    return SuiteVersion.in_force_for(suite.id)


def initialize_contract(
    suite: TestSuite, table_group: TableGroup, connection: Connection, username: str | None = None
) -> SuiteVersion:
    """Give a newly created contract its first draft, generation set and prefilled document."""
    session = get_current_session()
    draft = SuiteVersion(
        id=uuid4(),
        test_suite_id=suite.id,
        version=SuiteVersion.next_version_for(suite.id),
        metadata_document={
            "name": suite.test_suite,
            "servers": [build_server_block(connection, table_group)],
            "schema": [],
        },
        created_by=username,
    )
    session.add(draft)
    suite.generation_sets = [CONTRACT_GENERATION_SET]
    session.flush()
    return draft


# ODCS SchemaBaseProperty.logicalType is one of: string, date, number, integer, object,
# array, boolean. Only these four profiled general_type codes have a faithful match -- a
# "Time" or "Other" column carries no logicalType at all rather than a guessed one.
_LOGICAL_TYPE_FROM_GENERAL_TYPE: dict[str, str] = {
    "A": "string",
    "N": "number",
    "D": "date",
    "B": "boolean",
}


def declared_tables(document: dict | None) -> list[str]:
    """The table names a metadata document's schema section declares, in document order."""
    if not document:
        return []
    return [table["name"] for table in document.get("schema", [])]


def _column_descriptor(column: DataColumnChars) -> dict:
    """A profiled column's ODCS ``SchemaProperty`` descriptor, built from scratch.

    Carries only fields the ODCS schema defines: ``name`` (required), ``physicalType``
    when profiling captured one, ``logicalType`` when the profiled general type maps to
    one of the ODCS logical types with confidence, and the profiled functional type as a
    ``customProperties`` entry (ODCS has no dedicated field for it).
    """
    descriptor: dict = {"name": column.column_name}
    if column.column_type:
        descriptor["physicalType"] = column.column_type
    if logical_type := _LOGICAL_TYPE_FROM_GENERAL_TYPE.get(column.general_type):
        descriptor["logicalType"] = logical_type
    if column.functional_data_type:
        descriptor["customProperties"] = [{"property": "functionalDataType", "value": column.functional_data_type}]
    return descriptor


def _merge_functional_data_type(custom_properties: list[dict], functional_data_type: str) -> list[dict]:
    """``customProperties`` with the ``functionalDataType`` entry set, every other entry untouched."""
    merged = [dict(entry) for entry in custom_properties]
    for entry in merged:
        if entry.get("property") == "functionalDataType":
            entry["value"] = functional_data_type
            return merged
    merged.append({"property": "functionalDataType", "value": functional_data_type})
    return merged


def _merge_column_descriptor(existing: dict, column: DataColumnChars) -> dict:
    """An already-declared column's descriptor, refreshed with what profiling has to offer.

    Keeps every field ``existing`` carries. Overwrites ``physicalType`` and ``logicalType``
    only when profiling has a value for them, and updates or adds the ``functionalDataType``
    custom property only when profiling has one -- a field profiling has nothing to say
    about this time is left exactly as it was, not cleared.
    """
    merged = dict(existing)
    if column.column_type:
        merged["physicalType"] = column.column_type
    if logical_type := _LOGICAL_TYPE_FROM_GENERAL_TYPE.get(column.general_type):
        merged["logicalType"] = logical_type
    if column.functional_data_type:
        merged["customProperties"] = _merge_functional_data_type(
            merged.get("customProperties", []), column.functional_data_type
        )
    return merged


def _merge_properties(existing_properties: list[dict], columns: list[DataColumnChars]) -> list[dict]:
    """A table's column descriptors, refreshed from profiling without losing declared columns.

    A column already declared keeps every field it carries, refreshed by
    ``_merge_column_descriptor`` when profiling still sees it, and left untouched when
    profiling no longer does -- a hand-authored column profiling cannot see is exactly as
    legal as one it can. A profiled column not yet declared is added.
    """
    by_name = {column.column_name: column for column in columns}
    seen: set[str] = set()
    merged = []
    for prop in existing_properties:
        name = prop.get("name")
        seen.add(name)
        column = by_name.get(name)
        merged.append(_merge_column_descriptor(prop, column) if column else prop)
    for column in columns:
        if column.column_name not in seen:
            merged.append(_column_descriptor(column))
    return merged


def add_table(suite: TestSuite, table_name: str) -> dict:
    """Declare a table on the contract's draft, merging into any earlier descriptor for it.

    Keeps every field an existing descriptor for the table carries, refreshing only its
    ``properties`` from current profiling, and generates terms for the table. Returns a
    report with the declared table name in a list, and ``unverifiable: True`` when the
    table group holds no profiling for it.
    """
    version_id, _ = resolve_write_target(suite)
    draft = SuiteVersion.get(version_id)
    columns = _profiled_columns(suite, table_name)

    document = draft.metadata_document if draft.metadata_document is not None else {}
    schema = document.get("schema", [])
    existing = next((entry for entry in schema if entry["name"] == table_name), None)
    descriptor = dict(existing) if existing else {"name": table_name}
    descriptor["properties"] = _merge_properties(existing.get("properties", []) if existing else [], columns)

    if existing is None:
        schema = [*schema, descriptor]
    else:
        schema = [descriptor if entry["name"] == table_name else entry for entry in schema]
    document["schema"] = schema
    draft.metadata_document = document
    flag_modified(draft, "metadata_document")
    get_current_session().flush()

    _generate_for_tables(suite, [table_name])

    report: dict = {"declared": [table_name]}
    if not columns:
        report["unverifiable"] = True
    return report


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
    result = session.execute(
        delete(TestDefinition).where(
            TestDefinition.version_id == version_id,
            TestDefinition.table_name == table_name,
        )
    )
    session.flush()
    return {"terms_removed": result.rowcount}


def generate_terms(suite: TestSuite) -> dict:
    """Generate terms for every table the contract's draft currently declares."""
    version_id, _ = resolve_write_target(suite)
    draft = SuiteVersion.get(version_id)
    table_names = declared_tables(draft.metadata_document)
    _generate_for_tables(suite, table_names)
    return {"declared": table_names}


def _profiled_columns(suite: TestSuite, table_name: str) -> list[DataColumnChars]:
    """Profiled columns for a table in the suite's table group, ordered by ordinal position."""
    session = get_current_session()
    return session.scalars(
        select(DataColumnChars)
        .where(
            DataColumnChars.table_groups_id == suite.table_groups_id,
            DataColumnChars.table_name == table_name,
            DataColumnChars.drop_date.is_(None),
        )
        .order_by(asc(DataColumnChars.ordinal_position))
    ).all()


def _generate_for_tables(suite: TestSuite, table_names: list[str]) -> None:
    """Run test generation for a contract, filtered to the given declared tables."""
    run_test_generation(suite.id, table_names=table_names)
