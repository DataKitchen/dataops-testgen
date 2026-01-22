import os

from setuptools import setup
from setuptools.command.build_py import build_py

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_TOML = os.path.abspath(os.path.join(THIS_DIR, "pyproject.toml"))

class CustomBuildPy(build_py):
    def run(self):
        super().run()
        target_toml = os.path.join(self.build_lib, "testgen", "pyproject.toml")
        if os.path.exists(ROOT_TOML):
            os.makedirs(os.path.dirname(target_toml), exist_ok=True)
            self.copy_file(ROOT_TOML, target_toml)


setup(
    cmdclass={
        "build_py": CustomBuildPy,
    },
)
