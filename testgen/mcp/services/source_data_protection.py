"""Mode accessor and runtime-refuse decorator for MCP source-data protection.

The mode is a level, not a boolean, so a less restrictive level can be added
later without breaking installs configured today. :class:`SourceDataProtectionMode`
holds the levels; ``strict`` and ``yes`` both select :attr:`SourceDataProtectionMode.STRICT`.

Two independent switches select it:

- **Env var** (:data:`settings.MCP_SOURCE_DATA_PROTECTION`) — decided at MCP
  server startup. Under ``strict``, source-only tools are not registered with
  the MCP server at all.
- **DB setting** (:class:`PersistedSetting` row keyed
  :data:`MCP_SOURCE_DATA_PROTECTION_SETTING_KEY`) — runtime, no restart required.
  Under ``strict``, source-only tools remain in the schema but refuse at
  invocation via :func:`mcp_source_data_only`; field-level omissions in the
  mixed tools take effect on the next request.

The two switches resolve on a more-restrictive-wins rule: the effective mode is
whichever of the two is higher up :data:`_MODE_RANK`, which follows the enum's
declaration order.

Field-level omission call sites use :func:`mcp_source_data_protected`, a boolean
view that collapses every level above ``off`` to the same behavior. Adding an
intermediate level therefore needs no change to the resolver, but does need each
call site revisited — until then an intermediate level behaves as ``strict``,
which fails in the safe direction. ``server.py`` reads the env var alone, via
:func:`mcp_source_data_env_mode`, for its registration decision.

A misconfigured setting resolves to the most restrictive level: both a mistyped
level name and a stored value that is not a level at all. An unreachable database
is different — the env var alone decides, so where the setting is the sole enforcer
a database problem disables the mode. Deployments that require fail-closed
enforcement must set the env var.
"""

import functools
import logging
from enum import StrEnum

from testgen import settings
from testgen.common.models import database_session, get_current_session
from testgen.common.models.settings import PersistedSetting
from testgen.mcp.exceptions import MCPUserError

LOG = logging.getLogger("testgen")

MCP_SOURCE_DATA_PROTECTION_SETTING_KEY = "MCP_SOURCE_DATA_PROTECTION_ENABLED"


class SourceDataProtectionMode(StrEnum):
    """Protection levels, declared least- to most-restrictive.

    Declaration order is load-bearing: :data:`_MODE_RANK` is derived from it and
    drives the more-restrictive-wins resolution. Insert a new level in its correct
    position rather than appending.
    """

    OFF = "off"
    STRICT = "strict"


# Derived from the enum so the rank cannot drift out of sync with the levels.
_MODE_RANK: tuple[SourceDataProtectionMode, ...] = tuple(SourceDataProtectionMode)

# Accepted spellings per level. ``yes``/``true`` map to STRICT so an install
# configured with the boolean spelling keeps working. The empty string maps to OFF
# so an explicitly blank env var reads as unset.
_MODE_ALIASES: dict[str, SourceDataProtectionMode] = {
    "off": SourceDataProtectionMode.OFF,
    "no": SourceDataProtectionMode.OFF,
    "false": SourceDataProtectionMode.OFF,
    "": SourceDataProtectionMode.OFF,
    "strict": SourceDataProtectionMode.STRICT,
    "yes": SourceDataProtectionMode.STRICT,
    "true": SourceDataProtectionMode.STRICT,
}

# For operator-facing messages: the blank spelling is real but not worth naming.
_NAMED_ALIASES: str = ", ".join(sorted(alias for alias in _MODE_ALIASES if alias))


class UnreadableProtectionModeError(ValueError):
    """The stored value is not a level at all — malformed rather than mistyped."""


_SOURCE_ONLY_REFUSAL_MESSAGE = (
    "This tool is disabled by the MCP source-data protection policy on this install. "
    "Source-derived values are not surfaced through this MCP; only aggregates and "
    "structure are available."
)


