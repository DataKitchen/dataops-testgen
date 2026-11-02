"""What the Contract Metadata tab shows for a contract version, and how it saves the document and the tables."""

import copy
import logging
import re
from collections import Counter
from collections.abc import Callable
from enum import StrEnum
from typing import Any

import yaml

from testgen.common import contract_service
from testgen.common.contract_document import catalog_table_names, declared_tables, physical_name
from testgen.common.contract_rules import document_rules
from testgen.common.contract_service import (
    CheckableRuleError,
    InvalidContractDocumentError,
    OwnedFieldError,
    SavedMetadata,
)
from testgen.common.models import get_current_session
from testgen.common.models.suite_version import SuiteVersion, VersionState, format_version
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_suite import TestSuite
from testgen.common.odcs.quality_rules import is_declaration_marker, is_unverifiable_marker
from testgen.common.odcs.render import OrphanedTermError, render_document
from testgen.common.odcs.serialize import serialize_document

LOG = logging.getLogger("testgen")

DOCUMENT_INFO = (
    "Quality rules TestGen can check are on the Quality Rules tab. Rules it cannot check are kept here, "
    "marked unverifiable."
)
UNVERIFIABLE_RULE = "TestGen does not check this rule. It is kept in the contract and exported with it."
COMMENTS_NOT_KEPT = "Comments are not kept. The document is stored parsed, and saving discards them."
SERVICE_LEVELS_INFO = "Service levels are declared in the contract. TestGen does not check them."
UNVERIFIABLE_RULES_INFO = "These rules are kept in the contract, but TestGen cannot check them. Edit them as YAML."

_SERVER_FIELD_LABELS = {"serviceName": "Service name", "endpointUrl": "Endpoint URL"}

_DESCRIPTION_FIELDS = ("purpose", "usage", "limitations")

_TABLE_FIELDS = (
    ("description", "Description"), ("dataGranularityDescription", "Granularity"), ("logicalType", "Logical type"),
)
_COLUMN_FIELDS = (
    ("physicalName", "Physical name"), ("logicalType", "Logical type"), ("physicalType", "Physical type"),
    ("primaryKey", "Primary key"), ("primaryKeyPosition", "Primary key position"), ("classification", "Classification"),
    ("criticalDataElement", "Critical data element"), ("description", "Description"), ("examples", "Examples"),
)
# Fields shown only when present, since ODCS gives them no default.
_PRESENT_ONLY_FIELDS = frozenset({"physicalName"})
# Fields ODCS defaults to false, shown as No when absent.
_FALSE_BY_DEFAULT = frozenset({"primaryKey", "criticalDataElement"})
_TABLE_FORM_FIELDS = ("description", "dataGranularityDescription", "logicalType")
_COLUMN_TEXT_FIELDS = ("logicalType", "physicalType", "classification", "description")
_COLUMN_FLAGS = ("primaryKey", "criticalDataElement")
_DECLARABLE = ("required", "unique")
_INTEGER = re.compile(r"-?\d+")
_DECLARATION_LABELS = {
    "required": "Required", "unique": "Unique",
    "logicalTypeOptions.minimum": "Minimum", "logicalTypeOptions.maximum": "Maximum",
    "logicalTypeOptions.minLength": "Minimum length", "logicalTypeOptions.maxLength": "Maximum length",
}


_MEMBER_FIELDS = ("username", "name", "role", "dateIn", "dateOut")
_NUMBER = re.compile(r"-?\d+(\.\d+)?")


class MetadataSection(StrEnum):
    OVERVIEW = "overview"
    TEAM = "team"
    ROLES = "roles"
    SUPPORT = "support"
    SERVICE_LEVELS = "service_levels"
    SCHEMA_TABLE = "schema_table"
    SCHEMA_COLUMN = "schema_column"


_SECTION_LABELS = {
    MetadataSection.OVERVIEW: "Overview",
    MetadataSection.TEAM: "Team",
    MetadataSection.ROLES: "Roles",
    MetadataSection.SUPPORT: "Support",
    MetadataSection.SERVICE_LEVELS: "Service Levels",
}

# Each list section: the document key it is stored under, and the fields its form edits.
_LIST_SECTIONS = {
    MetadataSection.ROLES: ("roles", ("role", "access", "description", "firstLevelApprovers", "secondLevelApprovers")),
    MetadataSection.SUPPORT: ("support", ("channel", "tool", "scope", "url", "description")),
    MetadataSection.SERVICE_LEVELS: ("slaProperties", ("property", "value", "unit", "element", "driver", "description")),
}

