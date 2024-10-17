import typing

import streamlit as st
from pydantic import BaseModel, Field
from pydantic.json_schema import DEFAULT_REF_TEMPLATE, GenerateJsonSchema, JsonSchemaMode
from streamlit.delta_generator import DeltaGenerator
from streamlit_pydantic.ui_renderer import InputUI


class BaseForm(BaseModel):
    def __init__(self, /, **data: typing.Any) -> None:
        super().__init__(**data)

    @classmethod
    def empty(cls) -> typing.Self:
        non_validated_instance = cls.model_construct()
        non_validated_instance.model_post_init(None)

        return non_validated_instance

    @property
    def _disabled_fields(self) -> typing.Set[str]:
        if not getattr(self, "_disabled_fields_set", None):
            self._disabled_fields_set = set()
        return self._disabled_fields_set

    def disable(self, field: str) -> None:
        self._disabled_fields.add(field)

    def enable(self, field) -> None:
        self._disabled_fields.remove(field)

    @classmethod
    def model_json_schema(
        self_or_cls, # type: ignore
        by_alias: bool = True,
        ref_template: str = DEFAULT_REF_TEMPLATE,
        schema_generator: type[GenerateJsonSchema] = GenerateJsonSchema,
        mode: JsonSchemaMode = 'validation',
    ) -> dict[str, typing.Any]:
        schema = super().model_json_schema(
            by_alias=by_alias,
            ref_template=ref_template,
            schema_generator=schema_generator,
            mode=mode,
        )

        schema_properties: dict[str, dict] = schema.get("properties", {})
        disabled_fields: set[str] = getattr(self_or_cls, "_disabled_fields_set", set())
        for property_name, property_schema in schema_properties.items():
            if property_name in disabled_fields and not property_schema.get("readOnly"):
                property_schema["readOnly"] = True

        return schema

    @classmethod
    def get_field_label(cls, field_name: str) -> str:
        schema = cls.model_json_schema()
        schema_properties = schema.get("properties", {})
        field_schema = schema_properties[field_name]
        return field_schema.get("st_kwargs_label") or field_schema.get("title")


class ManualRender:
    @property
    def input_ui(self):
        if not getattr(self, "_input_ui", None):
            self._input_ui = InputUI(
                self.form_key(),
                self,  # type: ignore
                group_optional_fields="no",  # type: ignore
                lowercase_labels=False,
                ignore_empty_values=False,
                return_model=False,
            )
        return self._input_ui

    def form_key(self):
        raise NotImplementedError()

    def render_input_ui(self, container: DeltaGenerator, session_state: dict) -> typing.Self:
        raise NotImplementedError()

    def render_field(self, field_name: str, container: DeltaGenerator | None = None) -> typing.Any:
        streamlit_container = container or self.input_ui._streamlit_container
        model_property = self.input_ui._schema_properties[field_name]
        initial_value = getattr(self, field_name, None) or self.input_ui._get_value(field_name)
        is_disabled = field_name in getattr(self, "_disabled_fields", set())

        if is_disabled:
            model_property["readOnly"] = True

        if model_property.get("type") != "boolean" and initial_value not in [None, ""]:
            model_property["init_value"] = initial_value

        new_value = self.input_ui._render_property(streamlit_container, field_name, model_property)
        self.update_field_value(field_name, new_value)

        return new_value

    def update_field_value(self, field_name: str, value: typing.Any) -> typing.Any:
        self.input_ui._store_value(field_name, value)
        setattr(self, field_name, value)
        return value

    def get_field_value(self, field_name: str, latest: bool = False) -> typing.Any:
        if latest:
            return st.session_state.get(self.get_field_key(field_name))
        return self.input_ui._get_value(field_name)

    def reset_cache(self) -> None:
        for field_name in typing.cast(type[BaseForm], type(self)).model_fields.keys():
            st.session_state.pop(self.get_field_key(field_name), None)
        st.session_state.pop(self.form_key() + "-data", None)

    def get_field_key(self, field_name: str) -> typing.Any:
        return str(self.input_ui._session_state.run_id) + "-" + str(self.input_ui._key) + "-" + field_name
