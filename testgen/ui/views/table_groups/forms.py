# type: ignore
import typing

from streamlit.delta_generator import DeltaGenerator

from testgen.ui.forms import BaseForm, Field, ManualRender

SQLFlavor = typing.Literal["redshift", "snowflake", "mssql", "postgresql"]


class TableGroupForm(BaseForm, ManualRender):
    table_groups_name: str = Field(
        default="",
        min_length=1,
        max_length=40,
        st_kwargs_label="Table Group Name",
        st_kwargs_max_chars=40,
        st_kwargs_help="A unique name to describe the table group",
    )
    profiling_include_mask: str = Field(
        default="%",
        max_length=40,
        st_kwargs_label="Tables to Include Mask",
        st_kwargs_max_chars=40,
        st_kwargs_help="A SQL filter supported by your database's LIKE operator for table names to include",
    )
    profiling_exclude_mask: str = Field(
        default="tmp%",
        st_kwargs_label="Tables to Exclude Mask",
        st_kwargs_max_chars=40,
        st_kwargs_help="A SQL filter supported by your database's LIKE operator for table names to exclude",
    )
    profiling_table_set: str = Field(
        default="",
        st_kwargs_label="Explicit Table List",
        st_kwargs_max_chars=2000,
        st_kwargs_help="A list of specific table names to include, separated by commas",
    )
    table_group_schema: str = Field(
        default="",
        min_length=1,
        max_length=40,
        st_kwargs_label="Schema",
        st_kwargs_max_chars=40,
        st_kwargs_help="The database schema containing the tables in the Table Group",
    )
    profile_id_column_mask: str = Field(
        default="%_id",
        st_kwargs_label="Profiling ID column mask",
        st_kwargs_max_chars=40,
        st_kwargs_help="A SQL filter supported by your database's LIKE operator representing ID columns (optional)",
    )
    profile_sk_column_mask: str = Field(
        default="%_sk",
        st_kwargs_label="Profiling Surrogate Key column mask",
        st_kwargs_max_chars=40,
        st_kwargs_help="A SQL filter supported by your database's LIKE operator representing surrogate key columns (optional)",
    )
    profiling_delay_days: int = Field(
        default=0,
        st_kwargs_label="Min Profiling Age, Days",
        st_kwargs_min_value=0,
        st_kwargs_max_value=999,
        st_kwargs_help="The number of days to wait before new profiling will be available to generate tests",
    )
    profile_flag_cdes: bool = Field(
        default=True,
        st_kwargs_label="Detect critical data elements (CDEs) during profiling",
    )
    add_scorecard_definition: bool = Field(
        default=True,
        st_kwargs_label="Add scorecard for table group",
        st_kwargs_help="Add a new scorecard to the Quality Dashboard upon creation of this table group",
    )
    profile_use_sampling: bool = Field(
        default=True,
        st_kwargs_label="Use profile sampling",
        st_kwargs_help="Toggle on to base profiling on a sample of records instead of the full table",
    )
    profile_sample_percent: int = Field(
        default=30,
        st_kwargs_label="Sample percent",
        st_kwargs_min_value=1,
        st_kwargs_max_value=100,
        st_kwargs_help="Percent of records to include in the sample, unless the calculated count falls below the specified minimum.",
    )
    profile_sample_min_count: int = Field(
        default=15000,
        st_kwargs_label="Min Sample Record Count",
        st_kwargs_min_value=1,
        st_kwargs_max_value=1000000,
        st_kwargs_help="The minimum number of records to be included in any sample (if available)",
    )
    description: str = Field(
        default="",
        st_kwargs_label="Description",
        st_kwargs_max_chars=1000,
        st_kwargs_help="",
    )
    data_source: str = Field(
        default="",
        st_kwargs_label="Data Source",
        st_kwargs_max_chars=40,
        st_kwargs_help="Original source of the dataset",
    )
    source_system: str = Field(
        default="",
        st_kwargs_label="Source System",
        st_kwargs_max_chars=40,
        st_kwargs_help="Enterprise system source for the dataset",
    )
    source_process: str = Field(
        default="",
        st_kwargs_label="Source Process",
        st_kwargs_max_chars=40,
        st_kwargs_help="Process, program, or data flow that produced the dataset",
    )
    data_location: str = Field(
        default="",
        st_kwargs_label="Location",
        st_kwargs_max_chars=40,
        st_kwargs_help="Physical or virtual location of the dataset, e.g., Headquarters, Cloud",
    )
    business_domain: str = Field(
        default="",
        st_kwargs_label="Business Domain",
        st_kwargs_max_chars=40,
        st_kwargs_help="Business division responsible for the dataset, e.g., Finance, Sales, Manufacturing",
    )
    stakeholder_group: str = Field(
        default="",
        st_kwargs_label="Stakeholder Group",
        st_kwargs_max_chars=40,
        st_kwargs_help="Data owners or stakeholders responsible for the dataset",
    )
    transform_level: str = Field(
        default="",
        st_kwargs_label="Transform Level",
        st_kwargs_max_chars=40,
        st_kwargs_help="Data warehouse processing stage, e.g., Raw, Conformed, Processed, Reporting, or Medallion level (bronze, silver, gold)",
    )
    data_product: str = Field(
        default="",
        st_kwargs_label="Data Product",
        st_kwargs_max_chars=40,
        st_kwargs_help="Data domain that comprises the dataset",
    )
    table_group_id: int | None = Field(default=None)

    def form_key(self):
        return f"table_group_form:{self.table_group_id or 'new'}"

    def render_input_ui(self, container: DeltaGenerator, _: dict) -> "TableGroupForm":
        left_column, right_column = container.columns([.5, .5])

        self.render_field("table_groups_name", left_column)
        self.render_field("profiling_include_mask", left_column)
        self.render_field("profiling_exclude_mask", left_column)
        self.render_field("profiling_table_set", left_column)
        self.render_field("profile_flag_cdes", left_column)

        self.render_field("table_group_schema", right_column)
        self.render_field("profile_id_column_mask", right_column)
        self.render_field("profile_sk_column_mask", right_column)
        self.render_field("profiling_delay_days", right_column)

        if not self.table_group_id:
            self.render_field("add_scorecard_definition", right_column)

        self.render_field("profile_use_sampling", container)
        profile_sampling_expander = container.expander("Sampling Parameters", expanded=False)
        with profile_sampling_expander:
            expander_left_column, expander_right_column = profile_sampling_expander.columns([0.50, 0.50])
        self.render_field("profile_sample_percent", expander_left_column)
        self.render_field("profile_sample_min_count", expander_right_column)

        tags_expander = container.expander("Table Group Tags", expanded=False)
        with tags_expander:
            self.render_field("description", tags_expander)
            tags_left_column, tags_right_column = tags_expander.columns([0.50, 0.50])

        self.render_field("data_source", tags_left_column)
        self.render_field("source_system", tags_right_column)
        self.render_field("source_process", tags_left_column)
        self.render_field("data_location", tags_right_column)
        self.render_field("business_domain", tags_left_column)
        self.render_field("stakeholder_group", tags_right_column)
        self.render_field("transform_level", tags_left_column)
        self.render_field("data_product", tags_right_column)

        return self
