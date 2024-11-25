/**
 * @typedef ColumnPath
 * @type {object}
 * @property {string} column_id
 * @property {string} table_id
 * @property {string} column_name
 * @property {string} table_name
 * @property {'A' | 'B' | 'D' | 'N' | 'T' | 'X'} general_type
 * @property {number} column_drop_date
 * @property {number} table_drop_date
 *
 * @typedef Anomaly
 * @type {object}
 * @property {string} column_name
 * @property {string} anomaly_name
 * @property {'Definite' | 'Likely' | 'Possible' | 'Potential PII'} issue_likelihood
 * @property {string} detail
 * @property {'High' | 'Moderate'} pii_risk
 *
 * @typedef TestIssue
 * @type {object}
 * @property {string} id
 * @property {string} column_name
 * @property {string} test_name
 * @property {'Failed' | 'Warning' | 'Error' } result_status
 * @property {string} result_message
 * @property {string} test_suite
 * @property {string} test_run_id
 * @property {number} test_run_date
 *
 * @typedef Column
 * @type {ColumnProfile}
 * @property {string} id
 * @property {'column'} type
 * @property {string} column_name
 * @property {string} table_name
 * @property {string} table_group_id
 * * Characteristics
 * @property {string} column_type
 * @property {string} functional_data_type
 * @property {string} datatype_suggestion
 * @property {number} add_date
 * @property {number} last_mod_date
 * @property {number} drop_date
 * * Column Metadata
 * @property {boolean} critical_data_element
 * @property {string} data_source
 * @property {string} source_system
 * @property {string} source_process
 * @property {string} business_domain
 * @property {string} stakeholder_group
 * @property {string} transform_level
 * @property {string} aggregation_level
 * * Table Metadata
 * @property {boolean} table_critical_data_element
 * @property {string} table_cdata_source
 * @property {string} table_csource_system
 * @property {string} table_csource_process
 * @property {string} table_cbusiness_domain
 * @property {string} table_cstakeholder_group
 * @property {string} table_ctransform_level
 * @property {string} table_caggregation_level
 * * Latest Profile & Test Runs
 * @property {string} latest_profile_id
 * @property {number} latest_profile_date
 * @property {number} has_test_runs
 * * Issues
 * @property {Anomaly[]} latest_anomalies
 * @property {TestIssue[]} latest_test_issues
 *
 * @typedef Table
 * @type {object}
 * @property {string} id
 * @property {'table'} type
 * @property {string} table_name
 * @property {string} table_group_id
 * * Characteristics
 * @property {string} functional_table_type
 * @property {number} record_ct
 * @property {number} column_ct
 * @property {number} data_point_ct
 * @property {number} add_date
 * @property {number} drop_date
 * * Metadata
 * @property {boolean} critical_data_element
 * @property {string} data_source
 * @property {string} source_system
 * @property {string} source_process
 * @property {string} business_domain
 * @property {string} stakeholder_group
 * @property {string} transform_level
 * @property {string} aggregation_level
 * * Latest Profile & Test Runs
 * @property {string} latest_profile_id
 * @property {number} latest_profile_date
 * @property {number} has_test_runs
 * * Issues
 * @property {Anomaly[]} latest_anomalies
 * @property {TestResult[]} latest_test_results
 *
 * @typedef Properties
 * @type {object}
 * @property {ColumnPath[]} columns
 * @property {Table | Column} selected
 */
import van from '../van.min.js';
import { Tree } from '../components/tree.js';
import { Card } from '../components/card.js';
import { EditableCard } from '../components/editable_card.js';
import { Link } from '../components/link.js';
import { Attribute } from '../components/attribute.js';
import { Input } from '../components/input.js';
import { TooltipIcon } from '../components/tooltip_icon.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet } from '../utils.js';
import { formatTimestamp } from '../display_utils.js';
import { ColumnProfile } from '../components/column_profile.js';
import { RadioGroup } from '../components/radio_group.js';

const { div, h2, span, i } = van.tags;

