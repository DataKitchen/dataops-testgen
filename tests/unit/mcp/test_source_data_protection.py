import logging
from unittest.mock import MagicMock, patch

import pytest

from testgen.mcp.exceptions import MCPUserError
from testgen.mcp.server import _build_server_instructions, build_mcp_server
from testgen.mcp.services.source_data_protection import (
    _MODE_RANK,
    SourceDataProtectionMode,
    UnreadableProtectionModeError,
    mcp_source_data_env_mode,
    mcp_source_data_only,
    mcp_source_data_protected,
    mcp_source_data_protection_mode,
    parse_source_data_protection_mode,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # Level names.
        ("strict", SourceDataProtectionMode.STRICT),
        ("off", SourceDataProtectionMode.OFF),
        # Boolean spellings — an install configured before the value became a level.
        ("yes", SourceDataProtectionMode.STRICT),
        ("true", SourceDataProtectionMode.STRICT),
        ("no", SourceDataProtectionMode.OFF),
        ("false", SourceDataProtectionMode.OFF),
        # Case and whitespace tolerance.
        ("STRICT", SourceDataProtectionMode.STRICT),
        ("  Yes  ", SourceDataProtectionMode.STRICT),
        # Real booleans and their numeric spellings — JSONB rows can hold either.
        (True, SourceDataProtectionMode.STRICT),
        (False, SourceDataProtectionMode.OFF),
        (1, SourceDataProtectionMode.STRICT),
        (0, SourceDataProtectionMode.OFF),
        # Absent.
        (None, SourceDataProtectionMode.OFF),
        ("", SourceDataProtectionMode.OFF),
    ],
)
def test_parse_source_data_protection_mode(value, expected):
    assert parse_source_data_protection_mode(value) is expected


def test_parse_unrecognized_string_fails_safe_to_most_restrictive(caplog):
    """A typo in a compliance setting must not silently disable the protection."""
    with caplog.at_level(logging.WARNING, logger="testgen"):
        assert parse_source_data_protection_mode("bogus") is SourceDataProtectionMode.STRICT
    assert any("Unrecognized" in r.getMessage() for r in caplog.records)


def test_parse_unrecognized_string_warning_omits_the_blank_spelling(caplog):
    """The empty-string alias is real but must not appear in an operator-facing list."""
    with caplog.at_level(logging.WARNING, logger="testgen"):
        parse_source_data_protection_mode("bogus")
    message = next(r.getMessage() for r in caplog.records if "Unrecognized" in r.getMessage())
    accepted = message.split("Accepted values: ", 1)[1]
    assert not accepted.startswith(",")
    assert "strict" in accepted


@pytest.mark.parametrize("value", [{"mode": "strict"}, ["strict"], object()])
def test_parse_non_string_is_unreadable_not_a_typo(value):
    """A value that is not a level at all is distinguishable from a mistyped one."""
    with pytest.raises(UnreadableProtectionModeError):
        parse_source_data_protection_mode(value)


def test_mode_rank_covers_every_level():
    """The rank drives more-restrictive-wins; a level missing from it would raise."""
    assert set(_MODE_RANK) == set(SourceDataProtectionMode)
    assert _MODE_RANK[0] is SourceDataProtectionMode.OFF
    assert _MODE_RANK[-1] is SourceDataProtectionMode.STRICT


