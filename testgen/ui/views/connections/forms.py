# type: ignore
import time
import typing

import streamlit as st
from streamlit.delta_generator import DeltaGenerator
from streamlit.runtime.uploaded_file_manager import UploadedFile

from testgen.ui.components import widgets as testgen
from testgen.ui.forms import BaseForm, Field, ManualRender, computed_field
from testgen.ui.services import connection_service

SQL_FLAVORS = ["redshift", "snowflake", "mssql", "postgresql", "databricks"]
SQLFlavor = typing.Literal["redshift", "snowflake", "mssql", "postgresql", "databricks"]


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
        default=9000,
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
        time.sleep(0.1)
        main_fields_container, optional_fields_container = container.columns([0.7, 0.3])

        if self.get_field_value("connect_by_url", latest=True):
            self.disable("project_host")
            self.disable("project_port")
            self.disable("project_db")

        self.render_field("sql_flavor", container=main_fields_container)
        self.render_field("connection_name", container=main_fields_container)
        host_field_container, port_field_container = main_fields_container.columns([0.8, 0.2])
        self.render_field("project_host", container=host_field_container)
        self.render_field("project_port", container=port_field_container)

        self.render_field("project_db", container=main_fields_container)
        self.render_field("project_user", container=main_fields_container)
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

            time.sleep(0.1)

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
    def set_default_port(sql_flavor: SQLFlavor, form: type["BaseConnectionForm"]) -> None:
        if sql_flavor == "mssql":
            form.project_port = 1433
        elif sql_flavor == "redshift":
            form.project_port = 5439
        elif sql_flavor == "postgresql":
            form.project_port = 5432
        elif sql_flavor == "snowflake":
            form.project_port = 443
        elif sql_flavor == "databricks":
            form.project_port = 443

    @staticmethod
    def for_flavor(flavor: SQLFlavor) -> type["BaseConnectionForm"]:
        return {
            "redshift": PasswordConnectionForm,
            "snowflake": KeyPairConnectionForm,
            "mssql": PasswordConnectionForm,
            "postgresql": PasswordConnectionForm,
            "databricks": HttpPathConnectionForm,
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


class HttpPathConnectionForm(PasswordConnectionForm):
    http_path: str = Field(
        default="",
        max_length=200,
        st_kwargs_label="HTTP Path",
        st_kwargs_max_chars=50,
    )

    def render_extra(
        self,
        _container: DeltaGenerator,
        left_fields_container: DeltaGenerator,
        _right_fields_container: DeltaGenerator,
        _data: dict,
    ) -> None:
        super().render_extra(_container, left_fields_container, _right_fields_container, _data)
        self.render_field("http_path", left_fields_container)


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
    _uploaded_file: UploadedFile | None = None

    @computed_field(default="")
    def private_key(self) -> str:
        if self._uploaded_file is None:
            return ""

        file_contents: bytes = self._uploaded_file.getvalue()
        return file_contents.decode("utf-8")

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

            file_uploader_key = self.get_field_key("private_key_uploader")
            cached_file_upload_key = self.get_field_key("previous_private_key_file")

            self._uploaded_file = container.file_uploader(
                key=file_uploader_key,
                label="Upload private key (rsa_key.p8)",
                accept_multiple_files=False,
                on_change=lambda: st.session_state.pop(cached_file_upload_key, None),
            )

            if self._uploaded_file:
                st.session_state[cached_file_upload_key] = self._uploaded_file
            elif self._uploaded_file is None and (cached_file_upload := st.session_state.get(cached_file_upload_key)):
                self._uploaded_file = cached_file_upload
                file_size = f"{round(self._uploaded_file.size / 1024, 2)}KB"
                container.markdown(
                    f"""
                    <div style="display: flex; align-items: center; justify-content: flex-start; padding: 0 16px; margin-bottom: 16px;">
                        <span style="font-family: 'Material Symbols Rounded'; font-weight: normal; white-space: nowrap; overflow-wrap: normal; font-size: 28.8px; color: rgb(151, 166, 195);">draft</span>
                        <span style="margin-left: 16px; margin-right: 8px;">{self._uploaded_file.name}</span>
                        <small style='color: rgba(49, 51, 63, 0.6); font-size: 14px; line-height: 1.25;'>{file_size}</small>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    def reset_cache(self) -> None:
        st.session_state.pop(self.get_field_key("private_key_uploader"), None)
        st.session_state.pop(self.get_field_key("previous_private_key_file"), None)
        return super().reset_cache()
