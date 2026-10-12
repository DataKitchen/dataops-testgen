"""Regression tests for the API's discriminated-union body models.

FastAPI collapses ``Annotated[Union[...], Discriminator("field")]`` when the
alias is used bare as a ``Body`` annotation -- the Discriminator is stripped
from the generated OpenAPI schema and Pydantic falls back to first-match union
routing. Wrapping the union in a ``RootModel`` keeps both. These tests pin the
observable behavior so a future refactor cannot regress silently.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from testgen.api.schemas import (
    DestinationCreate,
    DestinationUpdate,
    EmailDestinationCreate,
    EmailDestinationUpdate,
    MonitorRunRuleCreate,
    RuleCreate,
    ScoreDropRuleCreate,
    TestRunRuleCreate,
    WebhookDestinationCreate,
    WebhookDestinationUpdate,
)

pytestmark = pytest.mark.unit


# ─── Discriminator-driven variant selection at Pydantic validation ───


def test_destination_create_routes_email_variant_by_type():
    body = DestinationCreate.model_validate({"type": "email", "name": "Team", "recipients": ["a@x.co"]})
    assert isinstance(body.root, EmailDestinationCreate)
    assert body.root.recipients == ["a@x.co"]


def test_destination_create_routes_webhook_variant_by_type():
    body = DestinationCreate.model_validate({
        "type": "webhook",
        "name": "Prod",
        "webhook_type": "slack",
        "url": "https://hooks.slack.com/services/T/B/x",
    })
    assert isinstance(body.root, WebhookDestinationCreate)
    assert body.root.webhook_type == "slack"


def test_destination_create_rejects_unknown_type():
    with pytest.raises(ValidationError):
        DestinationCreate.model_validate({"type": "sms", "name": "x"})


def test_destination_update_routes_variant_by_type():
    body = DestinationUpdate.model_validate({"type": "email", "recipients": ["b@x.co"]})
    assert isinstance(body.root, EmailDestinationUpdate)

    body = DestinationUpdate.model_validate({"type": "webhook", "url": "https://api.example.com/hook"})
    assert isinstance(body.root, WebhookDestinationUpdate)


def test_rule_create_routes_variant_by_event():
    body = RuleCreate.model_validate({
        "event": "test_run",
        "addressing": {"kind": "inline", "recipients": ["a@x.co"]},
    })
    assert isinstance(body.root, TestRunRuleCreate)

    body = RuleCreate.model_validate({
        "event": "score_drop",
        "addressing": {"kind": "inline", "recipients": ["a@x.co"]},
        "score_definition_id": "00000000-0000-0000-0000-000000000001",
        "total_threshold": 80.0,
    })
    assert isinstance(body.root, ScoreDropRuleCreate)


def test_monitor_rule_create_does_not_accept_table_group_id():
    """The table group is derived from the suite, never supplied by the caller.

    ``TableGroup.monitor_test_suite_id`` is a 1:1 link, and the delivery path
    resolves the table group from the suite rather than reading the rule's stored
    column -- so accepting it would only create a way to disagree with the suite.
    """
    body = RuleCreate.model_validate({
        "event": "monitor_run",
        "addressing": {"kind": "inline", "recipients": ["a@x.co"]},
        "test_suite_id": "00000000-0000-0000-0000-000000000001",
    })
    assert isinstance(body.root, MonitorRunRuleCreate)
    assert not hasattr(body.root, "table_group_id")


def test_monitor_rule_create_rejects_a_supplied_table_group_id():
    """The table group is derived from the suite, so a supplied one is refused rather than dropped."""
    with pytest.raises(ValidationError):
        RuleCreate.model_validate({
            "event": "monitor_run",
            "addressing": {"kind": "inline", "recipients": ["a@x.co"]},
            "test_suite_id": "00000000-0000-0000-0000-000000000001",
            "table_group_id": "00000000-0000-0000-0000-000000000002",
        })


def test_a_misspelled_scope_key_is_rejected_rather_than_creating_a_project_wide_rule():
    """Omitting ``test_suite_id`` scopes a rule to the whole project, so a typo in its name must not
    read as an omission."""
    with pytest.raises(ValidationError):
        RuleCreate.model_validate({
            "event": "test_run",
            "addressing": {"kind": "inline", "recipients": ["a@x.co"]},
            "test_suite": "00000000-0000-0000-0000-000000000001",
        })


@pytest.mark.parametrize("addressing", [
    {"kind": "inline", "recipients": ["a@x.co"], "extra": 1},
    {"kind": "destination", "destination_id": "00000000-0000-0000-0000-000000000001", "extra": 1},
])
def test_addressing_rejects_unknown_keys(addressing):
    with pytest.raises(ValidationError):
        RuleCreate.model_validate({"event": "test_run", "addressing": addressing})


@pytest.mark.parametrize("payload", [
    {"type": "email", "name": "Team", "recipients": ["a@x.co"], "extra": 1},
    {"type": "webhook", "name": "Hook", "webhook_type": "generic", "url": "https://x.example/h", "extra": 1},
])
def test_destination_create_rejects_unknown_keys(payload):
    with pytest.raises(ValidationError):
        DestinationCreate.model_validate(payload)


# ─── Discriminator survives FastAPI body binding + OpenAPI schema ────


def _destination_app() -> FastAPI:
    """POST /dest that echoes back which variant FastAPI's binding produced.

    Declaring the endpoint with an explicit ``DestinationCreate`` annotation
    lets FastAPI resolve the type at decoration time. If the Discriminator were
    stripped, Pydantic would fall back to first-match union routing and the
    variant class name in the response would be wrong on ambiguous payloads.
    """
    app = FastAPI()

    @app.post("/dest")
    def _echo(body: DestinationCreate):
        return {"variant": body.root.__class__.__name__}

    return app


def _rule_app() -> FastAPI:
    app = FastAPI()

    @app.post("/rule")
    def _echo(body: RuleCreate):
        return {"variant": body.root.__class__.__name__}

    return app


def test_fastapi_binds_email_destination_via_discriminator():
    client = TestClient(_destination_app())
    resp = client.post("/dest", json={"type": "email", "name": "Team", "recipients": ["a@x.co"]})
    assert resp.status_code == 200
    assert resp.json() == {"variant": "EmailDestinationCreate"}


def test_fastapi_binds_webhook_destination_via_discriminator():
    client = TestClient(_destination_app())
    resp = client.post("/dest", json={
        "type": "webhook", "name": "Prod",
        "webhook_type": "slack",
        "url": "https://hooks.slack.com/services/T/B/x",
    })
    assert resp.status_code == 200
    assert resp.json() == {"variant": "WebhookDestinationCreate"}


def test_fastapi_binds_rule_create_via_discriminator():
    client = TestClient(_rule_app())
    resp = client.post("/rule", json={
        "event": "score_drop",
        "addressing": {"kind": "inline", "recipients": ["a@x.co"]},
        "score_definition_id": "00000000-0000-0000-0000-000000000001",
        "total_threshold": 80.0,
    })
    assert resp.status_code == 200
    assert resp.json() == {"variant": "ScoreDropRuleCreate"}


def test_openapi_schema_carries_discriminator_on_body():
    """The OpenAPI schema for a RootModel body carries the discriminator mapping.

    A bare ``Annotated[Union[...], Discriminator(...)]`` body loses it -- the
    schema becomes an unqualified ``anyOf`` and code generators cannot tell the
    variants apart at compile time.
    """
    app = _destination_app()
    schema = app.openapi()
    body_schema = schema["paths"]["/dest"]["post"]["requestBody"]["content"]["application/json"]["schema"]
    resolved = _resolve_ref(schema, body_schema)
    assert "discriminator" in resolved, "Discriminator dropped from OpenAPI schema"
    assert resolved["discriminator"].get("propertyName") == "type"


def _resolve_ref(schema: dict, node: dict) -> dict:
    ref = node.get("$ref")
    if not ref or not ref.startswith("#/"):
        return node
    parts = ref[2:].split("/")
    current: Any = schema  # ``Any`` because the walk descends through mixed dict/list nodes
    for part in parts:
        current = current[part]
    return current


def test_published_descriptions_carry_no_implementation_detail():
    """Schema docstrings become OpenAPI descriptions in the public API reference.

    The release pipeline regenerates and commits ``docs/api/openapi.json``, so an
    implementation note left in a docstring ships to consumers. Developer notes
    belong in ``#`` comments above the class.
    """
    import re

    from testgen.server import create_app

    banned = re.compile(r"FastAPI|RootModel|body\.root|Annotated|\bMCP\b|monitor_test_suite_id|Discriminator")
    schema = create_app("test").openapi()

    offenders = []
    for name, component in (schema.get("components", {}).get("schemas") or {}).items():
        if banned.search(component.get("description") or ""):
            offenders.append(f"components/{name}")
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            if method not in ("get", "post", "put", "patch", "delete"):
                continue
            for field in ("summary", "description"):
                if banned.search(operation.get(field) or ""):
                    offenders.append(f"{method.upper()} {path} [{field}]")

    assert not offenders, f"implementation detail published to the API reference: {offenders}"


def test_every_notification_endpoint_is_described():
    """An endpoint with no description publishes a blank entry in the reference."""
    from testgen.server import create_app

    schema = create_app("test").openapi()
    undescribed = [
        f"{method.upper()} {path}"
        for path, operations in schema["paths"].items()
        if "notification" in path
        for method, operation in operations.items()
        if method in ("get", "post", "put", "patch", "delete")
        and not (operation.get("description") or operation.get("summary"))
    ]

    assert not undescribed


def test_scope_check_compares_suite_type_by_value_not_identity():
    """``suite_type`` round-trips from the database as a plain string.

    Comparing it against the enum with ``is`` is False for every row, which would
    reject every suite and make rule creation impossible. The fixture uses the
    string the column actually yields rather than an enum member, because an
    enum-valued fixture passes either way and hides the defect.
    """
    from types import SimpleNamespace

    from fastapi import HTTPException

    from testgen.api import notifications as api
    from testgen.common.enums import SuiteType

    def scope(stored_value, requested):
        entity = SimpleNamespace(project_code="P", suite_type=stored_value, id="s1")
        entity_class = SimpleNamespace(get=staticmethod(lambda _id: entity))
        return api._require_scope(entity_class, "s1", "P", suite_type=requested)

    # stored as the raw string, exactly as SQLAlchemy returns it
    assert scope("regular", SuiteType.REGULAR) is not None
    assert scope("monitor", SuiteType.MONITOR) is not None

    with pytest.raises(HTTPException) as monitor_as_regular:
        scope("monitor", SuiteType.REGULAR)
    assert monitor_as_regular.value.status_code == 400

    with pytest.raises(HTTPException) as regular_as_monitor:
        scope("regular", SuiteType.MONITOR)
    assert regular_as_monitor.value.status_code == 400


def test_scope_check_ignores_suite_type_for_entities_without_one():
    """Table groups and score definitions carry no suite type and must pass."""
    from types import SimpleNamespace

    from testgen.api import notifications as api

    entity = SimpleNamespace(project_code="P", id="tg1")
    entity_class = SimpleNamespace(get=staticmethod(lambda _id: entity))

    assert api._require_scope(entity_class, "tg1", "P") is entity