class Test_mcp_source_data_protection_mode:
    """Resolution of the env var against the DB setting, more-restrictive-wins."""

    def test_env_off_db_off_is_off(self):
        with patch("testgen.mcp.services.source_data_protection.settings.MCP_SOURCE_DATA_PROTECTION", "off"), \
             patch(
                 "testgen.mcp.services.source_data_protection.PersistedSetting.get",
                 return_value="off",
             ):
            assert mcp_source_data_protection_mode() is SourceDataProtectionMode.OFF
            assert mcp_source_data_protected() is False

    def test_env_strict_short_circuits_without_reading_db(self):
        # Env at the top level already decides; the DB is not consulted (must not raise).
        with patch("testgen.mcp.services.source_data_protection.settings.MCP_SOURCE_DATA_PROTECTION", "strict"), \
             patch(
                 "testgen.mcp.services.source_data_protection.PersistedSetting.get",
                 side_effect=AssertionError("PersistedSetting.get should not be called when env is strict"),
             ):
            assert mcp_source_data_protection_mode() is SourceDataProtectionMode.STRICT
            assert mcp_source_data_protected() is True

    def test_db_strict_env_off_is_strict(self):
        with patch("testgen.mcp.services.source_data_protection.settings.MCP_SOURCE_DATA_PROTECTION", "off"), \
             patch(
                 "testgen.mcp.services.source_data_protection.PersistedSetting.get",
                 return_value="strict",
             ):
            assert mcp_source_data_protection_mode() is SourceDataProtectionMode.STRICT
            assert mcp_source_data_protected() is True

    def test_legacy_boolean_db_row_still_resolves(self):
        # Rows written before the value became a level hold a JSONB boolean.
        with patch("testgen.mcp.services.source_data_protection.settings.MCP_SOURCE_DATA_PROTECTION", "off"), \
             patch(
                 "testgen.mcp.services.source_data_protection.PersistedSetting.get",
                 return_value=True,
             ):
            assert mcp_source_data_protection_mode() is SourceDataProtectionMode.STRICT

    def test_env_only_helper_ignores_db_setting(self):
        """The registration decision reads the env var alone."""
        with patch("testgen.mcp.services.source_data_protection.settings.MCP_SOURCE_DATA_PROTECTION", "off"), \
             patch(
                 "testgen.mcp.services.source_data_protection.PersistedSetting.get",
                 return_value="strict",
             ):
            assert mcp_source_data_env_mode() is SourceDataProtectionMode.OFF
            # ...while the effective mode still reflects the DB setting.
            assert mcp_source_data_protection_mode() is SourceDataProtectionMode.STRICT

    def test_active_session_branch_reuses_caller_session(self):
        """When a session is already active, the accessor must NOT open its own."""
        with patch(
            "testgen.mcp.services.source_data_protection.settings.MCP_SOURCE_DATA_PROTECTION",
            "off",
        ), patch(
            "testgen.mcp.services.source_data_protection.get_current_session",
            return_value=MagicMock(),
        ), patch(
            "testgen.mcp.services.source_data_protection.database_session",
        ) as db_session_mock, patch(
            "testgen.mcp.services.source_data_protection.PersistedSetting.get",
            return_value=True,
        ):
            assert mcp_source_data_protected() is True
            db_session_mock.assert_not_called()

    def test_fail_open_on_db_exception_logs_warning(self, caplog):
        """When the DB is unreachable and env is off, the accessor logs a WARN and returns False."""
        with patch(
            "testgen.mcp.services.source_data_protection.settings.MCP_SOURCE_DATA_PROTECTION",
            "off",
        ), patch(
            "testgen.mcp.services.source_data_protection.get_current_session",
            return_value=None,
        ), patch(
            "testgen.mcp.services.source_data_protection.database_session",
            side_effect=RuntimeError("db unreachable"),
        ):
            with caplog.at_level(logging.WARNING, logger="testgen"):
                assert mcp_source_data_protected() is False
            warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
            assert warnings, "expected a WARN log for the fail-open branch"
            assert "fails open" in warnings[-1].getMessage()
            assert warnings[-1].exc_info is not None, "expected exc_info=True on the WARN"

    @pytest.mark.parametrize("stored", [{"mode": "strict"}, ["strict"], 3.5])
    def test_malformed_stored_value_resolves_to_most_restrictive(self, stored, caplog):
        """A misconfigured row resolves the way a mistyped level does, not fail-open.

        The column is JSONB, so a dict or list is a reachable stored state — and
        "someone configured this wrong" should land on the safe side either way.
        """
        with patch(
            "testgen.mcp.services.source_data_protection.settings.MCP_SOURCE_DATA_PROTECTION",
            "off",
        ), patch(
            "testgen.mcp.services.source_data_protection.get_current_session",
            return_value=MagicMock(),
        ), patch(
            "testgen.mcp.services.source_data_protection.PersistedSetting.get",
            return_value=stored,
        ):
            with caplog.at_level(logging.WARNING, logger="testgen"):
                assert mcp_source_data_protection_mode() is SourceDataProtectionMode.STRICT
                assert mcp_source_data_protected() is True
            assert any("not a protection level" in r.getMessage() for r in caplog.records)

    def test_env_strict_still_wins_over_a_malformed_stored_value(self):
        """The env short-circuit means a corrupt row cannot weaken a strict install."""
        with patch(
            "testgen.mcp.services.source_data_protection.settings.MCP_SOURCE_DATA_PROTECTION",
            "strict",
        ), patch(
            "testgen.mcp.services.source_data_protection.PersistedSetting.get",
            return_value={"unexpected": "shape"},
        ):
            assert mcp_source_data_protection_mode() is SourceDataProtectionMode.STRICT


