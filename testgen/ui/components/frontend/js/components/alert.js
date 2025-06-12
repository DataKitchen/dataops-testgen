/**
 * @typedef Properties
 * @type {object}
 * @property {string?} icon
 * @property {number?} timeout
 * @property {boolean?} closeable
 * @property {'info'|'success'|'error'} type
 */
import van from '../van.min.js';
import { getValue, loadStylesheet, getRandomId } from '../utils.js';
import { Icon } from './icon.js';
import { Button } from './button.js';

const { div } = van.tags;
const alertTypeColors = {
    info: {backgroundColor: 'rgba(28, 131, 225, 0.1)', color: 'rgb(0, 66, 128)'},
    success: {backgroundColor: 'rgba(33, 195, 84, 0.1)', color: 'rgb(23, 114, 51)'},
    error: {backgroundColor: 'rgba(255, 43, 43, 0.09)', color: 'rgb(125, 53, 59)'},
};

const Alert = (/** @type Properties */ props, /** @type Array<HTMLElement> */ ...children) => {
    loadStylesheet('alert', stylesheet);

    const elementId = getValue(props.id) ?? 'tg-alert-' + getRandomId();
    const close = () => {
        document.getElementById(elementId)?.remove();
    };
    const timeout = getValue(props.timeout);
    if (timeout && timeout > 0) {
        setTimeout(close, timeout);
    }

    return div(
        {
            ...props,
            id: elementId,
            class: () => (getValue(props.class) ?? '') + ` tg-alert flex-row`,
            style: () => {
                const colors = alertTypeColors[getValue(props.type)];
                return `color: ${colors.color}; background-color: ${colors.backgroundColor};`;
            },
            role: 'alert',
        },
        () => {
            const icon = getValue(props.icon);
            return Icon({size: 20, classes: 'mr-2'}, icon);
        },
        div(
            {class: 'flex-column'},
            ...children,
        ),
        () => {
            const isCloseable = getValue(props.closeable) ?? false;
            if (!isCloseable) {
                return '';
            }

            const colors = alertTypeColors[getValue(props.type)];
            return Button({
                type: 'icon',
                icon: 'close',
                style: `margin-left: auto; color: ${colors.color};`,
            });
        },
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-alert {
    padding: 16px;
    border-radius: 0.5rem;
    font-size: 16px;
    line-height: 24px;
}
.tg-alert > .tg-icon {
    color: inherit !important;
}
`);

export { Alert };
