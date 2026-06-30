import pytest
from sqlalchemy.dialects.postgresql import dialect as pg_dialect

from testgen.common.models.test_definition import StatisticalTechnique, TestAlgorithm, TestType

pytestmark = pytest.mark.unit

DIALECT = pg_dialect()


@pytest.mark.parametrize(
    ("column_name", "enum_cls", "member"),
    [
        ("algorithm", TestAlgorithm, TestAlgorithm.BOUNDARY_CHECK),
        ("statistical_technique", StatisticalTechnique, StatisticalTechnique.COHENS_D),
    ],
)
def test_enum_column_reads_db_value_as_enum_member(column_name, enum_cls, member):
    column_type = TestType.__table__.c[column_name].type
    process = column_type.result_processor(DIALECT, None)

    result = process(member.value)

    assert result is member
    assert isinstance(result, enum_cls)


@pytest.mark.parametrize(
    ("column_name", "member"),
    [
        ("algorithm", TestAlgorithm.STATISTICAL_DRIFT),
        ("statistical_technique", StatisticalTechnique.JENSEN_SHANNON_DIVERGENCE),
    ],
)
def test_enum_column_writes_enum_as_db_value(column_name, member):
    column_type = TestType.__table__.c[column_name].type
    process = column_type.bind_processor(DIALECT)

    assert process(member) == member.value


@pytest.mark.parametrize("column_name", ["algorithm", "statistical_technique"])
def test_enum_column_round_trips_none(column_name):
    column_type = TestType.__table__.c[column_name].type
    read = column_type.result_processor(DIALECT, None)
    write = column_type.bind_processor(DIALECT)

    assert read(None) is None
    assert write(None) is None
