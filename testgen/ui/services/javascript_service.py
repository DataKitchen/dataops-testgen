import logging

from streamlit_javascript import st_javascript

from testgen.ui.services.user_session_service import AUTH_TOKEN_COOKIE_NAME

LOG = logging.getLogger("testgen")


def copy_to_clipboard(text):
    script = f"""await (async function () {{
        window.parent.postMessage({{ type: 'TestgenCopyToClipboard', text: '{text}' }}, '*');
        return 0;
    }})()
    """
    execute_javascript(script)


def clear_component_states():
    execute_javascript(
        f"""await (async function () {{
            window.parent.postMessage({{ type: 'TestgenLogout', cookie: '{AUTH_TOKEN_COOKIE_NAME}' }}, '*');
            return 0;
        }})()
        """
    )


def execute_javascript(script):
    return_value = st_javascript(script)
    if return_value != 0:
        LOG.warning(f"execute_javascript returned with non zero value: {return_value}, script: {script}")


def get_browser_locale_timezone():
    from streamlit_javascript import st_javascript

    return st_javascript(
        """await (async () => {
                const userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
                console.log(userTimezone)
                return userTimezone
    })().then(returnValue => returnValue)"""
    )
