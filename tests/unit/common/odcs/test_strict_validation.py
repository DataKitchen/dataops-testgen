"""One realistic contract, rendered through the product's own path, validated in strict mode.

The document is built the way the product builds one -- ``initialize_contract`` for the root
and the server block, ``add_table`` for each table's column descriptors, ``render_document``
for the quality rules -- then serialized, parsed back from YAML and validated against the
pinned ODCS schema. Validating the parsed text rather than the in-memory dict is what makes
serialization part of what this module proves: a value the schema accepts but
``yaml.safe_dump`` cannot represent (a leaked ``StrEnum`` member, for instance) fails here.

Real: ``initialize_contract``, ``build_server_block``, ``add_table``'s document merge,
``render_document``'s merge/attach/enum logic, ``project_rule`` and every shape it renders,
``slugify_term_id`` for each term's identity, ``serialize_document`` and ``validate_document``.
The test types and ``cat_test_conditions`` rows are the catalogue's own YAML, read off disk,
not invented stand-ins -- so the rendered ``query`` text is built from the measures the
execution engine runs.

Substituted: the database session everywhere, and with it ``render``'s six reading helpers
(``_terms_for_version``, ``_test_types_for``, ``_table_group_for``, ``_flavor_code_for``,
``_conditions_for``, ``_column_types_for``) and ``contract_service._profiled_columns`` --
the seam ``test_render.py`` already uses. Each is fed the data the query behind it would
return. Term generation (``_generate_for_tables``) is a no-op; the terms are constructed
directly instead.
"""

import copy
import functools
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import yaml

from testgen.common import contract_service
from testgen.common.enums import SuiteType
from testgen.common.flavors import SqlFlavorCode
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import TestDefinition, TestType, slugify_term_id
from testgen.common.odcs import render, serialize
from testgen.common.odcs.quality_rules import CatCondition, project_rule
from testgen.common.odcs.servers import ODCS_API_VERSION, ODCS_KIND, ServerType
from testgen.common.odcs.validation import validate_document
from testgen.common.read_file import get_template_files

pytestmark = pytest.mark.unit

_FLAVOR = SqlFlavorCode.POSTGRESQL
_SCHEMA = "public"

# (column_name, functional_data_type, column_type, db_data_type, logical_type) -- the
# DataColumnChars fields `add_table` and the renderer read.
_PROFILED_COLUMNS: dict[str, list[tuple[str, str, str, str, str]]] = {
    "orders": [
        ("order_id", "ID", "integer", "integer", "integer"),
        ("customer_id", "ID", "integer", "integer", "integer"),
        ("status", "Category", "varchar(20)", "character varying(20)", "string"),
        ("total_amount", "Amount", "numeric(12,2)", "numeric(12,2)", "number"),
        ("order_date", "Date", "date", "date", "date"),
    ],
    "customers": [
        ("customer_id", "ID", "integer", "integer", "integer"),
        ("email", "Email", "varchar(200)", "character varying(200)", "string"),
        ("city", "City", "varchar(80)", "character varying(80)", "string"),
        ("state", "State", "char(2)", "character(2)", "string"),
    ],
    "order_items": [
        ("order_id", "ID", "integer", "integer", "integer"),
        ("sku", "Code", "varchar(40)", "character varying(40)", "string"),
        ("quantity", "Measurement", "integer", "integer", "integer"),
    ],
}

# A rule a human wrote into the document by hand, before any term existed for it. The merge
# must carry it through untouched.
_RETAINED_RULE = {
    "id": "orders-refund-reconciliation",
    "type": "text",
    "description": "Refunds are reconciled against the finance ledger monthly.",
    "dimension": "accuracy",
    "customProperties": [{"property": "verifiable", "value": False, "vendor": "testgen"}],
}

_TEST_TYPE_COLUMNS = frozenset(column.name for column in TestType.__table__.columns)


@functools.cache
def _catalogue() -> dict[str, dict]:
    """Every test type in the YAML catalogue, keyed by its code."""
    entries = {}
    for path in get_template_files(r"test_types_.*\.yaml", sub_directory="dbsetup_test_types"):
        with path.open("r") as handle:
            entry = yaml.safe_load(handle)["test_types"]
        entries[entry["test_type"]] = entry
    assert entries, "parsed no test types from the test type catalogue"
    return entries


def _test_types(test_type_codes: set[str]) -> dict[str, TestType]:
    return {
        code: TestType(**{key: value for key, value in _catalogue()[code].items() if key in _TEST_TYPE_COLUMNS})
        for code in test_type_codes
    }