class Test_build_server_instructions:
    """The instructions block must reflect the mode."""

    def test_mode_off_includes_investigating_failures_no_specific_tool_names(self):
        text = _build_server_instructions(source_data_protected=False)
        assert "INVESTIGATING FAILURES" in text
        assert "SOURCE-DATA PROTECTION" not in text
        # Deliberately no specific source-only tool names — the instructions block
        # is baked in at server startup and can go stale when the DB toggle flips
        # mid-run. Referring to the source-data tools generically ("when available")
        # keeps the guidance correct in both modes.
        assert "get_source_data" not in text

    def test_mode_on_replaces_investigating_failures_with_protection_notice(self):
        text = _build_server_instructions(source_data_protected=True)
        assert "SOURCE-DATA PROTECTION" in text
        assert "Source-data exposure is disabled by global policy" in text
        assert "get_source_data" not in text
        assert "INVESTIGATING FAILURES" not in text

    def test_both_variants_keep_data_model_and_navigation(self):
        for flag in (True, False):
            text = _build_server_instructions(source_data_protected=flag)
            assert "DATA MODEL" in text
            assert "NAVIGATION" in text
            assert "CONVENTIONS" in text


class Test_mcp_source_data_only:
    """Runtime-refuse decorator for tools whose only purpose is exposing source data.

    The env var stops these tools from being registered at all; the decorator is what
    refuses when only the DB flag is on and the tools remain in the schema.
    """

    def test_calls_through_when_mode_is_off(self):
        with patch(
            "testgen.mcp.services.source_data_protection.mcp_source_data_protected",
            return_value=False,
        ):
            @mcp_source_data_only
            def sample():
                return "ok"

            assert sample() == "ok"

    def test_raises_when_mode_is_on(self):
        with patch(
            "testgen.mcp.services.source_data_protection.mcp_source_data_protected",
            return_value=True,
        ):
            @mcp_source_data_only
            def sample():
                return "should-not-be-reached"

            with pytest.raises(MCPUserError, match="disabled by the MCP source-data protection policy"):
                sample()

    def test_preserves_wrapped_signature_via_functools_wraps(self):
        @mcp_source_data_only
        def sample_tool(a, b=1):
            """A doc."""
            return a + b

        assert sample_tool.__name__ == "sample_tool"
        assert sample_tool.__doc__ == "A doc."


class Test_source_only_tool_gating:
    """The value-exposure tools, the two SQL dry-run tools and the contract export refuse under the mode."""

    GATED = (
        ("testgen.mcp.tools.source_data", "get_source_data"),
        ("testgen.mcp.tools.source_data", "get_source_data_query"),
        ("testgen.mcp.tools.source_data", "get_table_sample"),
        ("testgen.mcp.tools.profiling", "get_column_frequent_values"),
        ("testgen.mcp.tools.profiling", "get_column_patterns"),
        ("testgen.mcp.tools.test_definitions", "validate_custom_test"),
        ("testgen.mcp.tools.monitor_metrics", "validate_metric_expression"),
        ("testgen.mcp.tools.contracts", "export_contract"),
    )

    @pytest.mark.parametrize(("module", "name"), GATED)
    def test_refuses_before_touching_arguments(self, module, name):
        """The guard runs outermost, so a refusal needs no valid arguments."""
        import importlib

        tool = getattr(importlib.import_module(module), name)
        with patch(
            "testgen.mcp.services.source_data_protection.mcp_source_data_protected",
            return_value=True,
        ), pytest.raises(MCPUserError, match="disabled by the MCP source-data protection policy"):
            tool()

    @pytest.mark.parametrize(("module", "name"), GATED)
    def test_guard_preserves_the_wrapped_name(self, module, name):
        """FastMCP derives the tool name from ``__name__``, so the wrapper must keep it."""
        import importlib

        assert getattr(importlib.import_module(module), name).__name__ == name

    @staticmethod
    def _registered_tools(env_mode: SourceDataProtectionMode) -> set[str]:
        with (
            patch("testgen.mcp.server.mcp_source_data_env_mode", return_value=env_mode),
            patch(
                "testgen.mcp.server.mcp_source_data_protected",
                return_value=env_mode is not SourceDataProtectionMode.OFF,
            ),
        ):
            server = build_mcp_server(api_base_url="https://testgen.example.com")
        return {tool.name for tool in server._tool_manager.list_tools()}

    def test_they_are_registered_when_the_env_var_leaves_protection_off(self):
        assert {name for _, name in self.GATED} <= self._registered_tools(SourceDataProtectionMode.OFF)

    def test_none_is_registered_when_the_env_var_turns_protection_on(self):
        assert not {name for _, name in self.GATED} & self._registered_tools(SourceDataProtectionMode.STRICT)
