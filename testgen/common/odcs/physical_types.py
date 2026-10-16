"""Whether a column's declared ODCS ``physicalType`` names the type the data catalog records.

ODCS leaves ``physicalType`` as free text: an author may write a type in any case, by any of its
aliases, or without its length or precision. Both sides are parsed with sqlglot in the
connection's dialect and compared by the name that dialect writes the type back as, which
collapses its aliases (``int4`` and ``integer``; Snowflake's ``TEXT``, ``STRING`` and ``VARCHAR``).
"""

from enum import StrEnum

from sqlglot import exp
from sqlglot.errors import SqlglotError

# Flavor family -> sqlglot dialect. A family with no dialect compares by case-insensitive text.
_DIALECTS: dict[str, str] = {
    "bigquery": "bigquery",
    "databricks": "databricks",
    "duckdb": "duckdb",
    "mssql": "tsql",
    "oracle": "oracle",
    "postgresql": "postgres",
    "redshift": "redshift",
    "redshift_spectrum": "redshift",
    "snowflake": "snowflake",
}

# Types a dialect treats as one that sqlglot names apart.
_SAME_TYPE: dict[str, dict[str, str]] = {
    "snowflake": {"DATETIME": "TIMESTAMPNTZ"},
}

# Dialects whose integer types are all NUMBER(38,0), and the integer types sqlglot reads.
_INTEGERS_ARE_NUMBER = frozenset({"snowflake", "oracle"})
_INTEGER_TYPES = frozenset({
    exp.DataType.Type.TINYINT, exp.DataType.Type.SMALLINT, exp.DataType.Type.INT, exp.DataType.Type.BIGINT,
})


class TypeMatch(StrEnum):
    EQUIVALENT = "equivalent"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


def compare_physical_types(declared: str, recorded: str, flavor_family: str) -> TypeMatch:
    """Compare a declared ``physicalType`` with the type the catalog records for the column.

    A declared type without parameters matches the recorded type at any length or precision,
    except where the dialect fixes them: Snowflake and Oracle integer types are ``NUMBER(38,0)``,
    and a decimal declaring only its precision has a scale of 0. Declared parameters must equal
    the recorded ones. A time-zone variant of a timestamp matches
    only the same variant. ``UNKNOWN`` means the declared type cannot be read in the dialect, or
    declares parameters the catalog does not record, so the two cannot be compared.
    """
    if declared.strip().casefold() == recorded.strip().casefold():
        return TypeMatch.EQUIVALENT
    dialect = _DIALECTS.get(flavor_family)
    if dialect is None:
        return TypeMatch.UNKNOWN

    declared_type = _canonical(declared, dialect)
    recorded_type = _canonical(recorded, dialect)
    if declared_type is None or recorded_type is None:
        return TypeMatch.UNKNOWN

    declared_name, declared_params = declared_type
    recorded_name, recorded_params = recorded_type
    if declared_name != recorded_name:
        return TypeMatch.MISMATCH
    if not declared_params or declared_params == recorded_params:
        return TypeMatch.EQUIVALENT
    if not recorded_params:
        return TypeMatch.UNKNOWN
    return TypeMatch.MISMATCH


def _canonical(type_text: str, dialect: str) -> tuple[str, tuple[str, ...]] | None:
    """The type's name as ``dialect`` writes it, and its parameters, or ``None`` when unreadable."""
    try:
        data_type = exp.DataType.build(type_text, dialect=dialect)
    except (SqlglotError, ValueError):
        return None
    if data_type.this in (exp.DataType.Type.USERDEFINED, exp.DataType.Type.UNKNOWN):
        return None
    if dialect in _INTEGERS_ARE_NUMBER and data_type.this in _INTEGER_TYPES:
        data_type = exp.DataType.build("NUMBER(38,0)", dialect=dialect)

    params = tuple(param.sql(dialect).upper().replace(" ", "") for param in data_type.expressions)
    if dialect == "oracle":
        # BYTE is the length semantics the catalog writes without a suffix; `*` is the maximum precision.
        params = tuple("38" if param == "*" else param.removesuffix("BYTE") for param in params)
    if data_type.this in (exp.DataType.Type.DECIMAL, exp.DataType.Type.BIGDECIMAL) and len(params) == 1:
        # A decimal declaring only its precision has a scale of 0 in every dialect.
        params = (*params, "0")
    bare = data_type.copy()
    bare.set("expressions", [])
    name = bare.sql(dialect).upper()
    name = _SAME_TYPE.get(dialect, {}).get(name, name)

    if dialect == "tsql" and data_type.this is exp.DataType.Type.FLOAT and not params:
        # SQL Server's REAL is FLOAT(24) and a bare FLOAT is FLOAT(53); sqlglot reads both as FLOAT.
        params = ("24",) if type_text.strip().casefold() == "real" else ("53",)
    return name, params
