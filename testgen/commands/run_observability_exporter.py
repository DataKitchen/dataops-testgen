import json
import logging
import sys
import uuid
from collections import namedtuple
from urllib.parse import urlparse

import click
import requests
from requests_extensions import get_session

from testgen import settings
from testgen.common import date_service, read_template_sql_file
from testgen.common.database.database_service import (
    ExecuteDBQuery,
    RetrieveDBResultsToDictList,
    RetrieveDBResultsToList,
)

LOG = logging.getLogger("testgen")

DEFAULT_COMPONENT_TYPE = "dataset"

PAYLOAD_MAX_SIZE = 100000
PAYLOAD_MAX_ITEMS = 500


def calculate_chunk_size(test_outcomes):
    size = len(json.dumps(test_outcomes))
    split = size / PAYLOAD_MAX_SIZE * 2
    chunk_size = int(round(len(test_outcomes) / split))
    return min(PAYLOAD_MAX_ITEMS, chunk_size)


def post_event(event_type, payload, api_url, api_key, test_outcomes, is_test=False):
    qty_of_events = len(test_outcomes)
    if not is_test and qty_of_events == 0:
        click.echo("Nothing to be sent to Observability")
        return qty_of_events

    def chunkify(collection, chunk_size):
        return [collection[i : i + chunk_size] for i in range(0, len(collection), chunk_size)]

    if not is_test:
        chunk_size = calculate_chunk_size(test_outcomes)
        chunks = chunkify(test_outcomes, chunk_size)
    else:
        chunks = [[]]

    session = get_session()

    url = _get_api_endpoint(api_url, event_type)
    headers = {
        "Content-Type": "application/json",
        "ServiceAccountAuthenticationKey": api_key,
    }
    for chunk in chunks:
        payload["test_outcomes"] = chunk
        response = session.post(url, headers=headers, json=payload, verify=settings.OBSERVABILITY_VERIFY_SSL)
        if not response.ok:
            if is_test and "test_outcomes" in response.text and "Length must be between 1 and 500" in response.text:
                continue
            else:
                raise requests.HTTPError(
                    f"Call to {url} failed with status code: {response.status_code} and message: {response.text}"
                )
    return qty_of_events


def _get_api_endpoint(api_url: str | None, event_type: str) -> str:
    if not api_url:
        raise Warning("Unable to post events due to misconfigured Observability API URL")

    parsed_url = urlparse(api_url)
    return f"{parsed_url.scheme!s}://{parsed_url.netloc!s}{parsed_url.path!s}/events/v1/{event_type}"


def collect_event_data(test_suite_id):
    try:
        event_data_query = (
            read_template_sql_file("get_event_data.sql", "observability")
            .replace("{TEST_SUITE_ID}", test_suite_id)
        )

        event_data_query_result = RetrieveDBResultsToDictList("DKTG", event_data_query)
        if not event_data_query_result:
            LOG.error(
                f"Could not get event data for exporting to Observability. Test suite '{test_suite_id}'. EXITING!"
            )
            sys.exit(1)
        if len(event_data_query_result) == 0:
            LOG.error(
                f"Event data query is empty. Test suite '{test_suite_id}'. Exiting export to Observability!"
            )
            sys.exit(1)

        event = event_data_query_result[0]
        event_data = _get_event_data(event)
        api_key = event.observability_api_key
        api_url = event.observability_api_url
    except Exception:
        LOG.exception(
            f"Error collecting event data for exporting to Observability. Test suite '{test_suite_id}'"
        )
        sys.exit(2)
    else:
        return event_data, api_url, api_key


def _get_test_event_data(project_code):
    Event = namedtuple(
        "Event",
        [
            "sql_flavor",
            "dataset_key",
            "dataset_name",
            "schema",
            "connection_name",
            "project_db",
            "table_groups_id",
            "profile_use_sampling",
            "project_code",
            "profile_sample_percent",
            "profile_sample_minimum_count",
            "profiling_include_mask",
            "profiling_exclude_mask",
            "profiling_table_set",
        ],
    )

    event = Event(
        sql_flavor="redshift",
        dataset_key="test_dataset_key",
        dataset_name="test_dataset_name",
        schema="test_schema",
        connection_name="test_connection_name",
        project_db="test_project_db",
        table_groups_id=uuid.uuid4(),
        profile_use_sampling="N",
        project_code=project_code,
        profile_sample_percent="30",
        profile_sample_minimum_count="15000",
        profiling_include_mask="%",
        profiling_exclude_mask="tmp%",
        profiling_table_set="",
    )

    event_data = _get_event_data(event)
    return event_data


def _get_event_data(event):
    event_data = {
        "external_url": None,
        "stream_name": None,
        "run_key": None,
        "server_name": None,
        "task_name": None,
        "pipeline_key": None,
        "pipeline_name": None,
        "metadata": {},
        "run_name": None,
        "task_key": None,
        "stream_key": None,
        "server_key": None,
        "component_tool": event.sql_flavor,
        "dataset_key": event.dataset_key,
        "dataset_name": event.dataset_name,
        "event_timestamp": date_service.get_now_as_iso_timestamp(),
        "component_integrations": {
            "integrations": {
                "testgen": {
                    "schema": event.schema,
                    "connection_name": event.connection_name,
                    "database_name": event.project_db,
                    "version": 1,
                    "table_group_configuration": {
                        "group_id": str(event.table_groups_id),
                        "uses_sampling": event.profile_use_sampling == "Y",
                        "project_code": event.project_code,
                        "sample_percentage": (
                            event.profile_sample_percent if event.profile_use_sampling == "Y" else None
                        ),
                        "sample_minimum_count": (
                            event.profile_sample_minimum_count if event.profile_use_sampling == "Y" else None
                        ),
                    },
                    "tables": {
                        "include_pattern": event.profiling_include_mask,
                        "exclude_pattern": event.profiling_exclude_mask,
                        "include_list": _get_processed_profiling_table_set(event.profiling_table_set),
                    },
                }
            }
        },
    }
    return event_data


