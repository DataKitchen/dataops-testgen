"""
Data Contract — in-memory YAML mutation helpers and pending-edit state utilities.

All functions here are pure (no Streamlit, no DB).  They operate on parsed YAML
dicts or on the pending-edit dict stored in session state.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# YAML patch helpers
# ---------------------------------------------------------------------------

def _delete_term_yaml_patch(
    term_name: str,
    source: str,
    table_name: str,
    col_name: str,
    term_value: str,  # noqa: ARG001  kept for call-site symmetry
    doc: dict,
) -> tuple[bool, str]:
    """Remove a term from the in-memory contract YAML doc.

    Returns (patched: bool, error_msg: str).
    """
    col_key = f"{table_name}.{col_name}"

    # Foreign key lives in the top-level references list, not in schema properties.
    if source == "ddl" and term_name == "Foreign Key":
        refs = doc.get("references") or []
        before = len(refs)

        def _ref_matches(r: dict) -> bool:
            from_val = r.get("from")
            if isinstance(from_val, list):
                return col_key in from_val or col_name in from_val
            return from_val in (col_key, col_name)

        doc["references"] = [r for r in refs if not _ref_matches(r)]
        return len(doc["references"]) < before, "Foreign key reference not found."

    for tbl in (doc.get("schema") or []):
        if tbl.get("name") != table_name:
            continue
        for prop in (tbl.get("properties") or []):
            if prop.get("name") != col_name:
                continue

            def _pop_custom(cp_key: str) -> None:
                """Remove a testgen.* entry from customProperties; drop the list if empty."""
                existing = prop.get("customProperties") or []
                updated = [cp for cp in existing if cp.get("property") != cp_key]
                if updated:
                    prop["customProperties"] = updated
                else:
                    prop.pop("customProperties", None)

            if source == "governance":
                if term_name in ("Classification", "PII"):
                    prop.pop("classification", None)
                    _pop_custom("testgen.pii_flag")
                elif term_name in ("CDE", "Critical Data Element"):
                    prop.pop("criticalDataElement", None)
                elif term_name == "Description":
                    prop.pop("description", None)

            elif source == "profiling":
                if term_name == "Min Value":
                    _pop_custom("testgen.minimum")
                elif term_name == "Max Value":
                    _pop_custom("testgen.maximum")
                elif term_name == "Min Length":
                    _pop_custom("testgen.minLength")
                elif term_name == "Max Length":
                    _pop_custom("testgen.maxLength")
                elif term_name == "Format":
                    _pop_custom("testgen.format")
                elif term_name == "Logical Type":
                    prop.pop("logicalType", None)

            elif source == "ddl":
                if term_name == "Data Type":
                    prop.pop("physicalType", None)
                elif term_name == "Not Null":
                    prop.pop("required", None)
                    prop.pop("nullable", None)
                elif term_name == "Primary Key":
                    _pop_custom("testgen.primaryKey")

            return True, ""

    return False, f"Could not locate `{table_name}.{col_name}` in the contract."


def _patch_yaml_governance(doc: dict, table_name: str, col_name: str, field: str, value: object) -> bool:
    """Patch a governance field in-place on the parsed YAML doc. Returns True if patched."""
    field_map = {"Classification": "classification", "Description": "description", "CDE": "criticalDataElement"}
    yaml_field = field_map.get(field, field)
    for tbl in (doc.get("schema") or []):
        if tbl.get("name") == table_name:
            for prop in (tbl.get("properties") or []):
                if prop.get("name") == col_name:
                    if value is None or value == "" or value is False:
                        prop.pop(yaml_field, None)
                    else:
                        prop[yaml_field] = value
                    return True
    return False


# ---------------------------------------------------------------------------
# Pending-edit state helpers (pure, no Streamlit)
# ---------------------------------------------------------------------------

def _apply_pending_governance_edit(
    pending: dict,
    table_name: str,
    col_name: str,
    field: str,
    value: object,
    snapshot: dict | None = None,
) -> dict:
    """Add or replace a governance edit in the pending dict. Returns updated pending.

    snapshot — optional term display data for pending-deletion chips:
        {"name": str, "source": str, "verif": str}
    """
    gov = [
        e for e in pending.get("governance", [])
        if not (e["table"] == table_name and e["col"] == col_name and e["field"] == field)
    ]
    entry: dict = {"table": table_name, "col": col_name, "field": field, "value": value}
    if snapshot is not None:
        entry["snapshot"] = snapshot
    gov.append(entry)
    return {**pending, "governance": gov}


def _apply_pending_test_edit(
    pending: dict,
    rule_id: str,
    updates: dict,
) -> dict:
    """Add or replace a test edit in the pending dict. Returns updated pending."""
    tests = [e for e in pending.get("tests", []) if e.get("rule_id") != rule_id]
    tests.append({"rule_id": rule_id, **updates})
    return {**pending, "tests": tests}


def _pending_edit_count(pending: dict) -> int:
    """Total number of pending edits across all categories."""
    return len(pending.get("governance", [])) + len(pending.get("tests", []))


# ---------------------------------------------------------------------------
# Governance field helpers (pure, no Streamlit, no DB)
# ---------------------------------------------------------------------------

def _gov_field_to_db_col(field: str) -> tuple[str, object] | None:
    """Map a governance display field name to (db_column, None) or None if unknown.

    Returns None for unrecognized field names.
    Value normalization is the caller's responsibility — this just returns the column name.
    """
    _map: dict[str, str] = {
        "Classification":       "pii_flag",
        "Description":          "description",
        "CDE":                  "critical_data_element",
        "Critical Data Element": "critical_data_element",
        "Excluded Data Element": "excluded_data_element",
        "PII":                  "pii_flag",
        "Data Source":          "data_source",
        "Source System":        "source_system",
        "Source Process":       "source_process",
        "Business Domain":      "business_domain",
        "Stakeholder Group":    "stakeholder_group",
        "Transform Level":      "transform_level",
        "Aggregation Level":    "aggregation_level",
        "Data Product":         "data_product",
    }
    col = _map.get(field)
    return (col, None) if col else None


def _build_pending_governance_edit(
    table_name: str,
    col_name: str,
    field: str,
    value: object,
) -> dict | None:
    """Build a validated pending-edit dict entry for a governance field.

    Returns None if field is unrecognized (caller should ignore/warn).
    """
    result = _gov_field_to_db_col(field)
    if result is None:
        return None
    return {"table": table_name, "col": col_name, "field": field, "value": value}
