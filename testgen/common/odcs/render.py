"""Renders one contract version's ODCS document from its stored metadata and its own terms.

The stored ``metadata_document`` carries the contract's authored shape -- servers, declared
tables and columns, and any rule a human or another process wrote directly. This module adds
each term on top of that shape: as a declaration on its column's property when one makes
exactly the term's claim (``property_declaration``), otherwise as one quality rule. A
declaration replaces a differing stored value for the same field, since the term is what
TestGen checks; every other stored field and rule is left as it was.
"""

import copy
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select, text

from testgen.common.flavors import FLAVOR_CODE_TO_FAMILY, SqlFlavorCode
from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.data_column import DataColumnChars
from testgen.common.models.suite_version import SuiteVersion
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import MANAGED_TEST_TYPES, TestDefinition, TestType
from testgen.common.models.test_suite import TestSuite
from testgen.common.odcs.quality_rules import (
    RULE_MAPPINGS,
    CatCondition,
    RuleScope,
    RuleShape,
    _groupby_columns,
    declaration_marker,
    is_declaration_marker,
    lov_values,
    project_rule,
    property_declaration,
    rule_scope,
    rule_shape,
)
from testgen.common.odcs.servers import (
    FLAVOR_TO_SERVER_TYPE,
    ODCS_API_VERSION,
    ODCS_KIND,
    UnmappedFlavorError,
)


class OrphanedTermError(ValueError):
    """Raised when a term names a table the document does not declare."""


# The schema's own top-level `required` array -- the root fundamentals a document must carry
# to validate at all. `initialize_contract` writes all of these on a contract's first draft,
# so filling them here is a no-op for a contract created by the current code; it only matters
# for a document that predates that, or one a caller hand-edited down to fewer keys.
def _fill_root_fundamentals(document: dict[str, Any], version: SuiteVersion) -> None:
    document.setdefault("kind", ODCS_KIND)
    document.setdefault("id", str(version.test_suite_id))
    document.setdefault("version", SuiteVersion.document_version(version.version))
    if "apiVersion" not in document:
        # Not a plain setdefault: the value must agree with the row the document is about to
        # be validated against, not with whatever the pinned schema constant happens to be.
        document["apiVersion"] = version.odcs_api_version or ODCS_API_VERSION


def _terms_for_version(version_id: UUID) -> list[TestDefinition]:
    """Every active term stored against this exact version -- the ones execution runs.

    Reads ``version_id`` directly rather than through ``TestDefinition.version_clause()``:
    that predicate resolves a *suite* to its draft-or-latest-frozen version, which is the
    wrong question here -- the version to render is named by the caller, not resolved from
    the suite, and a frozen version must render its own terms even while a newer draft exists.
    """
    query = (
        select(TestDefinition)
        .where(TestDefinition.version_id == version_id, TestDefinition.test_active == True)
        .order_by(
            TestDefinition.table_name,
            TestDefinition.column_name,
            TestDefinition.test_type,
            TestDefinition.contract_term_id,
            TestDefinition.id,
        )
    )
    return list(get_current_session().scalars(query))


def _test_types_for(test_type_codes: set[str]) -> dict[str, TestType]:
    if not test_type_codes:
        return {}
    rows = get_current_session().scalars(select(TestType).where(TestType.test_type.in_(test_type_codes)))
    return {row.test_type: row for row in rows}


def _table_group_for(version: SuiteVersion) -> TableGroup:
    suite = TestSuite.get(version.test_suite_id)
    return TableGroup.get(suite.table_groups_id)


def _flavor_code_for(table_group: TableGroup) -> str:
    """The sql_flavor_code of the connection backing this contract.

    Reached via the suite's table group rather than reversing the document's declared
    ``servers[0].type`` through ``FLAVOR_TO_SERVER_TYPE``: that reverse mapping is not unique
    (``sqlserver`` answers to both ``azure_mssql`` and ``mssql``), so it would silently pick
    one of two dialects for every sqlserver-backed contract. This path is unambiguous, and it
    is the same connection ``build_server_block`` read the declared server from, so the
    declared server and this code agree by construction.
    """
    connection = Connection.get(table_group.connection_id)
    return connection.sql_flavor_code


_CONDITIONS_QUERY = text(
    "SELECT test_type, measure, test_operator, test_condition "
    "FROM cat_test_conditions WHERE sql_flavor = :family AND test_type = ANY(:test_types)"
)


