from testgen.utils.plugins import PluginSpec


def test_get_test_type_template_paths_defaults_to_empty():
    assert PluginSpec.get_test_type_template_paths() == []


def test_get_test_type_template_paths_is_overridable():
    class MyPlugin(PluginSpec):
        @classmethod
        def get_test_type_template_paths(cls) -> list[str]:
            return ["some_pkg.template.test_types"]

    assert MyPlugin.get_test_type_template_paths() == ["some_pkg.template.test_types"]
