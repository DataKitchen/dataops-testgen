import van from '/app/static/js/van.min.js';
import { getValue, loadStylesheet } from '/app/static/js/utils.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { Table } from '/app/static/js/components/table.js';
import { Code } from '/app/static/js/components/code.js';

const { div, span, h4, p, small } = van.tags;

/**
 * Shared dialog for displaying source data (used by test_results and hygiene_issues).
 *
 * @param {object} props
 * @param {object} props.sourceData - reactive state: set to data object to open, null to close
 * @param {function} props.onClose - called when dialog is closed
 * @param {function} [props.renderHeader] - (data) => VanJS node for page-specific metadata header
 * @param {string} [props.width='70rem']
 * @param {string} [props.testId]
 */
const SourceDataDialog = (props) => {
    const emit = props.emit;
    loadStylesheet('source-data-dialog', stylesheet);
    const open = van.state(false);
    const data = van.state(null);

    van.derive(() => {
        const raw = getValue(props.sourceData) ?? null;
        data.val = raw;
        open.val = !!raw;
    });

    const onClose = () => {
        open.val = false;
        props.onClose?.();
    };

    return Dialog(
        { title: 'Source Data', open, onClose, width: props.width || '70rem', testId: props.testId },
        () => {
            const d = data.val;
            if (!d) return '';

            const children = [];

            // Page-specific header
            if (props.renderHeader) {
                const headerNode = props.renderHeader(d);
                if (headerNode) children.push(headerNode);
            }

            // Status-based content
            if (d.status === 'ND' || d.status === 'NA') {
                children.push(div({ class: 'tg-sd--info-msg' }, d.message));
            } else if (d.status === 'ERR') {
                children.push(div({ class: 'tg-sd--error-msg' }, d.message));
            } else if (d.rows?.length) {
                if (d.message) {
                    children.push(div({ class: 'tg-sd--info-msg mb-2' }, d.message));
                }
                if (d.truncated) {
                    children.push(small({ class: 'text-caption', style: 'text-align: right; display: block; margin-bottom: 4px' }, '* Top 500 records displayed'));
                }

                const columns = d.columns.map(name => ({ name, label: name, overflow: 'hidden', align: 'left' }));
                const tableRows = van.state(d.rows.map(row => {
                    const obj = {};
                    d.columns.forEach((col, i) => { obj[col] = row[i] ?? ''; });
                    return obj;
                }));
                children.push(
                    div(
                        { style: 'margin-bottom: 12px' },
                        Table({ emit, columns, highDensity: true, height: 'auto', maxHeight: '300px' }, tableRows),
                    ),
                );
            } else if (!d.message) {
                children.push(div({ class: 'tg-sd--error-msg' }, 'An unknown error was encountered.'));
            }

            if (d.sql_query) {
                children.push(
                    h4({ style: 'margin: 12px 0 4px' }, 'SQL Query'),
                    Code({ language: 'sql' }, d.sql_query),
                );
            }

            return div({ class: 'flex-column' }, ...children);
        },
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-sd--info-msg {
    padding: 8px 12px;
    background: var(--blue-light, #e3f2fd);
    border-radius: 4px;
    color: var(--primary-text-color);
    font-size: 14px;
}
.tg-sd--error-msg {
    padding: 8px 12px;
    background: var(--red-light, #ffebee);
    border-radius: 4px;
    color: var(--red, #c62828);
    font-size: 14px;
}
`);

export { SourceDataDialog };