def _conditions_for(test_type_codes: set[str], family: str) -> dict[str, CatCondition]:
    """Resolved ``cat_test_conditions`` rows for the given SQL-shape test types and flavor family.

    ``cat_test_conditions`` has no ORM model and is not version-scoped -- it is reference data
    keyed by ``(test_type, sql_flavor)``, which stores families; it is the same join
    ``get_active_test_definitions.sql`` uses at execution time, binding
    ``connection.sql_flavor``. Fetched once for every SQL-shape test type a term needs, rather
    than once per term.
    """
    if not test_type_codes:
        return {}
    rows = get_current_session().execute(
        _CONDITIONS_QUERY, {"family": family, "test_types": sorted(test_type_codes)}
    ).mappings()
    return {
        row["test_type"]: CatCondition(
            measure=row["measure"], test_operator=row["test_operator"], test_condition=row["test_condition"]
        )
        for row in rows
    }


def _column_types_for(table_groups_id: UUID) -> dict[tuple[str, str], str | None]:
    """Profiled column types for the table group, keyed by ``(table_name, column_name)``."""
    rows = get_current_session().scalars(
        select(DataColumnChars).where(
            DataColumnChars.table_groups_id == table_groups_id,
            DataColumnChars.drop_date.is_(None),
        )
    )
    return {(row.table_name, row.column_name): row.column_type for row in rows}


_NON_IDENTIFIER_RUN = re.compile(r"[^A-Za-z0-9]+")


def _measure_property_name(subject: str) -> str:
    """A schema-legal property name derived from a raw measure subject, e.g. an aggregate
    expression that names no declared column."""
    return _NON_IDENTIFIER_RUN.sub("_", subject).strip("_")


def _synthesized_measure_property(subject: str) -> dict[str, Any]:
    return {
        "name": _measure_property_name(subject),
        "semanticType": "measure",
        "logicalType": "number",
        "transformLogic": subject,
    }


def _attach_to_property(
    table: dict[str, Any], subject: str, rule: dict[str, Any], synthesized_names: set[str]
) -> dict[str, Any]:
    """Attach ``rule`` to the property named ``subject``, synthesizing a measure property when
    none matches.

    Looked up twice: first by ``subject`` itself against every declared property, which matches
    a real column; then, only if that misses, by the slug ``_synthesized_measure_property``
    would name it, against ``synthesized_names`` alone -- the names this render call has itself
    minted, not every declared property. The slug step must not consult declared properties: a
    real column can be named exactly like some other subject's slug (or a slug can coincide
    with an unrelated declared column), and matching it there would attach an unrelated term's
    rule to a column it has nothing to do with. Looking up only by the raw subject, with no
    slug step at all, would miss the case this guards differently -- every term sharing an
    unmatched subject would mint its own duplicate property instead of reusing the first one.
    """
    properties = table.setdefault("properties", [])
    prop = next((candidate for candidate in properties if candidate.get("name") == subject), None)
    if prop is None:
        slug = _measure_property_name(subject)
        if slug in synthesized_names:
            prop = next((candidate for candidate in properties if candidate.get("name") == slug), None)
    if prop is None:
        prop = _synthesized_measure_property(subject)
        properties.append(prop)
        synthesized_names.add(prop["name"])
    prop.setdefault("quality", []).append(rule)
    return prop


def _property_name(term: TestDefinition, test_type: TestType) -> str:
    """The property a column-scoped ``term`` attaches to: its sole grouped column for a type whose
    scope follows the term, otherwise its ``column_name``."""
    mapping = RULE_MAPPINGS.get(test_type.test_type)
    if mapping is not None and mapping.scope_follows_term:
        return _groupby_columns(term)[0]
    return term.column_name


