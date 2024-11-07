import dataclasses
import inspect
import logging
import typing

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from testgen.ui.components import widgets as testgen
from testgen.ui.navigation.router import Router
from testgen.ui.session import temp_value

ResultsType = typing.TypeVar("ResultsType", bound=typing.Any | None)
StepResults = tuple[typing.Any, bool]
logger = logging.getLogger("testgen")


def wizard(
    *,
    key: str,
    steps: list[typing.Callable[..., StepResults] | "WizardStep"],
    on_complete: typing.Callable[..., bool],
    complete_label: str = "Complete",
    navigate_to: str | None = None,
    navigate_to_args: dict | None = None,
) -> None:
    """
    Creates a Wizard with the provided steps and handles the session for
    each step internally.

    For each step callable instances of WizardStep for the current step
    and previous steps are optionally provided as keyword arguments with
    specific names.

    Optional arguments that can be accessed as follows:

    ```
    def step_fn(current_step: WizardStep = ..., step_0: WizardStep = ...)
        ...
    ```

    For the `on_complete` callable, on top of passing each WizardStep, a
    Streamlit DeltaGenerator is also passed to allow rendering content
    inside the step's body.

    ```
    def on_complete(container: DeltaGenerator, step_0: WizardStep = ..., step_1: WizardStep = ...):
        ...
    ```

    After the `on_complete` callback returns, the wizard state is reset.

    :param key: used to cache current step and results of each step
    :param steps: a list of WizardStep instances or callable objects
    :param on_complete: callable object to execute after the last step.
        should return true to trigger a Streamlit rerun
    :param complete_label: customize the label for the complete button

    :return: None
    """

    if navigate_to:
        Router().navigate(navigate_to, navigate_to_args or {})

    current_step_idx = 0 
    wizard_state = st.session_state.get(key)
    if isinstance(wizard_state, int):
        current_step_idx = wizard_state

    instance = Wizard(
        key=key,
        steps=[
            WizardStep(
                key=f"{key}:{idx}",
                body=step,
                results=st.session_state.get(f"{key}:{idx}", None),
            ) if not isinstance(step, WizardStep) else dataclasses.replace(
                step,
                key=f"{key}:{idx}",
                results=st.session_state.get(f"{key}:{idx}", None),
            )
            for idx, step in enumerate(steps)
        ],
        current_step=current_step_idx,
        on_complete=on_complete,
    )

    current_step = instance.current_step
    current_step_index = instance.current_step_index
    testgen.caption(
        f"Step {current_step_index + 1} of {len(steps)}{': ' + current_step.title if current_step.title else  ''}"
    )

    step_body_container = st.empty()
    with step_body_container.container():
        was_complete_button_clicked, set_complete_button_clicked = temp_value(f"{key}:complete-button")

        if was_complete_button_clicked():
            instance.complete(step_body_container)
        else:
            instance.render()
            button_left_column, _, button_right_column = st.columns([0.30, 0.40, 0.30])
            with button_left_column:
                if not instance.is_first_step():
                    testgen.button(
                        type_="stroked",
                        color="basic",
                        label="Previous",
                        on_click=lambda: instance.previous(),
                        key=f"{key}:button-prev",
                    )

            with button_right_column:
                next_button_label = complete_label if instance.is_last_step() else "Next"

                testgen.button(
                    type_="stroked" if not instance.is_last_step() else "flat",
                    label=next_button_label,
                    on_click=lambda: set_complete_button_clicked(instance.next() or instance.is_last_step()),
                    key=f"{key}:button-next",
                    disabled=not current_step.is_valid,
                )


class Wizard:
    def __init__(
        self,
        *,
        key: str,
        steps: list["WizardStep"],
        on_complete: typing.Callable[..., bool] | None = None,
        current_step: int = 0,
    ) -> None:
        self._key = key
        self._steps = steps
        self._current_step = current_step
        self._on_complete = on_complete

    @property
    def current_step(self) -> "WizardStep":
        return self._steps[self._current_step]

    @property
    def current_step_index(self) -> int:
        return self._current_step

    def next(self) -> None:
        next_step = self._current_step + 1
        if not self.is_last_step():
            st.session_state[self._key] = next_step
            return

    def previous(self) -> None:
        previous_step = self._current_step - 1
        if previous_step > -1:
            st.session_state[self._key] = previous_step

    def is_first_step(self) -> bool:
        return self._current_step == 0

    def is_last_step(self) -> bool:
        return self._current_step == len(self._steps) - 1

    def complete(self, container: DeltaGenerator) -> None:
        if self._on_complete:
            signature = inspect.signature(self._on_complete)
            accepted_params = [param.name for param in signature.parameters.values()]
            kwargs: dict = {
                key: step for idx, step in enumerate(self._steps)
                if (key := f"step_{idx}") and key in accepted_params
            }
            if "container" in accepted_params:
                kwargs["container"] = container

            do_rerun = self._on_complete(**kwargs)
            self._reset()
            if do_rerun:
                st.rerun()

    def _reset(self) -> None:
        del st.session_state[self._key]
        for step_idx in range(len(self._steps)):
            del st.session_state[f"{self._key}:{step_idx}"]

    def render(self) -> None:
        step = self._steps[self._current_step]

        extra_args = {"current_step": step}
        extra_args.update({f"step_{idx}": step for idx, step in enumerate(self._steps)})

        signature = inspect.signature(step.body)
        step_accepted_params = [param.name for param in signature.parameters.values() if param.name in extra_args]
        extra_args = {key: value for key, value in extra_args.items() if key in step_accepted_params}

        try:
            results, is_valid = step.body(**extra_args)
        except TypeError as error:
            logger.exception("Error on wizard step %s", self._current_step, exc_info=True, stack_info=True)
            results, is_valid = None, True

        step.results = results
        step.is_valid = is_valid

        st.session_state[f"{self._key}:{self._current_step}"] = step.results


@dataclasses.dataclass(kw_only=True, slots=True)
class WizardStep(typing.Generic[ResultsType]):
    body: typing.Callable[..., StepResults]
    results: ResultsType = dataclasses.field(default=None)
    title: str = dataclasses.field(default="")
    key: str | None = dataclasses.field(default=None)
    is_valid: bool = dataclasses.field(default=True)
