import dataclasses
import importlib.metadata
import typing

PLUGIN_PREFIX = "testgen_"


def discover() -> typing.Generator["Plugin", None, None]:
    for package_path, distribution_names in importlib.metadata.packages_distributions().items():
        if package_path.startswith(PLUGIN_PREFIX):
            yield Plugin(package=package_path, version=importlib.metadata.version(distribution_names[0]))


@dataclasses.dataclass
class Plugin:
    package: str
    version: str
