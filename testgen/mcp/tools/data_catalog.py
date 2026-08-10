from collections.abc import Mapping
from typing import Annotated

from pydantic import Field

from testgen.common.data_catalog_service import (
    TAG_FIELDS,
    apply_column_metadata,
    apply_table_metadata,
    disable_autoflags,
    validate_metadata_fields,
)
from testgen.common.models import with_database_session
from testgen.common.models.data_column import DataColumnChars
from testgen.common.models.data_table import DataTable
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.permissions import get_project_permissions, mcp_permission
from testgen.mcp.tools.common import DocGroup, resolve_table_group
from testgen.mcp.tools.markdown import MdDoc

_DOC_GROUP = DocGroup.MANAGE

_BOOLEAN_ARGS = ("cde", "xde", "pii")

# MCP argument name -> data_*_chars column name.
_ARG_TO_COLUMN = {"cde": "critical_data_element", "xde": "excluded_data_element", "pii": "pii_flag"}
_COLUMN_TO_ARG = {v: k for k, v in _ARG_TO_COLUMN.items()}


@with_database_session
@mcp_permission("disposition")
def update_catalog_metadata(
    updates: Annotated[
        list[dict],
        Field(
            description="List of per-row update specs. Each requires `table_group_id` (UUID of the table group, "
            "e.g. from `get_data_inventory`) and `table_name`. Add `column_name` to target one column; omit it "
            "for a table-level update. Fields it can set: `description` — free text, max 1000 characters. "
            "`cde` — critical data element (true/false); set at table level to apply to every column unless a "
            "column overrides it. `xde` — exclude the column from future profiling and test generation "
            "(true/false). `pii` — column contains personally identifiable information (true/false); requires "
            "permission to view PII on the row's project. `data_source`, `source_system`, `source_process`, "
            "`business_domain`, `stakeholder_group`, `transform_level`, `aggregation_level`, `data_product`, "
            "`data_classification` — catalog tags, max 40 characters each. `xde` and `pii` apply to columns "
            "only: a table-level row carrying either one fails.",
        ),
    ],
) -> str:
    """Apply metadata updates to tables and columns within table groups.

    Each update targets one table, or one column within a table, and sets one or
    more metadata fields. Rows are processed independently: a failure on one row
    does not stop the others, and the response reports the outcome of every row.

    Omit a field to leave it unchanged, pass null to clear it, or pass a value to set it.
    """
    if not updates:
        raise MCPUserError("Provide at least one update.")

    perms = get_project_permissions()
    tg_cache: dict[str, object] = {}
    flag_writes: dict = {}  # tg.id -> {"tg": tg, "cde": bool, "pii": bool}
    inheritance_notices: list[str] = []
    exclusion_notices: list[str] = []
    rows: list[tuple[str, str, str]] = []

    for spec in updates:
        target = _target_label(spec)
        try:
            outcome, detail = _apply_update(spec, perms, tg_cache, flag_writes, inheritance_notices, exclusion_notices)
            rows.append((target, outcome, detail))
        except MCPUserError as err:
            rows.append((target, "Failed", str(err)))

    autoflag_notices: list[str] = []
    for entry in flag_writes.values():
        disabled = disable_autoflags(entry["tg"], wrote_cde=entry["cde"], wrote_pii=entry["pii"])
        for flag in disabled:
            autoflag_notices.append(
                f"Auto-disabled {flag} on table group `{entry['tg'].table_groups_name}` to preserve manual marks."
            )

    return _render(rows, autoflag_notices + inheritance_notices + exclusion_notices)


def _target_label(spec: Mapping) -> str:
    table = spec.get("table_name") or "?"
    column = spec.get("column_name")
    return f"{table}.{column}" if column else table


