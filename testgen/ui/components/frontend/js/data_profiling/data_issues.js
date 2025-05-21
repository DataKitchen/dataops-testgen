/**
 * @import { Column, Table, HygieneIssue, TestIssue } from './data_profiling_utils.js';
 *
 * @typedef Attribute
 * @type {object}
 * @property {string} key
 * @property {number} width
 * @property {string} label
 * @property {string} classes
 * @property {function?} value_function
 *
 * @typedef Properties
 * @type {object}
 * @property {boolean?} border
 * @property {boolean?} noLinks
 */
import van from '../van.min.js';
import { Card } from '../components/card.js';
import { Attribute } from '../components/attribute.js';
import { Link } from '../components/link.js';
import { formatTimestamp } from '../display_utils.js';

const { div, span, i } = van.tags;

const RISK_COLORS = {
    High: 'red',
    Moderate: 'orange',
};

const LIKELIHOOD_COLORS = {
    Definite: 'red',
    Likely: 'orange',
    Possible: 'yellow',
};

const STATUS_COLORS = {
    Failed: 'red',
    Warning: 'yellow',
    Error: 'brown',
};

const PotentialPIICard = (/** @type Properties */ props, /** @type Table | Column */ item) => {
    const attributes = [
        {
            key: 'detail', width: 150, label: 'Type',
            value_function: (issue) => (issue.detail || '').split('Type: ')[1],
        },
        {
            key: 'pii_risk', width: 100, label: 'Risk', classes: 'text-secondary',
            value_function: (issue) => div(
                { class: 'flex-row' },
                span({ class: 'dot mr-2', style: `color: var(--${RISK_COLORS[issue.pii_risk]});` }),
                issue.pii_risk,
            ),
        },
    ];
    if (item.type === 'table') {
        attributes.unshift(
            { key: 'column_name', width: 150, label: 'Column' },
        );
    }

    const potentialPII = item.hygiene_issues.filter(({ issue_likelihood }) => issue_likelihood === 'Potential PII');
    const linkProps = props.noLinks ? null : {
        href: 'profiling-runs:hygiene',
        params: { run_id: item.profile_run_id, issue_class: 'Potential PII' },
    };
    const noneContent = item.profile_run_id ? 'No potential PII detected' : null;

    return IssuesCard(props, 'Potential PII *', potentialPII, attributes, linkProps, noneContent);
};

const HygieneIssuesCard = (/** @type Properties */ props, /** @type Table | Column */ item) => {
    const attributes = [
        { key: 'anomaly_name', width: 200, label: 'Issue' },
        {
            key: 'issue_likelihood', width: 80, label: 'Likelihood', classes: 'text-secondary',
            value_function: (issue) => div(
                { class: 'flex-row' },
                span({ class: 'dot mr-2', style: `color: var(--${LIKELIHOOD_COLORS[issue.issue_likelihood]});` }),
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

    const hygieneIssues = item.hygiene_issues.filter(({ issue_likelihood }) => issue_likelihood !== 'Potential PII');
    const linkProps = props.noLinks ? null : {
        href: 'profiling-runs:hygiene',
        params: {
            run_id: item.profile_run_id,
            table_name: item.table_name,
            column_name: item.column_name,
        },
    };
    const noneContent = item.profile_run_id ? 'No hygiene issues detected' : null;

    return IssuesCard(props, 'Hygiene Issues *', hygieneIssues, attributes, linkProps, noneContent);
};

const TestIssuesCard = (/** @type Properties */ props, /** @type Table | Column */ item) => {
    const attributes = [
        { key: 'test_name', width: 150, label: 'Test' },
        {
            key: 'result_status', width: 80, label: 'Status', classes: 'text-secondary',
            value_function: (issue) => div(
                { class: 'flex-row' },
                span({ class: 'dot mr-2', style: `color: var(--${STATUS_COLORS[issue.result_status]});` }),
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
                props.noLinks
                    ? span(
                        { style: 'font-size: 12px; margin-top: 2px;' },
                        formatTimestamp(issue.test_run_date)
                    )
                    : Link({
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
                props.noLinks ? null : Link({
                    href: 'test-suites',
                    params: {
                        project_code: item.project_code,
                        table_group_id: item.table_group_id,
                    },
                    open_new: true,
                    label: 'Go to Test Suites',
                    right_icon: 'chevron_right',
                }),
            );
        }
    }

    return IssuesCard(props, 'Test Issues', item.test_issues, attributes, null, noneContent);
};

const IssuesCard = (
    /** @type Properties */ props,
    /** @type string */ title,
    /** @type HygieneIssue[] | TestIssue[] */ items,
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
        border: props.border,
        title: title.replace(/([^*]+)( \*)?$/, `$1 (${items.length})$2`),
        content,
        actionContent,
    });
}

export { PotentialPIICard, HygieneIssuesCard, TestIssuesCard };
