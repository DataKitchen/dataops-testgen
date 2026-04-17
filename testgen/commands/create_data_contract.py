"""Bootstrap a brand-new data contract from an uploaded ODCS YAML file."""
from __future__ import annotations

import yaml

from testgen.commands.contract_management import create_contract
from testgen.commands.contract_versions import save_contract_version
from testgen.common.credentials import get_tg_schema
from testgen.common.database.database_service import fetch_dict_from_db


def validate_odcs_header(yaml_content: str) -> list[str]:
    """Return a list of validation error strings (empty list = valid)."""
    errors = []
    try:
        doc = yaml.safe_load(yaml_content)
    except yaml.YAMLError as exc:
        return [f"Not valid YAML: {exc}"]
    if not isinstance(doc, dict):
        return ["YAML must be a mapping at the top level"]
    if "apiVersion" not in doc:
        errors.append("Missing required field: apiVersion")
    kind = doc.get("kind")
    if kind != "DataContract":
        errors.append(f"Missing or incorrect field: kind must be 'DataContract' (got {kind!r})")
    return errors


def create_contract_from_yaml(table_group_id: str, yaml_content: str, label: str | None = None) -> int:
    """Validate YAML, create a new contract row, and save as version 0. Returns new version number."""
    errors = validate_odcs_header(yaml_content)
    if errors:
        raise ValueError("Invalid ODCS YAML:\n" + "\n".join(f"  - {e}" for e in errors))

    schema = get_tg_schema()
    tg_rows = fetch_dict_from_db(
        f"SELECT project_code, table_groups_name FROM {schema}.table_groups WHERE id = CAST(:tg_id AS uuid)",
        params={"tg_id": table_group_id},
    )
    if not tg_rows:
        raise ValueError(f"Table group {table_group_id} not found")

    project_code: str = tg_rows[0]["project_code"]
    # Use the YAML info.title if available, otherwise fall back to the table group name.
    try:
        doc = yaml.safe_load(yaml_content)
        contract_name: str = (doc.get("info") or {}).get("title") or tg_rows[0]["table_groups_name"]
    except Exception:
        contract_name = tg_rows[0]["table_groups_name"]

    ids = create_contract(contract_name, project_code, table_group_id)
    contract_id: str = ids["contract_id"]
    return save_contract_version(contract_id, table_group_id, yaml_content, label=label)
