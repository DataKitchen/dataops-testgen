/**
* @typedef Message
* @type {object}
* @property {string} line1
* @property {string} line2
*
* @typedef Link
* @type {object}
* @property {string} href
* @property {string} label
*
* @typedef Properties
* @type {object}
* @property {string} icon
* @property {string} label
* @property {Message} message
* @property {Link?} link
* @property {any?} button
* @property {string?} class
*/
import van from '../van.min.js';
import { Card } from '../components/card.js';
import { getValue, loadStylesheet } from '../utils.js';
import { Link } from './link.js';

const { i, span, strong } = van.tags;

const EMPTY_STATE_MESSAGE = {
    connection: {
        line1: 'Begin by connecting your database.',
        line2: 'TestGen delivers data quality through data profiling, hygiene review, test generation, and test execution.',
    },
    tableGroup: {
        line1: 'Profile your tables to detect hygiene issues',
        line2: 'Create table groups for your connected databases to run data profiling and hygiene review.',
    },
    profiling: {
        line1: 'Profile your tables to detect hygiene issues',
        line2: 'Run data profiling on your table groups to understand data types, column contents, and data patterns.',
    },
    testSuite: {
        line1: 'Run data validation tests',
        line2: 'Automatically generate tests from data profiling results or write custom tests for your business rules.',
    },
    testExecution: {
        line1: 'Run data validation tests',
        line2: 'Execute tests to assess data quality of your tables.'
    },
    score: {
        line1: 'Track data quality scores',
        line2: 'Create custom scorecards to assess quality of your data assets across different categories.',
    },
    explorer: {
        line1: 'Track data quality scores',
        line2: 'Filter or select columns to assess the quality of your data assets across different categories.',
    },
};

const EmptyState = (/** @type Properties */ props) => {
    loadStylesheet('empty-state', stylesheet);

    return Card({
        class: `tg-empty-state flex-column fx-align-flex-center ${getValue(props.class ?? '')}`,
        content: [
            span({ class: 'tg-empty-state--title mb-5' }, props.label),
            i({class: 'material-symbols-rounded mb-5'}, props.icon),
            strong({ class: 'mb-2' }, props.message.line1),
            span({ class: 'mb-5' }, props.message.line2),
            (
                getValue(props.button) ??
                (
                    getValue(props.link)
                    ? Link({
                        class: 'tg-empty-state--link',
                        right_icon: 'chevron_right',
                        ...(getValue(props.link)),
                    })
                    : ''
                )
            ),
        ],
    });
}

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-empty-state {
    margin-top: 80px;
    border: 1px solid var(--border-color);
    padding: 112px 24px !important;
}

.tg-empty-state--title {
    font-size: 24px;
    color: var(--secondary-text-color);
}

.tg-empty-state > i {
    font-size: 60px;
    color: var(--disabled-text-color);
}

.tg-empty-state > .tg-empty-state--link {
    margin: auto;
    border-radius: 4px;
    border: var(--button-stroked-border);
    padding: 8px 8px 8px 16px;
    color: var(--primary-color);
}
`);

export { EMPTY_STATE_MESSAGE, EmptyState };
