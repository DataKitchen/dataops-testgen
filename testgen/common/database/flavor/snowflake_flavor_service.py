from urllib.parse import quote_plus

from testgen.common.database.flavor.flavor_service import FlavorService


class SnowflakeFlavorService(FlavorService):
    def get_connection_string_head(self, dctCredentials, strPW):
        strConnect = "snowflake://{}:{}@".format(dctCredentials["user"], quote_plus(strPW))
        return strConnect

    def get_connection_string_from_fields(self, dctCredentials, strPW):
        # SNOWFLAKE FORMAT:  strConnect = 'flavor://username:password@host/database'
        #   optionally + '/[schema]' + '?warehouse=xxx'
        #   NOTE:  Snowflake host should NOT include ".snowflakecomputing.com"

        def get_raw_host_name(host):
            endings = [
                ".azure.snowflakecomputing.com",
                ".snowflakecomputing.com",
            ]
            for ending in endings:
                if host.endswith(ending):
                    i = host.index(ending)
                    return host[0:i]
            return host

        raw_host = get_raw_host_name(dctCredentials["host"])
        strConnect = "snowflake://{}:{}@{}/{}/{}".format(
            dctCredentials["user"], quote_plus(strPW), raw_host, dctCredentials["dbname"], dctCredentials["dbschema"]
        )
        return strConnect

    def get_pre_connection_queries(self, dctCredentials):  # noqa ARG002
        return [
            "ALTER SESSION SET MULTI_STATEMENT_COUNT = 0;",
            "ALTER SESSION SET WEEK_START = 7;",
        ]
