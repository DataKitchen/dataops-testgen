"""Checks shared by the core and plugin test suites on the profile measures test types read."""

import re

from testgen.common.models.profile_result import ProfileResult


def undeclared_sampled_reads(test_type: dict) -> set[str]:
    """The measures a test type definition reads in its selection criteria or default parameter values
    that a sampled profile takes from the sample, minus those it lists in ``exact_measures`` or names
    in an ``{EXACT:...}`` token.
    """
    criteria = test_type.get("selection_criteria") or ""
    read = set(re.findall(r"[a-z_]+", f"{criteria} {test_type.get('default_parm_values') or ''}"))
    covered = set(test_type.get("exact_measures") or []) | ProfileResult.token_measures(criteria)
    return set(ProfileResult.taken_from_sample(sorted(read))) - covered