const tableIcon = { icon: 'table', iconSize: 20 };
const columnIcons = {
    A: { icon: 'abc' },
    B: { icon: 'toggle_off', iconSize: 20 },
    D: { icon: 'calendar_clock', iconSize: 20 },
    N: { icon: '123' },
    T: { icon: 'calendar_clock', iconSize: 20 },
    X: { icon: 'question_mark', iconSize: 18 },
};

const DataHierarchy = (/** @type Properties */ props) => {
    loadStylesheet('data_hierarchy', stylesheet);
    Streamlit.setFrameHeight(1); // Non-zero value is needed to render
    window.frameElement.style.setProperty('height', 'calc(100vh - 175px)');
    window.testgen.isPage = true;

    const treeNodes = van.derive(() => {
        let columns = [];
        try {
            columns = JSON.parse(getValue(props.columns));
        } catch { }

        const tables = {};
        columns.forEach(({ column_id, table_id, column_name, table_name, general_type, column_drop_date, table_drop_date }) => {
            if (!tables[table_id]) {
                tables[table_id] = {
                    id: table_id,
                    label: table_name,
                    classes: table_drop_date ? 'text-disabled' : '',
                    ...tableIcon,
                    children: [],
                };
            }
            tables[table_id].children.push({
                id: column_id,
                label: column_name,
                classes: column_drop_date ? 'text-disabled' : '',
                ...columnIcons[general_type || 'X'],
            });
        });
        return Object.values(tables);
    });

    const selectedItem = van.derive(() => {
        try {
            return JSON.parse(getValue(props.selected));
        } catch (e) {
            console.error(e)
            return null;
        }
    });

    return div(
        { class: 'flex-row tg-dh' },
        Tree({
            nodes: treeNodes,
            // Use .rawVal, so only initial value from query params is passed to tree
            selected: selectedItem.rawVal?.id,
            classes: 'tg-dh--tree',
        }),
        () => {
            const item = selectedItem.val;
            if (item) {
                return div(
                    { class: 'tg-dh--details' },
                    h2(
                        { class: 'tg-dh--title' },
                        item.type === 'column' ? [
                            span(
                                { class: 'text-secondary' },
                                `${item.table_name}: `,
                            ),
                            item.column_name,
                        ] : item.table_name,
                    ),
                    span(
                        { class: 'flex-row fx-gap-1 fx-justify-content-flex-end mb-2 text-secondary' },
                        '* as of latest profiling run on ',
                        Link({
                            href: 'profiling-runs:results',
                            params: {
                                run_id: item.latest_profile_id,
                                table_name: item.table_name,
                                column_name: item.column_name,
                            },
                            open_new: true,
                            label: formatTimestamp(item.latest_profile_date),
                        }),
                    ),
                    CharacteristicsCard(item),
                    item.type === 'column' ? Card({
                        title: 'Value Distribution *',
                        content: ColumnProfile(item),
                    }) : null,
                    MetadataCard(item),
                    PotentialPIICard(item),
                    HygieneIssuesCard(item),
                    TestIssuesCard(item),
                );
            }

            return div(
                { class: 'flex-column fx-align-flex-center fx-justify-center tg-dh--no-selection' },
                i(
                    { class: 'material-symbols-rounded text-disabled mb-5' },
                    'quick_reference_all',
                ),
                span(
                    { class: 'text-secondary' },
                    'Select a table or column on the left to view its details.',
                ),
            );
        },
    );
};

