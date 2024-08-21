/**
 * @typedef Properties
 * @type {object}
 * @property {string} id - id of the specific component to be rendered
 * @property {string} key - user key of the specific component to be rendered
 * @property {object} props - object with the props to pass to the rendered component 
 */
import van from './van.min.js';
import { Streamlit } from './streamlit.js';
import { Button } from './components/button.js'
import { Select } from './components/select.js'
import { Breadcrumbs } from './components/breadcrumbs.js'
import { SummaryBar } from './components/summary_bar.js';
import { ExpanderToggle } from './components/expander_toggle.js';

let currentWindowVan = van;
let topWindowVan = window.top.van;

const TestGenComponent = (/** @type {string} */ id, /** @type {object} */ props) => {
    const componentById = {
        select: Button,
        button: Select,
        breadcrumbs: Breadcrumbs,
        summary_bar: SummaryBar,
        expander_toggle: ExpanderToggle,
        sidebar: window.top.testgen.components.Sidebar,
    };

    if (Object.keys(componentById).includes(id)) {
        return componentById[id](props);
    }

    return '';
};

window.addEventListener('message', (event) => {
    if (event.data.type === 'streamlit:render') {
        const componentId = event.data.args.id;
        const componentKey = event.data.args.key;

        let van = currentWindowVan;
        let mountPoint = document.body;
        let componentState = window.testgen.states[componentKey];
        if (shouldRenderOutsideFrame(componentId)) {
            window.frameElement.style.display = 'none';
            componentState = window.top.testgen.states[componentKey];
            mountPoint = window.frameElement.parentElement;
            van = topWindowVan;
        }

        if (componentId === 'sidebar') {
            // The parent element [data-testid="stSidebarUserContent"] randoms flickers on page navigation
            // The [data-testid="stSidebarContent"] element seems to be stable
            // But only when the default [data-testid="stSidebarNav"] navbar element is present
            mountPoint = window.top.document.querySelector('[data-testid="stSidebarContent"]');

            window.top.testgen.components.Sidebar.StreamlitInstance = Streamlit;
        }

        if (componentState === undefined) {
            document.body.dataset.component = event.data.args.id;

            componentState = {};
            for (const [ key, value ] of Object.entries(event.data.args.props)) {
                componentState[key] = van.state(value);
            }

            if (shouldRenderOutsideFrame(componentId)) {
                window.top.testgen.states[componentKey] = componentState;
            } else {
                window.testgen.states[componentKey] = componentState;
            }

            return van.add(mountPoint, TestGenComponent(componentId, componentState));
        }

        for (const [ key, value ] of Object.entries(event.data.args.props)) {
            if (componentState[key].val !== value) {
                componentState[key].val = value;
            }
        }
    }
});

Streamlit.init();

function shouldRenderOutsideFrame(componentId) {
    return 'sidebar' === componentId;
}

window.testgen = {
    states: {},
    loadedStylesheets: {},
};
