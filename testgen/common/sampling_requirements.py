from dataclasses import dataclass

from testgen.common.models import with_database_session
from testgen.common.models.hygiene_issue import HygieneIssueType
from testgen.common.models.profile_result import ProfileResult
from testgen.common.models.test_definition import TestType


@dataclass(frozen=True)
class SampledProfileGaps:
    test_types: dict[str, str]
    """Test type code → short name of each active, public test type not generated on a sampled column."""
    hygiene_issues: list[str]
    """Names of the hygiene issue types not raised on a sampled column."""

    def to_props(self) -> dict[str, list[str]]:
        return {"test_types": sorted(self.test_types.values()), "hygiene_issues": self.hygiene_issues}


def requires_exact_label(exact_measures: list[str] | None) -> str | None:
    """Names of the measures that must be exact, in sentence case, or None when the type requires none."""
    if not exact_measures:
        return None
    return ", ".join(ProfileResult.measures[measure].sentence_label for measure in exact_measures)


@with_database_session
def sampled_profile_gaps() -> SampledProfileGaps:
    """The test types and hygiene issue types that a column profiled from a sample cannot support."""
    test_types = {
        tt.test_type: tt.test_name_short or tt.test_type
        for tt in TestType.select_where(TestType.active == "Y", TestType.is_public(), TestType.exact_measures.is_not(None))
        if ProfileResult.taken_from_sample(tt.exact_measures)
    }
    hygiene_issues = sorted(
        issue.name
        for issue in HygieneIssueType.select_where(HygieneIssueType.exact_measures.is_not(None))
        if ProfileResult.taken_from_sample(issue.exact_measures)
    )
    return SampledProfileGaps(test_types=test_types, hygiene_issues=hygiene_issues)
