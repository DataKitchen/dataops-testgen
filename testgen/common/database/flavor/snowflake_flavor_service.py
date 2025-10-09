from urllib.parse import quote_plus

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from snowflake.sqlalchemy import URL

from testgen.common.database.flavor.flavor_service import FlavorService


class SnowflakeFlavorService(FlavorService):

    escaped_underscore = "\\\\_"
    escape_clause = "ESCAPE '\\\\'"
    default_uppercase = True

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

        account, _ = self.host.split(".", maxsplit=1) if "." in self.host else ("", "")
        host = self.host
        if ".snowflakecomputing.com" not in host:
            host = f"{host}.snowflakecomputing.com"

        extra_params = {}
        if self.warehouse:
            extra_params["warehouse"] = self.warehouse

        connection_url = URL(
            host=host,
            port=int(self.port if str(self.port).isdigit() else 443),
            account=account,
            user=self.username,
            password="" if self.connect_by_key else self.password,
            database=self.dbname,
            schema=self.dbschema or "",
            **extra_params,
        )

        return connection_url

    def get_pre_connection_queries(self):
        return [
            ("ALTER SESSION SET MULTI_STATEMENT_COUNT = 0;", None),
            ("ALTER SESSION SET WEEK_START = 7;", None),
        ]
