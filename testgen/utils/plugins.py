from __future__ import annotations

import dataclasses
import importlib
import importlib.metadata
import inspect
import json
import os
import shutil
from collections.abc import Generator
from pathlib import Path
from types import ModuleType
from typing import ClassVar

from testgen.ui.assets import get_asset_path
from testgen.ui.auth import Authentication
from testgen.ui.navigation.page import Page

PLUGIN_PREFIX = "testgen_"
ui_plugins_components_directory = (
    Path(__file__).parent.parent / "ui" / "components" / "frontend" / "js" / "plugin_pages"
)
ui_plugins_provision_file = Path(__file__).parent.parent / "ui" / "components" / "frontend" / "js" / "plugins.js"
ui_plugins_entrypoint_prefix = "./plugin_pages"


def discover() -> Generator[Plugin, None, None]:
    ui_plugins_provision_file.touch(exist_ok=True)
    for package_path, distribution_names in importlib.metadata.packages_distributions().items():
        if package_path.startswith(PLUGIN_PREFIX):
            yield Plugin(package=package_path, version=importlib.metadata.version(distribution_names[0]))


def cleanup() -> None:
    if ui_plugins_components_directory.exists():
        for item in ui_plugins_components_directory.iterdir():
            if item.is_symlink():
                try:
                    item.unlink()
                except OSError as e:
                    ...
    _reset_ui_plugin_spec()


def _reset_ui_plugin_spec() -> None:
    ui_plugins_provision_file.touch(exist_ok=True)
    ui_plugins_provision_file.write_text("export default {};")


class Logo:
    image_path: str = get_asset_path("dk_logo.svg")
    icon_path: str = get_asset_path("dk_icon.svg")

    def render(self):
        import streamlit as st

        st.logo(
            image=self.image_path,
            icon_image=self.icon_path,
        )


@dataclasses.dataclass
class ComponentSpec:
    name: str
    root: Path
    entrypoint: str

    def provide(self) -> None:
        ui_plugins_components_directory.mkdir(exist_ok=True)

        target  = ui_plugins_components_directory / self.name
        try:
            if target.exists():
                if target.is_symlink():
                    target.unlink()
                else:
                    shutil.rmtree(target)

            try:
                if self.root.is_dir():
                    shutil.copytree(self.root, target)
                else:
                    shutil.copy2(self.root, target)
            except Exception:
                os.symlink(self.root, target)
        except FileExistsError:
            ...
        except OSError as e:
            ...

        plugins_provision: dict = _read_ui_plugin_spec()
        plugins_provision[self.name] = {
            "name": self.name,
            "entrypoint": f"{ui_plugins_entrypoint_prefix}/{self.name}/{self.entrypoint}",
        }
        ui_plugins_provision_file.write_text(f"""export default {json.dumps(plugins_provision, indent=2)};""")


def _read_ui_plugin_spec() -> dict:
    contents = ui_plugins_provision_file.read_text() or "export default {};"
    return json.loads(contents.replace("export default ", "")[:-1])


class RBACProvider:
    """Base RBAC provider. OS default: all permissions granted."""

    @staticmethod
    def check_permission(_user: object, _permission: str) -> bool:
        return True


class PluginSpec:
    rbac: ClassVar[type[RBACProvider]] = RBACProvider
    auth: ClassVar[type[Authentication] | None] = None
    pages: ClassVar[list[type[Page]]] = []
    logo: ClassVar[type[Logo] | None] = None
    component: ClassVar[ComponentSpec | None] = None


class PluginHook:
    """Singleton holding resolved plugin values, pre-loaded with defaults."""

    _instance: PluginHook | None = None
    rbac: type[RBACProvider] = RBACProvider

    @classmethod
    def instance(cls) -> PluginHook:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


def _find_plugin_spec(module: ModuleType) -> type[PluginSpec] | None:
    """Find the first concrete PluginSpec subclass in a module."""
    for name in dir(module):
        cls = getattr(module, name, None)
        if inspect.isclass(cls) and issubclass(cls, PluginSpec) and cls is not PluginSpec:
            return cls
    return None


@dataclasses.dataclass
class Plugin:
    package: str
    version: str

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
        """Full Streamlit load. Calls load() first, then returns spec for UI access."""
        spec = self.load()
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
