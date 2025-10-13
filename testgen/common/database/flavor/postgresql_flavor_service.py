from testgen.common.database.flavor.redshift_flavor_service import RedshiftFlavorService


class PostgresqlFlavorService(RedshiftFlavorService):

    escaped_underscore = "\\_"
