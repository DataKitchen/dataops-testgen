__all__ = ["export_metadata_records_to_yaml", "import_metadata_records_from_yaml"]

import logging
from importlib.resources import as_file
from os import mkdir
from os.path import isdir
from os.path import sep as path_seperator

from yaml import SafeDumper, safe_dump, safe_load

from testgen.common.database.database_service import execute_db_queries, fetch_from_db_threaded
from testgen.common.read_file import get_template_files

LOG = logging.getLogger("testgen")


TEST_TYPES_TEMPLATE_FOLDER = "dbsetup_test_types"
TEST_TYPES_PARENT_TABLE = "test_types"
TEST_TYPES_PARENT_KEY = "test_type"
TEST_TYPES_CHILD_TABLES = ["cat_test_conditions", "target_data_lookups", "test_templates"]

# Fallback PKs
TEST_TYPES_DEFAULT_PK = {
    "target_data_lookups": ["test_id", "sql_flavor", "error_type"],
    "test_templates": ["test_type", "sql_flavor"],
    "cat_test_conditions": ["test_type", "sql_flavor"],
}

# child_col → parent_col for filtering
TEST_TYPES_PARENT_CHILD_COLUMN_MAP = {
    "cat_test_conditions": {
        "test_type": "test_type",
    },
    "target_data_lookups": {
        "test_type": "test_type",
        "test_id":   "id",
    },
    "test_templates": {
        "test_type": "test_type",
    },
}

# Columns to treat as literal blocks (embedded special chars)
TEST_TYPES_LITERAL_FIELDS = {
    "test_types": [
        "test_description",
        "except_message",
        "measure_uom_description",
        "selection_criteria",
        "dq_score_prevalence_formula",
        "column_name_prompt",
        "column_name_help",
        "default_parm_values",
        "default_parm_prompts",
        "default_parm_help",
        "threshold_description",
        "usage_notes",
    ],
    "cat_test_conditions": [
        "measure",
        "test_condition",
    ],
    "target_data_lookups": [
        "lookup_query",
    ],
}


ANOMALY_TYPES_TEMPLATE_FOLDER = "dbsetup_anomaly_types"
ANOMALY_TYPES_PARENT_TABLE = "profile_anomaly_types"
ANOMALY_TYPES_PARENT_KEY = "anomaly_type"
ANOMALY_TYPES_CHILD_TABLES = ["target_data_lookups"]

# Fallback PKs
ANOMALY_TYPES_DEFAULT_PK = {
    "target_data_lookups": ["test_id", "sql_flavor", "error_type"],
}

# child_col → parent_col for filtering
ANOMALY_TYPES_PARENT_CHILD_COLUMN_MAP = {
    "target_data_lookups": {
        "test_type": "anomaly_type",
        "test_id":   "id",
    },
}

# Columns to treat as literal blocks (embedded special chars)
ANOMALY_TYPES_LITERAL_FIELDS = {
    "profile_anomaly_types": [
        "anomaly_description",
        "anomaly_criteria",
        "detail_expression",
        "suggested_action",
        "dq_score_prevalence_formula",
    ],
    "target_data_lookups": [
        "lookup_query",
    ],
}



class LiteralString(str):
    pass

def _add_literal_representer():
    def _literal_representer(dumper, data):
        # emit this string with | style
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    SafeDumper.add_representer(LiteralString, _literal_representer)


def _process_yaml_for_import(params_mapping: dict, data:dict, parent_table:str, parent_key:str, child_tables:list[str], default_pk:dict[str, list[str]], parent_child_column_map:dict[str, dict[str,str]]):
    queries = []
    parent = data.get(parent_table)
    if not isinstance(parent, dict):
        raise TypeError(f"YAML key '{parent_table}' must be a dict")

    for table_name in child_tables:
        records = parent.pop(table_name, [])
        if not isinstance(records, list):
            raise TypeError(f"YAML key '{table_name}' under parent must be a list")

        mapping = parent_child_column_map.get(table_name, {})

        pk_cols = default_pk.get(table_name) or [parent_key]

        for record in records:
            for child_col, parent_col in mapping.items():
                record.setdefault(child_col, parent.get(parent_col))

            columns = list(record.keys())

            insert_cols = ", ".join(columns)
            insert_vals = ", ".join(f":{c}" for c in columns)
            update_stmt = ", ".join(f"{c}=EXCLUDED.{c}" for c in columns if c not in pk_cols)
            bound_values = {c: record[c] for c in columns}

            sql = f"""
            INSERT INTO {params_mapping["SCHEMA_NAME"]}.{table_name} ({insert_cols})
            VALUES ({insert_vals})
            ON CONFLICT ({', '.join(pk_cols)}) DO UPDATE
            SET {update_stmt};
            """
            queries.append((sql, bound_values))

    columns = list(parent.keys())

    insert_cols = ", ".join(columns)
    insert_vals = ", ".join(f":{c}" for c in columns)
    update_stmt = ", ".join(f"{c}=EXCLUDED.{c}" for c in columns if c != parent_key)
    bound_values = {c: parent[c] for c in columns}
    parent_insert_query = f"""
    INSERT INTO {params_mapping["SCHEMA_NAME"]}.{parent_table} ({insert_cols})
    VALUES ({insert_vals})
    ON CONFLICT ({parent_key}) DO UPDATE
    SET {update_stmt};
    """

    queries = [(parent_insert_query, bound_values), *queries]

    execute_db_queries(
        queries,
        user_override=params_mapping["TESTGEN_ADMIN_USER"],
        password_override=params_mapping["TESTGEN_ADMIN_PASSWORD"],
        user_type="schema_admin",
    )
    return

