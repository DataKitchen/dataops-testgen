import logging

from streamlit_javascript import st_javascript

LOG = logging.getLogger("testgen")


def execute_javascript(script):
    return_value = st_javascript(script)
    if return_value != 0:
        LOG.warning(f"execute_javascript returned with non zero value: {return_value}, script: {script}")


def get_browser_locale_timezone():
    from streamlit_javascript import st_javascript

    return st_javascript(
        """await (async () => {
                const userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
                return userTimezone
    })().then(returnValue => returnValue)"""
    )
