"""Validate and apply an admin-uploaded test type YAML.

Validation is not stricter than the packaged YAML files themselves uphold:
those files are the reality baseline against which a file must be acceptable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from re import fullmatch
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError
from yaml import YAMLError, safe_load

from testgen import settings
from testgen.common.enums import HealthDimension, ImpactDimension, QualityDimension
from testgen.common.flavors import FLAVOR_FAMILIES
from testgen.common.models import database_session
from testgen.common.models.test_definition import (
    Severity,
    StatisticalTechnique,
    TestAlgorithm,
    TestRunType,
    TestScope,
)

LOG = logging.getLogger("testgen")


# Hardcoded rather than introspected from the ORM: several ``test_types`` columns
# are intentionally unmapped in ``TestType`` but the packaged YAMLs still use them,
# so the source of truth is the schema file (030_initialize_new_schema_structure.sql).

_PARENT_TABLE = "test_types"
_PARENT_KEY = "test_type"

_PARENT_FIELDS: frozenset[str] = frozenset({
    "id", "test_type", "test_name_short", "test_name_long", "test_description",
    "except_message", "measure_uom", "measure_uom_description", "selection_criteria",
    "generation_template", "dq_score_prevalence_formula", "dq_score_risk_factor",
    "column_name_prompt", "column_name_help",
    "default_parm_columns", "default_parm_values", "default_parm_prompts",
    "default_parm_help", "default_parm_required",
    "default_severity", "run_type", "test_scope", "dq_dimension", "impact_dimension",
    "health_dimension", "algorithm", "statistical_technique",
    "threshold_description", "result_visualization", "result_visualization_params",
    "usage_notes", "active", "overrides",
})

# ``uploaded_version`` is system-managed; the file must not set it.
_RESERVED_PARENT_FIELDS: frozenset[str] = frozenset({"uploaded_version"})

_REQUIRED_PARENT_FIELDS: tuple[str, ...] = (
    "id", "test_type", "test_name_short", "test_name_long", "test_description",
    "run_type", "test_scope", "dq_dimension", "default_severity", "algorithm", "active",
)

_CHILD_FIELDS: dict[str, frozenset[str]] = {
    "cat_test_conditions": frozenset({
        "id", "test_type", "sql_flavor", "measure", "test_operator", "test_condition",
    }),
    "target_data_lookups": frozenset({
        "id", "test_id", "test_type", "sql_flavor", "lookup_type", "lookup_query",
        "lookup_redactable_columns", "error_type",
    }),
    "test_templates": frozenset({
        "id", "test_type", "sql_flavor", "template",
    }),
}

_CHILD_LEADERS: dict[str, str] = {
    "cat_test_conditions": "Test condition",
    "target_data_lookups": "Target data lookup",
    "test_templates": "Test template",
}


_PARENT_ENUM_FIELDS: dict[str, type[StrEnum]] = {
    "run_type": TestRunType,
    "test_scope": TestScope,
    "dq_dimension": QualityDimension,
    "impact_dimension": ImpactDimension,
    "health_dimension": HealthDimension,
    "algorithm": TestAlgorithm,
    "statistical_technique": StatisticalTechnique,
}

# ``default_severity`` on ``test_types`` has a broader value space than the
# ``Severity`` enum, which is scoped to the values a user override may set.
# Packaged YAMLs also allow the passive "Log" default, so accept it here.
_DEFAULT_SEVERITY_VALUES: frozenset[str] = frozenset(
    {member.value for member in Severity} | {"Log"}
)

# VARCHAR(n) limits, kept in sync with 030_initialize_new_schema_structure.sql.
_PARENT_MAX_LENGTHS: dict[str, int] = {
    "test_type": 200,
    "test_name_short": 30,
    "test_name_long": 100,
    "test_description": 1000,
    "except_message": 1000,
    "measure_uom": 100,
    "measure_uom_description": 200,
    "generation_template": 100,
    "default_severity": 10,
    "run_type": 10,
    "dq_dimension": 50,
    "impact_dimension": 20,
    "health_dimension": 50,
    "algorithm": 64,
    "statistical_technique": 64,
    "threshold_description": 200,
    "result_visualization": 50,
}

_CHILD_MAX_LENGTHS: dict[str, dict[str, int]] = {
    "test_templates": {"sql_flavor": 20},
    "cat_test_conditions": {
        "sql_flavor": 20,
        "measure": 2000,
        "test_operator": 20,
        "test_condition": 2000,
    },
    "target_data_lookups": {
        "sql_flavor": 20,
        "lookup_type": 10,
        "lookup_redactable_columns": 100,
        "error_type": 30,
    },
}


@dataclass
class ParsedTestType:
    parent: dict[str, Any]
    cat_test_conditions: list[dict[str, Any]]
    target_data_lookups: list[dict[str, Any]]
    test_templates: list[dict[str, Any]]
    generation_sets: list[str]

    @property
    def test_type(self) -> str:
        return self.parent["test_type"]


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    parsed: ParsedTestType | None = None


def validate_test_type_yaml(content: str | bytes) -> ValidationResult:
    """Parse and statically validate. Pair with ``apply_test_type_upload(..., dry_run=True)``
    to also catch apply-time issues (length, type coercion, constraint) that static checks miss.
    """
    try:
        data = safe_load(content)
    except YAMLError:
        return ValidationResult(ok=False, errors=["This file is not valid YAML."])

    errors: list[str] = []

    if not isinstance(data, dict) or list(data.keys()) != [_PARENT_TABLE]:
        return ValidationResult(ok=False, errors=["This file is not a test type definition."])

    parent = data[_PARENT_TABLE]
    if not isinstance(parent, dict):
        return ValidationResult(ok=False, errors=["This file is not a test type definition."])

    _check_reserved_parent_fields(parent, errors)
    _check_parent_field_names(parent, errors)
    _check_required_parent_fields(parent, errors)
    _check_parent_enum_values(parent, errors)
    _check_parent_specials(parent, errors)
    _check_parent_lengths(parent, errors)

    generation_sets, gen_set_errors = _check_generation_sets(parent.get("generation_sets"))
    errors.extend(gen_set_errors)

    child_payloads: dict[str, list[dict[str, Any]]] = {}
    for child in ("cat_test_conditions", "target_data_lookups", "test_templates"):
        records, child_errors = _check_child_section(parent, child)
        child_payloads[child] = records
        errors.extend(child_errors)

    _check_run_type_child_pairing(parent, child_payloads, errors)

    if errors:
        return ValidationResult(ok=False, errors=errors)

    return ValidationResult(
        ok=True,
        parsed=ParsedTestType(
            parent=_strip_container_keys(parent),
            cat_test_conditions=child_payloads["cat_test_conditions"],
            target_data_lookups=child_payloads["target_data_lookups"],
            test_templates=child_payloads["test_templates"],
            generation_sets=generation_sets,
        ),
    )


def _check_reserved_parent_fields(parent: dict[str, Any], errors: list[str]) -> None:
    for field_name in parent:
        if field_name in _RESERVED_PARENT_FIELDS:
            errors.append(f"'{field_name}' is not a recognized field.")


def _check_parent_field_names(parent: dict[str, Any], errors: list[str]) -> None:
    known = _PARENT_FIELDS | frozenset(_CHILD_FIELDS) | frozenset({"generation_sets"})
    for field_name in parent:
        if field_name in _RESERVED_PARENT_FIELDS:
            continue  # already reported by the reserved-fields check
        if field_name not in known:
            errors.append(f"'{field_name}' is not a recognized field.")


def _check_required_parent_fields(parent: dict[str, Any], errors: list[str]) -> None:
    # Presence check on the key, not truthiness: packaged YAMLs occasionally use
    # ``dq_dimension: null`` (Schema_Drift). "Not stricter than reality" — accept
    # the same shape from uploads.
    for field_name in _REQUIRED_PARENT_FIELDS:
        if field_name not in parent:
            errors.append(f"{field_name} is required.")
            continue
        value = parent[field_name]
        if isinstance(value, str) and not value.strip():
            errors.append(f"{field_name} is required.")


def _check_parent_enum_values(parent: dict[str, Any], errors: list[str]) -> None:
    for field_name, enum_cls in _PARENT_ENUM_FIELDS.items():
        value = parent.get(field_name)
        if value is None or value == "":
            continue
        allowed = {member.value for member in enum_cls}
        if value not in allowed:
            errors.append(f"{field_name}: '{value}' is not a valid value.")

    severity = parent.get("default_severity")
    if severity is not None and severity != "" and severity not in _DEFAULT_SEVERITY_VALUES:
        errors.append(f"default_severity: '{severity}' is not a valid value.")


def _check_parent_specials(parent: dict[str, Any], errors: list[str]) -> None:
    test_type = parent.get("test_type")
    if test_type is not None and not isinstance(test_type, str):
        errors.append(f"test_type: '{test_type}' must be a quoted string.")
    elif isinstance(test_type, str) and test_type.strip() and not fullmatch(r"[A-Za-z0-9_]+", test_type):
        errors.append(
            f"test_type: '{test_type}' must contain only letters, numbers, and underscores."
        )

    # ``id`` is the row key for ``target_data_lookups.test_id`` and the store column is
    # ``VARCHAR``. YAML parses unquoted numbers as ``int``, which would send an int to
    # a text column at query time and raise a driver error; require a quoted string.
    id_value = parent.get("id")
    if id_value is not None:
        if not isinstance(id_value, str) or not id_value.strip():
            errors.append(f"id: '{id_value}' must be a quoted non-empty string.")

    # Reject anything that is not exactly ``Y`` or ``N``: consumers read the column
    # case-sensitively (``WHERE active = 'Y'`` in generation and picker SQL), so any
    # normalization we do here would still leave a mismatch at read time.
    active = parent.get("active")
    if active is not None and active not in {"Y", "N"}:
        errors.append(f"active: '{active}' is not a valid value. Expected Y or N.")

    algorithm = parent.get("algorithm")
    technique = parent.get("statistical_technique")
    if algorithm == TestAlgorithm.STATISTICAL_DRIFT.value and (technique is None or technique == ""):
        errors.append("statistical_technique is required for the 'Statistical drift' algorithm.")

    parm_required = parent.get("default_parm_required")
    if isinstance(parm_required, str) and parm_required != "":
        for token in parm_required.split(","):
            normalized = token.strip().upper()
            if normalized not in {"Y", "N", ""}:
                errors.append(
                    f"default_parm_required: '{parm_required}' is not a valid value. "
                    f"Expected a comma-separated list of Y or N."
                )
                break


def _check_parent_lengths(parent: dict[str, Any], errors: list[str]) -> None:
    for field_name, limit in _PARENT_MAX_LENGTHS.items():
        value = parent.get(field_name)
        if isinstance(value, str) and len(value) > limit:
            errors.append(f"{field_name}: value exceeds the {limit} character limit.")


def _check_run_type_child_pairing(
    parent: dict[str, Any],
    child_payloads: dict[str, list[dict[str, Any]]],
    errors: list[str],
) -> None:
    """CAT test types are executed via ``cat_test_conditions``; QUERY / METADATA
    types via ``test_templates``. The packaged files uphold this split — every
    CAT has cat_test_conditions and no test_templates, every QUERY/METADATA has
    the inverse. Enforcing it rejects uploads that would generate but never fire.
    """
    run_type = parent.get("run_type")
    if run_type == TestRunType.CAT.value and not child_payloads.get("cat_test_conditions"):
        errors.append("run_type CAT requires at least one cat_test_conditions entry.")
    if run_type in (TestRunType.QUERY.value, TestRunType.METADATA.value) and not child_payloads.get("test_templates"):
        errors.append(f"run_type {run_type} requires at least one test_templates entry.")


def _check_generation_sets(value: Any) -> tuple[list[str], list[str]]:
    if value is None:
        return [], []
    if not isinstance(value, list):
        return [], ["generation_sets: must be a list of set names."]
    errors: list[str] = []
    result: list[str] = []
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            errors.append("generation_sets: entries must be non-empty strings.")
            continue
        result.append(entry)
    return result, errors


def _check_child_section(
    parent: dict[str, Any], table: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    raw = parent.get(table)
    if raw is None:
        return [], []
    if not isinstance(raw, list):
        return [], [f"{_CHILD_LEADERS[table]}: must be a list."]

    allowed_fields = _CHILD_FIELDS[table]
    errors: list[str] = []
    records: list[dict[str, Any]] = []

    for index, entry in enumerate(raw, start=1):
        leader = f"{_CHILD_LEADERS[table]} {index}"
        if not isinstance(entry, dict):
            errors.append(f"{leader}: must be a mapping.")
            continue

        record: dict[str, Any] = {}
        for field_name, field_value in entry.items():
            if field_name not in allowed_fields:
                errors.append(f"{leader}: '{field_name}' is not a recognized field.")
                continue
            record[field_name] = field_value

        if "sql_flavor" not in record or (
            isinstance(record["sql_flavor"], str) and not record["sql_flavor"].strip()
        ):
            errors.append(f"{leader}: sql_flavor is required.")
        elif record["sql_flavor"] not in FLAVOR_FAMILIES:
            errors.append(f"{leader}: sql_flavor '{record['sql_flavor']}' is not a valid value.")

        if table == "target_data_lookups":
            if not record.get("error_type"):
                errors.append(f"{leader}: error_type is required.")

        for field_name, limit in _CHILD_MAX_LENGTHS.get(table, {}).items():
            value = record.get(field_name)
            if isinstance(value, str) and len(value) > limit:
                errors.append(f"{leader}: {field_name} value exceeds the {limit} character limit.")

        records.append(record)

    return records, errors


def _strip_container_keys(parent: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``parent`` with the child-section and generation_sets keys removed."""
    excluded = frozenset({"generation_sets"}) | frozenset(_CHILD_FIELDS)
    return {k: v for k, v in parent.items() if k not in excluded}


