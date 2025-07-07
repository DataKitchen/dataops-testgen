/**
 * @typedef Result
 * @type {object}
 * @property {boolean} success
 * @property {string} message
 * 
 * @typedef Constraint
 * @type {object}
 * @property {string} warning
 * @property {string} confirmation
 * 
 * @typedef Properties
 * @type {object}
 * @property {string} project_code
 * @property {string} message
 * @property {Constraint?} constraint
 * @property {Result?} result
 * @property {string?} button_label
 * @property {string?} button_type
 * @property {string?} button_color
 */

import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet, resizeFrameHeightOnDOMChange, resizeFrameHeightToElement } from '../utils.js';
import { Button } from '../components/button.js';
import { Toggle } from '../components/toggle.js';
import { Alert } from '../components/alert.js';

const { div, span } = van.tags;

/**
 * @param {Properties} props 
 * @returns 
 */
const ConfirmationDialog = (props) => {
    loadStylesheet('confirmation-dialog', stylesheet);
    Streamlit.setFrameHeight(1);
    window.testgen.isPage = true;

    const wrapperId = 'confirmation-dialog';
    const confirmed = van.state(false);
    const actionDisabled = van.derive(() => !!getValue(props.constraint) && !confirmed.val);
    const buttonLabel = van.derive(() => getValue(props.button_label) ?? 'Confirm');
    const buttonColor = van.derive(() => (actionDisabled.val ? 'basic' : getValue(props.button_color)) ?? 'basic');
    const buttonType = van.derive(() => (actionDisabled.val ? 'stroked' : getValue(props.button_type)) ?? 'flat');

    const message = getValue(props.message);
    const constraint = getValue(props.constraint);

    resizeFrameHeightToElement(wrapperId);
    resizeFrameHeightOnDOMChange(wrapperId);

    return div(
        { id: wrapperId, class: 'flex-column' },
        div({ class: 'flex-column fx-gap-4' }, message),
        constraint
            ? div(
                { class: 'flex-column fx-gap-4 mt-4' },
                Alert({ type: 'warn' }, span(constraint.warning)),
                Toggle({
                    name: 'confirm-action',
                    label: span(constraint.confirmation),
                    checked: confirmed,
                    onChange: (value) => confirmed.val = value,
                }),
            )
            : '',
        div(
            { class: 'flex-row fx-justify-content-flex-end' },
            Button({
                type: buttonType,
                color: buttonColor,
                label: buttonLabel,
                style: 'width: auto;',
                disabled: actionDisabled,
                onclick: () => emitEvent('ActionConfirmed', {}),
            }),
        ),
        () => {
            const result = getValue(props.result);

            if (!result) {
                return '';
            }

            return div(
                {class: 'mt-4'},
                Alert(
                    {
                        type: result.success ? 'success' : 'error',
                        closeable: true,
                    },
                    span(result.message),
                ),
            );
        },
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
`);

export { ConfirmationDialog };
