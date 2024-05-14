from shutil import which

from invoke.exceptions import Exit


def ensure_tools(*tools: str) -> None:
    """
    Check the PATH to see if the required tools exist. e.g.,

    ensure_tools("git", "bash")
    """
    result = [f"ERROR: Required tool '{tool}' is not installed on your path." for tool in tools if which(tool) is None]
    if result:
        raise Exit(message="\n".join(msg for msg in result), code=1)