_PATH_STEP = re.compile(r"\.([^.\[]+)|\[(\d+)\]")


def metadata_tab(suite: TestSuite, version: SuiteVersion, editable: bool) -> dict[str, Any]:
    """The Contract Metadata tab's props for one version of a contract.

    :param version: the version on screen
    :param editable: whether the user may edit this version
    :return: the declared tables, each marked unverifiable when the table group does not hold it, the tables
        the picker offers, the metadata document as YAML text, an info marker on each rule it marks
        unverifiable, its server entries, the rules it marks unverifiable with where each sits, and its
        overview
    """
    document = version.metadata_document or {}
    declared = declared_tables(document)
    catalog = catalog_table_names(suite.table_groups_id)
    unverifiable = [name for name in declared if name not in set(catalog)]

    unverifiable_message = None
    if unverifiable:
        table_group = TableGroup.get(suite.table_groups_id)
        verb, pronoun = ("is", "it") if len(unverifiable) == 1 else ("are", "they")
        unverifiable_message = (
            f"{_series(unverifiable)} {verb} declared but {verb} not in the table group "
            f"{table_group.table_groups_name}, so {pronoun} cannot be verified."
        )

    unverifiable_rules = [
        (rules, index, rule)
        for rules in document_rules(document)
        for index, rule in enumerate(rules.rules)
        if isinstance(rule, dict) and any(map(is_unverifiable_marker, rule.get("customProperties") or []))
    ]
    text = serialize_document(document)
    root = yaml.compose(text)
    return {
        "editable": editable,
        "tables": [{"name": name, "unverifiable": name in unverifiable} for name in declared],
        "table_options": [*catalog, *unverifiable],
        "unverifiable_message": unverifiable_message,
        "document": text,
        "unverifiable_markers": [
            {"line": _line_for_path(root, f"{rules.path}[{index}]"), "message": UNVERIFIABLE_RULE, "severity": "info"}
            for rules, index, _ in unverifiable_rules
        ],
        "document_info": DOCUMENT_INFO,
        "comments_caption": COMMENTS_NOT_KEPT,
        "servers": [
            {
                "name": server.get("server"),
                "fields": [
                    {"label": _SERVER_FIELD_LABELS.get(key, key.capitalize()), "value": server[key]}
                    for key in sorted(server, key=lambda key: key != "type")
                    if key != "server" and not isinstance(server[key], dict | list)
                ],
            }
            for server in document.get("servers") or []
            if isinstance(server, dict)
        ],
        "unverifiable_rules": [
            {
                "location": rules.label,
                "type": rule.get("metric") if rule.get("type") == "library" else rule.get("type"),
                "description": rule.get("description") or rule.get("name"),
            }
            for rules, _, rule in unverifiable_rules
        ],
        "unverifiable_rules_info": UNVERIFIABLE_RULES_INFO,
        "overview": _overview(suite, version, document),
        "schema": _schema(suite, version, document),
        "link_params": {"test_suite_id": str(suite.id), "version": str(version.version)},
        "team": _team(document),
        **{
            section.value: _rows(document.get(key), fields)
            for section, (key, fields) in _LIST_SECTIONS.items()
        },
        "service_levels_info": SERVICE_LEVELS_INFO,
    }


