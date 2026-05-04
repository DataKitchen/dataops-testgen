import van from '/app/static/js/van.min.js';
import { getValue, loadStylesheet } from '/app/static/js/utils.js';
import { Dialog } from '/app/static/js/components/dialog.js';
import { Table } from '/app/static/js/components/table.js';
import { Code } from '/app/static/js/components/code.js';
import { Alert } from '/app/static/js/components/alert.js';

const { div, h4, small } = van.tags;

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
                children.push(Alert({ type: 'info', class: 'tg-sd--msg' }, d.message));
            } else if (d.status === 'ERR') {
                children.push(Alert({ type: 'error', class: 'tg-sd--msg' }, d.message));
            } else if (d.rows?.length) {
                if (d.message) {
                    children.push(Alert({ type: 'info', class: 'tg-sd--msg' }, d.message));
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
                children.push(Alert({ type: 'error', class: 'tg-sd--msg' }, 'An unknown error was encountered.'));
            }

            if (d.sql_query) {
                children.push(
                    h4({ style: 'margin: 12px 0 4px' }, 'SQL Query'),
                    Code({ language: 'sql', class: 'tg-sg--sql-query-code' }, d.sql_query),
                );
            }

            return div({ class: 'flex-column' }, ...children);
        },
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-sd--msg {
    font-size: 14px !important;
}

.tg-sg--sql-query-code {
    max-height: 300px;
}
`);

export { SourceDataDialog };
