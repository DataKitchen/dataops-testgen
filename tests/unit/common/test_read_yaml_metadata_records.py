import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from testgen.common import read_yaml_metadata_records as loader

PARAMS = {
    "SCHEMA_NAME": "tg",
    "TESTGEN_ADMIN_USER": "admin",
    "TESTGEN_ADMIN_PASSWORD": "pw",
}


def _executed_queries(mock_exec):
    # execute_db_queries(queries, ...) -> first positional arg is the query list
    assert mock_exec.call_count == 1
    return mock_exec.call_args.args[0]


def test_generation_sets_membership_rows_are_inserted():
    data = {"test_types": {"test_type": "Foo", "id": "1", "generation_sets": ["Standard", "Monitor"]}}
    with patch.object(loader, "execute_db_queries") as mock_exec:
        loader._process_yaml_for_import(
            PARAMS, data, "test_types", "test_type",
            loader.TEST_TYPES_CHILD_TABLES, loader.TEST_TYPES_DEFAULT_PK,
            loader.TEST_TYPES_PARENT_CHILD_COLUMN_MAP,
        )
    queries = _executed_queries(mock_exec)
    membership = [(q, p) for q, p in queries if "generation_sets" in q]
    assert {p["generation_set"] for _, p in membership} == {"Standard", "Monitor"}
    assert all(p["test_type"] == "Foo" for _, p in membership)
    assert all("ON CONFLICT (generation_set, test_type) DO NOTHING" in q for q, _ in membership)
    # generation_sets must NOT leak into the test_types parent insert
    parent_insert = next(q for q, _ in queries if "INSERT INTO tg.test_types" in q)
    assert "generation_sets" not in parent_insert


def test_no_generation_sets_field_inserts_no_membership():
    data = {"test_types": {"test_type": "Bar", "id": "2"}}
    with patch.object(loader, "execute_db_queries") as mock_exec:
        loader._process_yaml_for_import(
            PARAMS, data, "test_types", "test_type",
            loader.TEST_TYPES_CHILD_TABLES, loader.TEST_TYPES_DEFAULT_PK,
            loader.TEST_TYPES_PARENT_CHILD_COLUMN_MAP,
        )
    queries = _executed_queries(mock_exec)
    assert not [q for q, _ in queries if "generation_sets" in q]


def test_plugin_test_type_paths_are_scanned_and_imported():
    with tempfile.TemporaryDirectory() as d:
        yaml_path = Path(d) / "test_types_Plugin_Type.yaml"
        yaml_path.write_text(
            "test_types:\n"
            "  test_type: Plugin_Type\n"
            "  id: '9999'\n"
            "  generation_sets:\n"
            "    - Plugin_Set\n"
        )

        fake_spec = MagicMock()
        fake_spec.get_test_type_template_paths.return_value = ["plugin.pkg.path"]
        fake_plugin = MagicMock()
        fake_plugin.load.return_value = fake_spec

        def fake_get_template_files(mask, sub_directory=None, path=None):
            # core + anomaly folder scans return nothing; the plugin path yields our temp YAML
            return [yaml_path] if path == "plugin.pkg.path" else []

        with patch("testgen.utils.plugins.discover", return_value=[fake_plugin]), \
             patch.object(loader, "get_template_files", side_effect=fake_get_template_files), \
             patch.object(loader, "execute_db_queries") as mock_exec, \
             patch.object(loader.settings, "VERSION", "1.0.0"):
            # ``_process_yaml_for_import`` also queries the current uploaded_version;
            # empty return keeps the rule-1 (packaged) path.
            mock_exec.return_value = ([], [])
            loader.import_metadata_records_from_yaml(PARAMS)

    all_queries = [q for call in mock_exec.call_args_list for q, _ in call.args[0]]
    assert any("Plugin_Type" in q or "generation_sets" in q for q in all_queries)
    membership = [
        p for call in mock_exec.call_args_list for q, p in call.args[0] if "generation_sets" in q
    ]
    assert any(p["generation_set"] == "Plugin_Set" and p["test_type"] == "Plugin_Type"
               for p in membership)


