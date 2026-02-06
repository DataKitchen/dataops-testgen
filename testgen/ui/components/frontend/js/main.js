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

let currentWindowVan = van;
let topWindowVan = window.top.van;

const componentLoaders = {
    breadcrumbs: () => import('./components/breadcrumbs.js').then(m => m.Breadcrumbs),
    button: () => import('./components/button.js').then(m => m.Button),
    expander_toggle: () => import('./components/expander_toggle.js').then(m => m.ExpanderToggle),
    link: () => import('./components/link.js').then(m => m.Link),
    paginator: () => import('./components/paginator.js').then(m => m.Paginator),
    sorting_selector: () => import('./components/sorting_selector.js').then(m => m.SortingSelector),
    sidebar: () => Promise.resolve(window.top.testgen.components.Sidebar),
    test_runs: () => import('./pages/test_runs.js').then(m => m.TestRuns),
    profiling_runs: () => import('./pages/profiling_runs.js').then(m => m.ProfilingRuns),
    data_catalog: () => import('./pages/data_catalog.js').then(m => m.DataCatalog),
    column_profiling_results: () => import('./data_profiling/column_profiling_results.js').then(m => m.ColumnProfilingResults),
    column_profiling_history: () => import('./data_profiling/column_profiling_history.js').then(m => m.ColumnProfilingHistory),
    project_dashboard: () => import('./pages/project_dashboard.js').then(m => m.ProjectDashboard),
    test_suites: () => import('./pages/test_suites.js').then(m => m.TestSuites),
    quality_dashboard: () => import('./pages/quality_dashboard.js').then(m => m.QualityDashboard),
    score_details: () => import('./pages/score_details.js').then(m => m.ScoreDetails),
    score_explorer: () => import('./pages/score_explorer.js').then(m => m.ScoreExplorer),
    schedule_list: () => import('./pages/schedule_list.js').then(m => m.ScheduleList),
    column_selector: () => import('./components/explorer_column_selector.js').then(m => m.ColumnSelector),
    connections: () => import('./pages/connections.js').then(m => m.Connections),
    table_group_wizard: () => import('./pages/table_group_wizard.js').then(m => m.TableGroupWizard),
    help_menu: () => import('./components/help_menu.js').then(m => m.HelpMenu),
    table_group_list: () => import('./pages/table_group_list.js').then(m => m.TableGroupList),
    table_group_delete: () => import('./pages/table_group_delete_confirmation.js').then(m => m.TableGroupDeleteConfirmation),
    run_profiling_dialog: () => import('./pages/run_profiling_dialog.js').then(m => m.RunProfilingDialog),
    confirm_dialog: () => import('./pages/confirmation_dialog.js').then(m => m.ConfirmationDialog),
    test_definition_summary: () => import('./pages/test_definition_summary.js').then(m => m.TestDefinitionSummary),
    notification_settings: () => import('./pages/notification_settings.js').then(m => m.NotificationSettings),
    monitors_dashboard: () => import('./pages/monitors_dashboard.js').then(m => m.MonitorsDashboard),
    table_monitoring_trends: () => import('./pages/table_monitoring_trends.js').then(m => m.TableMonitoringTrend),
    test_results_chart: () => import('./pages/test_results_chart.js').then(m => m.TestResultsChart),
    schema_changes_list: () => import('./components/schema_changes_list.js').then(m => m.SchemaChangesList),
    edit_monitor_settings: () => import('./pages/edit_monitor_settings.js').then(m => m.EditMonitorSettings),
};

const TestGenComponent = async (/** @type {string} */ id, /** @type {object} */ props) => {
    if (Object.keys(window.testgen.plugins).includes(id)) {
        return window.testgen.plugins[id](props);
    }

    const loader = componentLoaders[id];
    if (loader) {
        const Component = await loader();
        return Component(props);
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

            return van.add(mountPoint, await TestGenComponent(componentId, componentState));
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
