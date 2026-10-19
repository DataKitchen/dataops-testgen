"""Creating a contract: add the suite, initialize its first draft, then generate or import its terms."""

import logging
from dataclasses import dataclass
from uuid import UUID

from testgen.commands.test_generation import ContractGenerationResult, run_contract_generation
from testgen.common.contract_import import ContractImportPlan, apply_import
from testgen.common.contract_service import initialize_contract
from testgen.common.flavors import SqlFlavorCode
from testgen.common.models import get_current_session
from testgen.common.models.connection import Connection
from testgen.common.models.table_group import TableGroup
from testgen.common.models.test_suite import TestSuite
from testgen.common.odcs.servers import CustomServerReason

LOG = logging.getLogger("testgen")


@dataclass(frozen=True)
class ContractCreation:
    suite: TestSuite
    custom_server_reason: CustomServerReason | None
    generation: ContractGenerationResult | None
    generation_failed: bool


@dataclass(frozen=True)
class ContractImportCreation:
    suite: TestSuite
    custom_server_reason: CustomServerReason | None
    version_id: UUID
    conformance_failed: bool


def create_contract(
    suite: TestSuite, table_group: TableGroup, connection: Connection, table_names: list[str] | None
) -> ContractCreation:
    """Create ``suite`` as a contract with its first draft and, when ``table_names`` is given,
    declare those tables and generate the draft from them.

    The contract is committed before generation, so a generation failure rolls back to it and
    leaves a contract that exists. The failure is logged and reported in the result rather than raised.
    """
    session = get_current_session()
    session.add(suite)
    session.flush()
    initialized = initialize_contract(suite, table_group, connection)
    generation = None
    generation_failed = False
    if table_names:
        session.commit()
        try:
            generation = run_contract_generation(suite.id, table_names=list(dict.fromkeys(table_names)))
        except Exception:
            LOG.exception(f"Generating contract {suite.id} failed")
            session.rollback()
            generation_failed = True
    return ContractCreation(
        suite=suite,
        custom_server_reason=initialized.custom_server_reason,
        generation=generation,
        generation_failed=generation_failed,
    )


def create_contract_from_import(
    suite: TestSuite, table_group: TableGroup, connection: Connection, plan: ContractImportPlan
) -> ContractImportCreation:
    """Create ``suite`` as a contract and write ``plan`` to its first draft.

    The import is applied with ``apply_import``, which commits the session.
    """
    session = get_current_session()
    session.add(suite)
    session.flush()
    initialized = initialize_contract(suite, table_group, connection)
    applied = apply_import(plan, suite, table_group, SqlFlavorCode(connection.sql_flavor_code))
    return ContractImportCreation(
        suite=suite,
        custom_server_reason=initialized.custom_server_reason,
        version_id=applied.version_id,
        conformance_failed=applied.conformance_failed,
    )