def _schema(suite: TestSuite, version: SuiteVersion, document: dict[str, Any]) -> list[dict[str, Any]]:
    """Each declared table's descriptor and its columns', with the fields a quality rule declares on each column
    read from the rendered document, and the number of tests the Quality Rules tab lists for each."""
    try:
        rendered = render_document(version)
    except OrphanedTermError:
        LOG.warning(f"Contract {suite.id} version {version.version} could not be rendered for its Schema card")
        rendered = {}
    rendered_tables = {physical_name(table): table for table in rendered.get("schema") or [] if isinstance(table, dict)}

    definitions = TestDefinition.select_minimal_where(TestDefinition.test_suite_id == suite.id, version_id=version.id)
    counts = Counter((definition.table_name, definition.column_name) for definition in definitions)
    table_counts = Counter(definition.table_name for definition in definitions)
    test_names = {definition.test_type: definition.test_name_short for definition in definitions}

    tables = []
    for table in document.get("schema") or []:
        if not isinstance(table, dict):
            continue
        name = physical_name(table)
        rendered_columns = {
            physical_name(prop): prop
            for prop in rendered_tables.get(name, {}).get("properties") or []
            if isinstance(prop, dict)
        }
        columns = []
        for prop in table.get("properties") or []:
            if not isinstance(prop, dict):
                continue
            column = physical_name(prop)
            declared = _rule_declarations(rendered_columns.get(column, {}), test_names)
            owned = {field["path"] for field in declared}
            columns.append({
                "name": column,
                "label": prop.get("name"),
                "fields": [
                    *_fields(prop, _COLUMN_FIELDS),
                    *(
                        {"label": _DECLARATION_LABELS.get(path, path.removeprefix("logicalTypeOptions.")),
                         "value": _display(value)}
                        for path, value in _declarations(prop)
                        if path not in owned
                    ),
                ],
                "declared": [{key: value for key, value in field.items() if key != "path"} for field in declared],
                "rule_count": counts[(name, column)],
                "form": {
                    **{field: prop.get(field) for field in ("logicalType", "physicalType")},
                    **{flag: prop.get(flag) is True for flag in _COLUMN_FLAGS},
                    "primaryKeyPosition": _as_text(prop.get("primaryKeyPosition")) or "",
                    **{field: prop.get(field) for field in ("classification", "description")},
                    "examples": [_as_text(example) for example in prop.get("examples") or []],
                    **{key: prop.get(key) is True for key in _DECLARABLE if key not in owned},
                },
                "declarable": [key for key in _DECLARABLE if key not in owned],
            })
        tables.append({
            "name": name,
            "fields": _fields(table, _TABLE_FIELDS),
            "form": {field: table.get(field) for field in _TABLE_FORM_FIELDS},
            "columns": columns,
            "rule_count": table_counts[name],
        })
    return tables


def _fields(node: dict[str, Any], fields: tuple[tuple[str, str], ...]) -> list[dict[str, Any]]:
    return [
        {"label": label, "value": _display(node.get(key, False if key in _FALSE_BY_DEFAULT else None))}
        for key, label in fields
        if key not in _PRESENT_ONLY_FIELDS or node.get(key) is not None
    ]


def _declarations(prop: dict[str, Any]) -> list[tuple[str, Any]]:
    """A column's declared constraints, by their dotted paths: ``required``, ``unique`` and each
    ``logicalTypeOptions`` entry."""
    options = prop.get("logicalTypeOptions") if isinstance(prop.get("logicalTypeOptions"), dict) else {}
    return [
        *((key, prop[key]) for key in ("required", "unique") if key in prop),
        *((f"logicalTypeOptions.{key}", value) for key, value in options.items()),
    ]


def _rule_declarations(prop: dict[str, Any], test_names: dict[str, str]) -> list[dict[str, Any]]:
    values = dict(_declarations(prop))
    return [
        {
            "path": path,
            "label": _DECLARATION_LABELS.get(path, path),
            "value": _display(values.get(path)),
            "test_type": entry["value"]["testType"],
            "test_name": test_names.get(entry["value"]["testType"], entry["value"]["testType"]),
        }
        for entry in prop.get("customProperties") or []
        if is_declaration_marker(entry) and isinstance(entry.get("value"), dict)
        for path in entry["value"].get("declares") or []
    ]


def _display(value: Any) -> str | None:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, list):
        return " · ".join(str(item) for item in value)
    return _as_text(value)


def _team(document: dict[str, Any]) -> dict[str, Any]:
    team = document.get("team")
    deprecated_form = isinstance(team, list)
    if not isinstance(team, dict):
        team = {"members": team if deprecated_form else []}
    return {
        "name": team.get("name"),
        "description": team.get("description"),
        "deprecated_form": deprecated_form,
        "members": _rows(team.get("members"), _MEMBER_FIELDS),
    }


def _as_text(value: Any) -> str | None:
    return value if value is None or isinstance(value, str) else str(value)


def _rows(stored: Any, fields: tuple[str, ...]) -> list[dict[str, Any]]:
    """Each row of a stored list as its form shows it: the ``fields`` the form edits, and the ``index`` saving
    it maps back to."""
    return [
        {"index": index, **{field: _as_text(row.get(field)) for field in fields}}
        for index, row in enumerate(stored if isinstance(stored, list) else [])
        if isinstance(row, dict)
    ]


def _overview(suite: TestSuite, version: SuiteVersion, document: dict[str, Any]) -> dict[str, Any]:
    description = document.get("description") if isinstance(document.get("description"), dict) else {}
    return {
        "name": suite.test_suite,
        "status": contract_service.document_status(version),
        "domain": document.get("domain"),
        "tenant": document.get("tenant"),
        "tags": list(document.get("tags") or []),
        **{field: description.get(field) for field in _DESCRIPTION_FIELDS},
    }


