import glob
from pathlib import Path

import pytest

from testgen.common.test_type_upload import validate_test_type_yaml

# -- Reality baseline: every packaged file must validate --------------------


@pytest.mark.parametrize(
    "yaml_path",
    sorted(glob.glob("testgen/testgen/template/dbsetup_test_types/test_types_*.yaml")),
    ids=lambda p: Path(p).stem,
)
def test_packaged_yaml_validates(yaml_path: str) -> None:
    """The validator must accept every packaged file. It is the shipping baseline
    for what customer uploads have to look like."""
    result = validate_test_type_yaml(Path(yaml_path).read_text())
    assert result.ok, f"{Path(yaml_path).name}: {result.errors}"


# -- Parse + shape ----------------------------------------------------------


def test_unparseable_yaml() -> None:
    result = validate_test_type_yaml("::: not valid :::\n  {{")
    assert not result.ok
    assert result.errors == ["This file is not valid YAML."]


def test_missing_top_level_key() -> None:
    result = validate_test_type_yaml("something_else:\n  foo: bar\n")
    assert not result.ok
    assert result.errors == ["This file is not a test type definition."]


def test_top_level_value_not_dict() -> None:
    result = validate_test_type_yaml("test_types:\n  - one\n  - two\n")
    assert not result.ok
    assert result.errors == ["This file is not a test type definition."]


# -- Reserved and unknown fields --------------------------------------------


def _valid_parent_yaml(extra: str = "", *, include_cat_conditions: bool = True) -> str:
    """Minimal valid YAML fixture for the validator.

    ``run_type`` defaults to CAT, so the fixture includes a ``cat_test_conditions``
    entry to satisfy the run_type/child pairing rule. Tests that add their own
    ``cat_test_conditions`` (or override ``run_type``) pass ``include_cat_conditions=False``.
    """
    body = (
        "test_types:\n"
        "  id: '1900'\n"
        "  test_type: My_Test\n"
        "  test_name_short: Short\n"
        "  test_name_long: Long\n"
        "  test_description: Desc\n"
        "  run_type: CAT\n"
        "  test_scope: column\n"
        "  dq_dimension: Accuracy\n"
        "  default_severity: Fail\n"
        "  algorithm: Boundary check\n"
        "  active: Y\n"
    )
    if include_cat_conditions:
        body += (
            "  cat_test_conditions:\n"
            "    - sql_flavor: postgresql\n"
            "      test_condition: 1=1\n"
        )
    return body + extra


def test_reserved_uploaded_version_rejected() -> None:
    result = validate_test_type_yaml(_valid_parent_yaml("  uploaded_version: 5.85.0\n"))
    assert not result.ok
    assert "'uploaded_version' is not a recognized field." in result.errors


def test_unknown_parent_field_rejected() -> None:
    result = validate_test_type_yaml(_valid_parent_yaml("  bogus_field: X\n"))
    assert not result.ok
    assert "'bogus_field' is not a recognized field." in result.errors


# -- Required fields --------------------------------------------------------


def test_missing_required_field() -> None:
    yaml = (
        "test_types:\n"
        "  id: '1'\n"
        "  test_type: My_Test\n"
        "  test_name_short: S\n"
        "  test_name_long: L\n"
        "  test_description: D\n"
        "  run_type: CAT\n"
        "  test_scope: column\n"
        # dq_dimension deliberately absent
        "  default_severity: Fail\n"
        "  algorithm: Boundary check\n"
        "  active: Y\n"
    )
    result = validate_test_type_yaml(yaml)
    assert not result.ok
    assert "dq_dimension is required." in result.errors


def test_required_field_null_is_ok() -> None:
    """Packaged Schema_Drift has ``dq_dimension: null``; the presence-of-key check
    must accept explicit null values."""
    result = validate_test_type_yaml(_valid_parent_yaml("  dq_dimension: ~\n").replace(
        "  dq_dimension: Accuracy\n", ""
    ))
    assert result.ok, result.errors


# -- Enums ------------------------------------------------------------------


def test_bad_run_type() -> None:
    result = validate_test_type_yaml(_valid_parent_yaml().replace("run_type: CAT", "run_type: BOGUS"))
    assert not result.ok
    assert "run_type: 'BOGUS' is not a valid value." in result.errors


def test_bad_health_dimension() -> None:
    result = validate_test_type_yaml(_valid_parent_yaml("  health_dimension: Made Up\n"))
    assert not result.ok
    assert "health_dimension: 'Made Up' is not a valid value." in result.errors


def test_default_severity_accepts_log() -> None:
    """``default_severity`` allows Log in packaged YAMLs even though the Severity
    enum (scoped to user overrides) does not."""
    result = validate_test_type_yaml(_valid_parent_yaml().replace(
        "default_severity: Fail", "default_severity: Log"
    ))
    assert result.ok, result.errors


# -- Format / special rules --------------------------------------------------


def test_test_type_bad_characters() -> None:
    result = validate_test_type_yaml(_valid_parent_yaml().replace("test_type: My_Test", "test_type: My Test"))
    assert not result.ok
    assert any("test_type" in e and "must contain only letters" in e for e in result.errors)


def test_active_bad_value() -> None:
    result = validate_test_type_yaml(_valid_parent_yaml().replace("active: Y", "active: true"))
    assert not result.ok
    assert any("active" in e for e in result.errors)


