import streamlit as st
from starlette.middleware import Middleware

from testgen import settings
from testgen.ui.static_cache import STATIC_FOLDER, StaticCacheMiddleware

app = st.App(
    "app.py",
    middleware=[
        Middleware(
            StaticCacheMiddleware,
            static_folder=STATIC_FOLDER,
            dev=settings.IS_DEBUG,
            base_path=settings.UI_BASE_PATH,
        )
    ],
)
