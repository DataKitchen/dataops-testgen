# type: ignore
import base64
import typing

import streamlit as st
from pydantic import computed_field
from streamlit.delta_generator import DeltaGenerator

from testgen.ui.components import widgets as testgen
from testgen.ui.forms import BaseForm, Field, ManualRender
from testgen.ui.services import connection_service

SQL_FLAVORS = ["redshift", "snowflake", "mssql", "postgresql"]
SQLFlavor = typing.Literal["redshift", "snowflake", "mssql", "postgresql"]


class BaseConnectionForm(BaseForm, ManualRender):
    connection_name: str = Field(
        default="",
        min_length=3,
        max_length=40,
        st_kwargs_max_chars=40,
        st_kwargs_label="Connection Name",
        st_kwargs_help="Your name for this connection. Can be any text.",
    )
    project_host: str = Field(
        default="",
        max_length=250,
        st_kwargs_max_chars=250,
        st_kwargs_label="Host",
    )
    project_port: str = Field(default="", max_length=5, st_kwargs_max_chars=5, st_kwargs_label="Port")
    project_db: str = Field(
        default="",
        max_length=100,
        st_kwargs_max_chars=100,
        st_kwargs_label="Database",
        st_kwargs_help="The name of the database defined on your host where your schemas and tables is present.",
    )
    project_user: str = Field(
        default="",
        max_length=50,
        st_kwargs_max_chars=50,
        st_kwargs_label="User",
        st_kwargs_help="Username to connect to your database.",
    )
    connect_by_url: bool = Field(
        default=False,
        st_kwargs_label="URL override",
        st_kwargs_help=(
            "If this switch is set to on, the connection string will be driven by the field below. "
            "Only user name and password will be passed per the relevant fields above."
        ),
    )
    url_prefix: str = Field(
        default="",
        readOnly=True,
        st_kwargs_label="URL Prefix",
    )
    url: str = Field(
        default="",
        max_length=200,
        st_kwargs_label="URL Suffix",
        st_kwargs_max_chars=200,
        st_kwargs_help=(
            "Provide a connection string directly. This will override connection parameters if "
            "the 'Connect by URL' switch is set."
        ),
    )
    max_threads: int = Field(
        default=4,
        ge=1,
        le=8,
        st_kwargs_min_value=1,
        st_kwargs_max_value=8,
        st_kwargs_label="Max Threads (Advanced Tuning)",
        st_kwargs_help=(
            "Maximum number of concurrent threads that run tests. Default values should be retained unless "
            "test queries are failing."
        ),
    )
    max_query_chars: int = Field(
        default=10000,
        ge=500,
        le=14000,
        st_kwargs_label="Max Expression Length (Advanced Tuning)",
        st_kwargs_min_value=500,
        st_kwargs_max_value=14000,
        st_kwargs_help=(
            "Some tests are consolidated into queries for maximum performance. Default values should be retained "
            "unless test queries are failing."
        ),
    )
    project_qc_schema: str = Field(
        default="qc",
        max_length=50,
        st_kwargs_label="QC Utility Schema",
        st_kwargs_max_chars=50,
        st_kwargs_help="The name of the schema on your database that will contain TestGen's profiling functions.",
    )

    connection_id: int | None = Field(default=None)

    sql_flavor: SQLFlavor = Field(
        ...,
        st_kwargs_label="SQL Flavor",
        st_kwargs_options=SQL_FLAVORS,
        st_kwargs_help=(
            "The type of database server that you will connect to. This determines TestGen's drivers and SQL dialect."
        ),
    )

    def form_key(self):
        return f"connection_form:{self.connection_id or 'new'}"

    def render_input_ui(self, container: DeltaGenerator, data: dict) -> "BaseConnectionForm":
        main_fields_container, optional_fields_container = container.columns([0.7, 0.3])

        if self.get_field_value("connect_by_url", latest=True):
            self.disable("project_host")
            self.disable("project_port")
            self.disable("project_db")

        self.render_field("sql_flavor", container=main_fields_container)
        self.render_field("connection_name", container=main_fields_container)
        host_field_container, port_field_container = main_fields_container.columns([0.6, 0.4])
        self.render_field("project_host", container=host_field_container)
        self.render_field("project_port", container=port_field_container)

        self.render_field("project_db", container=main_fields_container)
        self.render_field("project_user", container=main_fields_container)
        self.render_field("project_qc_schema", container=optional_fields_container)
        self.render_field("max_threads", container=optional_fields_container)
        self.render_field("max_query_chars", container=optional_fields_container)

        self.render_extra(container, main_fields_container, optional_fields_container, data)

        testgen.divider(margin_top=8, margin_bottom=8, container=container)

        self.url_prefix = data.get("url_prefix", "")
        self.render_field("connect_by_url")
        if self.connect_by_url:
            connection_string = connection_service.form_overwritten_connection_url(data)
            connection_string_beginning, connection_string_end = connection_string.split("@", 1)

            self.update_field_value(
                "url_prefix",
                f"{connection_string_beginning}@".replace("%3E", ">").replace("%3C", "<"),
            )
            if not data.get("url", ""):
                self.update_field_value("url", connection_string_end)

            url_override_left_column, url_override_right_column = st.columns([0.25, 0.75])
            self.render_field("url_prefix", container=url_override_left_column)
            self.render_field("url", container=url_override_right_column)

        return self

    def render_extra(
        self,
        _container: DeltaGenerator,
        _left_fields_container: DeltaGenerator,
        _right_fields_container: DeltaGenerator,
        _data: dict,
    ) -> None:
        ...

    @staticmethod
    def for_flavor(flavor: SQLFlavor) -> type["BaseConnectionForm"]:
        return {
            "redshift": PasswordConnectionForm,
            "snowflake": KeyPairConnectionForm,
            "mssql": PasswordConnectionForm,
            "postgresql": PasswordConnectionForm,
        }[flavor]


