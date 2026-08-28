from types import ModuleType
from unittest.mock import patch

import pytest

from testgen.utils.plugins import Plugin, PluginSpec


def test_get_test_type_template_paths_defaults_to_empty():
    assert PluginSpec.get_test_type_template_paths() == []


def test_get_test_type_template_paths_is_overridable():
    class MyPlugin(PluginSpec):
        @classmethod
        def get_test_type_template_paths(cls) -> list[str]:
            return ["some_pkg.template.test_types"]

    assert MyPlugin.get_test_type_template_paths() == ["some_pkg.template.test_types"]


def _module(name: str, file: str | None, path: list[str] | None = None) -> ModuleType:
    module = ModuleType(name)
    module.__file__ = file
    if path is not None:
        module.__path__ = path
    return module


@pytest.mark.unit
def test_load_rejects_a_shadowed_package():
    """A directory shadowing the install imports as a namespace package with no plugin code."""
    shadowed = _module("testgen_a_plugin", file=None, path=["/site-packages/testgen_a_plugin"])

    with patch("importlib.import_module", return_value=shadowed):
        with pytest.raises(ImportError, match=r"/site-packages/testgen_a_plugin"):
            Plugin(package="testgen_a_plugin", version="1.0.0").load()


@pytest.mark.unit
def test_load_falls_back_to_the_base_spec_when_the_module_declares_none():
    module = _module("testgen_a_plugin", file="/site-packages/testgen_a_plugin/__init__.py")

    with patch("importlib.import_module", return_value=module):
        assert Plugin(package="testgen_a_plugin", version="1.0.0").load() is PluginSpec


@pytest.mark.unit
def test_load_returns_the_declared_spec():
    class APlugin(PluginSpec):
        pass

    module = _module("testgen_a_plugin", file="/site-packages/testgen_a_plugin/__init__.py")
    module.APlugin = APlugin

    with patch("importlib.import_module", return_value=module):
        assert Plugin(package="testgen_a_plugin", version="1.0.0").load() is APlugin