def _conditions(test_type_codes: set[str]) -> dict[str, CatCondition]:
    """The catalogue's own ``cat_test_conditions`` row for each code, for this flavor.

    A code with no row for the flavor -- a routing-deferred type has none at all -- is absent
    from the result, the same as the query behind ``_conditions_for`` would leave it.
    """
    resolved = {}
    for code in test_type_codes:
        for row in _catalogue()[code].get("cat_test_conditions") or []:
            if row["sql_flavor"] == _FLAVOR.value:
                resolved[code] = CatCondition(
                    measure=row["measure"],
                    test_operator=row["test_operator"],
                    test_condition=row["test_condition"],
                )
    return resolved


def _term(test_type: str, table_name: str, column_name: str | None, **overrides) -> TestDefinition:
    return TestDefinition(
        test_type=test_type,
        schema_name=_SCHEMA,
        table_name=table_name,
        column_name=column_name,
        contract_term_id=slugify_term_id(test_type, _SCHEMA, table_name, column_name),
        **overrides,
    )


def _terms() -> list[TestDefinition]:
    return [
        _term("Required", "orders", "total_amount", threshold_value="0"),
        _term("Row_Ct", "orders", None, threshold_value="1000"),
        _term("LOV_Match", "orders", "status", baseline_value="('NEW','SHIPPED','CANCELED')", threshold_value="0"),
        _term(
            "Avg_Shift", "orders", "SUM(total_amount)",
            threshold_value="0.5", baseline_avg="184.25", baseline_sd="32.75", baseline_value_ct="48000",
        ),
        _term("Recency", "orders", "order_date", threshold_value="2"),
        _term(
            "Condition_Flag", "orders", "Quantity Consistency",
            threshold_value="0", custom_query="total_amount < 0",
        ),
        _term(
            "Pattern_Match", "customers", "email",
            threshold_value="0",
            baseline_value=r"^[^@]+@[^@]+\.[a-z]{2,}$",
            custom_metadata={
                "odcs": {
                    "name": "Email addresses are well formed",
                    "businessImpact": "operational",
                    "dimension": "conformity",
                    "tags": ["pii", "contact"],
                    "authoritativeDefinitions": [
                        {"url": "https://wiki.example.com/email-policy", "type": "businessDefinition"},
                    ],
                    # Stored before the model's save-time validator existed: an ``id`` the
                    # StableId pattern refuses and a key the sealed CustomProperty schema
                    # does not allow.
                    "customProperties": [
                        {
                            "id": "email.policy",
                            "property": "reviewedBy",
                            "value": "data-governance",
                            "confidence": "high",
                        },
                    ],
                },
                "owner": "crm-team",
                "openIssues": 3,
            },
        ),
        # A genuinely multi-column "Categorical Column List": a single column would land on a
        # real declared property either way and hide where the rule is actually placed.
        _term(
            "Combo_Match", "customers", "city,state",
            match_schema_name="reference", match_table_name="us_regions", match_column_names="city,state",
        ),
        _term("CUSTOM", "order_items", "Unit price sanity", threshold_value="0", custom_query="unit_price > 0"),
    ]


def _draft() -> SuiteVersion:
    suite = MagicMock()
    suite.id = uuid4()
    suite.suite_type = SuiteType.CONTRACT
    suite.test_suite = "Orders contract"

    connection = MagicMock()
    connection.sql_flavor_code = _FLAVOR
    connection.connection_name = "analytics_pg"
    connection.project_host = "db.example.com"
    connection.project_port = "5432"
    connection.project_db = "analytics"
    connection.parameters = {}
    table_group = MagicMock()
    table_group.table_group_schema = _SCHEMA

    session = MagicMock()
    with (
        patch.object(SuiteVersion, "next_version_for", return_value=1),
        patch("testgen.common.contract_service.get_current_session", return_value=session),
    ):
        contract_service.initialize_contract(suite, table_group=table_group, connection=connection)
    version = session.add.call_args.args[0]

    for table_name, columns in _PROFILED_COLUMNS.items():
        profiled = [
            MagicMock(
                column_name=name, functional_data_type=functional, db_data_type=db_type, logical_type=logical
            )
            for name, functional, _column_type, db_type, logical in columns
        ]
        with (
            patch.object(contract_service, "resolve_write_target", return_value=(version.id, {})),
            patch.object(SuiteVersion, "get", return_value=version),
            patch.object(contract_service, "_profiled_columns", return_value=profiled),
            patch.object(contract_service, "_generate_for_tables"),
            patch("testgen.common.contract_service.get_current_session", return_value=MagicMock()),
        ):
            contract_service.add_table(suite, table_name)

    orders = next(table for table in version.metadata_document["schema"] if table["name"] == "orders")
    orders["quality"] = [copy.deepcopy(_RETAINED_RULE)]
    return version


