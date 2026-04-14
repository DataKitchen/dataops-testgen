"""Bootstrap a brand-new data contract from an uploaded ODCS YAML file."""
from __future__ import annotations

import yaml

from testgen.commands.contract_versions import has_any_version, save_contract_version


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
    """Validate, check no prior version exists, save as version 0. Returns new version number."""
    errors = validate_odcs_header(yaml_content)
    if errors:
        raise ValueError("Invalid ODCS YAML:\n" + "\n".join(f"  - {e}" for e in errors))
    if has_any_version(table_group_id):
        raise ValueError(
            "A contract version already exists for this table group. "
            "Use the Upload tab to update the existing contract."
        )
    return save_contract_version(table_group_id, yaml_content, label)  # type: ignore[no-any-return]