def problem_markers(text: str, problems: list[str]) -> list[dict[str, Any]]:
    """Editor markers for ``problems``, each on the line of ``text`` its JSON path names.

    A path the text does not reach in full is marked at the deepest node it does reach, and a problem
    without a path on the first line.
    """
    try:
        root = yaml.compose(text)
    except yaml.YAMLError:
        root = None
    return [
        {"line": _line_for_path(root, problem.partition(": ")[0]) if problem.startswith("$") else 1,
         "message": problem.removeprefix("$.")}
        for problem in problems
    ]


def _line_for_path(root: yaml.Node | None, path: str) -> int:
    if root is None:
        return 1
    node: yaml.Node | None = root
    line = root.start_mark.line
    for key, index in _PATH_STEP.findall(path.removeprefix("$")):
        if key and isinstance(node, yaml.MappingNode):
            entry = next((entry for entry in node.value if entry[0].value == key), None)
            if entry is None:
                break
            line = entry[0].start_mark.line
            node = entry[1]
        elif index and isinstance(node, yaml.SequenceNode) and int(index) < len(node.value):
            node = node.value[int(index)]
            line = node.start_mark.line
        else:
            break
    return line + 1


def save_document(suite: TestSuite, text: str) -> dict[str, Any]:
    """Save the editor's text as the contract's metadata document, in its draft.

    :return: ``success``, the ``message`` to show, the ``problems`` that refused the save with ``markers``
        placing each on its line, and on success the draft ``version`` it was saved to
    """
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        problem = getattr(e, "problem", None) or str(e)
        return _refused(
            "No changes saved. The document is not valid YAML:",
            [problem],
            [{"line": mark.line + 1 if mark else 1, "message": problem}],
        )
    if not isinstance(document, dict):
        return _refused("No changes saved. The document must be a YAML mapping of fields, such as `name: orders`.")

    return _store(suite, document, "Contract document", text)


def save_section(suite: TestSuite, section: MetadataSection, values: dict[str, Any]) -> dict[str, Any]:
    """Save one section of the contract's metadata document from its card's form, in its draft.

    The section is replaced by ``values``; every other part of the stored document is kept as it is.

    :return: ``success``, the ``message`` to show, the ``problems`` that refused the save, and on success
        the draft ``version`` it was saved to
    """
    document = copy.deepcopy(_editable_version(suite).metadata_document or {})
    if section in (MetadataSection.SCHEMA_TABLE, MetadataSection.SCHEMA_COLUMN):
        return _save_schema_node(suite, document, section, values)
    if section == MetadataSection.OVERVIEW:
        _replace_overview(document, values)
    elif section == MetadataSection.TEAM:
        _replace_team(document, values)
    else:
        key, fields = _LIST_SECTIONS[section]
        if rows := _merge_rows(document.get(key), values.get("rows") or [], fields):
            document[key] = rows
        else:
            document.pop(key, None)
    return _store(suite, document, _SECTION_LABELS[section])


def _replace_overview(document: dict[str, Any], values: dict[str, Any]) -> None:
    for key in ("domain", "tenant"):
        _set_text(document, key, values.get(key))
    if tags := list(dict.fromkeys(tag.strip() for tag in values.get("tags") or [] if tag.strip())):
        document["tags"] = tags
    else:
        document.pop("tags", None)

    description = document.get("description") if isinstance(document.get("description"), dict) else {}
    for field in _DESCRIPTION_FIELDS:
        _set_text(description, field, values.get(field))
    if description:
        document["description"] = description
    else:
        document.pop("description", None)


