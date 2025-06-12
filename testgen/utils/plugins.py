import dataclasses
import importlib.metadata
import inspect
import json
import os
from collections.abc import Generator
from pathlib import Path
from typing import ClassVar

from testgen.ui.assets import get_asset_path
from testgen.ui.navigation.page import Page

PLUGIN_PREFIX = "testgen_"
ui_plugins_components_directory = (
    Path(__file__).parent.parent / "ui" / "components" / "frontend" / "js" / "plugin_pages"
)
ui_plugins_provision_file = Path(__file__).parent.parent / "ui" / "components" / "frontend" / "js" / "plugins.js"
ui_plugins_entrypoint_prefix = "./plugin_pages"


def discover() -> Generator["Plugin", None, None]:
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


class PluginSpec:
    page: ClassVar[type[Page] | None] = None
    logo: ClassVar[type[Logo] | None] = None
    component: ClassVar[ComponentSpec | None] = None


@dataclasses.dataclass
class Plugin:
    package: str
    version: str

    def load(self) -> PluginSpec:
        plugin_page = None
        plugin_logo = None
        plugin_component_spec = None

        module = importlib.import_module(self.package)
        for property_name in dir(module):
            if ((maybe_class := getattr(module, property_name, None)) and inspect.isclass(maybe_class)):
                if issubclass(maybe_class, PluginSpec):
                    return maybe_class

                if issubclass(maybe_class, Page):
                    plugin_page = maybe_class

                elif issubclass(maybe_class, Logo):
                    plugin_logo = maybe_class

        return type("AnyPlugin", (PluginSpec,), {
            "page": plugin_page,
            "logo": plugin_logo,
            "component": plugin_component_spec,
        })
