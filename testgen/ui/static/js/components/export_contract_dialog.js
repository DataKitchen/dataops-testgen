/**
 * @typedef ExportData
 * @type {object}
 * @property {string} contract
 * @property {string} version
 * @property {string?} document
 * @property {string?} file_name
 * @property {string[]} problems
 * @property {string?} error
 *
 * @typedef Properties
 * @type {object}
 * @property {ExportData?} data - reactive: set to open the dialog, null to close it
 * @property {(() => void)?} onClose
 */
import van from '../van.min.js';
import { getValue, loadStylesheet } from '../utils.js';
import { Alert } from './alert.js';
import { Button } from './button.js';
import { Code } from './code.js';
import { Dialog } from './dialog.js';

const { div, li, span, ul } = van.tags;

const ExportContractDialog = (/** @type Properties */ props) => {
    loadStylesheet('export-contract-dialog', stylesheet);
    const open = van.state(false);
    const data = van.state(null);

    van.derive(() => {
        const raw = getValue(props.data) ?? null;
        data.val = raw;
        open.val = !!raw;
    });

    const onClose = () => {
        open.val = false;
        props.onClose?.();
    };

    const download = () => {
        const d = data.val;
        const url = URL.createObjectURL(new Blob([d.document], { type: 'application/yaml' }));
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = d.file_name;
        anchor.click();
        URL.revokeObjectURL(url);
    };

    return Dialog(
        { title: 'Export Contract', open, onClose, width: '60rem' },
        () => {
            const d = data.val;
            if (!d) {
                return '';
            }
            return div(
                { class: 'flex-column fx-gap-3', 'data-testid': 'export-contract-dialog' },
                span({ class: 'text-secondary' }, `${d.contract} · ${d.version}`),
                d.error
                    ? Alert({ type: 'error' }, span(`The contract document could not be produced. ${d.error}`))
                    : '',
                d.problems?.length
                    ? Alert(
                        { type: 'warn' },
                        div(
                            { class: 'flex-column' },
                            span('This document does not validate against the ODCS schema:'),
                            ul({ class: 'mt-1 mb-0 pl-4' }, d.problems.map((problem) => li(problem))),
                        ),
                    )
                    : '',
                d.document !== null
                    ? Code({ language: 'yaml', class: 'tg-export-contract--document' }, d.document)
                    : '',
                d.document !== null
                    ? div(
                        { class: 'flex-row fx-justify-flex-end' },
                        Button({ type: 'stroked', color: 'primary', icon: 'download', label: 'Download', width: 'auto', onclick: download }),
                    )
                    : '',
            );
        },
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-export-contract--document {
    max-height: 60vh;
}
`);

export { ExportContractDialog };
