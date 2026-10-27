import asyncio
import re
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from mcp.shared.exceptions import McpError
from mcp.types import (
    INTERNAL_ERROR,
    ElicitationCapability,
    ErrorData,
    FormElicitationCapability,
    UrlElicitationCapability,
)
from pydantic import ValidationError

from testgen.mcp import confirmation
from testgen.mcp.confirmation import TOKEN_TTL_SECONDS, confirm_destructive_action
from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.permissions import set_mcp_username

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def no_pending_tokens():
    confirmation._pending.clear()
    yield
    confirmation._pending.clear()


def _ctx(elicitation: ElicitationCapability | None = None, action: str = "accept", confirm: bool = True) -> MagicMock:
    ctx = MagicMock()
    ctx.session.client_params.capabilities.elicitation = elicitation
    ctx.elicit = AsyncMock(return_value=MagicMock(action=action, data=MagicMock(confirm=confirm)))
    return ctx


def _confirm(
    ctx: MagicMock,
    operation_id: str = "delete_tests:abc",
    token: str | None = None,
    scope: str | None = None,
    **counts: int,
) -> None:
    asyncio.run(
        confirm_destructive_action(
            ctx,
            operation_id=operation_id,
            prompt="Delete every test in suite `orders`?",
            counts=counts or {"Tests": 12, "Notes": 0},
            confirmation_token=token,
            scope=scope,
        )
    )


def _issued_token(ctx: MagicMock, operation_id: str = "delete_tests:abc", scope: str | None = None) -> str:
    with pytest.raises(MCPUserError) as raised:
        _confirm(ctx, operation_id, scope=scope)
    return re.search(r"`confirmation_token` set to `([^`]+)`", str(raised.value)).group(1)


def test_a_confirmed_elicitation_returns():
    ctx = _ctx(ElicitationCapability())

    _confirm(ctx)

    ctx.elicit.assert_awaited_once()


def test_the_elicitation_names_the_operation_and_its_nonzero_counts():
    ctx = _ctx(ElicitationCapability())

    _confirm(ctx, Tests=1200, Notes=0)

    message = ctx.elicit.await_args.args[0]
    assert message.startswith("Delete every test in suite `orders`?")
    assert "- Tests: 1,200" in message
    assert "Notes" not in message


@pytest.mark.parametrize(
    ("action", "confirm"),
    [("accept", False), ("decline", True), ("cancel", True)],
)
def test_anything_but_an_accepted_confirmation_refuses(action, confirm):
    with pytest.raises(MCPUserError, match="did not confirm. Nothing was deleted"):
        _confirm(_ctx(ElicitationCapability(), action=action, confirm=confirm))


def test_a_capability_naming_form_mode_is_asked():
    ctx = _ctx(ElicitationCapability(form=FormElicitationCapability(), url=UrlElicitationCapability()))

    _confirm(ctx)

    ctx.elicit.assert_awaited_once()


def test_a_url_only_capability_falls_back_to_a_token():
    ctx = _ctx(ElicitationCapability(url=UrlElicitationCapability()))

    _issued_token(ctx)

    ctx.elicit.assert_not_awaited()


def test_without_elicitation_the_caller_gets_a_token_and_the_counts():
    with pytest.raises(MCPUserError) as raised:
        _confirm(_ctx())

    message = str(raised.value)
    assert message.startswith("Confirmation required. Nothing was deleted.")
    assert "Delete every test in suite `orders`?" in message
    assert "- Tests: 12" in message
    assert f"expires in {TOKEN_TTL_SECONDS // 60} minutes" in message


def test_a_client_that_sent_no_initialization_falls_back_to_a_token():
    ctx = _ctx()
    ctx.session.client_params = None

    _issued_token(ctx)


def test_an_issued_token_confirms_the_same_operation_once():
    token = _issued_token(_ctx())

    _confirm(_ctx(), token=token)
    with pytest.raises(MCPUserError, match="invalid, expired, already used"):
        _confirm(_ctx(), token=token)


def test_a_token_supplied_skips_elicitation():
    token = _issued_token(_ctx())
    ctx = _ctx(ElicitationCapability())

    _confirm(ctx, token=token)

    ctx.elicit.assert_not_awaited()


def test_a_token_does_not_confirm_a_different_operation():
    token = _issued_token(_ctx(), operation_id="delete_tests:abc")

    with pytest.raises(MCPUserError, match="issued for a different request"):
        _confirm(_ctx(), operation_id="delete_tests:xyz", token=token)


