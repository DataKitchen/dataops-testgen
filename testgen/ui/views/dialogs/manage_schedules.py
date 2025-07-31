import json
import zoneinfo
from datetime import datetime
from typing import Any
from uuid import UUID

import cron_converter
import streamlit as st
from sqlalchemy.exc import IntegrityError

from testgen.common.models import Session, with_database_session
from testgen.common.models.scheduler import JobSchedule
from testgen.ui.components import widgets as testgen
from testgen.ui.components.widgets import tz_select
from testgen.ui.services import user_session_service


class ScheduleDialog:

    title: str = ""
    arg_label: str = ""
    job_key: str = ""

    def __init__(self):
        self.project_code = None

    def init(self) -> None:
        raise NotImplementedError

    def get_arg_value(self, job):
        raise NotImplementedError

    def arg_value_input(self) -> tuple[bool, list[Any], dict[str, Any]]:
        raise NotImplementedError

    @with_database_session
    def open(self, project_code: str) -> None:
        st.session_state["schedule_form_success"] = None
        st.session_state["schedule_cron_expr"] = ""
        self.project_code = project_code
        self.init()
        return st.dialog(title=self.title)(self.render)()

    def render(self) -> None:
        with Session() as db_session:
            scheduled_jobs = (
                db_session.query(JobSchedule)
                .where(JobSchedule.project_code == self.project_code, JobSchedule.key == self.job_key)
            )
            scheduled_jobs_json = []
            for job in scheduled_jobs:
                job_json = {
                    "id": str(job.id),
                    "argValue": self.get_arg_value(job),
                    "cronExpr": job.cron_expr,
                    "cronTz": job.cron_tz_str,
                    "sample": [
                        sample.strftime("%a %b %-d, %-I:%M %p")
                        for sample in job.get_sample_triggering_timestamps(2)
                    ],
                }
                scheduled_jobs_json.append(job_json)

        def on_delete_sched(item):
            with Session() as db_session:
                try:
                    sched, = db_session.query(JobSchedule).where(JobSchedule.id == UUID(item["id"]))
                    db_session.delete(sched)
                except ValueError:
                    db_session.rollback()
                else:
                    db_session.commit()
                    st.rerun(scope="fragment")

        testgen.testgen_component(
            "schedule_list",
            props={
                "items": json.dumps(scheduled_jobs_json),
                "arg_abel": self.arg_label,
                "permissions": {"can_edit": user_session_service.user_can_edit()},
            },
            event_handlers={"DeleteSchedule": on_delete_sched}
        )

        if user_session_service.user_can_edit():
            with st.container(border=True):
                self.add_schedule_form()

    def add_schedule_form(self):
        st.html("<b>Add schedule</b>")
        arg_column, expr_column, tz_column, button_column = st.columns([.3, .4, .3, .1], vertical_alignment="bottom")
        status_container = st.empty()

        with status_container:
            match st.session_state.get("schedule_form_success", None):
                case True:
                    st.success("Schedule added.", icon=":material/check:")
                    st.session_state["schedule_cron_expr"] = ""
                    del st.session_state["schedule_cron_tz"]
                    del st.session_state["schedule_form_success"]
                case False:
                    st.error("This schedule already exists.", icon=":material/block:")
                case None:
                    testgen.whitespace(56, "px")

        with arg_column:
            args_valid, args, kwargs = self.arg_value_input()

        with expr_column:
            cron_expr = st.text_input(
                label="Cron Expression",
                help="Examples: Every day at 6:00 AM: 0 6 * * * &mdash; Every Monday at 5:30 PM: 30 17 * * 1",
                key="schedule_cron_expr",
            )

        with tz_column:
            cron_tz = tz_select(label="Timezone", key="schedule_cron_tz")

        cron_obj = None
        if cron_expr:
            with status_container:
                try:
                    cron_obj = cron_converter.Cron(cron_expr)
                    cron_schedule = cron_obj.schedule(datetime.now(zoneinfo.ZoneInfo(cron_tz)))
                    sample = [cron_schedule.next().strftime("%a %b %-d, %-I:%M %p") for _ in range(3)]
                except ValueError as e:
                    st.warning(str(e), icon=":material/warning:")
                except Exception as e:
                    st.error("Error validating the Cron expression")
                else:
                    # We postpone the validation status update when the previous rerun had a failed
                    # attempt to insert a schedule. This prevents the error message of being overridden
                    if st.session_state.get("schedule_form_success", None) is None:
                        st.info(
                            f"**Next runs:** {' | '.join(sample)} ({cron_tz.replace('_', ' ')})",
                            icon=":material/check:",
                        )
                    else:
                        st.session_state["schedule_form_success"] = None

        is_form_valid = bool(args_valid and cron_obj)
        with button_column:
            add_button = st.button("Add", use_container_width=True, disabled=not is_form_valid)

        # We also check for `is_form_valid` here because apparently it's possible to click a disabled button =)
        if add_button and is_form_valid:
            with Session() as db_session:
                try:
                    sched_model = JobSchedule(
                        project_code=self.project_code,
                        key=self.job_key,
                        cron_expr=cron_obj.to_string(),
                        cron_tz=cron_tz,
                        args=args,
                        kwargs=kwargs,
                    )
                    db_session.add(sched_model)
                    db_session.commit()
                except IntegrityError:
                    st.session_state["schedule_form_success"] = False
                else:
                    st.session_state["schedule_form_success"] = True
            st.rerun(scope="fragment")