def _apply_update(spec, perms, tg_cache, flag_writes, inheritance_notices, exclusion_notices) -> tuple[str, str]:
    if not isinstance(spec, Mapping):
        raise MCPUserError("Each update must be an object.")

    table_group_id = spec.get("table_group_id")
    table_name = spec.get("table_name")
    if not table_group_id:
        raise MCPUserError("table_group_id is required.")
    if not table_name:
        raise MCPUserError("table_name is required.")
    column_name = spec.get("column_name")
    is_column = column_name is not None

    for arg in _BOOLEAN_ARGS:
        if arg in spec and spec[arg] is not None and not isinstance(spec[arg], bool):
            raise MCPUserError(f"{arg} must be true or false.")

    if not is_column:
        if "xde" in spec:
            raise MCPUserError("xde applies to columns only; omit it for table-level updates.")
        if "pii" in spec:
            raise MCPUserError("pii applies to columns only; omit it for table-level updates.")

    tg = tg_cache.get(table_group_id)
    if tg is None:
        tg = resolve_table_group(table_group_id)
        tg_cache[table_group_id] = tg

    if "pii" in spec and not perms.has_permission("view_pii", tg.project_code):
        raise MCPUserError(f"Setting pii requires permission to view PII on project `{tg.project_code}`.")

    fields = _build_fields(spec)
    errors = validate_metadata_fields(fields)
    if errors:
        raise MCPUserError("; ".join(errors))

    if not fields:
        return "Skipped", "no metadata fields provided"

    if is_column:
        target = _resolve_column(tg.id, table_name, column_name)
        if target is None:
            raise MCPUserError(f"Column `{column_name}` not found in table `{table_name}`.")
    else:
        target = _resolve_table(tg.id, table_name)
        if target is None:
            raise MCPUserError(f"Table `{table_name}` not found in this table group.")

    # Disable a table group's auto-detect flag only on a real change, matching the UI's confirm-to-disable
    # behavior. A no-op write (e.g. cde: false on an already-false column) must not silently turn it off.
    cde_changed = "cde" in spec and target.critical_data_element != spec["cde"]
    pii_changed = "pii" in spec and target.pii_flag != ("MANUAL" if spec["pii"] else None)

    if is_column:
        apply_column_metadata(target, fields)
    else:
        apply_table_metadata(target, fields)

    entry = flag_writes.setdefault(tg.id, {"tg": tg, "cde": False, "pii": False})
    if cde_changed:
        entry["cde"] = True
    if pii_changed:
        entry["pii"] = True

    if not is_column and spec.get("cde") is True:
        inheritance_notices.append(
            f"Table-level CDE set; affects all columns of `{table_name}` unless explicitly overridden."
        )
    if is_column and spec.get("xde") is True:
        exclusion_notices.append(
            f"Column `{table_name}.{column_name}` excluded; next profiling run and test generation will skip it."
        )

    return "Updated", _change_summary(fields)


def _build_fields(spec: Mapping) -> dict:
    """Translate a spec into a {data_*_chars column: value} dict (pii bool -> MANUAL/None)."""
    fields: dict = {}
    if "description" in spec:
        fields["description"] = spec["description"]
    for tag in TAG_FIELDS:
        if tag in spec:
            fields[tag] = spec[tag]
    if "cde" in spec:
        fields["critical_data_element"] = spec["cde"]
    if "xde" in spec:
        fields["excluded_data_element"] = spec["xde"]
    if "pii" in spec:
        fields["pii_flag"] = "MANUAL" if spec["pii"] else None
    return fields


def _resolve_table(table_groups_id, table_name: str):
    matches = list(DataTable.select_where(
        DataTable.table_groups_id == table_groups_id,
        DataTable.table_name == table_name,
    ))
    return matches[0] if matches else None


def _resolve_column(table_groups_id, table_name: str, column_name: str):
    matches = list(DataColumnChars.select_where(
        DataColumnChars.table_groups_id == table_groups_id,
        DataColumnChars.table_name == table_name,
        DataColumnChars.column_name == column_name,
    ))
    return matches[0] if matches else None


def _change_summary(fields: dict) -> str:
    parts = []
    for column, value in fields.items():
        label = _COLUMN_TO_ARG.get(column, column)
        parts.append(f"{label} cleared" if value is None else f"{label} set")
    return ", ".join(parts)


def _render(rows: list[tuple[str, str, str]], notices: list[str]) -> str:
    succeeded = sum(1 for _, outcome, _ in rows if outcome == "Updated")
    skipped = sum(1 for _, outcome, _ in rows if outcome == "Skipped")
    failed = sum(1 for _, outcome, _ in rows if outcome == "Failed")

    doc = MdDoc()
    doc.heading(1, "Catalog metadata update")
    doc.field("Rows attempted", len(rows))
    doc.field("Updated", succeeded)
    doc.field("Skipped", skipped)
    doc.field("Failed", failed)
    doc.table(["Target", "Outcome", "Details"], [list(row) for row in rows], code=[0])
    for notice in notices:
        doc.text(notice)
    return doc.render()
