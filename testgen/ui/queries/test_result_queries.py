from typing import Literal

import pandas as pd
import streamlit as st

from testgen.ui.services.database_service import fetch_df_from_db


@st.cache_data(show_spinner="Loading data ...")
def get_test_results(
    run_id: str,
    test_statuses: list[str] | None = None,
    test_type_id: str | None = None,
    table_name: str | None = None,
    column_name: str | None = None,
    action: Literal["Confirmed", "Dismissed", "Muted", "No Action"] | None = None,
    sorting_columns: list[str] | None = None,
) -> pd.DataFrame:
    query = f"""
    WITH run_results
        AS (SELECT *
                FROM test_results r
            WHERE
                r.test_run_id = :run_id
                {"AND r.result_status IN :test_statuses" if test_statuses else ""}
                {"AND r.test_type = :test_type_id" if test_type_id else ""}
                {"AND r.table_name = :table_name" if table_name else ""}
                {"AND r.column_names ILIKE :column_name" if column_name else ""}
                {"AND r.disposition IS NULL" if action == "No Action" else "AND r.disposition = :disposition" if action else ""}
            )
    SELECT r.table_name,
            p.project_name, ts.test_suite, tg.table_groups_name, cn.connection_name, cn.project_host, cn.sql_flavor,
            tt.dq_dimension, tt.test_scope,
            r.schema_name, r.column_names, r.test_time::DATE as test_date, r.test_type, tt.id as test_type_id,
            tt.test_name_short, tt.test_name_long, r.test_description, tt.measure_uom, tt.measure_uom_description,
            c.test_operator, r.threshold_value::NUMERIC(16, 5), r.result_measure::NUMERIC(16, 5), r.result_status,
            CASE
                WHEN r.result_code <> 1 THEN r.disposition
                ELSE 'Passed'
            END as disposition,
            NULL::VARCHAR(1) as action,
            r.input_parameters, r.result_message, CASE WHEN result_code <> 1 THEN r.severity END as severity,
            r.result_code as passed_ct,
            (1 - r.result_code)::INTEGER as exception_ct,
            CASE
                WHEN result_status = 'Warning'
                AND result_message NOT ILIKE 'Inactivated%%' THEN 1
            END::INTEGER as warning_ct,
            CASE
                WHEN result_status = 'Failed'
                AND result_message NOT ILIKE 'Inactivated%%' THEN 1
            END::INTEGER as failed_ct,
            CASE
                WHEN result_message ILIKE 'Inactivated%%' THEN 1
            END as execution_error_ct,
            p.project_code, r.table_groups_id::VARCHAR,
            r.id::VARCHAR as test_result_id, r.test_run_id::VARCHAR,
            c.id::VARCHAR as connection_id, r.test_suite_id::VARCHAR,
            r.test_definition_id::VARCHAR as test_definition_id_runtime,
            CASE
                WHEN r.auto_gen = TRUE THEN d.id
                                    ELSE r.test_definition_id
            END::VARCHAR as test_definition_id_current,
            r.auto_gen,

            -- These are used in the PDF report
            tt.threshold_description, tt.usage_notes, r.test_time,
            dcc.description as column_description,
            COALESCE(dcc.critical_data_element, dtc.critical_data_element) as critical_data_element,
            COALESCE(dcc.data_source, dtc.data_source, tg.data_source) as data_source,
            COALESCE(dcc.source_system, dtc.source_system, tg.source_system) as source_system,
            COALESCE(dcc.source_process, dtc.source_process, tg.source_process) as source_process,
            COALESCE(dcc.business_domain, dtc.business_domain, tg.business_domain) as business_domain,
            COALESCE(dcc.stakeholder_group, dtc.stakeholder_group, tg.stakeholder_group) as stakeholder_group,
            COALESCE(dcc.transform_level, dtc.transform_level, tg.transform_level) as transform_level,
            COALESCE(dcc.aggregation_level, dtc.aggregation_level) as aggregation_level,
            COALESCE(dcc.data_product, dtc.data_product, tg.data_product) as data_product
        FROM run_results r
    INNER JOIN test_types tt
        ON (r.test_type = tt.test_type)
    LEFT JOIN test_definitions d
        ON (r.test_suite_id = d.test_suite_id
        AND  r.table_name = d.table_name
        AND  COALESCE(r.column_names, 'N/A') = COALESCE(d.column_name, 'N/A')
        AND  r.test_type = d.test_type
        AND  r.auto_gen = TRUE
        AND  d.last_auto_gen_date IS NOT NULL)
    INNER JOIN test_suites ts
        ON r.test_suite_id = ts.id
    INNER JOIN projects p
        ON (ts.project_code = p.project_code)
    INNER JOIN table_groups tg
        ON (ts.table_groups_id = tg.id)
    INNER JOIN connections cn
        ON (tg.connection_id = cn.connection_id)
    LEFT JOIN cat_test_conditions c
        ON (cn.sql_flavor = c.sql_flavor
        AND  r.test_type = c.test_type)
    LEFT JOIN data_column_chars dcc
        ON (tg.id = dcc.table_groups_id
        AND  r.schema_name = dcc.schema_name
        AND  r.table_name = dcc.table_name
        AND  r.column_names = dcc.column_name)
    LEFT JOIN data_table_chars dtc
        ON dcc.table_id = dtc.table_id
    {f"ORDER BY {', '.join(' '.join(col) for col in sorting_columns)}" if sorting_columns else ""};
    """
    params = {
        "run_id": run_id,
        "test_statuses": tuple(test_statuses or []),
        "test_type_id": test_type_id,
        "table_name": table_name,
        "column_name": column_name,
        "disposition": {
            "Muted": "Inactive",
        }.get(action, action),
    }

    df = fetch_df_from_db(query, params)
    df["test_date"] = pd.to_datetime(df["test_date"])
    return df


@st.cache_data(show_spinner=False)
def get_test_result_history(tr_data, limit: int | None = None):
    query = f"""
    SELECT test_date,
        test_type,
        test_name_short,
        test_name_long,
        measure_uom,
        test_operator,
        threshold_value::NUMERIC,
        result_measure::NUMERIC,
        result_status
    FROM v_test_results
    WHERE {f"""
        test_suite_id = :test_suite_id
        AND table_name = :table_name
        AND column_names {"= :column_names" if tr_data["column_names"] else "IS NULL"}
        AND test_type = :test_type
        AND auto_gen = TRUE
    """ if tr_data["auto_gen"] else """
        test_definition_id_runtime = :test_definition_id_runtime
    """}
    ORDER BY test_date DESC
    {'LIMIT ' + str(limit) if limit else ''};
    """
    params = {
        "test_suite_id": tr_data["test_suite_id"],
        "table_name": tr_data["table_name"],
        "column_names": tr_data["column_names"],
        "test_type": tr_data["test_type"],
        "test_definition_id_runtime": tr_data["test_definition_id_runtime"],
    }

    df = fetch_df_from_db(query, params)
    df["test_date"] = pd.to_datetime(df["test_date"])
    df["threshold_value"] = pd.to_numeric(df["threshold_value"])
    df["result_measure"] = pd.to_numeric(df["result_measure"])

    return df