const CharacteristicsCard = (/** @type Table | Column */ item) => {
    let attributes = [];
    if (item.type === 'column') {
        attributes.push(
            { key: 'column_type', label: 'Data Type' },
            { key: 'datatype_suggestion', label: 'Suggested Data Type' },
            { key: 'functional_data_type', label: 'Semantic Data Type' },
            { key: 'add_date', label: 'First Detected' },
        );
        if (item.last_mod_date !== item.add_date) {
            attributes.push({ key: 'last_mod_date', label: 'Modification Detected' });
        }
    } else {
        attributes.push(
            { key: 'functional_table_type', label: 'Semantic Table Type' },
            { key: 'record_ct', label: 'Row Count' },
            { key: 'column_ct', label: 'Column Count' },
            { key: 'data_point_ct', label: 'Data Point Count' },
            { key: 'add_date', label: 'First Detected' },
        );
    }
    if (item.drop_date) {
        attributes.push({ key: 'drop_date', label: 'Drop Detected' });
    }

    return Card({
        title: `${item.type} Characteristics *`,
        content: div(
            { class: 'flex-row fx-flex-wrap fx-gap-4' },
            attributes.map(({ key, label }) => {
                let value = item[key];
                if (key === 'column_type') {
                    const { icon, iconSize } = columnIcons[item.general_type || 'X'];
                    value = div(
                        { class: 'flex-row' },
                        i(
                            {
                                class: 'material-symbols-rounded tg-dh--column-icon',
                                style: `font-size: ${iconSize || 24}px;`,
                            },
                            icon,
                        ),
                        (value || 'unknown').toLowerCase(),
                    );
                } else if (key === 'datatype_suggestion') {
                    value = (value || '').toLowerCase();
                } else if (key === 'functional_table_type') {
                    value = (value || '').split('-')
                        .map(word => word ? (word[0].toUpperCase() + word.substring(1)) : '')
                        .join(' ');
                } else if (['add_date', 'last_mod_date', 'drop_date'].includes(key)) {
                    value = formatTimestamp(value, true);
                    if (key === 'drop_date') {
                        label = span({ class: 'text-error' }, label);
                    }
                }

                return Attribute({ label, value, width: 300 });
            }),
        ),
    });
};

const MetadataCard = (/** @type Table | Column */ item) => {
    const attributes = [
        'critical_data_element',
        'data_source',
        'source_system',
        'source_process',
        'business_domain',
        'stakeholder_group',
        'transform_level',
        'aggregation_level',
    ].map(key => ({
        key,
        label: key.replaceAll('_', ' '),
        state: van.state(item[key]),
        inherited: item[`table_${key}`], // Table values inherited by column 
    }));

    const InheritedIcon = () => TooltipIcon({
        icon: 'layers',
        iconSize: 18,
        classes: 'text-disabled',
        tooltip: 'Inherited from table metadata',
        tooltipPosition: 'top-right',
    });
    const width = 300;

    const content = div(
        { class: 'flex-row fx-flex-wrap fx-gap-4' },
        attributes.map(({ key, label, state, inherited }) => {
            let value = state.rawVal ?? inherited;
            const isInherited = item.type === 'column' && state.rawVal === null;

            if (key === 'critical_data_element') {
                return span(
                    { class: 'flex-row fx-gap-1', style: `width: ${width}px` },
                    i(
                        { class: `material-symbols-rounded ${value ? 'text-green' : 'text-disabled'}` },
                        value ? 'check_circle' : 'cancel',
                    ),
                    span(
                        { class: value ? 'text-capitalize' : 'text-secondary' },
                        value ? label : `Not a ${label}`,
                    ),
                    isInherited ? InheritedIcon() : null,
                );
            }

            if (isInherited && value) {
                value = span(
                    { class: 'flex-row fx-gap-1' },
                    InheritedIcon(),
                    value,
                );
            }
            return Attribute({ label, value, width });
        }),
    );

    const editingContent = div(
        { class: 'flex-row fx-flex-wrap fx-gap-4' },
        attributes.map(({ key, label, state, inherited }) => {
            if (key === 'critical_data_element') {
                const options = [
                    { label: 'Yes', value: true },
                    { label: 'No', value: false },
                ];
                if (item.type === 'column') {
                    options.push({ label: 'Inherit', value: null });
                }
                return RadioGroup({
                    label, width, options,
                    value: item.type === 'column' ? state.rawVal : !!state.rawVal, // Coerce null to false for tables
                    onChange: (value) => state.val = value,
                });
            };

            return Input({
                label, width,
                value: state.rawVal,
                placeholder: inherited ? `Inherited: ${inherited}` : null,
                onChange: (value) => state.val = value || null,
            });
        }),
    );

    return EditableCard({
        title: `${item.type} Metadata`,
        content,
        // Pass as function so the block is re-rendered with reset values when re-editing after a cancel
        editingContent: () => editingContent,
        onSave: () => {
            const payload = attributes.reduce((object, { key, state }) => {
                object[key] = state.rawVal;
                return object;
            }, { id: item.id });
            emitEvent('MetadataChanged', { payload })
        },
        // Reset states to original values on cancel
        onCancel: () => attributes.forEach(({ key, state }) => state.val = item[key]),
        hasChanges: () => attributes.some(({ key, state }) => state.val !== item[key]),
    });
};