def parse_source_data_protection_mode(value: object) -> SourceDataProtectionMode:
    """Coerce a configured value to a mode level.

    Accepts the level names, the boolean spellings (``yes`` / ``true`` / ``no`` /
    ``false``), real booleans, ``0`` / ``1``, ``None``, and empty strings.

    An unrecognized *string* resolves to the most restrictive level and logs a WARN:
    it reads as a value someone meant to configure, and a typo in a compliance
    setting must not silently disable the protection.

    A value of any other type raises :class:`UnreadableProtectionModeError`. The env
    var is always a string, so only the stored row can reach that.
    """
    if value is None:
        return SourceDataProtectionMode.OFF
    # bool before int: bool is an int subclass and both spellings mean the same here.
    if isinstance(value, bool | int):
        return SourceDataProtectionMode.STRICT if value else SourceDataProtectionMode.OFF

    if not isinstance(value, str):
        raise UnreadableProtectionModeError(
            f"expected one of {_NAMED_ALIASES}, got {type(value).__name__}"
        )

    key = value.strip().lower()
    if key in _MODE_ALIASES:
        return _MODE_ALIASES[key]

    LOG.warning(
        "Unrecognized MCP source-data protection value %r; defaulting to the most restrictive level (%s). "
        "Accepted values: %s.",
        value,
        SourceDataProtectionMode.STRICT.value,
        _NAMED_ALIASES,
    )
    return _MODE_ALIASES["strict"]


def _more_restrictive(
    left: SourceDataProtectionMode, right: SourceDataProtectionMode
) -> SourceDataProtectionMode:
    return max(left, right, key=_MODE_RANK.index)


def mcp_source_data_env_mode() -> SourceDataProtectionMode:
    """Return the protection level configured by the env var alone.

    ``server.py`` uses this for the registration decision: only the env var
    removes source-only tools from the schema, because registration happens once
    at server startup and the DB setting is meant to be flippable without a
    restart.
    """
    return parse_source_data_protection_mode(settings.MCP_SOURCE_DATA_PROTECTION)


def mcp_source_data_protection_mode() -> SourceDataProtectionMode:
    """Return the effective protection level for this install.

    Resolves :data:`settings.MCP_SOURCE_DATA_PROTECTION` (env var) against the
    ``MCP_SOURCE_DATA_PROTECTION_ENABLED`` :class:`PersistedSetting` row on a
    more-restrictive-wins rule.

    Callable in three contexts:

    - Inside an active database session (per-request field-omission calls) — reuses
      the caller's session.
    - At MCP server startup — opens its own short-lived session for the DB read.
    - In environments without a functioning session factory (unit tests that mock
      the ORM at import time, CLI paths that never open a session) — reports the
      env-var level only.

    A stored value that is not a protection level resolves to the most restrictive
    level, matching how a mistyped level resolves. An unreachable database instead
    lets the env var alone decide, which fails open where the setting is the sole
    enforcer — fail-closed deployments must set the env var.
    """
    env_mode = mcp_source_data_env_mode()
    if env_mode is _MODE_RANK[-1]:
        return env_mode

    try:
        if get_current_session() is not None:
            return _more_restrictive(env_mode, _read_db_mode())
        with database_session():
            return _more_restrictive(env_mode, _read_db_mode())
    except UnreadableProtectionModeError:
        # A stored value that is not a level is a misconfiguration, not a connectivity
        # failure, so it resolves the way a mistyped level does — most restrictive.
        LOG.warning(
            "The %s setting holds a value that is not a protection level; resolving to %s.",
            MCP_SOURCE_DATA_PROTECTION_SETTING_KEY,
            _MODE_RANK[-1].value,
            exc_info=True,
        )
        return _MODE_RANK[-1]
    except Exception:
        LOG.warning(
            "MCP source-data protection could not read the %s setting; resolving from the environment "
            "variable alone (%s). Where the setting is the sole enforcer this fails open — set "
            "TG_MCP_SOURCE_DATA_PROTECTION for fail-closed enforcement.",
            MCP_SOURCE_DATA_PROTECTION_SETTING_KEY,
            env_mode.value,
            exc_info=True,
        )
        return env_mode


def _read_db_mode() -> SourceDataProtectionMode:
    return parse_source_data_protection_mode(
        PersistedSetting.get(MCP_SOURCE_DATA_PROTECTION_SETTING_KEY, default=None)
    )


def mcp_source_data_protected() -> bool:
    """Return True when source-derived values must be hidden from the MCP surface.

    Boolean view over :func:`mcp_source_data_protection_mode` for the field-omission
    call sites, which behave identically at every level above ``off``.
    """
    return mcp_source_data_protection_mode() is not SourceDataProtectionMode.OFF


def mcp_source_data_only(fn):
    """Refuse the call at invocation time when the source-data protection mode is on.

    Applied to tools whose entire purpose is exposing source-derived values. When
    the env var selects a protected level these tools are never registered and this
    guard never runs; when only the DB setting selects one, the tools remain in the
    schema and this guard raises :class:`MCPUserError` on every call.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if mcp_source_data_protected():
            raise MCPUserError(_SOURCE_ONLY_REFUSAL_MESSAGE)
        return fn(*args, **kwargs)
    return wrapper
