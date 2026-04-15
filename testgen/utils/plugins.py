from __future__ import annotations

import importlib
import importlib.metadata
import inspect
from collections.abc import Generator
from typing import ClassVar, get_args

from testgen.ui.assets import get_asset_path
from testgen.ui.auth import Authentication
from testgen.ui.navigation.page import Page

PLUGIN_PREFIX = "testgen_"


def discover() -> Generator[Plugin, None, None]:
    for package_path, distribution_names in importlib.metadata.packages_distributions().items():
        if package_path.startswith(PLUGIN_PREFIX):
            yield Plugin(package=package_path, version=importlib.metadata.version(distribution_names[0]))


class Logo:
    image_path: str = get_asset_path("dk_logo.svg")
    icon_path: str = get_asset_path("dk_icon.svg")

    def render(self):
        import streamlit as st

        st.logo(
            image=self.image_path,
            icon_image=self.icon_path,
        )


class RBACProvider:
    """Base RBAC provider. OS default: all permissions granted."""

    @staticmethod
    def check_permission(_user: object, _permission: str) -> bool:
        return True

    @staticmethod
    def get_roles_with_permission(_permission: str) -> list[str]:
        """Return roles that have the given permission. OS default: all roles."""
        from testgen.common.models.project_membership import RoleType

        return list(get_args(RoleType))


class PluginSpec:
    rbac: ClassVar[type[RBACProvider]] = RBACProvider
    auth: ClassVar[type[Authentication] | None] = None
    pages: ClassVar[list[type[Page]]] = []
    logo: ClassVar[type[Logo] | None] = None

    @classmethod
    def configure_ui(cls) -> None:
        """Populate UI-related class attributes (pages, auth, logo).

        Override this in plugins to defer Streamlit-dependent imports until Streamlit
        is actually running. Called by ``Plugin.load_streamlit()``, never by ``Plugin.load()``.
        """


class PluginHook:
    """Singleton holding resolved plugin values, pre-loaded with defaults."""

    _instance: PluginHook | None = None
    rbac: type[RBACProvider] = RBACProvider

    @classmethod
    def instance(cls) -> PluginHook:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


def _find_plugin_spec(module) -> type[PluginSpec] | None:
    """Find the first concrete PluginSpec subclass in a module."""
    for name in dir(module):
        cls = getattr(module, name, None)
        if inspect.isclass(cls) and issubclass(cls, PluginSpec) and cls is not PluginSpec:
            return cls
    return None


class Plugin:
    def __init__(self, package: str, version: str) -> None:
        self.package = package
        self.version = version

    def load(self) -> type[PluginSpec]:
        """Lightweight load: import plugin module and populate PluginHook."""
        module = importlib.import_module(self.package)
        spec = _find_plugin_spec(module)
        if spec is not None:
            hook = PluginHook.instance()
            if spec.rbac is not RBACProvider:
                hook.rbac = spec.rbac
        return spec or PluginSpec

    def load_streamlit(self) -> type[PluginSpec]:
        """Full Streamlit load. Calls load() first, then configure_ui() for UI attributes."""
        spec = self.load()
        spec.configure_ui()
        if spec is not PluginSpec:
            return spec

        # Fallback: discover UI classes from module (backward compat for plugins without explicit PluginSpec)
        _discoverable: dict[type, str] = {Page: "page", Authentication: "auth", Logo: "logo"}
        attrs: dict[str, type] = {}
        module = importlib.import_module(self.package)

        for name in dir(module):
            cls = getattr(module, name, None)
            if not inspect.isclass(cls):
                continue
            for base, attr in _discoverable.items():
                if issubclass(cls, base) and cls is not base:
                    if attr == "page":
                        attrs.setdefault("pages", []).append(cls)
                    else:
                        attrs[attr] = cls

        return type("AnyPlugin", (PluginSpec,), attrs) if attrs else PluginSpec