def _attach_rule(
    table: dict[str, Any], term: TestDefinition, test_type: TestType, rule: dict[str, Any], synthesized_names: set[str]
) -> dict[str, Any] | None:
    """Attach ``rule`` to the node its term's ``RuleScope`` names, creating a measure property
    if needed.

    Placement follows the term's ``RuleScope`` (``rule_scope``) and never whether the term
    happens to carry a ``column_name``. ``Dupe_Rows`` is the one type whose node depends on the
    term rather than the type: a grouping of one column attaches to that column, a grouping of
    several to the table, named by ``groupby_names`` and never by ``column_name``.
    ``column_name`` does not mean the same thing across types: on ``Condition_Flag`` and ``CUSTOM``
    it is a free-text label distinguishing
    one term from another on the same table, and on the ``Combo_Match`` family it is a
    comma-separated list of columns. Attaching by it would fabricate a property representing
    no real column, and for a routed ``TABLE``-scope type would also contradict the rule
    ``project_rule`` already built around ``{object}`` rather than ``{property}``.

    A ``COLUMN``-scope type attaches to the named property (see ``_attach_to_property``); the
    caller has already refused a term with no ``column_name`` to attach to before this is
    reached.

    ``synthesized_names`` collects the names this render call has itself minted for this table
    (see ``_attach_to_property``); the caller owns one set per table and passes the same one
    across every term on it.

    Returns the column-level property node the rule landed on, or ``None`` for a table-level
    rule, so a caller with more to say about that property (an enum) can find it without
    searching again. Never replaces or clears an existing ``quality`` list: only appends, so a
    rule already stored there survives.
    """
    if rule_scope(term, test_type) is RuleScope.TABLE:
        table.setdefault("quality", []).append(rule)
        return None
    return _attach_to_property(table, _property_name(term, test_type), rule, synthesized_names)


def _apply_enum(prop: dict[str, Any], term: TestDefinition) -> None:
    """Declare ``prop``'s ``enum`` from a ``LOV_Match`` term's baseline values, when absent.

    The schema's ``enum`` is an array of ``{"value": ...}`` objects, not a list of bare
    strings, so the stored literal is parsed into individual values first. Never overwrites an
    already-declared enum.
    """
    if "enum" in prop or not term.baseline_value:
        return
    values = lov_values(term.baseline_value)
    if values:
        prop["enum"] = [{"value": value} for value in values]


def _declared_property(
    table: dict[str, Any], term: TestDefinition, test_type: TestType, synthesized_names: set[str]
) -> dict[str, Any] | None:
    """The declared property a column-scoped ``term`` names, or ``None`` for a table-scoped term, a
    column the table does not declare, or a measure property this render synthesized."""
    if rule_scope(term, test_type) is RuleScope.TABLE:
        return None
    name = _property_name(term, test_type)
    if name in synthesized_names:
        return None
    return next((prop for prop in table.get("properties", []) if prop.get("name") == name), None)


def _declare(prop: dict[str, Any], declaration: dict[str, Any], claimed: dict[tuple[str, ...], Any]) -> bool:
    """Set ``declaration``'s fields on ``prop``, unless an earlier term in this render already set
    one of them to a different value. Returns whether it did.

    ``claimed`` maps each field path this render has set on ``prop`` to its value; the caller owns
    one per property. A field set only by the stored metadata is not claimed, so the term replaces it.
    """
    fields: list[tuple[tuple[str, ...], Any]] = []
    for key, value in declaration.items():
        if isinstance(value, dict):
            fields.extend(((key, sub_key), sub_value) for sub_key, sub_value in value.items())
        else:
            fields.append(((key,), value))
    if any(path in claimed and claimed[path] != value for path, value in fields):
        return False
    for path, value in fields:
        node = prop
        for key in path[:-1]:
            node = node.setdefault(key, {})
        node[path[-1]] = value
        claimed[path] = value
    return True


def _drop_declarations(document: dict[str, Any]) -> None:
    """Remove every ``testgenTerm`` entry the stored metadata carries, with the fields it declares.

    Those entries and fields came from terms, not from the metadata, and this render writes them
    again for each term that still declares them.
    """
    for table in document.get("schema", []):
        for prop in table.get("properties", []):
            entries = prop.get("customProperties") or []
            for entry in filter(is_declaration_marker, entries):
                paths = entry.get("value", {}).get("declares") if isinstance(entry.get("value"), dict) else None
                for path in paths if isinstance(paths, list) else []:
                    _drop_field(prop, str(path).split("."))
            if "customProperties" in prop:
                kept = [entry for entry in entries if not is_declaration_marker(entry)]
                if kept:
                    prop["customProperties"] = kept
                else:
                    del prop["customProperties"]


def _drop_field(node: dict[str, Any], path: list[str]) -> None:
    """Remove the field at ``path`` under ``node``, and a parent object it leaves empty."""
    if len(path) == 1:
        node.pop(path[0], None)
        return
    child = node.get(path[0])
    if isinstance(child, dict):
        _drop_field(child, path[1:])
        if not child:
            del node[path[0]]