const PotentialPIICard = (/** @type Table | Column */ item) => {
    const riskColors = {
        High: 'red',
        Moderate: 'orange',
    };

    const attributes = [
        {
            key: 'detail', width: 150, label: 'Type',
            value_function: (issue) => (issue.detail || '').split('Type: ')[1],
        },
        {
            key: 'pii_risk', width: 100, label: 'Risk', classes: 'text-secondary',
            value_function: (issue) => div(
                { class: 'flex-row' },
                span({ class: 'dot mr-2', style: `color: var(--${riskColors[issue.pii_risk]});` }),
                issue.pii_risk,
            ),
        },
    ];
    if (item.type === 'table') {
        attributes.unshift(
            { key: 'column_name', width: 150, label: 'Column' },
        );
    }

    const potentialPII = item.latest_anomalies.filter(({ issue_likelihood }) => issue_likelihood === 'Potential PII');
    const linkProps = {
        href: 'profiling-runs:hygiene',
        params: { run_id: item.latest_profile_id, issue_class: 'Potential PII' },
    };

    return IssuesCard('Potential PII', potentialPII, attributes, linkProps, 'No potential PII detected');
};

const HygieneIssuesCard = (/** @type Table | Column */ item) => {
    const likelihoodColors = {
        Definite: 'red',
        Likely: 'orange',
        Possible: 'yellow',
    };

    const attributes = [
        { key: 'anomaly_name', width: 200, label: 'Issue' },
        {
            key: 'issue_likelihood', width: 80, label: 'Likelihood', classes: 'text-secondary',
            value_function: (issue) => div(
                { class: 'flex-row' },
                span({ class: 'dot mr-2', style: `color: var(--${likelihoodColors[issue.issue_likelihood]});` }),
                issue.issue_likelihood,
            ),
        },
        { key: 'detail', width: 300, label: 'Detail' },
    ];
    if (item.type === 'table') {
        attributes.unshift(
            { key: 'column_name', width: 150, label: 'Column' },
        );
    }

    const hygieneIssues = item.latest_anomalies.filter(({ issue_likelihood }) => issue_likelihood !== 'Potential PII');
    const linkProps = {
        href: 'profiling-runs:hygiene',
        params: {
            run_id: item.latest_profile_id,
            table_name: item.table_name,
            column_name: item.column_name,
        },
    };

    return IssuesCard('Hygiene Issues', hygieneIssues, attributes, linkProps, 'No hygiene issues detected');
};

