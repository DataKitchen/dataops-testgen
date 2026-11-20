from collections.abc import Sequence
from typing import Any

from google.api_core.exceptions import NotFound
from google.cloud.bigquery import QueryJobConfig
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from testgen.common.database.column_chars import ColumnChars
from testgen.common.database.flavor.flavor_service import (
    ConnectionParams,
    FlavorService,
    ResolvedConnectionParams,
    base_type_name,
)
from testgen.common.database.statement_cancel import RunningStatement, cancel_each
from testgen.common.job_context import job_context
from testgen.common.value_hash import DECIMAL_BOUND

# Label on every query job a TestGen run starts, whose value is the run's id. The DB-API hides the
# job a statement runs as, so the label is how a canceled run finds its own.
RUN_LABEL = "testgen-run"


class BigqueryFlavorService(FlavorService):

    quote_character = "`"
    escaped_single_quote = "\\'"
    literal_escapes_backslash = True
    varchar_type = "STRING"
    url_scheme = "bigquery"

    # A managed, versionless engine: no instance can lack APPROX_QUANTILES, so nothing to probe.
    supports_approx_percentile = True

    supports_value_hash = True
    float_types = frozenset({"float64"})
    wide_decimal_type = "BIGNUMERIC"

    def exact_text(self, text_expr: str) -> str:
        return f"CAST({text_expr} AS BYTES)"

    def is_missing_schema_error(self, error: DBAPIError) -> bool:
        # The DB-API driver wraps the API's NotFound as its DatabaseError's only argument. A
        # missing project or table is also a NotFound, so the message has to name a dataset. The
        # message of a failed REST call starts with the request line, so the match is not anchored.
        cause = error.orig.args[0] if error.orig is not None and error.orig.args else None
        return isinstance(cause, NotFound) and "Not found: Dataset" in cause.message

    def number_literal(self, number: str) -> str:
        # A plain literal with a decimal point is FLOAT64; NUMERIC would refuse more than 9 decimal places
        return f"BIGNUMERIC '{number}'"

    def canonical_number(self, column_ref: str, is_float: bool) -> str:
        # ROUND of an INT64 returns a FLOAT64, so the value is widened first
        exact = f"CAST({column_ref} AS BIGNUMERIC)"
        if is_float:
            exact = f"ROUND({exact}, 9)"
        return f"CAST(ROUND({exact}, 6) * 1000000 AS STRING)"

    def hashable_condition(self, column_ref: str, column: ColumnChars) -> str:
        if column.general_type == "N" and not self.is_float(column):
            # BigQuery has no integer literal as wide as the bound, and a BIGNUMERIC can hold a value that
            # rounds up to it
            return f"{column_ref} IS NOT NULL AND ABS(CAST({column_ref} AS BIGNUMERIC)) < BIGNUMERIC '{DECIMAL_BOUND}'"
        return super().hashable_condition(column_ref, column)

    def md5_hex(self, text_expr: str) -> str:
        return f"TO_HEX(MD5({text_expr}))"

    def hex_to_wide_decimal(self, hex_expr: str) -> str:
        return f"CAST(CAST(CONCAT('0x', {hex_expr}) AS INT64) AS BIGNUMERIC)"

    def utc_timestamp(self, column_ref: str, column: ColumnChars) -> str:
        # A TIMESTAMP is an instant; a DATETIME is a wall-clock time
        if base_type_name(column.db_data_type) == "timestamp":
            return f"DATETIME({column_ref}, 'UTC')"
        return f"DATETIME({column_ref})"

    def format_timestamp(self, timestamp_expr: str) -> str:
        return f"FORMAT_DATETIME('%Y-%m-%d %H:%M:%S', {timestamp_expr})"

    def epoch_seconds(self, timestamp_expr: str) -> str:
        return f"DATETIME_DIFF(DATETIME_TRUNC({timestamp_expr}, SECOND), DATETIME '1970-01-01 00:00:00', SECOND)"

    def create_engine(self, connection_params: ConnectionParams, table_group_schema: str | None = None) -> Engine:
        engine = super().create_engine(connection_params, table_group_schema)
        event.listen(engine, "connect", _label_run_queries)
        return engine

    def cancel_statements(self, statements: Sequence[RunningStatement]) -> int:
        # The connections share one client, and a statement does not name its job, so the run's jobs
        # are found once by their label.
        if not statements or (run_id := job_context.get().job_id) is None:
            return 0
        client = statements[0].dbapi_connection._client
        # Keyed by id: a job that starts between the two listings appears in both.
        run_jobs = list({
            job.job_id: job
            for state in ("pending", "running")
            for job in client.list_jobs(state_filter=state)
            if (job.labels or {}).get(RUN_LABEL) == str(run_id)
        }.values())

        def cancel(job: Any) -> bool:
            client.cancel_job(job.job_id, location=job.location)
            return True

        return cancel_each(run_jobs, cancel)

    def get_connection_string_head(self, params: ResolvedConnectionParams) -> str:  # noqa: ARG002
        return f"{self.url_scheme}://"

    def get_connection_string_from_fields(self, params: ResolvedConnectionParams) -> str:
        project_id = params.service_account_key["project_id"] if params.service_account_key else ""
        return f"{self.url_scheme}://{project_id}"

    def get_connect_args(self, params: ResolvedConnectionParams) -> dict:  # noqa: ARG002
        return {}

    def get_engine_args(self, params: ResolvedConnectionParams) -> dict[str, Any]:
        return {"credentials_info": params.service_account_key} if params.service_account_key else {}


def _label_run_queries(dbapi_connection: Any, _connection_record: Any) -> None:
    """Label the query jobs a connection starts with the run it starts them for, if any."""
    if (run_id := job_context.get().job_id) is None:
        return
    client = dbapi_connection._client
    config = client.default_query_job_config or QueryJobConfig()
    config.labels = {**(config.labels or {}), RUN_LABEL: str(run_id)}
    client.default_query_job_config = config
