"""What the Contract Metadata tab shows for a contract version, and how it saves the document and the tables."""

import logging
import re
from typing import Any

import yaml

from testgen.common import contract_service
from testgen.common.contract_document import catalog_table_names, declared_tables
from testgen.common.contract_rules import document_rules
from testgen.common.contract_service import CheckableRuleError, InvalidContractDocumentError, OwnedFieldError
from testgen.common.models import get_current_session
from testgen.common.models.suite_version import SuiteVersion, VersionState, format_version
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_definition import TestDefinition
from testgen.common.models.test_suite import TestSuite
from testgen.common.odcs.quality_rules import is_unverifiable_marker
from testgen.common.odcs.serialize import serialize_document

LOG = logging.getLogger("testgen")

DOCUMENT_INFO = (
    "Quality rules TestGen can check are on the Quality Rules tab. Rules it cannot check are kept here, "
    "marked unverifiable."
)
UNVERIFIABLE_RULE = "TestGen does not check this rule. It is kept in the contract and exported with it."
COMMENTS_NOT_KEPT = "Comments are not kept. The document is stored parsed, and saving discards them."

_PATH_STEP = re.compile(r"\.([^.\[]+)|\[(\d+)\]")


def metadata_tab(suite: TestSuite, version: SuiteVersion, editable: bool) -> dict[str, Any]:
    """The Contract Metadata tab's props for one version of a contract.

    :param version: the version on screen
    :param editable: whether the user may edit this version
    :return: the declared tables, each marked unverifiable when the table group does not hold it, the tables
        the picker offers, the metadata document as YAML text, and an info marker on each rule it marks
        unverifiable
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
            for rules in document_rules(document)
            for index, rule in enumerate(rules.rules)
            if isinstance(rule, dict) and any(map(is_unverifiable_marker, rule.get("customProperties") or []))
        ],
        "document_info": DOCUMENT_INFO,
        "comments_caption": COMMENTS_NOT_KEPT,
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
    message = f"Contract document saved to {format_version(version.version, VersionState.DRAFT)}."
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
    return {"success": True, "message": message, "problems": [], "markers": [], "version": version.version}


def _refused(message: str, problems: list[str] | None = None, markers: list[dict] | None = None) -> dict[str, Any]:
    return {"success": False, "message": message, "problems": problems or [], "markers": markers or []}


def _refused_with_problems(message: str, text: str, problems: list[str]) -> dict[str, Any]:
    return _refused(message, [problem.removeprefix("$.") for problem in problems], problem_markers(text, problems))


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
