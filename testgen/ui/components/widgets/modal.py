from contextlib import contextmanager

import streamlit
import streamlit.components.v1 as components
from streamlit_modal import Modal as BaseModal


class Modal(BaseModal):
    @contextmanager
    def container(self):
        streamlit.markdown(self._modal_styles(), unsafe_allow_html=True)
        with streamlit.container():
            _container = streamlit.container()
            if self.title:
                _container.markdown(f"<h2>{self.title}</h2>", unsafe_allow_html=True)

            close_ = streamlit.button("X", key=f"{self.key}-close")
            if close_:
                self.close()

            if not close_:
                components.html(self._modal_script(), height=0, width=0)

        with _container:
            yield _container

    def _modal_styles(self) -> str:
        max_width = f"{self.max_width}px" if self.max_width else "unset"

        return f"""
        <style>
            div[data-modal-container='true'][key='{self.key}'] {{
                position: fixed;
                width: 100vw !important;
                left: 0;
                z-index: 1001;
            }}

            div[data-modal-container='true'][key='{self.key}'] > div:first-child {{
                margin: auto;
            }}

            div[data-modal-container='true'][key='{self.key}'] h1 a {{
                display: none
            }}

            div[data-modal-container='true'][key='{self.key}']::before {{
                    position: fixed;
                    content: ' ';
                    left: 0;
                    right: 0;
                    top: 0;
                    bottom: 0;
                    z-index: 1000;
                    background-color: rgba(0, 0, 0, 0.5);
            }}
            div[data-modal-container='true'][key='{self.key}'] > div:first-child {{
                max-width: {max_width};
            }}

            div[data-modal-container='true'][key='{self.key}'] > div:first-child > div:first-child {{
                width: unset !important;
                background-color: #fff;
                padding: {self.padding}px;
                margin-top: {2*self.padding}px;
                margin-left: -{self.padding}px;
                margin-right: -{self.padding}px;
                margin-bottom: -{2*self.padding}px;
                z-index: 1001;
                border-radius: 5px;
            }}
            div[data-modal-container='true'][key='{self.key}'] > div > div:nth-child(1 of .element-container)  {{
                z-index: 1003;
                position: absolute;
            }}
            div[data-modal-container='true'][key='{self.key}'] > div > div:nth-child(1 of .element-container) > div {{
                text-align: right;
                padding-right: {self.padding}px;
                max-width: {max_width};
            }}

            div[data-modal-container='true'][key='{self.key}'] > div > div:nth-child(1 of .element-container) > div > button {{
                right: 0;
                margin-top: {2*self.padding + 14}px;
            }}
        </style>
        """

    def _modal_script(self) -> str:
        return f"""
        <script type="text/javascript">
            const modalContainer = window.frameElement.parentElement.parentElement.parentElement;

            modalContainer.setAttribute('data-modal-container', 'true');
            modalContainer.setAttribute('key', '{self.key}');
        </script>
        """
