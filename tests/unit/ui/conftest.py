import sys
from unittest.mock import MagicMock

# Mock the Streamlit component registration that fails outside a running Streamlit app.
# The testgen_component module triggers component registration at import time, which
# requires a Streamlit runtime. We mock it so pure-logic tests can import freely.
sys.modules.setdefault("testgen.ui.components.widgets.testgen_component", MagicMock())

# widgets/__init__.py calls components_v2.component() at module level; stub it out so
# views that import widgets don't fail collection without a Streamlit runtime.
sys.modules.setdefault("testgen.ui.components.widgets", MagicMock())
