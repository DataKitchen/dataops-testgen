from testgen.common.audit.actions import AuditAction
from testgen.common.audit.recorder import created_changes, record
from testgen.common.audit.safety import never_raises
from testgen.common.models.test_suite import MONITOR_SETTING_DEFAULTS, TestSuite

_CONTRACT_FIELDS = tuple(name for name in TestSuite.__audit__.declared() if name not in MONITOR_SETTING_DEFAULTS)


@never_raises()
def record_contract_created(contract: TestSuite) -> None:
    """Record a new contract with the values it holds, other than the monitor settings no contract uses."""
    record(AuditAction.TEST_SUITE_CREATED, contract, changes=created_changes(contract, only=_CONTRACT_FIELDS))