def _save_schema_node(
    suite: TestSuite, document: dict[str, Any], section: MetadataSection, values: dict[str, Any]
) -> dict[str, Any]:
    table_name, column_name = values.get("table"), values.get("column")
    table = next(
        (table for table in document.get("schema") or [] if isinstance(table, dict) and physical_name(table) == table_name),
        None,
    )
    if section == MetadataSection.SCHEMA_TABLE:
        if table is None:
            return _refused(f"No changes saved. {table_name} is no longer in the contract.")
        for field in _TABLE_FORM_FIELDS:
            _set_text(table, field, values.get(field))
        return _store(suite, document, table_name)

    label = f"{table_name}.{column_name}"
    column = next(
        (
            prop for prop in (table or {}).get("properties") or []
            if isinstance(prop, dict) and physical_name(prop) == column_name
        ),
        None,
    )
    if column is None:
        return _refused(f"No changes saved. {label} is no longer in the contract.")

    for field in _COLUMN_TEXT_FIELDS:
        _set_text(column, field, values.get(field))
    for flag in _COLUMN_FLAGS:
        _set_flag(column, flag, values.get(flag))
    position = values.get("primaryKeyPosition") or ""
    if position != (_as_text(column.get("primaryKeyPosition")) or ""):
        _set_text(column, "primaryKeyPosition", position)
        if _INTEGER.fullmatch(column.get("primaryKeyPosition") or ""):
            column["primaryKeyPosition"] = int(column["primaryKeyPosition"])
    examples = [example.strip() for example in values.get("examples") or [] if example.strip()]
    if examples != [_as_text(example) for example in column.get("examples") or []]:
        if examples:
            column["examples"] = examples
        else:
            column.pop("examples", None)
    declared = [key for key in _DECLARABLE if key in values and values[key] and column.get(key) is not True]
    for key in _DECLARABLE:
        if key in values:
            _set_flag(column, key, values[key])

    def warnings(saved: SavedMetadata) -> list[str]:
        return [
            f"`{key}` is declared on {label}, but no quality rule checks it."
            for key in declared
            if f"{label}: {key}" in saved.unchecked_paths
        ]

    return _store(suite, document, label, warnings=warnings)


def _set_flag(container: dict[str, Any], key: str, value: Any) -> None:
    """Set ``key`` true, or remove it when ``value`` is false. A stored value the form shows unchanged is kept."""
    if bool(value) == (container.get(key) is True):
        return
    if value:
        container[key] = True
    else:
        container.pop(key, None)


def _replace_team(document: dict[str, Any], values: dict[str, Any]) -> None:
    stored = document.get("team")
    team = stored if isinstance(stored, dict) else {}
    stored_members = stored if isinstance(stored, list) else team.get("members")
    for key in ("name", "description"):
        _set_text(team, key, values.get(key))
    if members := _merge_rows(stored_members, values.get("members") or [], _MEMBER_FIELDS):
        team["members"] = members
    else:
        team.pop("members", None)
    if team:
        document["team"] = team
    else:
        document.pop("team", None)


def _merge_rows(stored: Any, rows: list[dict[str, Any]], fields: tuple[str, ...]) -> list[dict[str, Any]]:
    """The form's ``rows`` as a stored list, in the form's order.

    A row with the ``index`` of a stored row starts from it, so the fields the form does not edit are kept,
    and so is a field whose text the form did not change, in its stored type. A row without an ``index`` is
    new. A stored row the form left out is removed. A changed ``value`` that reads as a number is stored as one.
    """
    stored = stored if isinstance(stored, list) else []
    merged = []
    for row in rows:
        index = row.get("index")
        kept = stored[index] if isinstance(index, int) and 0 <= index < len(stored) else None
        item = dict(kept) if isinstance(kept, dict) else {}
        for field in fields:
            text = row.get(field)
            if field in item and text == _as_text(item[field]):
                continue
            _set_text(item, field, text)
            if field == "value" and _NUMBER.fullmatch(item.get(field) or ""):
                item[field] = float(item[field]) if "." in item[field] else int(item[field])
        merged.append(item)
    return merged


def _set_text(container: dict[str, Any], key: str, value: str | None) -> None:
    if value and value.strip():
        container[key] = value.strip()
    else:
        container.pop(key, None)


def _store(
    suite: TestSuite,
    document: dict[str, Any],
    label: str,
    text: str | None = None,
    warnings: Callable[[SavedMetadata], list[str]] | None = None,
) -> dict[str, Any]:
    try:
        saved = contract_service.save_metadata_document(suite, document)
    except CheckableRuleError as e:
        return _refused_with_problems(
            "No changes saved. TestGen checks these rules, so add each one as a test on the Quality Rules tab:",
            text, e.problems,
        )
    except OwnedFieldError as e:
        return _refused_with_problems("No changes saved.", text, e.problems)
    except InvalidContractDocumentError as e:
        return _refused_with_problems("No changes saved. The document would not be valid ODCS:", text, e.problems)
    except ValueError as e:
        return _refused(str(e))

    version = SuiteVersion.get(saved.version_id)
    message = f"{label} saved to {format_version(version.version, VersionState.DRAFT)}."
    if rules := len(saved.unverifiable_rules):
        message += (
            f" {rules} {'rule' if rules == 1 else 'rules'} no test type checks "
            f"{'was' if rules == 1 else 'were'} stored as unverifiable."
        )
    if problems := len(saved.problems):
        message += (
            f" The document still has {problems} {'problem' if problems == 1 else 'problems'}, and the draft "
            f"cannot be frozen until {'it is' if problems == 1 else 'they are'} fixed."
        )
    return {
        "success": True, "message": message, "problems": [], "markers": [], "version": version.version,
        "warnings": warnings(saved) if warnings else [],
    }


