/**
 * @typedef Properties
 * @type {object}
 * @property {string} id - id of the specific component to be rendered
 * @property {string} key - user key of the specific component to be rendered
 * @property {object} props - object with the props to pass to the rendered component
 */
import van from './van.min.js';
import pluginSpec from './plugins.js';
import { Streamlit } from './streamlit.js';
import { isEqual, getParents } from './utils.js';
import { Button } from './components/button.js'
import { Breadcrumbs } from './components/breadcrumbs.js'
import { ExpanderToggle } from './components/expander_toggle.js';
import { Link } from './components/link.js';
import { Paginator } from './components/paginator.js';
import { SortingSelector } from './components/sorting_selector.js';
import { ColumnSelector } from './components/explorer_column_selector.js';
import { TestRuns } from './pages/test_runs.js';
import { ProfilingRuns } from './pages/profiling_runs.js';
import { DataCatalog } from './pages/data_catalog.js';
import { ProjectDashboard } from './pages/project_dashboard.js';
import { TestSuites } from './pages/test_suites.js';
import { QualityDashboard } from './pages/quality_dashboard.js';
import { ScoreDetails } from './pages/score_details.js';
import { ScoreExplorer } from './pages/score_explorer.js';
import { ColumnProfilingResults } from './data_profiling/column_profiling_results.js';
import { ColumnProfilingHistory } from './data_profiling/column_profiling_history.js';
import { ScheduleList } from './pages/schedule_list.js';
import { Connections } from './pages/connections.js';
import { TableGroupWizard } from './pages/table_group_wizard.js';
import { HelpMenu } from './components/help_menu.js'
import { TableGroupList } from './pages/table_group_list.js';
import { TableGroupDeleteConfirmation } from './pages/table_group_delete_confirmation.js';
import { RunProfilingDialog } from './pages/run_profiling_dialog.js';
import { ConfirmationDialog } from './pages/confirmation_dialog.js';
import { TestDefinitionSummary } from './pages/test_definition_summary.js';

let currentWindowVan = van;
let topWindowVan = window.top.van;

const TestGenComponent = (/** @type {string} */ id, /** @type {object} */ props) => {
    const componentById = {
        breadcrumbs: Breadcrumbs,
        button: Button,
        expander_toggle: ExpanderToggle,
        link: Link,
        paginator: Paginator,
        sorting_selector: SortingSelector,
        sidebar: window.top.testgen.components.Sidebar,
        test_runs: TestRuns,
        profiling_runs: ProfilingRuns,
        data_catalog: DataCatalog,
        column_profiling_results: ColumnProfilingResults,
        column_profiling_history: ColumnProfilingHistory,
        project_dashboard: ProjectDashboard,
        test_suites: TestSuites,
        quality_dashboard: QualityDashboard,
        score_details: ScoreDetails,
        score_explorer: ScoreExplorer,
        schedule_list: ScheduleList,
        column_selector: ColumnSelector,
        connections: Connections,
        table_group_wizard: TableGroupWizard,
        help_menu: HelpMenu,
        table_group_list: TableGroupList,
        table_group_delete: TableGroupDeleteConfirmation,
        run_profiling_dialog: RunProfilingDialog,
        confirm_dialog: ConfirmationDialog,
        test_definition_summary: TestDefinitionSummary,
    };

    if (Object.keys(window.testgen.plugins).includes(id)) {
        return window.testgen.plugins[id](props);
    } else if (Object.keys(componentById).includes(id)) {
        return componentById[id](props);
    }
    return '';
};

window.addEventListener('message', async (event) => {
    if (event.data.type === 'streamlit:render') {
        await loadPlugins();

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
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }
});

document.addEventListener('click', (event) => {
    const openedPortals = (Object.values(window.testgen.portals) ?? []).filter(portal => portal.opened.val);
    if (Object.keys(openedPortals).length <= 0) {
        return;
    }

    const targetParents = getParents(event.target);
    for (const portal of openedPortals) {
        const targetEl = document.getElementById(portal.targetId);
        const portalEl = document.getElementById(portal.domId);

        if (event?.target?.id !== portal.targetId && event?.target?.id !== portal.domId && !targetParents.includes(targetEl) && !targetParents.includes(portalEl)) {
            portal.opened.val = false;
        }
    }
});

Streamlit.init();

function shouldRenderOutsideFrame(componentId) {
    return 'sidebar' === componentId;
}

async function loadPlugins() {
    if (!window.testgen.pluginsLoaded) {
        try {
            const modules = await Promise.all(Object.values(pluginSpec).map(plugin => import(plugin.entrypoint)))
            for (const pluginModule of modules) {
                if (pluginModule && pluginModule.components) {
                    Object.assign(window.testgen.plugins, pluginModule.components)
                } else if (pluginModule) {
                    console.warn(`Plugin '${pluginModule}' does not export a member 'components'.`);
                }
            }
        } catch (error) {
            console.warn('Error loading plugins:', error);
        }
    }

    window.testgen.pluginsLoaded = true;
}

window.testgen = {
    states: {},
    loadedStylesheets: {},
    portals: {},
    plugins: {},
    pluginsLoaded: false,
};