def test_broken_plugin_is_skipped_and_later_import_still_runs():
    broken_plugin = MagicMock()
    broken_plugin.package = "testgen_broken_plugin"
    broken_plugin.load.side_effect = RuntimeError("plugin failed to load")

    good_spec = MagicMock()
    good_spec.get_test_type_template_paths.return_value = ["good.plugin.pkg.path"]
    good_plugin = MagicMock()
    good_plugin.package = "testgen_good_plugin"
    good_plugin.load.return_value = good_spec

    with tempfile.TemporaryDirectory() as d:
        yaml_path = Path(d) / "test_types_Good_Type.yaml"
        yaml_path.write_text(
            "test_types:\n"
            "  test_type: Good_Type\n"
            "  id: '9998'\n"
        )

        def fake_get_template_files(mask, sub_directory=None, path=None):
            # core + anomaly folder scans return nothing; only the good plugin's path yields a YAML
            return [yaml_path] if path == "good.plugin.pkg.path" else []

        with patch("testgen.utils.plugins.discover", return_value=[broken_plugin, good_plugin]), \
             patch.object(loader, "get_template_files", side_effect=fake_get_template_files), \
             patch.object(loader, "execute_db_queries") as mock_exec, \
             patch.object(loader.settings, "VERSION", "1.0.0"):
            mock_exec.return_value = ([], [])
            loader.import_metadata_records_from_yaml(PARAMS)

    # The broken plugin's load() was attempted but did not propagate.
    broken_plugin.load.assert_called_once()
    # The good plugin, discovered after the broken one, was still processed.
    all_params = [p for call in mock_exec.call_args_list for _, p in call.args[0]]
    assert any(p.get("test_type") == "Good_Type" for p in all_params)


def test_export_includes_generation_sets_when_present(tmp_path):
    parent_rows = [("Foo",)]
    parent_cols = ["test_type"]

    def fake_fetch(queries):
        (query, _), = queries
        if "FROM tg.test_types" in query:
            return parent_rows, parent_cols, None
        if "FROM tg.generation_sets" in query:
            return [("Standard",), ("Monitor",)], ["generation_set"], None
        return [], [], None   # empty child tables

    dumped = {}
    with patch.object(loader, "fetch_from_db_threaded", side_effect=fake_fetch), \
         patch.object(loader, "safe_dump", side_effect=lambda payload, _f, **_: dumped.update(payload)):
        loader._process_records_for_export(
            {"SCHEMA_NAME": "tg"}, str(tmp_path),
            "test_types", "test_type",
            loader.TEST_TYPES_CHILD_TABLES, loader.TEST_TYPES_DEFAULT_PK,
            loader.TEST_TYPES_PARENT_CHILD_COLUMN_MAP, loader.TEST_TYPES_LITERAL_FIELDS,
        )
    assert dumped["test_types"]["generation_sets"] == ["Standard", "Monitor"]


def test_export_omits_generation_sets_when_absent(tmp_path):
    parent_rows = [("Foo",)]
    parent_cols = ["test_type"]

    def fake_fetch(queries):
        (query, _), = queries
        if "FROM tg.test_types" in query:
            return parent_rows, parent_cols, None
        if "FROM tg.generation_sets" in query:
            return [], ["generation_set"], None
        return [], [], None   # empty child tables

    dumped = {}
    with patch.object(loader, "fetch_from_db_threaded", side_effect=fake_fetch), \
         patch.object(loader, "safe_dump", side_effect=lambda payload, _f, **_: dumped.update(payload)):
        loader._process_records_for_export(
            {"SCHEMA_NAME": "tg"}, str(tmp_path),
            "test_types", "test_type",
            loader.TEST_TYPES_CHILD_TABLES, loader.TEST_TYPES_DEFAULT_PK,
            loader.TEST_TYPES_PARENT_CHILD_COLUMN_MAP, loader.TEST_TYPES_LITERAL_FIELDS,
        )
    assert "generation_sets" not in dumped["test_types"]
