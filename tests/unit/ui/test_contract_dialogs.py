from unittest.mock import patch
from uuid import uuid4

import pytest

from testgen.common.models.test_suite import TestSuite
from testgen.ui.views.dialogs import contract_dialogs

pytestmark = pytest.mark.unit


def _follow(query_params: dict, editable: int | None):
    with (
        patch.object(contract_dialogs.st, "query_params", query_params),
        patch.object(contract_dialogs, "editable_version_number", return_value=editable),
        patch.object(contract_dialogs, "Router") as router,
    ):
        contract_dialogs.follow_editable_version(TestSuite(id=uuid4()))
    return router.return_value.set_query_params


def test_a_write_that_opened_a_draft_moves_the_page_to_it():
    set_params = _follow({"version": "3"}, editable=4)

    set_params.assert_called_once_with({"version": "4"})


def test_a_page_already_on_the_editable_version_stays():
    _follow({"version": "4"}, editable=4).assert_not_called()


def test_a_page_without_a_version_already_follows_the_editable_one():
    _follow({}, editable=4).assert_not_called()


def _contract_data(tab: str | None):
    page = contract_dialogs.ContractPage(
        summary={"selected_version": 3}, selected_version_id=uuid4(), read_version_id=None, editable=True,
        run_option={}, run_disabled_reason=None,
    )
    with (
        patch.object(contract_dialogs.st, "session_state", {}),
        patch.object(contract_dialogs.SuiteVersion, "get"),
        patch.object(contract_dialogs.TableGroup, "get"),
        patch.object(contract_dialogs.contract_metadata_service, "metadata_tab", return_value={"schema": []}) as tab_props,
    ):
        data, _ = contract_dialogs.contract_props(TestSuite(id=uuid4()), page, "DEFAULT", tab)
    return data, tab_props


def test_the_metadata_tab_is_built_when_it_is_open():
    data, tab_props = _contract_data("metadata")

    tab_props.assert_called_once()
    assert data["metadata"]["schema"] == []


@pytest.mark.parametrize("tab", ["rules", None, "unknown"])
def test_the_metadata_tab_is_not_built_while_another_tab_is_open(tab):
    data, tab_props = _contract_data(tab)

    tab_props.assert_not_called()
    assert data["metadata"] is None
