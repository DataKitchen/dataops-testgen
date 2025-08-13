from urllib.parse import quote_plus

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

from testgen.common.database.flavor.flavor_service import FlavorService


class SnowflakeFlavorService(FlavorService):

    def get_connect_args(self):
        if self.connect_by_key:
            # https://docs.snowflake.com/en/developer-guide/python-connector/sqlalchemy#key-pair-authentication-support
            private_key_passphrase = self.private_key_passphrase.encode() if self.private_key_passphrase else None
            private_key = serialization.load_pem_private_key(
                self.private_key.encode(),
                password=private_key_passphrase,
                backend=default_backend(),
            )

            private_key_bytes = private_key.private_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )

            return {"private_key": private_key_bytes}
        return {}

    def get_connection_string_head(self):
        if self.connect_by_key:
            return f"snowflake://{self.username}@"
        else:
            return f"snowflake://{self.username}:{quote_plus(self.password)}@"

    def get_connection_string_from_fields(self):
        # SNOWFLAKE FORMAT:  strConnect = 'flavor://username:password@host/database'
        #   optionally + '/[schema]' + '?warehouse=xxx'
        #   NOTE:  Snowflake host should NOT include ".snowflakecomputing.com"

        def get_raw_host_name(host):
            endings = [
                ".snowflakecomputing.com",
            ]
            for ending in endings:
                if host.endswith(ending):
                    i = host.index(ending)
                    return host[0:i]
            return host

        raw_host = get_raw_host_name(self.host)
        host = raw_host
        if self.port != "443":
            host += ":" + self.port

        if self.connect_by_key:
            return f"snowflake://{self.username}@{host}/{self.dbname}/{self.dbschema}"
        else:
            return f"snowflake://{self.username}:{quote_plus(self.password)}@{host}/{self.dbname}/{self.dbschema}"

    def get_pre_connection_queries(self):
        return [
            ("ALTER SESSION SET MULTI_STATEMENT_COUNT = 0;", None),
            ("ALTER SESSION SET WEEK_START = 7;", None),
        ]