const TestIssuesCard = (/** @type Table | Column */ item) => {
    const statusColors = {
        Failed: 'red',
        Warning: 'yellow',
        Error: 'brown',
    };

    const attributes = [
        { key: 'test_name', width: 150, label: 'Test' },
        {
            key: 'result_status', width: 80, label: 'Status', classes: 'text-secondary',
            value_function: (issue) => div(
                { class: 'flex-row' },
                span({ class: 'dot mr-2', style: `color: var(--${statusColors[issue.result_status]});` }),
                issue.result_status,
            ),
        },
        { key: 'result_message', width: 300, label: 'Details' },
        {
            key: 'test_run_id', width: 150, label: 'Test Suite | Start Time',
            value_function: (issue) => div(
                div(
                    { class: 'text-secondary' },
                    issue.test_suite,
                ),
                Link({
                    href: 'test-runs:results',
                    params: {
                        run_id: issue.test_run_id,
                        table_name: item.table_name,
                        column_name: item.column_name,
                        selected: issue.id,
                    },
                    open_new: true,
                    label: formatTimestamp(issue.test_run_date),
                    style: 'font-size: 12px; margin-top: 2px;',
                }),
            ),
        },
    ];
    if (item.type === 'table') {
        attributes.unshift(
            { key: 'column_name', width: 150, label: 'Column' },
        );
    }

    let noneContent = 'No test issues detected';
    if (!item.has_test_runs) {
        if (item.drop_date) {
            noneContent = span({ class: 'text-secondary' }, `No test results for ${item.type}`);
        } else {
            noneContent = span(
                { class: 'text-secondary flex-row fx-gap-1 fx-justify-content-flex-end' },
                `No test results yet for ${item.type}.`,
                Link({
                    href: 'test-suites',
                    open_new: true,
                    label: 'Go to Test Suites',
                    right_icon: 'chevron_right',
                }),
            );
        }
    }

    return IssuesCard('Test Issues', item.latest_test_issues, attributes, null, noneContent);
};

/**
 * @typedef Attribute
 * @type {object}
 * @property {string} key
 * @property {number} width
 * @property {string} label
 * @property {string} classes
 * @property {function?} value_function
 */
const IssuesCard = (
    /** @type string */ title,
    /** @type (Anomaly | TestIssue)[] */ items,
    /** @type Attribute[] */ attributes,
    /** @type object? */ linkProps,
    /** @type (string | object)? */ noneContent,
) => {
    const gap = 8;
    const minWidth = attributes.reduce((sum, { width }) => sum + width, attributes.length * gap);

    let content = null;
    let actionContent = null;
    if (items.length) {
        content = div(
            { style: 'overflow: auto; max-height: 300px;' },
            div(
                {
                    class: 'flex-row table-row text-caption pt-0',
                    style: `gap: ${gap}px; min-width: ${minWidth}px;`,
                },
                attributes.map(({ label, width }) => span(
                    { style: `flex: 1 0 ${width}px;` },
                    label,
                )),
            ),
            items.map(item => div(
                {
                    class: 'flex-row table-row pt-2 pb-2',
                    style: `gap: ${gap}px; min-width: ${minWidth}px;`,
                },
                attributes.map(({ key, width, value_function, classes }) => {
                    const value = value_function ? value_function(item) : item[key];
                    return span(
                        {
                            class: classes || '',
                            style: `flex: 1 0 ${width}px; word-break: break-word;`,
                        },
                        value || '--',
                    );
                }),
            )),
        );

        if (linkProps) {
            actionContent = Link({
                ...linkProps,
                open_new: true,
                label: 'View details',
                right_icon: 'chevron_right',
            });
        }
    } else {
        actionContent = typeof noneContent === 'string' ? span(
            { class: 'text-secondary flex-row fx-gap-1' },
            noneContent,
            i({ class: 'material-symbols-rounded text-green' }, 'check_circle'),
        ) : (noneContent || null);
    }

    return Card({
        title: `${title} (${items.length})`,
        content,
        actionContent,
    });
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-dh {
    height: 100%;
    align-items: stretch;
}

.tg-dh--tree {
    min-width: 250px;
    border-radius: 8px;
    border: 1px solid var(--border-color);
    background-color: var(--sidebar-background-color);
}

.tg-dh--details {
    padding: 8px 0 0 20px;
    overflow: auto;
    flex-grow: 1;
}

.tg-dh--title {
    margin: 0;
    color: var(--primary-text-color);
    font-size: 20px;
    font-weight: 500;
}

.tg-dh--details > .tg-card {
    min-width: 400px;
}

.tg-dh--column-icon {
    margin-right: 4px;
    width: 24px;
    color: #B0BEC5;
    text-align: center;
}

.tg-dh--no-selection {
    flex: auto;
    max-height: 400px;
    padding: 16px;
}

.tg-dh--no-selection > i {
    font-size: 80px;
}

.tg-dh--no-selection > span {
    font-size: 18px;
    text-align: center;
}
`);

export { DataHierarchy };
