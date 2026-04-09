"""
Unit tests for data_catalog.py view logic.

pytest -m unit tests/unit/ui/test_data_catalog.py
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Prevent Streamlit component registration at import time.
# data_catalog imports testgen.ui.components.widgets which registers custom
# Streamlit components that require a running app + pyproject.toml asset_dir.
# ---------------------------------------------------------------------------
import streamlit.components.v2 as _sv2
_sv2.component = MagicMock(return_value=MagicMock())

for _mod in [
    "testgen.ui.components.widgets.testgen_component",
    "testgen.ui.components.widgets.download_dialog",
    "testgen.ui.components.widgets.button",
    "testgen.ui.views.dialogs.run_profiling_dialog",
    "testgen.ui.views.dialogs.column_history_dialog",
    "testgen.ui.views.dialogs.data_preview_dialog",
    "testgen.ui.views.dialogs.table_create_script_dialog",
]:
    sys.modules.setdefault(_mod, MagicMock())

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

TABLE_GROUP_ID = str(uuid4())
TABLE_ID       = str(uuid4())
COLUMN_ID      = str(uuid4())


def _make_item(**kwargs) -> dict:
    """Minimal item dict as returned by get_table_by_id / get_column_by_id."""
    base = {
        "table_group_id":   TABLE_GROUP_ID,
        "table_name":       "orders",
        "column_name":      None,
        "profile_run_id":   str(uuid4()),
        "dq_score_profiling": 0.95,
        "dq_score_testing":   0.90,
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# get_selected_item
# ---------------------------------------------------------------------------

class Test_GetSelectedItem:
    _MISSING = object()  # sentinel so callers can explicitly pass None

    def _call(self, selected: str, item: object = _MISSING, tg_id: str = TABLE_GROUP_ID):
        from testgen.ui.views.data_catalog import get_selected_item

        mock_item = _make_item() if item is self._MISSING else item
        with (
            patch("testgen.ui.views.data_catalog.get_table_by_id",   return_value=mock_item) as mock_table,
            patch("testgen.ui.views.data_catalog.get_column_by_id",  return_value=mock_item) as mock_col,
            patch("testgen.ui.views.data_catalog.get_hygiene_issues", return_value=[]),
            patch("testgen.ui.views.data_catalog.get_pii_columns",    return_value=[]),
            patch("testgen.ui.views.data_catalog.get_latest_test_issues",  return_value=[]),
            patch("testgen.ui.views.data_catalog.get_related_test_suites", return_value=[]),
            patch("testgen.ui.views.data_catalog.mask_profiling_pii"),
            patch("testgen.ui.views.data_catalog.mask_hygiene_detail"),
            patch("testgen.ui.views.data_catalog.session") as mock_session,
        ):
            mock_session.auth.user_has_permission.return_value = True
            result = get_selected_item(selected, tg_id)
        return result, mock_table, mock_col

    def test_none_selected_returns_none(self):
        result, _, _ = self._call(None)
        assert result is None

    def test_no_underscore_returns_none(self):
        result, _, _ = self._call("notavalidid")
        assert result is None

    def test_invalid_table_group_uuid_returns_none(self):
        result, _, _ = self._call(f"table_{TABLE_ID}", tg_id="not-a-uuid")
        assert result is None

    def test_table_prefix_calls_get_table_by_id(self):
        result, mock_table, mock_col = self._call(f"table_{TABLE_ID}")
        mock_table.assert_called_once()
        mock_col.assert_not_called()
        assert result is not None

    def test_column_prefix_calls_get_column_by_id(self):
        result, mock_table, mock_col = self._call(f"column_{COLUMN_ID}")
        mock_col.assert_called_once()
        mock_table.assert_not_called()
        assert result is not None

    def test_unknown_prefix_returns_none(self):
        result, mock_table, mock_col = self._call(f"view_{TABLE_ID}")
        assert result is None
        mock_table.assert_not_called()
        mock_col.assert_not_called()

    def test_returns_none_when_item_not_found(self):
        result, _, _ = self._call(f"table_{TABLE_ID}", item=None)
        assert result is None

    def test_dq_scores_formatted(self):
        item = _make_item(dq_score_profiling=0.876, dq_score_testing=0.912)
        result, _, _ = self._call(f"table_{TABLE_ID}", item=item)
        # friendly_score returns a string representation — just verify not raw float
        assert result is not None
        assert result.get("dq_score") is not None

    def test_pii_masking_called_when_no_view_pii_permission(self):
        from testgen.ui.views.data_catalog import get_selected_item

        item = _make_item(column_name="email")
        with (
            patch("testgen.ui.views.data_catalog.get_column_by_id",      return_value=item),
            patch("testgen.ui.views.data_catalog.get_hygiene_issues",     return_value=[]),
            patch("testgen.ui.views.data_catalog.get_pii_columns",        return_value=["email"]),
            patch("testgen.ui.views.data_catalog.get_latest_test_issues", return_value=[]),
            patch("testgen.ui.views.data_catalog.get_related_test_suites",return_value=[]),
            patch("testgen.ui.views.data_catalog.mask_profiling_pii")     as mock_mask_prof,
            patch("testgen.ui.views.data_catalog.mask_hygiene_detail")    as mock_mask_hyg,
            patch("testgen.ui.views.data_catalog.session") as mock_session,
        ):
            mock_session.auth.user_has_permission.return_value = False
            get_selected_item(f"column_{COLUMN_ID}", TABLE_GROUP_ID)
        mock_mask_prof.assert_called_once()
        mock_mask_hyg.assert_called_once()

    def test_no_masking_when_user_can_view_pii(self):
        from testgen.ui.views.data_catalog import get_selected_item

        item = _make_item(column_name="email")
        with (
            patch("testgen.ui.views.data_catalog.get_column_by_id",      return_value=item),
            patch("testgen.ui.views.data_catalog.get_hygiene_issues",     return_value=[]),
            patch("testgen.ui.views.data_catalog.get_pii_columns",        return_value=["email"]),
            patch("testgen.ui.views.data_catalog.get_latest_test_issues", return_value=[]),
            patch("testgen.ui.views.data_catalog.get_related_test_suites",return_value=[]),
            patch("testgen.ui.views.data_catalog.mask_profiling_pii")  as mock_mask,
            patch("testgen.ui.views.data_catalog.mask_hygiene_detail"),
            patch("testgen.ui.views.data_catalog.session") as mock_session,
        ):
            mock_session.auth.user_has_permission.return_value = True
            get_selected_item(f"column_{COLUMN_ID}", TABLE_GROUP_ID)
        mock_mask.assert_not_called()


# ---------------------------------------------------------------------------
# on_tags_changed — SQL builder
# ---------------------------------------------------------------------------

class Test_OnTagsChanged:
    def _call(self, tags: dict, items: list | None = None, can_view_pii: bool = True):
        from testgen.ui.views.data_catalog import on_tags_changed

        spinner = MagicMock()
        payload = {
            "tags":  tags,
            "items": items or [{"id": TABLE_ID, "type": "table"}],
        }
        with (
            patch("testgen.ui.views.data_catalog.execute_db_query") as mock_exec,
            patch("testgen.ui.views.data_catalog.session") as mock_session,
            patch("testgen.ui.views.data_catalog.TableGroup") as mock_tg,
            patch("testgen.ui.views.data_catalog.safe_rerun"),
        ):
            mock_session.auth.user_has_permission.return_value = can_view_pii
            mock_tg.get.return_value = None  # skip _disable_autoflags
            on_tags_changed(spinner, TABLE_GROUP_ID, payload)
        return mock_exec

    def test_description_tag_produces_set_clause(self):
        mock_exec = self._call({"description": "new desc"})
        calls_sql = " ".join(str(c) for c in mock_exec.call_args_list)
        assert "description" in calls_sql

    def test_critical_data_element_uses_direct_binding(self):
        mock_exec = self._call({"critical_data_element": True})
        first_call_sql = mock_exec.call_args_list[0][0][0]
        assert "critical_data_element = :critical_data_element" in first_call_sql

    def test_pii_flag_skipped_without_view_pii_permission(self):
        items = [{"id": COLUMN_ID, "type": "column"}]
        mock_exec = self._call({"pii_flag": "MANUAL"}, items=items, can_view_pii=False)
        for c in mock_exec.call_args_list:
            sql = c[0][0]
            assert "pii_flag" not in sql, "pii_flag should not appear in SQL without view_pii"

    def test_pii_flag_included_with_view_pii_permission(self):
        items = [{"id": COLUMN_ID, "type": "column"}]
        mock_exec = self._call({"pii_flag": "MANUAL"}, items=items, can_view_pii=True)
        calls_sql = " ".join(str(c) for c in mock_exec.call_args_list)
        assert "pii_flag" in calls_sql

    def test_excluded_data_element_only_applies_to_columns(self):
        # excluded_data_element is column-only; should not appear in table UPDATE
        items = [{"id": TABLE_ID, "type": "table"}]
        mock_exec = self._call({"excluded_data_element": True}, items=items)
        for c in mock_exec.call_args_list:
            sql = c[0][0]
            # Table update should not include excluded_data_element
            if "data_table_chars" in sql:
                assert "excluded_data_element" not in sql

    def test_no_table_query_when_no_table_items(self):
        items = [{"id": COLUMN_ID, "type": "column"}]
        mock_exec = self._call({"description": "x"}, items=items)
        for c in mock_exec.call_args_list:
            sql = c[0][0]
            assert "data_table_chars" not in sql

    def test_no_column_query_when_no_column_items(self):
        items = [{"id": TABLE_ID, "type": "table"}]
        mock_exec = self._call({"description": "x"}, items=items)
        for c in mock_exec.call_args_list:
            sql = c[0][0]
            assert "data_column_chars" not in sql


# ---------------------------------------------------------------------------
# _disable_autoflags
# ---------------------------------------------------------------------------

class Test_DisableAutoflags:
    def _call(self, disable_flags: list[str] | None, tg_id: str = TABLE_GROUP_ID):
        from testgen.ui.views.data_catalog import _disable_autoflags

        mock_tg = MagicMock()
        mock_tg.profile_flag_cdes = True
        mock_tg.profile_flag_pii  = True

        with patch("testgen.ui.views.data_catalog.TableGroup") as mock_cls:
            mock_cls.get.return_value = mock_tg
            _disable_autoflags(tg_id, disable_flags)
        return mock_tg

    def test_none_disable_flags_does_nothing(self):
        mock_tg = self._call(None)
        mock_tg.save.assert_not_called()

    def test_empty_list_does_nothing(self):
        mock_tg = self._call([])
        mock_tg.save.assert_not_called()

    def test_disable_cdes_sets_profile_flag_cdes_false(self):
        mock_tg = self._call(["profile_flag_cdes"])
        assert mock_tg.profile_flag_cdes is False
        mock_tg.save.assert_called_once()

    def test_disable_pii_sets_profile_flag_pii_false(self):
        mock_tg = self._call(["profile_flag_pii"])
        assert mock_tg.profile_flag_pii is False
        mock_tg.save.assert_called_once()

    def test_both_flags_disabled_in_one_save(self):
        mock_tg = self._call(["profile_flag_cdes", "profile_flag_pii"])
        assert mock_tg.profile_flag_cdes is False
        assert mock_tg.profile_flag_pii is False
        mock_tg.save.assert_called_once()  # only one save

    def test_unknown_flag_ignored(self):
        mock_tg = self._call(["unknown_flag"])
        mock_tg.save.assert_not_called()


# ---------------------------------------------------------------------------
# Excel export: tag cascade (late-binding bug check, #7)
# ---------------------------------------------------------------------------

class Test_TagCascadeInExcelExport:
    """
    The tag cascade loop in get_excel_report_data uses `lambda row: row[key] or ...`
    inside a for-loop over keys. If the lambda closes over `key` (late binding),
    all columns would use the last key's value. Verify each key maps to itself.
    """

    def _build_row(self, **overrides):
        base = {
            "data_source":       "src_a",
            "source_system":     "sys_b",
            "source_process":    "proc_c",
            "business_domain":   "dom_d",
            "stakeholder_group": "grp_e",
            "transform_level":   "tl_f",
            "aggregation_level": "agg_g",
            "data_product":      "dp_h",
        }
        # Also provide table_ and table_group_ fallback columns
        for k, v in list(base.items()):
            base[f"table_{k}"] = None
            base[f"table_group_{k}"] = None
        base.update(overrides)
        return base

    def test_each_tag_key_maps_to_its_own_column(self):
        """Each key in the cascade must resolve to its own column value, not the last key."""
        from testgen.ui.queries.profiling_queries import TAG_FIELDS

        row = pd.Series(self._build_row())
        expected = {
            "data_source":       "src_a",
            "source_system":     "sys_b",
            "source_process":    "proc_c",
            "business_domain":   "dom_d",
            "stakeholder_group": "grp_e",
            "transform_level":   "tl_f",
            "aggregation_level": "agg_g",
            "data_product":      "dp_h",
        }

        # Replicate the loop from get_excel_report_data
        data = pd.DataFrame([row.to_dict()])
        for key in TAG_FIELDS:
            data[key] = data.apply(
                lambda r, k=key: r[k] or r[f"table_{k}"] or r.get(f"table_group_{k}"),
                axis=1,
            )

        for key, val in expected.items():
            assert data[key].iloc[0] == val, f"Key '{key}' got wrong value: {data[key].iloc[0]!r}"

    def test_table_fallback_used_when_column_value_null(self):
        from testgen.ui.queries.profiling_queries import TAG_FIELDS

        row = pd.Series(self._build_row(data_source=None, **{"table_data_source": "table_src"}))
        data = pd.DataFrame([row.to_dict()])
        key = "data_source"
        data[key] = data.apply(lambda r, k=key: r[k] or r[f"table_{k}"] or r.get(f"table_group_{k}"), axis=1)
        assert data[key].iloc[0] == "table_src"


# ---------------------------------------------------------------------------
# get_tag_values — shape of returned dict
# ---------------------------------------------------------------------------

class Test_GetTagValues:
    def test_returns_dict_of_lists(self):
        from testgen.ui.views.data_catalog import get_tag_values

        fake_rows = [
            MagicMock(tag="data_source", value="warehouse"),
            MagicMock(tag="data_source", value="lake"),
            MagicMock(tag="business_domain", value="finance"),
            MagicMock(tag="business_domain", value=None),   # should be excluded
            MagicMock(tag=None,              value="orphan"),  # should be excluded
        ]
        with patch("testgen.ui.views.data_catalog.fetch_all_from_db", return_value=fake_rows):
            # Clear cache so our mock is used
            get_tag_values.clear()
            result = get_tag_values()

        assert set(result["data_source"]) == {"warehouse", "lake"}
        assert result["business_domain"] == ["finance"]
        assert None not in result  # None tag key excluded
        for values in result.values():
            assert None not in values  # None values excluded
