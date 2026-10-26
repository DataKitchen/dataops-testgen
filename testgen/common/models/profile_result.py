import math
import re
from collections.abc import Iterable, Mapping, MutableMapping
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from enum import StrEnum
from types import MappingProxyType
from typing import Any, ClassVar
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Column,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    and_,
    asc,
    delete,
    desc,
    exists,
    func,
    or_,
    select,
    text,
)
from sqlalchemy.dialects import postgresql

from testgen.common.models import database_session, get_current_session
from testgen.common.models.entity import Entity


class ColumnSort(StrEnum):
    """Sort order for the per-run column-profiles listing."""

    hygiene_severity = "hygiene_severity"
    table = "table"


_EXACT_TOKEN = re.compile(r"\{EXACT:([^}]*)\}")
_EXACT_SQL = "(sample_ratio IS NULL OR value_ct = 0)"


def _token_names(names: str) -> list[str]:
    return [name.strip() for name in names.split(",")]


class PercentileMethod(StrEnum):
    EXACT = "exact"
    APPROXIMATE = "approximate"


class MeasureAcquisition(StrEnum):
    """How a profiling measure is taken, which together with the row's ``sample_ratio`` and
    ``percentile_method`` says whether its value is exact, approximate or a sampled estimate."""

    WHOLE_TABLE = "whole_table"
    """Read over every row of the table, exactly."""
    PERCENTILE = "percentile"
    """Read over every row of the table, exactly or approximately as ``percentile_method`` records."""
    SAMPLEABLE_COUNT = "sampleable_count"
    """Counted on the sample when the row has a ``sample_ratio``, and lifted to the whole-table scale
    by the ratio of the whole-table value count to the value count the sample observed."""
    SAMPLEABLE = "sampleable"
    """Read on the sample when the row has a ``sample_ratio``, and stored as measured."""


@dataclass(frozen=True)
class ProfileMeasure:
    """A column of ``profile_results`` that measures the profiled column."""

    label: str
    """The measure's name, in Title Case."""
    acquisition: MeasureAcquisition

    @property
    def sentence_label(self) -> str:
        """The measure's name in sentence case, such as "Leading spaces"."""
        return self.label[:1] + self.label[1:].lower()


class MeasureProvenance(StrEnum):
    """Whether a profile row's value of a measure is exact, approximate, or estimated from a sample."""

    EXACT = "exact"
    APPROXIMATE = "approximate"
    SAMPLED = "sampled"


def _is_positive(value: Any) -> bool:
    # A NaN, which pandas holds for a NULL, compares false
    return value is not None and float(value) > 0


def sample_percent_label(sample_ratio: float) -> str:
    """The share of rows a sample with ``sample_ratio`` read, as a percent label such as ``30%``."""
    percent = 100 / sample_ratio
    if percent < 1:
        return f"{percent:.2g}%"
    if percent > 99:
        return f"{min(percent, 99.9):.1f}%"
    return f"{round(percent)}%"


def _as_decimal(value: Any) -> Decimal | None:
    # Target drivers return counts as int, Decimal or float; Databricks returns float('nan') for NULL.
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() else None