def test_active_lowercase_rejected() -> None:
    result = validate_test_type_yaml(_valid_parent_yaml().replace("active: Y", "active: y"))
    assert not result.ok
    assert any("active" in e and "Y or N" in e for e in result.errors)


def test_unquoted_int_id_rejected() -> None:
    result = validate_test_type_yaml(_valid_parent_yaml().replace("id: '1900'", "id: 1900"))
    assert not result.ok
    assert any("id" in e and "quoted" in e for e in result.errors)


def test_unquoted_int_test_type_rejected() -> None:
    result = validate_test_type_yaml(_valid_parent_yaml().replace("test_type: My_Test", "test_type: 12345"))
    assert not result.ok
    assert any("test_type" in e and "quoted" in e for e in result.errors)


def test_statistical_technique_required_when_drift() -> None:
    result = validate_test_type_yaml(_valid_parent_yaml().replace(
        "algorithm: Boundary check", "algorithm: Statistical drift"
    ))
    assert not result.ok
    assert any("statistical_technique is required" in e for e in result.errors)


def test_default_parm_required_bad_token() -> None:
    result = validate_test_type_yaml(_valid_parent_yaml("  default_parm_required: Y,Z,N\n"))
    assert not result.ok
    assert any("default_parm_required" in e for e in result.errors)


def test_default_parm_required_ok() -> None:
    result = validate_test_type_yaml(_valid_parent_yaml("  default_parm_required: Y,N,Y\n"))
    assert result.ok, result.errors


# -- Child sections ---------------------------------------------------------


def test_child_unknown_field() -> None:
    result = validate_test_type_yaml(_valid_parent_yaml(
        "  cat_test_conditions:\n"
        "    - sql_flavor: postgresql\n"
        "      bogus_field: X\n",
        include_cat_conditions=False,
    ))
    assert not result.ok
    assert any("Test condition 1" in e and "bogus_field" in e for e in result.errors)


def test_child_bad_flavor() -> None:
    result = validate_test_type_yaml(_valid_parent_yaml(
        "  test_templates:\n"
        "    - sql_flavor: made_up_db\n"
        "      template: SELECT 1\n"
    ))
    assert not result.ok
    assert any("Test template 1" in e and "sql_flavor 'made_up_db'" in e for e in result.errors)


def test_child_missing_flavor() -> None:
    result = validate_test_type_yaml(_valid_parent_yaml(
        "  test_templates:\n"
        "    - template: SELECT 1\n"
    ))
    assert not result.ok
    assert any("Test template 1" in e and "sql_flavor is required" in e for e in result.errors)


def test_cat_run_type_requires_cat_test_conditions() -> None:
    result = validate_test_type_yaml(_valid_parent_yaml(include_cat_conditions=False))
    assert not result.ok
    assert any("run_type CAT requires" in e for e in result.errors)


def test_query_run_type_requires_test_templates() -> None:
    yaml = _valid_parent_yaml(include_cat_conditions=False).replace(
        "run_type: CAT", "run_type: QUERY",
    )
    result = validate_test_type_yaml(yaml)
    assert not result.ok
    assert any("run_type QUERY requires" in e for e in result.errors)


def test_target_data_lookups_missing_error_type() -> None:
    result = validate_test_type_yaml(_valid_parent_yaml(
        "  target_data_lookups:\n"
        "    - sql_flavor: postgresql\n"
        "      lookup_query: SELECT 1\n"
    ))
    assert not result.ok
    assert any("Target data lookup 1" in e and "error_type is required" in e for e in result.errors)


# -- generation_sets --------------------------------------------------------


def test_generation_sets_ok() -> None:
    result = validate_test_type_yaml(_valid_parent_yaml(
        "  generation_sets:\n"
        "    - Standard\n"
        "    - Monitor\n"
    ))
    assert result.ok, result.errors
    assert result.parsed.generation_sets == ["Standard", "Monitor"]


def test_generation_sets_bad_shape() -> None:
    result = validate_test_type_yaml(_valid_parent_yaml("  generation_sets: not_a_list\n"))
    assert not result.ok
    assert any("generation_sets" in e for e in result.errors)


def test_generation_sets_empty_entry() -> None:
    result = validate_test_type_yaml(_valid_parent_yaml(
        "  generation_sets:\n"
        "    - Standard\n"
        "    - ''\n"
    ))
    assert not result.ok
    assert any("non-empty strings" in e for e in result.errors)


# -- Parsed shape -----------------------------------------------------------


def test_parsed_shape_strips_container_keys() -> None:
    """The parent dict on ``ParsedTestType`` must not carry the child-section keys
    (they live on their own dataclass fields instead)."""
    result = validate_test_type_yaml(_valid_parent_yaml(
        "  cat_test_conditions:\n"
        "    - sql_flavor: postgresql\n"
        "      measure: X\n"
        "  generation_sets:\n"
        "    - Standard\n",
        include_cat_conditions=False,
    ))
    assert result.ok, result.errors
    assert "cat_test_conditions" not in result.parsed.parent
    assert "generation_sets" not in result.parsed.parent
    assert result.parsed.cat_test_conditions[0]["measure"] == "X"
    assert result.parsed.generation_sets == ["Standard"]