class PasswordConnectionForm(BaseConnectionForm):
    password: str = Field(
        default="",
        max_length=50,
        writeOnly=True,
        st_kwargs_label="Password",
        st_kwargs_max_chars=50,
        st_kwargs_help="Password to connect to your database.",
    )

    def render_extra(
        self,
        _container: DeltaGenerator,
        left_fields_container: DeltaGenerator,
        _right_fields_container: DeltaGenerator,
        _data: dict,
    ) -> None:
        self.render_field("password", left_fields_container)


class KeyPairConnectionForm(PasswordConnectionForm):
    connect_by_key: bool = Field(default=None)
    private_key_passphrase: str = Field(
        default="",
        max_length=200,
        writeOnly=True,
        st_kwargs_max_chars=200,
        st_kwargs_help=(
            "Passphrase used while creating the private Key (leave empty if not applicable)"
        ),
        st_kwargs_label="Private Key Passphrase",
    )
    private_key_inner: str = Field(
        default="",
        format="base64",
        st_kwargs_label="Upload private key (rsa_key.p8)",
    )

    @computed_field
    @property
    def private_key(self) -> str:
        if not self.private_key_inner:
            return ""
        return base64.b64decode(self.private_key_inner).decode("utf-8")

    def render_extra(
        self,
        container: DeltaGenerator,
        _left_fields_container: DeltaGenerator,
        _right_fields_container: DeltaGenerator,
        _data: dict,
    ) -> None:
        testgen.divider(margin_top=8, margin_bottom=8, container=container)

        connect_by_key = self.connect_by_key
        if connect_by_key is None:
            connect_by_key = self.get_field_value("connect_by_key")

        connection_option: typing.Literal["Connect by Password", "Connect by Key-Pair"] = container.radio(
            "Connection options",
            options=["Connect by Password", "Connect by Key-Pair"],
            index=1 if connect_by_key else 0,
            horizontal=True,
            help="Connection strategy",
            key=self.get_field_key("connection_option"),
        )
        self.update_field_value("connect_by_key", connection_option == "Connect by Key-Pair")

        if connection_option == "Connect by Password":
            self.render_field("password", container)
        else:
            self.render_field("private_key_passphrase", container)
            self.render_field("private_key_inner", container)
