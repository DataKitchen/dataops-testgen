/**
 * @typedef Alert
 * @type {object}
 * @property {string} value
 * @property {string} color
 * @property {string} label
 * 
 * @typedef Properties
 * @type {object}
 * @property {string?} icon
 * @property {'info'|'success'|'error'} type
 * @property {string?} message
 */
import van from '../van.min.js';
import { getValue, loadStylesheet } from '../utils.js';
import { Icon } from './icon.js';

const { div } = van.tags;
const alertTypeColors = {
    info: {backgroundColor: 'rgba(28, 131, 225, 0.1)', color: 'rgb(0, 66, 128)'},
    success: {backgroundColor: 'rgba(33, 195, 84, 0.1)', color: 'rgb(23, 114, 51)'},
    error: {backgroundColor: 'rgba(255, 43, 43, 0.09)', color: 'rgb(125, 53, 59)'},
};

const Alert = (/** @type Properties */ props, /** @type Array<HTMLElement> */ ...children) => {
    loadStylesheet('alert', stylesheet);

    return div(
        {
            ...props,
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
