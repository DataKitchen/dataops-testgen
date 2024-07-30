"""
Streamlit component's callbacks are broken for CustomComponents, this is
a temporary patch picked up from the internet.

https://gist.github.com/okld/1a2b2fd2cb9f85fc8c4e92e26c6597d5
"""

import logging

from streamlit import session_state
from streamlit.components.v1 import components

LOG = logging.getLogger("testgen")


def _patch_register_widget(register_widget):
    def wrapper_register_widget(*args, **kwargs):
        user_key = kwargs.get("user_key", None)
        callbacks = session_state.get("_components_callbacks", None)

        # Check if a callback was registered for that user_key.
        if user_key and callbacks and user_key in callbacks:
            callback = callbacks[user_key]

            # Add callback-specific args for the real register_widget function.
            kwargs["on_change_handler"] = callback[0]
            kwargs["args"] = callback[1]
            kwargs["kwargs"] = callback[2]

        # Call the original function with updated kwargs.
        return register_widget(*args, **kwargs)

    return wrapper_register_widget


# Patch function only once.
if not hasattr(components.register_widget, "__callbacks_patched__"):
    components.register_widget.__callbacks_patched__ = True
    components.register_widget = _patch_register_widget(components.register_widget)


def register_callback(element_key, callback, *callback_args, **callback_kwargs):
    # Initialize callbacks store.
    if "_components_callbacks" not in session_state:
        session_state._components_callbacks = {}

    # Register a callback for a given element_key.
    try:
        session_state._components_callbacks[element_key] = (callback, callback_args, callback_kwargs)
    except:
        LOG.debug("unexpected error registering component callback", exc_info=False, stack_info=False)