def _lift(count: Any, whole: Decimal, sampled: Decimal) -> int | None:
    number = _as_decimal(count)
    if number is None:
        return None
    return int((number * whole / sampled).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _lift_frequent(frequent: MutableMapping[str, Any], whole: Decimal, sampled: Decimal) -> None:
    for entry in frequent["values"]:
        entry["ct"] = _lift(entry["ct"], whole, sampled)
    if other := frequent.get("other"):
        other["ct"] = _lift(other["ct"], whole, sampled)


def _lift_partition(counts: list[Decimal], whole: Decimal, sampled: Decimal) -> list[int]:
    """Scale counts that add up to ``sampled`` so that they add up to ``whole``.

    Each count gets the integer part of its share, and the units still missing go one each to the
    counts with the largest fractional parts, earlier counts first on a tie.
    """
    numerators = [int(count) * int(whole) for count in counts]
    lifted = [numerator // int(sampled) for numerator in numerators]
    shortfall = int(whole) - sum(lifted)
    by_remainder = sorted(range(len(counts)), key=lambda index: numerators[index] % int(sampled), reverse=True)
    for index in by_remainder[:shortfall]:
        lifted[index] += 1
    return lifted


# Timestamps read from the target, rather than set by TestGen.
_SOURCE_TIMESTAMPS = frozenset({"min_date", "max_date"})
_PERCENTILES = ("percentile_25", "percentile_50", "percentile_75")


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
    frequent_values: dict[str, Any] | None = Column(postgresql.JSONB(none_as_null=True))
    frequent_patterns: dict[str, Any] | None = Column(postgresql.JSONB(none_as_null=True))
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
    percentile_method: PercentileMethod | None = Column(String)
    fractional_sum: float | None = Column(Numeric(38, 6))
    sum_value: Decimal | None = Column(Numeric(38, 8))

    # Table comparison: value hashes over the column's non-null values, the table's inferred key,
    # and the column's hash keyed by it
    multiset_hash: Decimal | None = Column(Numeric(38, 0))
    epoch_sum: Decimal | None = Column(Numeric(38, 0))
    key_column_name: str | None = Column(String)
    keyed_hash: Decimal | None = Column(Numeric(38, 0))

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
        for column in _SOURCE_TIMESTAMPS & values.keys():
            if isinstance(values[column], datetime) and values[column].tzinfo is not None:
                # The wall time the target session reports, which is what a test's measure renders
                # on that same connection. Binding the zone instead stores the UTC instant.
                values[column] = values[column].replace(tzinfo=None)
        low, high = values.get("min_value"), values.get("max_value")
        if low is not None and high is not None:
            for column in _PERCENTILES:
                if values.get(column) is not None:
                    # An approximate percentile can land a rounding error outside the exact range.
                    values[column] = min(max(values[column], low), high)
        statement = postgresql.insert(cls).values(values)
        overwrite = {column: statement.excluded[column] for column in values if column not in cls._upsert_key}
        if overwrite:
            statement = statement.on_conflict_do_update(index_elements=list(cls._upsert_key), set_=overwrite)
        else:
            statement = statement.on_conflict_do_nothing(index_elements=list(cls._upsert_key))
        with database_session() as session, session.begin_nested():
            session.execute(statement)

    measures: ClassVar[Mapping[str, ProfileMeasure]] = MappingProxyType({
        "record_ct": ProfileMeasure("Row Count", MeasureAcquisition.WHOLE_TABLE),
        "value_ct": ProfileMeasure("Value Count", MeasureAcquisition.WHOLE_TABLE),
        "null_value_ct": ProfileMeasure("Null Values", MeasureAcquisition.WHOLE_TABLE),
        "distinct_value_ct": ProfileMeasure("Distinct Values", MeasureAcquisition.WHOLE_TABLE),
        "zero_value_ct": ProfileMeasure("Zero Values", MeasureAcquisition.WHOLE_TABLE),
        "min_length": ProfileMeasure("Minimum Length", MeasureAcquisition.WHOLE_TABLE),
        "max_length": ProfileMeasure("Maximum Length", MeasureAcquisition.WHOLE_TABLE),
        "avg_length": ProfileMeasure("Average Length", MeasureAcquisition.WHOLE_TABLE),
        "min_text": ProfileMeasure("Minimum Text", MeasureAcquisition.WHOLE_TABLE),
        "max_text": ProfileMeasure("Maximum Text", MeasureAcquisition.WHOLE_TABLE),
        "distinct_std_value_ct": ProfileMeasure("Distinct Standard Values", MeasureAcquisition.WHOLE_TABLE),
        "min_value": ProfileMeasure("Minimum Value", MeasureAcquisition.WHOLE_TABLE),
        "min_value_over_0": ProfileMeasure("Minimum Value > 0", MeasureAcquisition.WHOLE_TABLE),
        "max_value": ProfileMeasure("Maximum Value", MeasureAcquisition.WHOLE_TABLE),
        "avg_value": ProfileMeasure("Average Value", MeasureAcquisition.WHOLE_TABLE),
        "stdev_value": ProfileMeasure("Standard Deviation", MeasureAcquisition.WHOLE_TABLE),
        "fractional_sum": ProfileMeasure("Fractional Sum", MeasureAcquisition.WHOLE_TABLE),
        "sum_value": ProfileMeasure("Sum", MeasureAcquisition.WHOLE_TABLE),
        "multiset_hash": ProfileMeasure("Value Hash", MeasureAcquisition.WHOLE_TABLE),
        "epoch_sum": ProfileMeasure("Epoch Sum", MeasureAcquisition.WHOLE_TABLE),
        "keyed_hash": ProfileMeasure("Keyed Value Hash", MeasureAcquisition.WHOLE_TABLE),
        "min_date": ProfileMeasure("Minimum Date", MeasureAcquisition.WHOLE_TABLE),
        "max_date": ProfileMeasure("Maximum Date", MeasureAcquisition.WHOLE_TABLE),
        "before_1yr_date_ct": ProfileMeasure("Before 1 Year", MeasureAcquisition.WHOLE_TABLE),
        "before_5yr_date_ct": ProfileMeasure("Before 5 Years", MeasureAcquisition.WHOLE_TABLE),
        "before_20yr_date_ct": ProfileMeasure("Before 20 Years", MeasureAcquisition.WHOLE_TABLE),
        "before_100yr_date_ct": ProfileMeasure("Before 100 Years", MeasureAcquisition.WHOLE_TABLE),
        "within_1yr_date_ct": ProfileMeasure("Within 1 Year", MeasureAcquisition.WHOLE_TABLE),
        "within_1mo_date_ct": ProfileMeasure("Within 1 Month", MeasureAcquisition.WHOLE_TABLE),
        "future_date_ct": ProfileMeasure("Future Dates", MeasureAcquisition.WHOLE_TABLE),
        "distant_future_date_ct": ProfileMeasure("Distant Future Dates", MeasureAcquisition.WHOLE_TABLE),
        "date_days_present": ProfileMeasure("Days Present", MeasureAcquisition.WHOLE_TABLE),
        "date_weeks_present": ProfileMeasure("Weeks Present", MeasureAcquisition.WHOLE_TABLE),
        "date_months_present": ProfileMeasure("Months Present", MeasureAcquisition.WHOLE_TABLE),
        "boolean_true_ct": ProfileMeasure("True Count", MeasureAcquisition.WHOLE_TABLE),
        "percentile_25": ProfileMeasure("25th Percentile", MeasureAcquisition.PERCENTILE),
        "percentile_50": ProfileMeasure("Median Value", MeasureAcquisition.PERCENTILE),
        "percentile_75": ProfileMeasure("75th Percentile", MeasureAcquisition.PERCENTILE),
        "zero_length_ct": ProfileMeasure("Zero Length", MeasureAcquisition.SAMPLEABLE_COUNT),
        "lead_space_ct": ProfileMeasure("Leading Spaces", MeasureAcquisition.SAMPLEABLE_COUNT),
        "quoted_value_ct": ProfileMeasure("Quoted Values", MeasureAcquisition.SAMPLEABLE_COUNT),
        "includes_digit_ct": ProfileMeasure("Includes Digits", MeasureAcquisition.SAMPLEABLE_COUNT),
        "filled_value_ct": ProfileMeasure("Dummy Values", MeasureAcquisition.SAMPLEABLE_COUNT),
        "upper_case_ct": ProfileMeasure("Upper Case", MeasureAcquisition.SAMPLEABLE_COUNT),
        "lower_case_ct": ProfileMeasure("Lower Case", MeasureAcquisition.SAMPLEABLE_COUNT),
        "non_alpha_ct": ProfileMeasure("Non-Alpha", MeasureAcquisition.SAMPLEABLE_COUNT),
        # Generated by the database from the letter-case counts, so it is taken as they are
        "mixed_case_ct": ProfileMeasure("Mixed Case", MeasureAcquisition.SAMPLEABLE_COUNT),
        "non_printing_ct": ProfileMeasure("Non-Printing Characters", MeasureAcquisition.SAMPLEABLE_COUNT),
        "numeric_ct": ProfileMeasure("Numeric Values", MeasureAcquisition.SAMPLEABLE_COUNT),
        "date_ct": ProfileMeasure("Date Values", MeasureAcquisition.SAMPLEABLE_COUNT),
        "embedded_space_ct": ProfileMeasure("Embedded Spaces", MeasureAcquisition.SAMPLEABLE_COUNT),
        "frequent_patterns": ProfileMeasure("Frequent Patterns", MeasureAcquisition.SAMPLEABLE_COUNT),
        "avg_embedded_spaces": ProfileMeasure("Average Embedded Spaces", MeasureAcquisition.SAMPLEABLE),
        "std_pattern_match": ProfileMeasure("Standard Pattern Match", MeasureAcquisition.SAMPLEABLE),
        "distinct_pattern_ct": ProfileMeasure("Distinct Patterns", MeasureAcquisition.SAMPLEABLE),
        "frequent_values": ProfileMeasure("Frequent Values", MeasureAcquisition.SAMPLEABLE_COUNT),
        "distinct_value_hash": ProfileMeasure("Distinct Value Hash", MeasureAcquisition.SAMPLEABLE),
    })
    """Each measure column, keyed by column name."""

    @classmethod
    def run_sampled(cls, profile_run_id: UUID) -> bool:
        """Whether any column of a profiling run was estimated from a sample."""
        query = select(cls.id).where(cls.profile_run_id == profile_run_id, text(cls.sampled_column_sql)).limit(1)
        return get_current_session().scalar(query) is not None

    @classmethod
    def taken_from_sample(cls, measures: Iterable[str]) -> list[str]:
        """The ``measures`` a sampled profile reads on the sample rather than over every row."""
        return [
            measure
            for measure in measures
            if measure in cls.measures
            and cls.measures[measure].acquisition in (MeasureAcquisition.SAMPLEABLE, MeasureAcquisition.SAMPLEABLE_COUNT)
        ]

    @classmethod
    def exact_clause(cls, measures: Iterable[str]) -> str:
        """SQL condition over unqualified ``profile_results`` columns that holds on a row where every
        one of ``measures``, each taken from the sample on a sampled row, is exact.

        Such a measure is exact on a row profiled without sampling, and on a row whose column holds
        no values, where the sample has nothing to count. Raises ``ValueError`` for a name that is not
        in ``measures`` or names a measure a sampled profile does not take from the sample.
        """
        for measure in measures:
            if measure not in cls.measures:
                raise ValueError(f"'{measure}' is not a profiling measure")
            if not cls.taken_from_sample([measure]):
                raise ValueError(f"'{measure}' is measured over every row even when profiling samples")
        return _EXACT_SQL

    @staticmethod
    def token_measures(criteria: str) -> set[str]:
        """The measures named in the ``{EXACT:measure,...}`` tokens of ``criteria``."""
        return {name for names in _EXACT_TOKEN.findall(criteria) for name in _token_names(names)}

    @classmethod
    def apply_exact_measures(cls, criteria: str, exact_measures: Iterable[str] | None) -> str:
        """Render selection or detection criteria against a profile row.

        Each ``{EXACT:measure,...}`` token in ``criteria`` is replaced by the ``exact_clause`` of the
        measures it names. When ``exact_measures`` is given, the result also holds only where those
        measures are exact.
        """
        rendered = _EXACT_TOKEN.sub(lambda match: f"({cls.exact_clause(_token_names(match.group(1)))})", criteria)
        if exact_measures:
            rendered = f"({rendered}\n) AND {cls.exact_clause(exact_measures)}"
        return rendered

    sampled_column_sql: ClassVar[str] = f"NOT {_EXACT_SQL}"
    """SQL condition over unqualified ``profile_results`` columns for a column estimated from a sample."""

    approximate_percentile_sql: ClassVar[str] = f"percentile_method = '{PercentileMethod.APPROXIMATE}' AND value_ct > 0"
    """SQL condition over unqualified ``profile_results`` columns for a column with approximate percentiles."""

    @classmethod
    def provenance_counts(cls, profile_run_id: UUID) -> tuple[int, int]:
        """The number of a profiling run's columns estimated from a sample, and the number with
        approximate percentiles."""
        query = select(
            func.count().filter(text(cls.sampled_column_sql)),
            func.count().filter(text(cls.approximate_percentile_sql)),
        ).where(cls.profile_run_id == profile_run_id)
        sampled, approximate = get_current_session().execute(query).one()
        return sampled, approximate

    @classmethod
    def provenance(cls, measure: str, row: Mapping[str, Any]) -> MeasureProvenance:
        """Whether ``row``'s value of ``measure`` is exact, approximate, or estimated from a sample.

        ``row`` carries the profile row's ``sample_ratio``, ``percentile_method``, and ``value_ct``. A row
        with no ``percentile_method`` reads its percentiles as exact. A measure taken from the sample is
        exact on a row profiled without sampling. Every measure is exact on a row whose column holds no
        values.
        """
        acquisition = cls.measures[measure].acquisition
        if not _is_positive(row.get("value_ct")):
            return MeasureProvenance.EXACT
        if acquisition == MeasureAcquisition.PERCENTILE:
            if row.get("percentile_method") == PercentileMethod.APPROXIMATE:
                return MeasureProvenance.APPROXIMATE
            return MeasureProvenance.EXACT
        if acquisition in (MeasureAcquisition.SAMPLEABLE, MeasureAcquisition.SAMPLEABLE_COUNT):
            if _is_positive(row.get("sample_ratio")):
                return MeasureProvenance.SAMPLED
        return MeasureProvenance.EXACT

    @classmethod
    def provenance_label(cls, measure: str, row: Mapping[str, Any]) -> str | None:
        """The display label of ``row``'s value of ``measure``, or None when it is exact.

        A sampled value reads "Estimated from a 30% sample" with the row's sample percent, and an
        approximate one "Approximate".
        """
        match cls.provenance(measure, row):
            case MeasureProvenance.SAMPLED:
                return f"Estimated from a {sample_percent_label(row['sample_ratio'])} sample"
            case MeasureProvenance.APPROXIMATE:
                return "Approximate"
        return None

    @classmethod
    def provenance_details(cls, row: Mapping[str, Any]) -> dict[str, dict[str, str]]:
        """How ``row`` holds the measures it does not hold exactly, as ``{"kinds": {measure: provenance},
        "descriptions": {provenance: text}}``. A description is the ``provenance_label`` for a sampled
        value and a fuller sentence for an approximate one."""
        kinds = {}
        descriptions = {}
        for measure in cls.measures:
            if label := cls.provenance_label(measure, row):
                kind = cls.provenance(measure, row)
                kinds[measure] = kind
                descriptions[kind] = (
                    f"{label}: computed over every row with an approximate percentile function"
                    if kind == MeasureProvenance.APPROXIMATE
                    else label
                )
        return {"kinds": kinds, "descriptions": descriptions}

    _case_class_columns: ClassVar[tuple[str, ...]] = ("upper_case_ct", "lower_case_ct", "non_alpha_ct")

    @classmethod
    def calibrate_sampled_counts(cls, row: MutableMapping[str, Any]) -> None:
        """Lift the counts a column query took on the sample onto the whole-table scale, in place.

        The query reports how many values its two sample reads held, ``sample_value_ct`` for the
        counts and ``sample_pattern_value_ct`` for ``frequent_patterns``, and both are removed from
        the row. Each ``SAMPLEABLE_COUNT`` count is multiplied by ``value_ct`` over the value count of
        the read it was taken on and rounded to the nearest integer, ties away from zero, so a count
        covering every sampled value lands exactly on ``value_ct``. The letter-case counts are shared
        out by largest remainder instead, so that they and the mixed-case values they leave add up
        to ``value_ct``. A count that is NULL or not a number stays NULL. When the sample held no
        values while the table did, there is no ratio and the counts become NULL.
        A row without ``sample_value_ct`` is left as it is.
        """
        if "sample_value_ct" not in row:
            return
        whole = _as_decimal(row.get("value_ct"))
        sampled = _as_decimal(row.pop("sample_value_ct"))
        pattern_sampled = _as_decimal(row.pop("sample_pattern_value_ct"))
        if whole is None or sampled is None:
            return

        with localcontext() as context:
            context.prec = 60
            if (patterns := row.get("frequent_patterns")) and pattern_sampled != whole:
                _lift_frequent(patterns, whole, pattern_sampled)
            if whole == sampled:
                return

            counts = [
                column
                for column, measure in cls.measures.items()
                if measure.acquisition is MeasureAcquisition.SAMPLEABLE_COUNT
                and column not in ("frequent_patterns", "frequent_values")
                and column in row
            ]
            if not sampled:
                # The sample held no values while the table did: there is no ratio to lift by.
                for column in counts:
                    row[column] = None
                return

            case_classes = [_as_decimal(row.get(column)) for column in cls._case_class_columns]
            if None not in case_classes:
                mixed = sampled - sum(case_classes)
                lifted = _lift_partition([*case_classes, mixed], whole, sampled)
                row.update(zip(cls._case_class_columns, lifted[:-1], strict=True))
                counts = [column for column in counts if column not in cls._case_class_columns]
            for column in counts:
                row[column] = _lift(row[column], whole, sampled)

    @staticmethod
    def calibrate_frequent_values(frequent: MutableMapping[str, Any] | None, whole: Any, sampled: Any) -> None:
        """Lift the counts in a ``frequent_values`` field taken on the sample onto the whole-table scale, in place.

        Each value's count and the count of the trailing ``other`` entry are multiplied by ``whole``, the
        column's whole-table value count, over ``sampled``, the value count of the read the frequencies
        were taken on, and rounded to the nearest integer, ties away from zero. The number of distinct
        values the ``other`` entry covers is left as observed. Nothing changes when either value count is
        missing or ``sampled`` is zero.
        """
        whole_ct = _as_decimal(whole)
        sampled_ct = _as_decimal(sampled)
        if not frequent or whole_ct is None or not sampled_ct or whole_ct == sampled_ct:
            return

        with localcontext() as context:
            context.prec = 60
            _lift_frequent(frequent, whole_ct, sampled_ct)

    @classmethod
    def delete_for_run(cls, profile_run_id: UUID) -> int:
        """Remove a run's results. A run that starts over keeps its id, so anything it wrote
        for a column that has since gone would otherwise outlive the column."""
        result = get_current_session().execute(delete(cls).where(cls.profile_run_id == profile_run_id))
        return result.rowcount or 0

    @classmethod
    def has_value_hashes(cls, profile_run_id: UUID) -> bool:
        """Whether a profiling run computed value hashes for any column."""
        return bool(
            get_current_session().scalar(
                select(
                    exists().where(
                        cls.profile_run_id == profile_run_id,
                        or_(cls.multiset_hash.is_not(None), cls.epoch_sum.is_not(None)),
                    )
                )
            )
        )

    @classmethod
    def list_keyed_hash_columns(cls, profile_run_id: UUID) -> dict[str, tuple[str, list[str]]]:
        """Return, for each table of a run that has a key column, its key and its other hashed columns.

        Returns:
            ``{table_name: (key_column_name, [column_name, ...])}``, columns in position order.
        """
        rows = get_current_session().execute(
            select(cls.table_name, cls.key_column_name, cls.column_name)
            .where(
                cls.profile_run_id == profile_run_id,
                cls.key_column_name.is_not(None),
                cls.multiset_hash.is_not(None),
                cls.column_name != cls.key_column_name,
            )
            .order_by(cls.table_name, cls.position, cls.column_name)
        ).all()
        keyed: dict[str, tuple[str, list[str]]] = {}
        for table_name, key_column_name, column_name in rows:
            keyed.setdefault(table_name, (key_column_name, []))[1].append(column_name)
        return keyed

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

    @classmethod
    def list_column_errors_for_run(
        cls,
        profile_run_id: UUID,
        *clauses,
        limit: int,
    ) -> "tuple[list[ColumnErrorRow], int]":
        """The first ``limit`` columns of a profiling run whose profiling query failed, and how many
        there are in all, ordered by schema, table and column position.

        Extra ``*clauses`` are AND'd into the WHERE and refer to ``ProfileResult`` columns.
        """
        query = (
            select(cls.schema_name, cls.table_name, cls.column_name, cls.query_error)
            .where(cls.profile_run_id == profile_run_id, cls.query_error.isnot(None), *clauses)
            .order_by(asc(cls.schema_name), asc(cls.table_name), asc(cls.position), asc(cls.column_name))
        )
        return cls._paginate(query, page=1, limit=limit, data_class=ColumnErrorRow)

    @classmethod
    def list_columns_for_run(
        cls,
        profile_run_id: UUID,
        *clauses,
        sort: ColumnSort,
        page: int,
        limit: int,
    ) -> "tuple[list[ColumnProfileRow], int]":
        """Paginated per-column profile listing for one profiling run.

        Each row combines per-run stats (``profile_results``) with the column's latest
        catalog attributes (``pii_flag``, ``critical_data_element``, scores) from
        ``data_column_chars``. A column with no critical data element flag of its own takes
        its table's.
        Hygiene-issue counts come from the six-bucket per-column subquery on
        ``HygieneIssue``.

        Scores and ``pii_flag`` are the column's current catalog values — a column that
        has been re-profiled since ``profile_run_id`` still reports the latest scores.
        Callers wanting the historical value should read ``profile_results.pii_flag``
        for the run directly.

        Extra ``*clauses`` are AND'd into the WHERE and refer to ``ProfileResult`` columns
        (e.g. ``ProfileResult.table_name == "orders"``).
        """
        from testgen.common.models.data_column import DataColumnChars
        from testgen.common.models.data_table import DataTable, column_cde
        from testgen.common.models.hygiene_issue import HygieneIssue

        issue_subq = HygieneIssue.counts_by_column_subquery(profile_run_id)
        cde_expr = column_cde().label("critical_data_element")

        natural_key = and_(
            DataColumnChars.table_groups_id == cls.table_groups_id,
            DataColumnChars.table_name == cls.table_name,
            DataColumnChars.column_name == cls.column_name,
        )
        issue_join = and_(
            issue_subq.c.schema_name == cls.schema_name,
            issue_subq.c.table_name == cls.table_name,
            issue_subq.c.column_name == cls.column_name,
        )

        definite = func.coalesce(issue_subq.c.definite, 0).label("definite")
        likely = func.coalesce(issue_subq.c.likely, 0).label("likely")
        possible = func.coalesce(issue_subq.c.possible, 0).label("possible")
        high = func.coalesce(issue_subq.c.high, 0).label("high")
        moderate = func.coalesce(issue_subq.c.moderate, 0).label("moderate")
        dismissed = func.coalesce(issue_subq.c.dismissed, 0).label("dismissed")

        query = (
            select(
                cls.schema_name,
                cls.table_name,
                cls.column_name,
                cls.general_type,
                cls.functional_data_type,
                cls.db_data_type,
                cls.datatype_suggestion,
                DataColumnChars.pii_flag.label("pii_flag"),
                cde_expr,
                cls.record_ct,
                cls.null_value_ct,
                cls.distinct_value_ct,
                cls.filled_value_ct,
                DataColumnChars.dq_score_profiling.label("profiling_score"),
                DataColumnChars.dq_score_testing.label("testing_score"),
                definite,
                likely,
                possible,
                high,
                moderate,
                dismissed,
            )
            .select_from(cls)
            .outerjoin(DataColumnChars, natural_key)
            .outerjoin(DataTable, DataTable.id == DataColumnChars.table_id)
            .outerjoin(issue_subq, issue_join)
            .where(cls.profile_run_id == profile_run_id, *clauses)
        )

        tiebreaker = (
            asc(func.lower(cls.schema_name)),
            asc(func.lower(cls.table_name)),
            asc(cls.position),
            asc(cls.column_name),
        )
        if sort == ColumnSort.hygiene_severity:
            order_exprs = (
                desc(definite),
                desc(likely),
                desc(possible),
                desc(high),
                desc(moderate),
                *tiebreaker,
            )
        else:
            order_exprs = tiebreaker
        query = query.order_by(*order_exprs)

        return cls._paginate(query, page=page, limit=limit, data_class=ColumnProfileRow)


@dataclass
class ColumnProfileRow:
    """One paginated row from :meth:`ProfileResult.list_columns_for_run`.

    Field names match the SELECT column labels exactly — ``Entity._paginate`` unpacks each
    row by keyword, so renaming a field here or a ``.label(...)`` in the query without
    matching the other breaks row construction.
    """

    schema_name: str
    table_name: str
    column_name: str
    general_type: str | None
    functional_data_type: str | None
    db_data_type: str | None
    datatype_suggestion: str | None
    pii_flag: str | None
    critical_data_element: bool
    record_ct: int | None
    null_value_ct: int | None
    distinct_value_ct: int | None
    filled_value_ct: int | None
    profiling_score: float | None
    testing_score: float | None
    definite: int
    likely: int
    possible: int
    high: int
    moderate: int
    dismissed: int


@dataclass
class ColumnErrorRow:
    """One row from :meth:`ProfileResult.list_column_errors_for_run`."""

    schema_name: str
    table_name: str
    column_name: str
    query_error: str