def _rendered_contract(terms: list[TestDefinition]) -> dict:
    test_type_codes = {term.test_type for term in terms}
    column_types = {
        (table_name, name): column_type
        for table_name, columns in _PROFILED_COLUMNS.items()
        for name, _functional, column_type, _db_type, _logical in columns
    }
    with (
        patch.object(render, "_terms_for_version", return_value=terms),
        patch.object(render, "_test_types_for", return_value=_test_types(test_type_codes)),
        patch.object(render, "_table_group_for", return_value=TableGroup(id=uuid4(), connection_id=1)),
        patch.object(render, "_flavor_code_for", return_value=_FLAVOR.value),
        patch.object(render, "_conditions_for", return_value=_conditions(test_type_codes)),
        patch.object(render, "_column_types_for", return_value=column_types),
    ):
        return render.render_document(_draft())


def _round_tripped(document: dict) -> dict:
    return yaml.safe_load(serialize.serialize_document(document))


def _all_rules(document: dict) -> list[dict]:
    """Every rule in the document, table level and column level, flattened into one list."""
    rules = []
    for table in document["schema"]:
        rules.extend(table.get("quality", []))
        for prop in table.get("properties", []):
            rules.extend(prop.get("quality", []))
    return rules


def test_a_realistic_contract_validates_in_strict_mode():
    document = _round_tripped(_rendered_contract(_terms()))
    problems = validate_document(document)
    assert problems == [], f"the rendered contract does not validate: {problems}"


def test_the_rendered_contract_survives_the_yaml_round_trip():
    """Everything the schema does not police: an enum's shape, a boolean custom-property
    value, a nested authoritativeDefinitions entry, a multiline query's block scalar."""
    document = _rendered_contract(_terms())
    assert _round_tripped(document) == document


def test_every_term_is_rendered_exactly_once():
    terms = _terms()
    document = _round_tripped(_rendered_contract(terms))
    rules = _all_rules(document)

    assert len(rules) == len(terms) + 1
    assert {rule["id"] for rule in rules} == {term.contract_term_id for term in terms} | {_RETAINED_RULE["id"]}


def test_a_stray_key_inside_a_custom_property_is_rejected():
    """The negative control. ``CustomProperty`` is sealed with ``additionalProperties: false``,
    which is why ``_reconstruct_sealed_entries`` rebuilds a stored entry field by field instead
    of forwarding it -- so an unrecognised key inside one is both a shape the product could
    really emit and one the schema rejects. A validator that stopped checking below the root
    would leave every other test in this module green.
    """
    document = _round_tripped(_rendered_contract(_terms()))
    _all_rules(document)[0]["customProperties"][0]["units"] = "rows"

    assert validate_document(document)


def test_a_custom_rule_with_an_object_implementation_validates_in_strict_mode():
    """The standard's prose calls `implementation` a text block; the pinned schema accepts a
    string or an object. The object is what this renderer emits, and this is what confirms it.
    """
    term = _term("Avg_Shift", "orders", "total_amount", threshold_value="0.5", baseline_avg="142.7")
    test_type = TestType(
        test_type="Avg_Shift",
        dq_dimension="Consistency",
        test_name_short="Average Shift",
        test_name_long="Average Shift",
        default_parm_columns="baseline_avg,threshold_value",
        test_description="Tests for a shift in mean value.",
        except_message="Difference is over the threshold.",
        threshold_description="Standardized Difference Measure",
    )
    rule = project_rule(term, test_type, ServerType.POSTGRES)
    assert isinstance(rule["implementation"], dict)
    document = {
        "version": "1.0.0",
        "apiVersion": ODCS_API_VERSION,
        "kind": ODCS_KIND,
        "id": "contract-1",
        "schema": [{"name": "orders", "properties": [{"name": "total_amount", "quality": [rule]}]}],
    }
    problems = validate_document(_round_tripped(document))
    assert problems == [], f"the custom rule does not validate: {problems}"


def test_a_custom_rule_from_a_term_with_no_parameter_values_validates_in_strict_mode():
    term = _term("Table_Freshness", "orders", None)
    test_type = TestType(
        test_type="Table_Freshness",
        dq_dimension="Timeliness",
        test_name_short="Freshness",
        test_name_long="Freshness",
        default_parm_columns=None,
    )
    rule = project_rule(term, test_type, ServerType.POSTGRES)
    assert rule["implementation"] == {}
    document = {
        "version": "1.0.0",
        "apiVersion": ODCS_API_VERSION,
        "kind": ODCS_KIND,
        "id": "contract-1",
        "schema": [{"name": "orders", "quality": [rule]}],
    }
    problems = validate_document(_round_tripped(document))
    assert problems == [], f"the custom rule does not validate: {problems}"