def test_a_token_rejected_for_a_different_operation_is_spent():
    token = _issued_token(_ctx(), operation_id="delete_tests:abc")
    with pytest.raises(MCPUserError):
        _confirm(_ctx(), operation_id="delete_tests:xyz", token=token)

    with pytest.raises(MCPUserError, match="already used"):
        _confirm(_ctx(), operation_id="delete_tests:abc", token=token)


def test_a_token_does_not_confirm_for_another_user():
    set_mcp_username("alice")
    token = _issued_token(_ctx())

    set_mcp_username("mallory")
    with pytest.raises(MCPUserError, match="invalid, expired"):
        _confirm(_ctx(), token=token)


def test_an_expired_token_is_refused():
    with patch("testgen.mcp.confirmation.time.monotonic", return_value=1000.0):
        token = _issued_token(_ctx())

    with (
        patch("testgen.mcp.confirmation.time.monotonic", return_value=1000.0 + TOKEN_TTL_SECONDS),
        pytest.raises(MCPUserError, match="expired"),
    ):
        _confirm(_ctx(), token=token)


def test_an_unknown_token_is_refused():
    with pytest.raises(MCPUserError, match="Call again without `confirmation_token`"):
        _confirm(_ctx(), token=str(uuid4()))


def test_expired_tokens_are_dropped_when_the_store_is_next_used():
    with patch("testgen.mcp.confirmation.time.monotonic", return_value=1000.0):
        _issued_token(_ctx(), operation_id="delete_tests:old")
    assert len(confirmation._pending) == 1

    with patch("testgen.mcp.confirmation.time.monotonic", return_value=1000.0 + TOKEN_TTL_SECONDS + 1):
        _issued_token(_ctx(), operation_id="delete_tests:new")

    assert [pending.operation_id for pending in confirmation._pending.values()] == ["delete_tests:new"]


@pytest.mark.parametrize(
    "error",
    [
        ValidationError.from_exception_data("_Confirmation", []),
        ValueError("Unexpected elicitation action: accept"),
    ],
    ids=["content-does-not-fit-the-form", "accept-without-content"],
)
def test_an_accept_the_sdk_cannot_read_counts_as_not_confirmed(error):
    ctx = _ctx(ElicitationCapability())
    ctx.elicit.side_effect = error

    with pytest.raises(MCPUserError, match="did not confirm. Nothing was deleted"):
        _confirm(ctx)


def test_an_unticked_box_the_client_leaves_out_reads_as_not_confirmed():
    assert confirmation._Confirmation.model_validate({}).confirm is False


def test_a_client_that_answers_the_elicitation_with_an_error_gets_a_token():
    ctx = _ctx(ElicitationCapability())
    ctx.elicit.side_effect = McpError(ErrorData(code=INTERNAL_ERROR, message="elicitation not available"))

    token = _issued_token(ctx)

    _confirm(_ctx(), token=token)


def test_a_token_for_the_same_scope_but_other_contents_says_what_it_would_delete_changed():
    token = _issued_token(_ctx(), operation_id="delete_test_suite:s1:counts-shown", scope="delete_test_suite:s1")

    with pytest.raises(MCPUserError) as refused:
        _confirm(_ctx(), operation_id="delete_test_suite:s1:counts-now", token=token, scope="delete_test_suite:s1")

    assert str(refused.value).startswith("Nothing was deleted. What this request would delete changed")
    assert "invalid" not in str(refused.value)


def test_a_token_for_another_scope_is_refused_as_any_unknown_token():
    token = _issued_token(_ctx(), operation_id="delete_test_suite:s1:counts", scope="delete_test_suite:s1")

    with pytest.raises(MCPUserError, match="issued for a different request"):
        _confirm(_ctx(), operation_id="delete_test_suite:s2:counts", token=token, scope="delete_test_suite:s2")


def test_a_changed_scope_token_is_spent_like_any_other():
    token = _issued_token(_ctx(), operation_id="delete_test_suite:s1:a", scope="delete_test_suite:s1")
    with pytest.raises(MCPUserError, match="changed"):
        _confirm(_ctx(), operation_id="delete_test_suite:s1:b", token=token, scope="delete_test_suite:s1")

    with pytest.raises(MCPUserError, match="already used"):
        _confirm(_ctx(), operation_id="delete_test_suite:s1:a", token=token, scope="delete_test_suite:s1")


def test_another_users_token_in_the_same_scope_is_refused_without_saying_what_changed():
    set_mcp_username("alice")
    token = _issued_token(_ctx(), operation_id="delete_test_suite:s1:a", scope="delete_test_suite:s1")

    set_mcp_username("mallory")
    with pytest.raises(MCPUserError, match="invalid, expired"):
        _confirm(_ctx(), operation_id="delete_test_suite:s1:b", token=token, scope="delete_test_suite:s1")
