"""User confirmation for MCP tools whose deletes reach beyond what the request names."""

import logging
import secrets
import threading
import time
from dataclasses import dataclass
from enum import StrEnum

from mcp.server.fastmcp import Context
from mcp.shared.exceptions import McpError
from pydantic import BaseModel, Field, ValidationError

from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.permissions import get_mcp_username

LOG = logging.getLogger("testgen")

TOKEN_TTL_SECONDS = 300


class _Confirmation(BaseModel):
    # Checked by default: clients show the field as a checkbox, and Accept alone has to confirm
    confirm: bool = Field(default=True, description="Go ahead with the deletion.")


@dataclass(frozen=True, slots=True)
class _PendingConfirmation:
    operation_id: str
    scope: str | None
    username: str | None
    expires_at: float


class _Redemption(StrEnum):
    CONFIRMED = "confirmed"
    CHANGED = "changed"
    REFUSED = "refused"


_pending: dict[str, _PendingConfirmation] = {}
_pending_lock = threading.Lock()


def _drop_expired(now: float) -> None:
    for token in [token for token, pending in _pending.items() if pending.expires_at <= now]:
        del _pending[token]


def _issue_token(operation_id: str, scope: str | None) -> str:
    now = time.monotonic()
    token = secrets.token_urlsafe(16)
    with _pending_lock:
        _drop_expired(now)
        _pending[token] = _PendingConfirmation(operation_id, scope, get_mcp_username(), now + TOKEN_TTL_SECONDS)
    return token


def _redeem_token(token: str, operation_id: str, scope: str | None) -> _Redemption:
    """Consume ``token``, and say whether it confirms this operation.

    A live token of this user that was issued for a different operation within the same ``scope`` reads as
    ``CHANGED``: the request acts on the same thing, but what it would remove is no longer what was confirmed.
    """
    now = time.monotonic()
    with _pending_lock:
        _drop_expired(now)
        pending = _pending.pop(token, None)
    if pending is None or pending.username != get_mcp_username():
        return _Redemption.REFUSED
    if pending.operation_id == operation_id:
        return _Redemption.CONFIRMED
    if scope is not None and pending.scope == scope:
        return _Redemption.CHANGED
    return _Redemption.REFUSED


def _supports_form_elicitation(ctx: Context) -> bool:
    params = ctx.session.client_params
    capability = params.capabilities.elicitation if params else None
    if capability is None:
        return False
    # A capability naming neither mode predates the modes and means form.
    return capability.form is not None or capability.url is None


def _render(prompt: str, counts: dict[str, int]) -> str:
    lines = [f"- {label}: {count:,}" for label, count in counts.items() if count]
    return "\n".join([prompt, "", "This removes:", *lines]) if lines else prompt


async def confirm_destructive_action(
    ctx: Context,
    *,
    operation_id: str,
    prompt: str,
    counts: dict[str, int],
    confirmation_token: str | None = None,
    scope: str | None = None,
) -> None:
    """Return once the user has confirmed the operation; raise ``MCPUserError`` otherwise.

    Args:
        ctx: The tool call's MCP context.
        operation_id: Identifies the exact operation, so a token confirms only that operation.
        prompt: The question put to the user, naming what is deleted.
        counts: Entity label to the number of rows the operation removes. Zero counts are left out.
        confirmation_token: A token issued by an earlier call for the same operation.
        scope: Identifies what the operation acts on, apart from what it would remove. A token issued within the
            same scope for a different operation is refused as a change in what the request would remove, rather
            than as an unknown token.

    A supplied token is redeemed: it works once, for the user and operation it was issued
    for, within ``TOKEN_TTL_SECONDS``. Without one, the user is asked through elicitation when
    the client supports it. Otherwise, or when the client answers the elicitation with an error, a
    token is issued and the error carrying it tells the caller to ask the user and call again with it. That token reaches the user only through the
    assistant: it rules out a delete in a single call, but not an assistant that skips asking.
    """
    if confirmation_token is not None:
        redemption = _redeem_token(confirmation_token, operation_id, scope)
        if redemption == _Redemption.CHANGED:
            raise MCPUserError(
                "Nothing was deleted. What this request would delete changed after the user was asked to confirm "
                "it. Call again without `confirmation_token` to show the user what it would delete now."
            )
        if redemption == _Redemption.REFUSED:
            raise MCPUserError(
                "Nothing was deleted. The confirmation token is invalid, expired, already used, or was issued "
                "for a different request. Call again without `confirmation_token` to get a new one."
            )
        return

    message = _render(prompt, counts)
    if _supports_form_elicitation(ctx):
        try:
            result = await ctx.elicit(message, _Confirmation)
        except McpError as error:
            # The client advertised elicitation but answered the request with an error; a token still lets the
            # user confirm.
            LOG.warning(f"MCP elicitation failed, falling back to a confirmation token: {error}")
        except (ValidationError, ValueError) as error:
            # The SDK raises these for an accept whose content is missing or does not fit the form.
            raise MCPUserError("The user did not confirm. Nothing was deleted.") from error
        else:
            if result.action != "accept":
                raise MCPUserError("The user did not confirm. Nothing was deleted.")
            if not result.data.confirm:
                raise MCPUserError("The user accepted with the confirmation box cleared. Nothing was deleted.")
            return

    token = _issue_token(operation_id, scope)
    raise MCPUserError(
        f"Confirmation required. Nothing was deleted.\n\n{message}\n\n"
        "Show this to the user and ask whether to go ahead. If they confirm, call this tool again with the "
        f"same arguments and `confirmation_token` set to `{token}`. The token works once and expires in "
        f"{TOKEN_TTL_SECONDS // 60} minutes."
    )
