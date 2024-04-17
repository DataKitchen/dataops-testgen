__all__ = ["install", "lint", "clean", "build_public_image"]

from os.path import exists, join
from shutil import rmtree, which

import tomli
from invoke import Exit, task

from .toolbox import ensure_tools

DOCKER_BUILDER_NAME = "dk-builder"
DOCKER_BUILDER_PLATFORMS = "linux/amd64,linux/arm64"


@task
def required_tools(ctx):
    ensure_tools("git", "find", "docker")


@task
def install(ctx, quiet_pip=False):
    """Installs the package as a developer (editable, all optional dependencies)."""
    if quiet_pip:
        print("testgen package is being re-installed.")
    ctx.run("pip install -e .[dev]", hide=quiet_pip)


@task
def lint(ctx):
    """Runs the standard suite of quality/linting tools."""
    ctx.run("isort .")
    ctx.run("black .")
    ctx.run("ruff check . --fix --show-fixes")
    print("Lint complete!")


@task
def precommit(ctx, all_files=False):
    """Runs pre-commit."""
    if which("pre-commit") is None:
        install(ctx)
    if not exists(".git/hooks/pre-commit"):
        ctx.run("pre-commit install")

    command = "pre-commit run --all-files" if all_files else "pre-commit run"
    ctx.run(command)


@task(pre=(required_tools,))
def clean(ctx):
    """Deletes old python files and build artifacts"""
    repo_root = ctx.run("git rev-parse --show-toplevel", hide=True).stdout.strip()

    with open(join(repo_root, "pyproject.toml"), "rb") as f:
        project_name: str = tomli.load(f)["project"]["name"]

    ctx.run("find . -type f -name '*.py[co]' -delete -o -type d -name __pycache__ -delete")
    for d in ("dist", "build", f"{project_name}.egg-info"):
        if exists(d):
            rmtree(d)
    print("Cleaning finished!")


@task(pre=(required_tools,))
def build_public_image(ctx, version: str, push=False, local=False):
    """Builds and pushes the TestGen image"""
    use_cmd = f"docker buildx use {DOCKER_BUILDER_NAME}"
    if push and local:
        raise Exit("Cannot use --local and --push at the same time.")

    if not ctx.run(use_cmd, hide=True, warn=True).ok:
        ctx.run(f"docker buildx create --name {DOCKER_BUILDER_NAME} --platform {DOCKER_BUILDER_PLATFORMS}")
        ctx.run(use_cmd)

    extra_args = []
    if push:
        extra_args.append("--push")
    elif local:
        extra_args.extend(("--load", "--set=*.platform=$BUILDPLATFORM"))
    ctx.run(
        f"docker buildx bake -f deploy/docker-bake.json testgen {' '.join(extra_args)} ",
        env={"TESTGEN_VERSION": version},
        echo=True,
    )
