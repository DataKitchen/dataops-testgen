import importlib
import pkgutil

import pytest

import testgen.common.models
from testgen.common.audit.fields import declaration_errors
from testgen.common.models import Base

pytestmark = pytest.mark.unit


def _declared_models() -> list[type]:
    for module in pkgutil.iter_modules(testgen.common.models.__path__):
        importlib.import_module(f"testgen.common.models.{module.name}")
    return [mapper.class_ for mapper in Base.registry.mappers if hasattr(mapper.class_, "__audit__")]


def test_models_with_recorded_operations_are_declared():
    names = {model.__name__ for model in _declared_models()}
    assert {
        "User", "ProjectMembership", "OAuth2Client", "OAuth2Token", "Project", "Connection", "TableGroup", "TestSuite",
        "JobSchedule", "NotificationSettings", "NotificationDestination", "ScoreDefinition",
    } <= names


@pytest.mark.parametrize("model", _declared_models(), ids=lambda model: model.__name__)
def test_declaration_names_columns_and_never_a_secret_with_values(model):
    assert declaration_errors(model) == []
