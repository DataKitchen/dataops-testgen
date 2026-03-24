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
 * @property {string} message
 * @property {Constraint?} constraint
 * @property {Result?} result
 * @property {string?} button_label
 * @property {string?} button_type
 * @property {string?} button_color
 */

import van from '/app/static/js/van.min.js';
import { Streamlit } from '/app/static/js/streamlit.js';
import { emitEvent, getValue, isEqual, loadStylesheet } from '/app/static/js/utils.js';
import { Button } from '/app/static/js/components/button.js';
import { Toggle } from '/app/static/js/components/toggle.js';
import { Alert } from '/app/static/js/components/alert.js';

const { div, span } = van.tags;

/**
 * @param {Properties} props 
 * @returns 
 */
const ConfirmationDialog = (props) => {
    loadStylesheet('confirmation-dialog', stylesheet);

    const wrapperId = 'confirmation-dialog';
    const confirmed = van.state(false);
    const actionDisabled = van.derive(() => !!getValue(props.constraint) && !confirmed.val);
    const buttonLabel = van.derive(() => getValue(props.button_label) ?? 'Confirm');
    const buttonColor = van.derive(() => (actionDisabled.val ? 'basic' : getValue(props.button_color)) ?? 'basic');
    const buttonType = van.derive(() => (actionDisabled.val ? 'stroked' : getValue(props.button_type)) ?? 'flat');

    return div(
        { id: wrapperId, class: 'flex-column' },
        div({ class: 'flex-column fx-gap-4' }, () => getValue(props.message)),
        () => {
            const constraint = getValue(props.constraint);
            return constraint
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
                : '';
        },
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

export default (component) => {
    const { data, setStateValue, setTriggerValue, parentElement } = component;

    Streamlit.enableV2(setTriggerValue);

    let componentState = parentElement.state;
    if (componentState === undefined) {
        componentState = {};
        for (const [key, value] of Object.entries(data)) {
            componentState[key] = van.state(value);
        }
        parentElement.state = componentState;
        van.add(parentElement, ConfirmationDialog(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => { parentElement.state = null; };
};