def import_metadata_records_from_yaml(params_mapping: dict) -> None:
    files = sorted(get_template_files(mask="^.*ya?ml$", sub_directory=TEST_TYPES_TEMPLATE_FOLDER), key=lambda key: str(key))
    for yaml_file in files:
        with as_file(yaml_file) as f:
            with f.open("r") as file:
                data = safe_load(file)
                _process_yaml_for_import(
                    params_mapping,
                    data,
                    TEST_TYPES_PARENT_TABLE,
                    TEST_TYPES_PARENT_KEY,
                    TEST_TYPES_CHILD_TABLES,
                    TEST_TYPES_DEFAULT_PK,
                    TEST_TYPES_PARENT_CHILD_COLUMN_MAP,
                )
    files = sorted(get_template_files(mask="^.*ya?ml$", sub_directory=ANOMALY_TYPES_TEMPLATE_FOLDER), key=lambda key: str(key))
    for yaml_file in files:
        with as_file(yaml_file) as f:
            with f.open("r") as file:
                LOG.info(f"Importing {yaml_file}")
                data = safe_load(file)
                _process_yaml_for_import(
                    params_mapping,
                    data,
                    ANOMALY_TYPES_PARENT_TABLE,
                    ANOMALY_TYPES_PARENT_KEY,
                    ANOMALY_TYPES_CHILD_TABLES,
                    ANOMALY_TYPES_DEFAULT_PK,
                    ANOMALY_TYPES_PARENT_CHILD_COLUMN_MAP,
                )
    return

def _wrap_literal(table_name: str, recs: list[dict], literal_fields: dict[str, list[str]]):
    for rec in recs:
        for fld in literal_fields.get(table_name, []):
            val = rec.get(fld)
            if isinstance(val, str) and val != "":
                rec[fld] = LiteralString(val)

def _process_records_for_export(params_mapping: dict, export_path:str, parent_table:str, parent_key:str, child_tables:list[str], default_pk:dict[str, list[str]], parent_child_column_map:dict[str, dict[str,str]], literal_fields:dict[str, list[str]]) -> None:
    if not isdir(export_path):
        mkdir(export_path)
    fetch_parent_query = f"""
    SELECT *
    FROM {params_mapping["SCHEMA_NAME"]}.{parent_table};
    """
    parent_records, parent_columns, _ = fetch_from_db_threaded(
        [(fetch_parent_query, None)],
    )
    for parent_record in parent_records:
        parent_record_dict = dict(zip(parent_columns, parent_record, strict=False))
        for child_name in child_tables:
            child_key = next(key for key, value in parent_child_column_map[child_name].items() if value==parent_key)
            fetch_children_query = f"""
            SELECT * FROM {params_mapping["SCHEMA_NAME"]}.{child_name}
            WHERE {child_key} = '{parent_record_dict[parent_key]}'
            ORDER BY {", ".join(default_pk[child_name])};
            """
            child_records, child_columns, _ = fetch_from_db_threaded(
                [(fetch_children_query, None)],
            )
            child_records_dict = []
            for child_record in child_records:
                child_records_dict.append(dict(zip(child_columns, child_record, strict=False)))
            _wrap_literal(child_name, child_records_dict, literal_fields)
            parent_record_dict[child_name] = child_records_dict

        _wrap_literal(parent_table, [parent_record_dict], literal_fields)
        payload = {parent_table: parent_record_dict}
        out_file = f"{export_path}{path_seperator}{parent_table}_{parent_record_dict[parent_key].replace(' ','_')}.yaml"
        LOG.info(f"Exporting {out_file}")
        with open(out_file, "w") as f:
            safe_dump(payload, f, sort_keys=False)


def export_metadata_records_to_yaml(params_mapping: dict, templates_path: str) -> None:
    _add_literal_representer()
    _process_records_for_export(
        params_mapping,
        f"{templates_path}{path_seperator}{TEST_TYPES_TEMPLATE_FOLDER}",
        TEST_TYPES_PARENT_TABLE,
        TEST_TYPES_PARENT_KEY,
        TEST_TYPES_CHILD_TABLES,
        TEST_TYPES_DEFAULT_PK,
        TEST_TYPES_PARENT_CHILD_COLUMN_MAP,
        TEST_TYPES_LITERAL_FIELDS,
    )
    _process_records_for_export(
        params_mapping,
        f"{templates_path}{path_seperator}{ANOMALY_TYPES_TEMPLATE_FOLDER}",
        ANOMALY_TYPES_PARENT_TABLE,
        ANOMALY_TYPES_PARENT_KEY,
        ANOMALY_TYPES_CHILD_TABLES,
        ANOMALY_TYPES_DEFAULT_PK,
        ANOMALY_TYPES_PARENT_CHILD_COLUMN_MAP,
        ANOMALY_TYPES_LITERAL_FIELDS,
    )
    return
