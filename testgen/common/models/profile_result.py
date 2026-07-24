import math
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Column, Float, ForeignKey, Integer, Numeric, String, asc, desc
from sqlalchemy.dialects import postgresql

from testgen.common.models import database_session
from testgen.common.models.entity import Entity


def _sanitize_write_value(value: Any) -> Any:
    # Databricks (via Arrow) returns float('nan') for NULL numerics, which PostgreSQL
    # rejects; PostgreSQL rejects NUL bytes in text; empty strings are stored as NULL.
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str):
        value = value.replace("\x00", "")
        if value == "":
            return None
    return value


class ProfileResult(Entity):
    __tablename__ = "profile_results"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    profile_run_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("profiling_runs.id"))
    table_groups_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("table_groups.id"))
    schema_name: str = Column(String)
    table_name: str = Column(String)
    column_name: str = Column(String)
    position: int = Column(Integer)
    project_code: str | None = Column(String(30))
    connection_id: int | None = Column(BigInteger)
    run_date: datetime | None = Column(postgresql.TIMESTAMP)

    general_type: str | None = Column(String)
    column_type: str | None = Column(String)
    db_data_type: str | None = Column(String)
    functional_data_type: str | None = Column(String)
    functional_table_type: str | None = Column(String)
    datatype_suggestion: str | None = Column(String)
    pii_flag: str | None = Column(String(50))

    record_ct: int | None = Column(BigInteger)
    value_ct: int | None = Column(BigInteger)
    null_value_ct: int | None = Column(BigInteger)
    distinct_value_ct: int | None = Column(BigInteger)
    filled_value_ct: int | None = Column(BigInteger)
    zero_value_ct: int | None = Column(BigInteger)

    # Alpha-specific
    min_length: int | None = Column(Integer)
    max_length: int | None = Column(Integer)
    avg_length: float | None = Column(Float)
    min_text: str | None = Column(String)
    max_text: str | None = Column(String)
    top_freq_values: str | None = Column(String)
    top_patterns: str | None = Column(String)
    distinct_value_hash: str | None = Column(String(40))
    distinct_std_value_ct: int | None = Column(BigInteger)
    distinct_pattern_ct: int | None = Column(BigInteger)
    std_pattern_match: str | None = Column(String)
    mixed_case_ct: int | None = Column(BigInteger)
    lower_case_ct: int | None = Column(BigInteger)
    upper_case_ct: int | None = Column(BigInteger)
    non_alpha_ct: int | None = Column(BigInteger)
    non_printing_ct: int | None = Column(BigInteger)
    includes_digit_ct: int | None = Column(BigInteger)
    numeric_ct: int | None = Column(BigInteger)
    date_ct: int | None = Column(BigInteger)
    quoted_value_ct: int | None = Column(BigInteger)
    lead_space_ct: int | None = Column(BigInteger)
    embedded_space_ct: int | None = Column(BigInteger)
    avg_embedded_spaces: float | None = Column(Float)
    zero_length_ct: int | None = Column(BigInteger)

    # Numeric-specific
    min_value: float | None = Column(Float)
    min_value_over_0: float | None = Column(Float)
    max_value: float | None = Column(Float)
    avg_value: float | None = Column(Float)
    stdev_value: float | None = Column(Float)
    percentile_25: float | None = Column(Float)
    percentile_50: float | None = Column(Float)
    percentile_75: float | None = Column(Float)
    fractional_sum: float | None = Column(Numeric(38, 6))

    # Date-specific
    min_date: datetime | None = Column(postgresql.TIMESTAMP)
    max_date: datetime | None = Column(postgresql.TIMESTAMP)
    before_1yr_date_ct: int | None = Column(BigInteger)
    before_5yr_date_ct: int | None = Column(BigInteger)
    before_20yr_date_ct: int | None = Column(BigInteger)
    before_100yr_date_ct: int | None = Column(BigInteger)
    within_1yr_date_ct: int | None = Column(BigInteger)
    within_1mo_date_ct: int | None = Column(BigInteger)
    future_date_ct: int | None = Column(BigInteger)
    distant_future_date_ct: int | None = Column(BigInteger)
    date_days_present: int | None = Column(BigInteger)
    date_weeks_present: int | None = Column(BigInteger)
    date_months_present: int | None = Column(BigInteger)

    # Boolean-specific
    boolean_true_ct: int | None = Column(BigInteger)

    sample_ratio: float | None = Column(Float)

    # Per-column profiling failure (independent of run-level status)
    query_error: str | None = Column(String)

    _default_order_by = (asc(position), asc(column_name))

    # Natural key backing the uix_pr_tg_t_c_prun unique index.
    _upsert_key = ("table_groups_id", "table_name", "column_name", "profile_run_id")

    @classmethod
    def upsert(cls, row: Mapping[str, Any]) -> None:
        """Insert one profile-results row, overwriting on natural-key conflict.

        The row is mapped by column name, so callers supply only the columns they
        populate; the rest fall to their defaults on insert. Re-running the same key
        overwrites its prior values rather than duplicating the row. The write runs in
        its own SAVEPOINT, so a failure on one row (e.g. an out-of-range value) rolls
        back only that row and leaves the surrounding transaction usable.
        """
        values = {column: _sanitize_write_value(value) for column, value in row.items()}
        statement = postgresql.insert(cls).values(values)
        overwrite = {column: statement.excluded[column] for column in values if column not in cls._upsert_key}
        if overwrite:
            statement = statement.on_conflict_do_update(index_elements=list(cls._upsert_key), set_=overwrite)
        else:
            statement = statement.on_conflict_do_nothing(index_elements=list(cls._upsert_key))
        with database_session() as session, session.begin_nested():
            session.execute(statement)

    @classmethod
    def get_for_column(
        cls,
        table_groups_id: UUID,
        table_name: str,
        column_name: str,
        profiling_run_id: UUID | None = None,
    ) -> "ProfileResult | None":
        """Fetch the profile-results row for one column.

        Resolves to the explicit ``profiling_run_id`` when given, otherwise to the
        column's latest profile run (via ``data_column_chars.last_complete_profile_run_id``).
        Returns ``None`` when no row exists.
        """
        # Local import: data_column imports ProfileResult at module top.
        from testgen.common.models.data_column import DataColumnChars

        clauses = [
            cls.table_groups_id == table_groups_id,
            cls.table_name == table_name,
            cls.column_name == column_name,
        ]
        if profiling_run_id is not None:
            clauses.append(cls.profile_run_id == profiling_run_id)
        else:
            latest = list(
                DataColumnChars.select_where(
                    DataColumnChars.table_groups_id == table_groups_id,
                    DataColumnChars.table_name == table_name,
                    DataColumnChars.column_name == column_name,
                )
            )
            if not latest or latest[0].last_complete_profile_run_id is None:
                return None
            clauses.append(cls.profile_run_id == latest[0].last_complete_profile_run_id)

        rows = list(cls.select_where(*clauses, order_by=(desc(cls.profile_run_id),)))
        return rows[0] if rows else None

    @classmethod
    def select_for_runs(
        cls,
        run_ids: Iterable[UUID],
        table_name: str | None = None,
        column_name: str | None = None,
    ) -> list["ProfileResult"]:
        """Fetch profile-results rows for a set of profiling runs in one query.

        Optional ``table_name`` and ``column_name`` filters narrow the result to one
        entity (case-sensitive exact match).
        """
        run_ids = list(run_ids)
        if not run_ids:
            return []
        clauses = [cls.profile_run_id.in_(run_ids)]
        if table_name is not None:
            clauses.append(cls.table_name == table_name)
        if column_name is not None:
            clauses.append(cls.column_name == column_name)
        return list(cls.select_where(*clauses))
