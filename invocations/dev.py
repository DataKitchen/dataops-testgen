__all__ = ["build_public_image", "clean", "install", "lint"]

import re
from os.path import exists, join
from shutil import rmtree, which
from typing import Literal

import tomli
from invoke.context import Context
from invoke.exceptions import Exit
from invoke.tasks import task

from .toolbox import ensure_tools

DOCKER_BUILDER_NAME = "dk-builder"
DOCKER_BUILDER_PLATFORMS = "linux/amd64,linux/arm64"

@task
def required_tools(ctx: Context) -> None:
    ensure_tools("git", "find", "docker")

@task
def prep_dk_builer(ctx: Context) -> None:
    use_cmd = f"docker buildx use {DOCKER_BUILDER_NAME}"
    if (result := ctx.run(use_cmd, hide=True, warn=True)) and not result.ok:
        ctx.run(f"docker buildx create --name {DOCKER_BUILDER_NAME} --platform {DOCKER_BUILDER_PLATFORMS}")
        ctx.run(use_cmd)


@task
def install(ctx: Context, quiet_pip: bool = False) -> None:
    """Installs the package as a developer (editable, all optional dependencies)."""
    if quiet_pip:
        print("testgen package is being re-installed.")
    ctx.run("pip install -e .[dev]", hide=quiet_pip)


@task
def lint(ctx: Context) -> None:
    """Runs the standard suite of quality/linting tools."""
    ctx.run("ruff check . --fix --show-fixes")
    print("Lint complete!")


@task
def precommit(ctx: Context, all_files: bool = False) -> None:
    """Runs pre-commit."""
    if which("pre-commit") is None:
        install(ctx)
    if not exists(".git/hooks/pre-commit"):
        ctx.run("pre-commit install")

    command = "pre-commit run --all-files" if all_files else "pre-commit run"
    ctx.run(command)


@task(pre=(required_tools,))
def clean(ctx: Context) -> None:
    """Deletes old python files and build artifacts"""
    result = ctx.run("git rev-parse --show-toplevel", hide=True)
    if not result:
        raise Exit("Failure running git rev-parse")

    repo_root = result.stdout.strip()
    with open(join(repo_root, "pyproject.toml"), "rb") as f:
        project_name: str = tomli.load(f)["project"]["name"]

    ctx.run("find . -type f -name '*.py[co]' -delete -o -type d -name __pycache__ -delete")
    for d in ("dist", "build", f"{project_name}.egg-info"):
        if exists(d):
            rmtree(d)
    print("Cleaning finished!")


@task(
    pre=(required_tools, prep_dk_builer),
    iterable=["label"],
    help={
        "target": "Docker bake target. Valid values are: base, qa, release",
        "label": "Image label. The repository is pre-determined by the target. Set more than one to push multiple tags.",
        "load": "Load locally instead of pushing",
        "base_label": "TestGen's base image tag to be used to build TestGen's images",
        "version": "TestGen's version to be considered to generate the lables",
    })
def build_public_image(
    ctx: Context,
    target: Literal["base", "qa", "release"],
    label: list[str],
    version: str = "",

    load: bool = False,
    base_label: str = "",
    debug: bool = False
) -> None:
    """Builds and pushes the TestGen image"""

    valid_targets = ("base", "qa", "release")
    if target not in valid_targets:
        raise Exit(f"--target must be one of [{', '.join(valid_targets)}].")

    if (label and version) or not (label or version):
        raise Exit("Exactly one argument should be set for [label] or [version]")

    if version:
        if match := re.match(r"(\d+)\.(\d+)\.(\d+)", version):
            major, minor, patch = match.groups()
            label = [f"v{major}.{minor}.{patch}", f"v{major}.{minor}", f"v{major}"]
        else:
            raise Exit("Version has to be in <major>.<minor>.<patch> format")

    extra_args = ["--load", "--set=*.platform=$BUILDPLATFORM"] if load else ["--push"]
    if debug:
        extra_args.append("--print")

    env={
        "TESTGEN_LABELS": " ".join(label),
        "TESTGEN_VERSION": version,
    }
    if base_label:
        env["TESTGEN_BASE_LABEL"] = base_label

    cmd = f"docker buildx bake -f deploy/docker-bake.hcl testgen-{target} {' '.join(extra_args)} "
    ctx.run(cmd, env=env, echo=True)
