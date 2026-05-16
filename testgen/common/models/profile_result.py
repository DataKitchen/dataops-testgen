from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import BigInteger, Column, Float, ForeignKey, Integer, Numeric, String, asc, desc
from sqlalchemy.dialects import postgresql

from testgen.common.models.entity import Entity


class ProfileResult(Entity):
    __tablename__ = "profile_results"

    id: UUID = Column(postgresql.UUID(as_uuid=True), primary_key=True, default=uuid4)
    profile_run_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("profiling_runs.id"))
    table_groups_id: UUID = Column(postgresql.UUID(as_uuid=True), ForeignKey("table_groups.id"))
    schema_name: str = Column(String)
    table_name: str = Column(String)
    column_name: str = Column(String)
    position: int = Column(Integer)

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
    distinct_std_value_ct: int | None = Column(BigInteger)
    distinct_pattern_ct: int | None = Column(BigInteger)
    std_pattern_match: str | None = Column(String)
    mixed_case_ct: int | None = Column(BigInteger)
    lower_case_ct: int | None = Column(BigInteger)
    upper_case_ct: int | None = Column(BigInteger)
    non_alpha_ct: int | None = Column(BigInteger)
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
    within_1yr_date_ct: int | None = Column(BigInteger)
    within_1mo_date_ct: int | None = Column(BigInteger)
    future_date_ct: int | None = Column(BigInteger)

    # Boolean-specific
    boolean_true_ct: int | None = Column(BigInteger)

    # Per-column profiling failure (independent of run-level status)
    query_error: str | None = Column(String)

    _default_order_by = (asc(position), asc(column_name))

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