def _refused(message: str, problems: list[str] | None = None, markers: list[dict] | None = None) -> dict[str, Any]:
    return {"success": False, "message": message, "problems": problems or [], "markers": markers or []}


def _refused_with_problems(message: str, text: str | None, problems: list[str]) -> dict[str, Any]:
    markers = problem_markers(text, problems) if text is not None else []
    return _refused(message, [problem.removeprefix("$.") for problem in problems], markers)


def remove_tables_dialog(suite: TestSuite, selected: list[str]) -> dict[str, str] | None:
    """The Remove Tables confirmation for saving ``selected`` as the contract's tables, or None when the
    selection keeps every declared table."""
    current = _editable_version(suite)
    removed = [name for name in declared_tables(current.metadata_document) if name not in selected]
    if not removed:
        return None
    terms = contract_service.term_count(current.id, TestDefinition.table_name.in_(removed))
    one = len(removed) == 1
    descriptors = "Its descriptor" if one else "Their descriptors"
    deleted = f"{descriptors} and {'its' if one else 'their'} {_terms(terms)}" if terms else descriptors
    return {
        "question": f"Remove {_series(removed)} from the contract {suite.test_suite}?",
        "warning": f"{deleted} will be deleted from the draft.",
    }


def save_tables(suite: TestSuite, selected: list[str]) -> dict[str, Any]:
    """Make ``selected`` the contract's declared tables, in its draft: remove each table it drops with its
    terms, and declare and generate each table it adds.

    Each table added is its own unit of work. When one fails, the tables before it stay saved and the
    message names them before the failure.

    :return: ``success``, the ``message`` to show, and on success the draft ``version`` the change landed
        on, None when nothing changed
    """
    declared = declared_tables(_editable_version(suite).metadata_document)
    removed = [name for name in declared if name not in selected]
    added = [name for name in selected if name not in declared]
    if not removed and not added:
        return {"success": True, "message": "No tables changed.", "version": None}

    session = get_current_session()
    sentences = []
    generated, not_profiled, tests = [], [], 0
    failure = None
    step = f"removing {_series(removed)}"
    try:
        if removed:
            terms = sum(contract_service.remove_table(suite, name)["terms_removed"] for name in removed)
            removed_text = f"Removed {_series(removed)}"
            if terms:
                removed_text += f" and its {_terms(terms)}" if len(removed) == 1 else f", and their {_terms(terms)}"
            sentences.append(f"{removed_text}.")
        for name in added:
            # add_table commits partway through, so a rollback after its failure must not reach the steps before it.
            session.commit()
            step = f"adding {name}"
            generation = contract_service.add_table(suite, name)
            if name in generation.tables_not_profiled:
                not_profiled.append(name)
            else:
                generated.append(name)
                tests += generation.term_count
    except ValueError as e:
        session.rollback()
        failure = str(e)
    except Exception:
        LOG.exception("Could not save a contract's declared tables")
        session.rollback()
        failure = f"Something went wrong while {step}."

    if generated:
        holds = "holds" if len(generated) == 1 else "hold"
        sentences.append(f"{_series(generated)} now {holds} {tests} {'quality test' if tests == 1 else 'quality tests'}.")
    if not_profiled:
        has = "has" if len(not_profiled) == 1 else "have"
        sentences.append(f"No quality tests were generated for {_series(not_profiled)}, which {has} not been profiled.")
    if failure:
        return {"success": False, "message": " ".join([*sentences, failure])}
    draft = SuiteVersion.draft_for(suite.id)
    return {"success": True, "message": " ".join(sentences), "version": draft.version if draft else None}


def _editable_version(suite: TestSuite) -> SuiteVersion:
    version = SuiteVersion.draft_for(suite.id) or SuiteVersion.in_force_for(suite.id)
    if version is None:
        raise ValueError("A contract has at least one version.")
    return version


def _terms(count: int) -> str:
    return f"{count} {'term' if count == 1 else 'terms'}"


def _series(names: list[str]) -> str:
    if len(names) <= 2:
        return " and ".join(names)
    return f"{', '.join(names[:-1])}, and {names[-1]}"
