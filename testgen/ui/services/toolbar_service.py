from time import sleep

import streamlit as st


class ToolBar:
    slot_count = 5
    toolbar_prompt = None
    action_prompt = None
    help_link = "https://docs.datakitchen.io/article/dataops-testgen-help/dataops-testgen-help"

    long_slots = None
    short_slots = None
    button_slots = None
    status_bar = None
    action_container = None

    def __init__(self, long_slot_count=5, short_slot_count=0, button_slot_count=0, prompt=None, multiline=False):
        self.toolbar_prompt = prompt

        lst_slots_line2 = []
        slots_line2 = None

        # Initialize Toolbar Slots for widgets at right size ratio
        lst_slots_line1 = [10] * long_slot_count
        if multiline:
            lst_slots_line2 = [7] * short_slot_count
            lst_slots_line2 += [2] * button_slot_count
        else:
            lst_slots_line1 += [7] * short_slot_count
            lst_slots_line1 += [2] * button_slot_count

        slots_line1 = st.columns(lst_slots_line1)
        if multiline:
            slots_line2 = st.columns(lst_slots_line2)

        if long_slot_count > 0:
            self.long_slots = slots_line1[:long_slot_count]
        if multiline:
            if short_slot_count > 0:
                self.short_slots = slots_line2[0:short_slot_count]
            if button_slot_count > 0:
                self.button_slots = slots_line2[-1 * button_slot_count :]
        else:
            if short_slot_count > 0:
                self.short_slots = slots_line1[long_slot_count : long_slot_count + short_slot_count]
            if button_slot_count > 0:
                self.button_slots = slots_line1[-1 * button_slot_count :]

        # Add vertical space to short slots
        for i in range(short_slot_count):
            self.short_slots[i].markdown("</p>&nbsp;</br>", unsafe_allow_html=True)

        # Add vertical space to button slots
        for i in range(button_slot_count):
            self.button_slots[i].markdown("</p>&nbsp;</br>", unsafe_allow_html=True)

        self.status_bar = st.empty()
        self.set_prompt()

    def set_prompt(self, str_new_prompt=None):
        str_prompt = self.toolbar_prompt if str_new_prompt is None else str_new_prompt
        if str_prompt:
            self.toolbar_prompt = str_prompt
            self.status_bar.markdown(f":green[**{str_prompt}**]")
        else:
            self.status_bar.empty()

    def show_status(self, str_message, str_type):
        if str_type == "success":
            self.status_bar.success(str_message, icon="✅")
        elif str_type == "error":
            self.status_bar.error(str_message, icon="❌")
        elif str_type == "info":
            self.status_bar.info(str_message, icon="💡")
        sleep(2)
        self.set_prompt()