def _get_processed_profiling_table_set(profiling_table_set):
    if profiling_table_set is None:
        return []
    items = profiling_table_set.split(",")
    items_no_quotes = [x.replace("'", "") for x in items]
    items_remove_blank = list(filter(lambda x: x != "", items_no_quotes))
    return items_remove_blank


def collect_test_results(test_suite_id, max_qty_events):
    try:
        query = (
            read_template_sql_file("get_test_results.sql", "observability")
            .replace("{TEST_SUITE_ID}", test_suite_id)
            .replace("{MAX_QTY_EVENTS}", str(max_qty_events))
        )
        query_results = RetrieveDBResultsToDictList("DKTG", query)
        collected = []
        updated_ids = []
    except Exception:
        LOG.exception("Error collecting test results! EXITING!")
        sys.exit(2)
    for result in query_results:
        try:
            result_payload = {
                "integrations": {
                    "testgen": {
                        "columns": result.column_names.split(",") if result.column_names is not None else [],
                        "table": result.table_name,
                        "test_suite": result.test_suite,
                        "test_parameters": _get_input_parameters(result.input_parameters),
                        "version": 1,
                    }
                },
                "key": str(result.test_definition_id),
                "type": result.type,
                "min_threshold": result.min_threshold,
                "max_threshold": result.max_threshold,
                "name": result.name,
                "description": result.description,
                "metadata": {},
                "start_time": date_service.as_iso_timestamp(result.start_time),
                "result": result.result_message,
                "end_time": date_service.as_iso_timestamp(result.end_time),
                "dimensions": [result.dq_dimension],
                "status": result.result_status.upper(),
                "metric_value": result.metric_value,
                "metric_name": result.measure_uom,
                "metric_description": result.measure_uom_description,
            }

            collected.append(result_payload)
            updated_ids.append(str(result.result_id))
        except Exception:
            LOG.warning("Error collecting record", exc_info=True)

    return collected, updated_ids


def _get_input_parameters(input_parameters):
    ret = []
    if input_parameters is None:
        return ret

    items = input_parameters.split("=")

    if len(items) < 2:
        return ret

    is_first = True
    item_number = 0
    name = None
    for item in items:
        item_number += 1
        if is_first:
            name = item
            is_first = False
        elif len(items) == item_number:  # is last
            value = item
            ret.append({"name": name.strip(), "value": value.strip()})
        else:
            words = item.split(",")
            value = ",".join(words[:-1])  # everything but the last word
            ret.append({"name": name.strip(), "value": value.strip()})
            name = words[-1]  # the last word is the next name
    return ret


def mark_exported_results(test_suite_id, ids):
    if len(ids) == 0:
        return

    result_ids = ", ".join(ids)
    query = (
        read_template_sql_file("update_test_results_exported_to_observability.sql", "observability")
        .replace("{TEST_SUITE_ID}", test_suite_id)
        .replace("{RESULT_IDS}", result_ids)
    )
    try:
        ExecuteDBQuery("DKTG", query)
    except Exception:
        LOG.exception("Error marking exported results.")
        LOG.error(  # noqa: TRY400
            f"These should be marked manually!. Run the following query to fix \n------\n{query}\n------"
        )
        sys.exit(3)


def export_test_results(test_suite_id):
    LOG.info("Observability Export V2 - Privileged UI")
    event, api_url, api_key = collect_event_data(test_suite_id)
    max_qty_events = settings.OBSERVABILITY_EXPORT_LIMIT
    qty_of_exported_events = 0
    while True:
        click.echo(f"Observability Export Increment - {qty_of_exported_events} exported events so far")
        test_outcomes, updated_ids = collect_test_results(test_suite_id, max_qty_events)
        if len(test_outcomes) == 0:
            return qty_of_exported_events
        qty_of_exported_events += post_event("test-outcomes", event, api_url, api_key, test_outcomes)
        mark_exported_results(test_suite_id, updated_ids)


def run_observability_exporter(project_code, test_suite):
    LOG.info("CurrentStep: Observability Export - Test Results")
    result = RetrieveDBResultsToList(
        "DKTG",
        f"SELECT id::VARCHAR FROM test_suites WHERE test_suite = '{test_suite}' AND project_code = '{project_code}'"
    )
    qty_of_exported_events = export_test_results(result[0][0][0])
    click.echo(f"{qty_of_exported_events} events have been exported.")


def test_observability_exporter(project_code, api_url, api_key):
    event = _get_test_event_data(project_code)
    test_outcomes = []
    post_event("test-outcomes", event, api_url, api_key, test_outcomes, is_test=True)
    LOG.info("Test Observability Exporter Finished")
