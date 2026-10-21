"""What the Export Contract dialog shows for a version of a contract."""

import re
from typing import Any

from testgen.common import contract_service
from testgen.common.models.suite_version import SuiteVersion, format_version, version_state
from testgen.common.models.test_suite import TestSuite


def contract_export(suite: TestSuite, version: int | None) -> dict[str, Any]:
    """The Export Contract dialog's props for one version of a contract.

    :param suite: the contract
    :param version: the version number to export; the draft, else the version in force, when None
    :return: the version's name, its document and download file name, and its validation problems,
        or the reason the document could not be produced
    """
    target = contract_service.version_for_export(suite, version)
    label = format_version(target.version, version_state(target.frozen_at, SuiteVersion.is_active(target.id, suite.id)))
    try:
        exported = contract_service.export_version(target)
    except ValueError as e:
        return {
            "contract": suite.test_suite,
            "version": label,
            "document": None,
            "file_name": None,
            "problems": [],
            "error": str(e),
        }
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", f"{suite.test_suite}_{label}").strip("_")
    return {
        "contract": suite.test_suite,
        "version": label,
        "document": exported.text,
        "file_name": f"{slug}.yaml",
        "problems": exported.problems,
        "error": None,
    }
