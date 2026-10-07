"""Serializes a contract document to YAML in a stable, canonical key order.

The order is read off the pinned ODCS JSON schema's own property order rather than invented,
so a document loaded and re-saved without edits produces identical text -- the metadata
editor and the version-comparison screen both depend on that stability. The serialiser
orders; it does not filter: a key the order does not name follows the named ones, in the
order it arrived in, rather than being dropped.
"""

from typing import Any

import yaml

# The root document's own property order (23 keys), from the pinned schema's top-level
# ``properties``.
ROOT_KEY_ORDER = [
    "version",
    "kind",
    "apiVersion",
    "id",
    "name",
    "tenant",
    "tags",
    "status",
    "servers",
    "dataProduct",
    "description",
    "domain",
    "context",
    "schema",
    "support",
    "price",
    "team",
    "roles",
    "slaDefaultElement",
    "slaProperties",
    "authoritativeDefinitions",
    "customProperties",
    "contractCreatedTs",
]

# ``$defs.SchemaObject`` -- a table node's own property order (7 keys). The schema does not
# list ``name`` here (it comes from the sibling ``SchemaElement`` definition), so a table
# node's ``name`` is placed first, ahead of this order, rather than folded into it.
SCHEMA_KEY_ORDER = [
    "logicalType",
    "physicalName",
    "dataGranularityDescription",
    "properties",
    "relationships",
    "quality",
    "context",
]

# ``$defs.SchemaBaseProperty`` -- a column node's own property order (21 keys). Same ``name``
# wrinkle as ``SCHEMA_KEY_ORDER``.
PROPERTY_KEY_ORDER = [
    "primaryKey",
    "primaryKeyPosition",
    "logicalType",
    "logicalTypeOptions",
    "physicalType",
    "physicalName",
    "required",
    "unique",
    "semanticType",
    "partitioned",
    "partitionKeyPosition",
    "classification",
    "encryptedName",
    "transformSourceObjects",
    "transformLogic",
    "transformDescription",
    "examples",
    "enum",
    "criticalDataElement",
    "relationships",
    "quality",
]

# ``$defs.DataQuality`` -- a rule's own property order (14 keys). Shape-specific keys
# (``metric``, ``arguments``, ``query``, the ``mustBe*`` operators, ...) are not part of this
# base definition and so are not named here; they follow the named keys in arrival order.
RULE_KEY_ORDER = [
    "id",
    "authoritativeDefinitions",
    "businessImpact",
    "customProperties",
    "description",
    "dimension",
    "method",
    "name",
    "schedule",
    "scheduler",
    "severity",
    "tags",
    "type",
    "unit",
]


class _OdcsDumper(yaml.SafeDumper):
    """``yaml.SafeDumper`` with one extra representer: multiline strings as block scalars.

    Subclassing (rather than dumping with plain ``yaml.safe_dump``) is what lets a multiline
    ``query`` render as ``|`` block style instead of a folded, escaped one-liner, while still
    raising ``RepresenterError`` on an unregistered type such as a ``StrEnum`` member -- the
    added representer is registered for ``str`` only, so it does not change how any other
    type, including a ``str`` subclass, is represented.
    """


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_OdcsDumper.add_representer(str, _represent_str)


def _reorder(mapping: dict[str, Any], order: list[str]) -> dict[str, Any]:
    """Return a copy of ``mapping`` with ``order``'s keys first, then the rest, unfiltered."""
    ordered = {key: mapping[key] for key in order if key in mapping}
    ordered.update((key, value) for key, value in mapping.items() if key not in ordered)
    return ordered


def _reorder_named(mapping: dict[str, Any], order: list[str]) -> dict[str, Any]:
    """Like ``_reorder``, with ``name`` placed first when present, ahead of ``order``.

    Used for a table or column node, whose ``name`` the schema declares on a sibling
    definition rather than on the node's own property list.
    """
    rest = _reorder({key: value for key, value in mapping.items() if key != "name"}, order)
    if "name" in mapping:
        return {"name": mapping["name"], **rest}
    return rest


def _reorder_rule(rule: dict[str, Any]) -> dict[str, Any]:
    return _reorder(rule, RULE_KEY_ORDER)


def _reorder_quality(quality: Any) -> Any:
    if not isinstance(quality, list):
        return quality
    return [_reorder_rule(rule) if isinstance(rule, dict) else rule for rule in quality]


def _reorder_property(prop: Any) -> Any:
    if not isinstance(prop, dict):
        return prop
    ordered = _reorder_named(prop, PROPERTY_KEY_ORDER)
    if "quality" in ordered:
        ordered["quality"] = _reorder_quality(ordered["quality"])
    return ordered


def _reorder_table(table: Any) -> Any:
    if not isinstance(table, dict):
        return table
    ordered = _reorder_named(table, SCHEMA_KEY_ORDER)
    if "properties" in ordered and isinstance(ordered["properties"], list):
        ordered["properties"] = [_reorder_property(prop) for prop in ordered["properties"]]
    if "quality" in ordered:
        ordered["quality"] = _reorder_quality(ordered["quality"])
    return ordered


def _reorder_root(document: dict[str, Any]) -> dict[str, Any]:
    ordered = _reorder(document, ROOT_KEY_ORDER)
    if "schema" in ordered and isinstance(ordered["schema"], list):
        ordered["schema"] = [_reorder_table(table) for table in ordered["schema"]]
    return ordered


def serialize_document(document: dict[str, Any]) -> str:
    """Render ``document`` as YAML with every known section in canonical schema order.

    Reorders the root document, each table in ``schema``, each table's columns in
    ``properties``, and every rule in a ``quality`` list -- recursively, so nested sections
    are ordered the same way the root is. A key none of those orders name follows the named
    ones, in the order it arrived in; nothing is dropped. Raises ``yaml.representer.
    RepresenterError`` if any value is not plain JSON-safe data (for example a leaked
    ``StrEnum`` member).
    """
    return yaml.dump(
        _reorder_root(document),
        Dumper=_OdcsDumper,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )
