"""
Release and CI/CD tasks belong here.
"""

__all__ = ["check_valid_release_type", "ci_dotenv"]


import os

import semver
from invoke.exceptions import Exit
from invoke.tasks import task


@task
def ci_dotenv(ctx):
    """
    This writes out a dotenv file that will set some extra CI variables.
    """

    tag: str | None = os.getenv("CI_COMMIT_TAG", None)
    if tag is None:
        raise Exit("$CI_COMMIT_TAG is not set in the environment. Did you run this in an inappropriate stage?")

    print(f"New tag is '{tag}'")
    try:
        version: semver.Version = semver.Version.parse(tag)
    except (TypeError, ValueError):
        raise Exit(f"Could not parse {tag} as a semver!", code=1) from None

    with open("ci-vars.env", "+w") as f:
        # Will get tagged into all releases in the Major series. So, for tag == 2 and the releases
        # 2.1.0, 2.1.2, and 2.2.3, the user will get 2.2.3
        f.write(f"CI_MAJOR_RELEASE_CHANNEL={version.major}\n")
        # Will get tagged into all releases in the feature series. So, for tag == 2.1 and the releases
        # 2.1.0, 2.1.2, and 2.2.3, the user will get 2.1.2
        f.write(f"CI_MINOR_RELEASE_CHANNEL={version.major}.{version.minor}\n")
        # The full release. So, for tag == 2.1.0 and the releases
        # 2.1.0, 2.1.2, and 2.2.3, the user will get 2.1.0
        f.write(f"CI_IMAGE_RELEASE_VERSION={version}\n")

    print(f"CI_MAJOR_RELEASE_CHANNEL={version.major}")
    print(f"CI_MINOR_RELEASE_CHANNEL={version.major}.{version.minor}")
    print(f"CI_IMAGE_RELEASE_VERSION={version}")


@task
def check_valid_release_type(ctx):
    """Does some sanity checking on RELEASE_TYPE and NEW_RELEASE_VERSION environment variables. Probably overkill."""
    if "RELEASE_TYPE" not in os.environ or os.getenv("RELEASE_TYPE", None) is None:
        raise Exit("The variable 'RELEASE_TYPE' is not set in the environment!", code=1)

    release: str = os.environ["RELEASE_TYPE"]
    if "set-version" in release:
        if "NEW_RELEASE_VERSION" not in os.environ or os.getenv("NEW_RELEASE_VERSION", None) is None:
            raise Exit("The variable 'NEW_RELEASE_VERSION' is not set in the environment!")
        force_version = os.getenv("NEW_RELEASE_VERSION", "")
        try:
            semver.Version = semver.Version.parse(force_version)
        except (ValueError, TypeError):
            raise Exit(
                (
                    "Failed to parse NEW_RELEASE_VERSION as semver."
                    f" Got {force_version}. Did you remember to override it in the job?"
                ),
                code=1,
            ) from None
    else:
        if release not in ("major", "minor", "patch"):
            raise Exit(f"Unsupported release type '{release}'!", code=1)
