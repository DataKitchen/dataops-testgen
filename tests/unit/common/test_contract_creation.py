from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from testgen.commands.test_generation import ContractGenerationResult
from testgen.common import contract_creation as MODULE
from testgen.common.contract_import import AppliedImport
from testgen.common.enums import SuiteType
from testgen.common.flavors import SqlFlavorCode
from testgen.common.models.test_suite import TestSuite

pytestmark = pytest.mark.unit

VERSION_ID = uuid4()


def _suite():
    return TestSuite(id=uuid4(), project_code="demo", test_suite="orders", suite_type=SuiteType.CONTRACT.value)


@pytest.fixture
def calls():
    order: list[str] = []
    session = MagicMock()
    session.add.side_effect = lambda _: order.append("add")
    session.flush.side_effect = lambda: order.append("flush")
    session.commit.side_effect = lambda: order.append("commit")
    session.rollback.side_effect = lambda: order.append("rollback")
    initialized = MagicMock(custom_server_reason=None)
    with (
        patch.object(MODULE, "get_current_session", return_value=session),
        patch.object(
            MODULE, "initialize_contract", side_effect=lambda *_a, **_k: order.append("initialize") or initialized
        ),
        patch.object(MODULE, "run_contract_generation") as generate,
        patch.object(MODULE, "apply_import") as apply,
    ):
        generate.side_effect = lambda *_a, **_k: order.append("generate") or ContractGenerationResult(
            term_count=7, tables_declared=["orders"], tables_not_in_catalog=[], tables_not_profiled=[],
        )
        apply.side_effect = lambda *_a, **_k: order.append("apply") or AppliedImport(
            version_id=VERSION_ID, conformance_failed=False
        )
        yield SimpleNamespace(order=order, generate=generate, apply=apply, initialized=initialized)


def test_create_contract_adds_initializes_then_generates_the_tables(calls):
    suite = _suite()

    created = MODULE.create_contract(suite, MagicMock(), MagicMock(), ["orders", "lines", "orders"])

    assert calls.order == ["add", "flush", "initialize", "commit", "generate"]
    calls.generate.assert_called_once_with(suite.id, table_names=["orders", "lines"])
    assert created.generation.term_count == 7
    assert created.generation_failed is False


def test_create_contract_without_tables_only_initializes(calls):
    created = MODULE.create_contract(_suite(), MagicMock(), MagicMock(), None)

    assert calls.order == ["add", "flush", "initialize"]
    assert created.generation is None
    assert created.generation_failed is False


def test_a_generation_failure_rolls_back_to_the_committed_contract_and_reports_it(calls):
    def fail(*_a, **_k):
        calls.order.append("generate")
        raise RuntimeError("boom")

    calls.generate.side_effect = fail

    created = MODULE.create_contract(_suite(), MagicMock(), MagicMock(), ["orders"])

    assert calls.order == ["add", "flush", "initialize", "commit", "generate", "rollback"]
    assert created.generation is None
    assert created.generation_failed is True


def test_create_contract_passes_the_custom_server_reason(calls):
    calls.initialized.custom_server_reason = reason = MagicMock()

    assert MODULE.create_contract(_suite(), MagicMock(), MagicMock(), None).custom_server_reason is reason


def test_create_contract_from_import_adds_initializes_then_applies(calls):
    suite, table_group = _suite(), MagicMock()
    connection = MagicMock(sql_flavor_code="postgresql")
    plan = MagicMock()

    created = MODULE.create_contract_from_import(suite, table_group, connection, plan)

    assert calls.order == ["add", "flush", "initialize", "apply"]
    calls.apply.assert_called_once_with(plan, suite, table_group, SqlFlavorCode.POSTGRESQL)
    assert (created.version_id, created.conformance_failed) == (VERSION_ID, False)


def test_create_contract_from_import_passes_a_conformance_failure(calls):
    calls.apply.side_effect = lambda *_a, **_k: AppliedImport(version_id=VERSION_ID, conformance_failed=True)

    created = MODULE.create_contract_from_import(
        _suite(), MagicMock(), MagicMock(sql_flavor_code="postgresql"), MagicMock()
    )

    assert created.conformance_failed