def render_document(version: SuiteVersion) -> dict[str, Any]:
    """Merge ``version``'s stored metadata document with its terms, each rendered as a property
    declaration or a quality rule.

    A term renders as a declaration when ``property_declaration`` finds one on its declared
    column that no earlier term contradicts (``_declare``), otherwise as a quality rule.

    Returns a new document; the version's own ``metadata_document`` is never mutated. Raises
    ``OrphanedTermError`` if a term names a table the document does not declare, names a test
    type the catalogue no longer holds, or is column-scoped with no ``column_name`` to attach
    its rule to; ``UnmappedFlavorError`` if the backing connection's flavor maps to no ODCS
    server type; and ``ValueError`` (from ``rule_scope``) if a term's test type is excluded --
    none is ever silently dropped or placed somewhere its query would not mean what it claims.
    Terms of a managed test type are left out: they check what the document itself declares,
    so the document is already their assertion.
    """
    document = copy.deepcopy(version.metadata_document) if version.metadata_document else {}
    _fill_root_fundamentals(document, version)
    _drop_declarations(document)

    terms = [term for term in _terms_for_version(version.id) if term.test_type not in MANAGED_TEST_TYPES]
    if not terms:
        return document

    test_types = _test_types_for({term.test_type for term in terms})
    tables_by_name = {table["name"]: table for table in document.get("schema", [])}
    for term in terms:
        if term.table_name not in tables_by_name:
            raise OrphanedTermError(
                f"Term {term.contract_term_id!r} names table {term.table_name!r}, which this "
                "document does not declare."
            )
        if term.test_type not in test_types:
            # A frozen version's terms outlive the catalogue they were generated against.
            raise OrphanedTermError(
                f"Term {term.contract_term_id!r} names test type {term.test_type!r}, which the "
                "catalogue no longer holds."
            )
        if rule_scope(term, test_types[term.test_type]) is RuleScope.COLUMN and not _property_name(
            term, test_types[term.test_type]
        ):
            # project_rule decides the query's placeholder (`{property}` vs `{object}`) from
            # the mapping's own scope, independent of where this renderer attaches the result.
            # A column-scoped mapping with no column_name would still validate -- the schema
            # never inspects query text -- but land a `{property}`-carrying query on the table
            # node, where the spec defines no resolution for it. Refused rather than placed.
            raise OrphanedTermError(
                f"Term {term.contract_term_id!r} of test type {term.test_type!r} is "
                "column-scoped but carries no column_name to attach its rule to."
            )

    table_group = _table_group_for(version)
    flavor_code = _flavor_code_for(table_group)
    server_type = FLAVOR_TO_SERVER_TYPE.get(SqlFlavorCode(flavor_code))
    if server_type is None:
        raise UnmappedFlavorError(f"No server type for flavor {flavor_code!r}.")
    sql_test_types = {term.test_type for term in terms if rule_shape(term.test_type) is RuleShape.SQL}
    conditions = _conditions_for(sql_test_types, FLAVOR_CODE_TO_FAMILY[SqlFlavorCode(flavor_code)])
    column_types = _column_types_for(table_group.id)
    # One synthesized-name set per table: the slug fallback in `_attach_to_property` must only
    # ever reuse a property this render call minted itself, never a declared one that happens
    # to share its name.
    synthesized_by_table: dict[str, set[str]] = {}
    claimed_by_property: dict[tuple[str, str], dict[tuple[str, ...], Any]] = {}

    for term in terms:
        table = tables_by_name[term.table_name]
        test_type = test_types[term.test_type]
        synthesized_names = synthesized_by_table.setdefault(term.table_name, set())
        declared = _declared_property(table, term, test_type, synthesized_names)
        logical_type = declared.get("logicalType") if declared is not None else None
        if declared is not None and (declaration := property_declaration(term, logical_type)) is not None:
            claimed = claimed_by_property.setdefault((term.table_name, declared["name"]), {})
            if _declare(declared, declaration, claimed):
                declared.setdefault("customProperties", []).append(
                    declaration_marker(term, test_type, declaration)
                )
                continue

        rule = project_rule(
            term,
            test_type,
            server_type,
            condition=conditions.get(term.test_type),
            column_type=column_types.get((term.table_name, term.column_name)),
            logical_type=logical_type,
        )
        prop = _attach_rule(table, term, test_type, rule, synthesized_names)
        if prop is not None and term.test_type == "LOV_Match":
            _apply_enum(prop, term)

    return document