# -- Apply --------------------------------------------------------------------


def apply_test_type_upload(
    parsed: ParsedTestType,
    *,
    current_version: str | None = None,
    dry_run: bool = False,
) -> None:
    """Persist the parsed upload, or roll back if ``dry_run=True``.

    A wider prior definition (e.g. a customer's previous file that covered
    flavors this one omits) must not leak across the replacement, so child rows
    and generation-set memberships are cleared before the new rows insert.
    ``IntegrityError`` / ``DataError`` surface to callers already rolled back.

    Runs inside a savepoint (``session.begin_nested``) so ``dry_run=True`` rolls
    back even when the caller already owns a session — the outer commit only
    persists a real (non dry-run) apply.
    """
    if current_version is None:
        current_version = settings.VERSION or "unset"

    test_type = parsed.test_type

    try:
        with database_session() as session, session.begin_nested() as savepoint:
            _emit_apply_statements(session, parsed, current_version)
            if dry_run:
                savepoint.rollback()
    except (IntegrityError, DataError) as exc:
        LOG.info("Test type upload for '%s' failed apply-time validation: %s", test_type, exc)
        raise


def _emit_apply_statements(session, parsed: ParsedTestType, current_version: str) -> None:
    test_type = parsed.test_type

    for table in ("cat_test_conditions", "target_data_lookups", "test_templates", "generation_sets"):
        session.execute(
            text(f"DELETE FROM {table} WHERE test_type = :test_type"),
            {"test_type": test_type},
        )

    parent = {**parsed.parent, "uploaded_version": current_version}
    session.execute(
        text(_build_upsert_sql(_PARENT_TABLE, _PARENT_KEY, list(parent.keys()))),
        parent,
    )

    for record in parsed.cat_test_conditions:
        row = {**record, "test_type": test_type}
        session.execute(
            text(f"INSERT INTO cat_test_conditions ({', '.join(row.keys())}) "
                 f"VALUES ({', '.join(f':{k}' for k in row)})"),
            row,
        )
    for record in parsed.target_data_lookups:
        row = {**record, "test_type": test_type}
        row.setdefault("test_id", parent.get("id"))
        session.execute(
            text(f"INSERT INTO target_data_lookups ({', '.join(row.keys())}) "
                 f"VALUES ({', '.join(f':{k}' for k in row)})"),
            row,
        )
    for record in parsed.test_templates:
        row = {**record, "test_type": test_type}
        session.execute(
            text(f"INSERT INTO test_templates ({', '.join(row.keys())}) "
                 f"VALUES ({', '.join(f':{k}' for k in row)})"),
            row,
        )

    # 4. Generation-set memberships (idempotent).
    for generation_set in parsed.generation_sets:
        session.execute(
            text("INSERT INTO generation_sets (generation_set, test_type) "
                 "VALUES (:generation_set, :test_type) "
                 "ON CONFLICT (generation_set, test_type) DO NOTHING"),
            {"generation_set": generation_set, "test_type": test_type},
        )


def _build_upsert_sql(table: str, key: str, columns: list[str]) -> str:
    insert_cols = ", ".join(columns)
    insert_vals = ", ".join(f":{c}" for c in columns)
    update_stmt = ", ".join(f"{c}=EXCLUDED.{c}" for c in columns if c != key)
    return (
        f"INSERT INTO {table} ({insert_cols}) "
        f"VALUES ({insert_vals}) "
        f"ON CONFLICT ({key}) DO UPDATE SET {update_stmt}"
    )


def check_id_collision(parsed: ParsedTestType) -> str | None:
    """Return a user-facing error if the parsed ``id`` is bound to a different
    test_type in the DB. Same-code matches are the replace case and return None.
    """
    with database_session() as session:
        row = session.execute(
            text("SELECT test_type FROM test_types WHERE id = :id LIMIT 1"),
            {"id": parsed.parent["id"]},
        ).first()
    if row is None:
        return None
    collision_test_type = row[0]
    if collision_test_type == parsed.test_type:
        return None
    return f"id: '{parsed.parent['id']}' is already used by test type '{collision_test_type}'."
