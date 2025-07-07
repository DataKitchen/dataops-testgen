/**
 * @typedef Properties
 * @type {object}
 * @property {string?} icon
 * @property {number?} timeout
 * @property {boolean?} closeable
 * @property {string?} class
 * @property {'info'|'success'|'warn'|'error'} type
 */
import van from '../van.min.js';
import { getValue, loadStylesheet, getRandomId } from '../utils.js';
import { Icon } from './icon.js';
import { Button } from './button.js';

const { div } = van.tags;

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
            class: () => `tg-alert flex-row ${getValue(props.class) ?? ''} tg-alert-${getValue(props.type)}`,
            role: 'alert',
        },
        () => {
            const icon = getValue(props.icon);
            if (!icon) {
                return '';
            }

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

            return Button({
                type: 'icon',
                icon: 'close',
                style: `margin-left: auto;`,
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

.tg-alert-info {
    background-color: rgba(28, 131, 225, 0.1);
    color: rgb(0, 66, 128);
}

.tg-alert-success {
    background-color: rgba(33, 195, 84, 0.1);
    color: rgb(23, 114, 51);
}

.tg-alert-warn {
    background-color: rgba(255, 227, 18, 0.1);
    color: rgb(146, 108, 5);
}

.tg-alert-error {
    background-color: rgba(255, 43, 43, 0.09);
    color: rgb(125, 53, 59);
}

@media (prefers-color-scheme: dark) {
    .tg-alert-info {
        background-color: rgba(61, 157, 243, 0.2);
        color: rgb(199, 235, 255);
    }

    .tg-alert-success {
        background-color: rgba(61, 213, 109, 0.2);
        color: rgb(223, 253, 233);
    }

    .tg-alert-warn {
        background-color: rgba(255, 227, 18, 0.2);
        color: rgb(255, 255, 194);
    }

    .tg-alert-error {
        background-color: rgba(255, 108, 108, 0.2);
        color: rgb(255, 222, 222);
    }
}

.tg-alert > .tg-icon {
    color: inherit !important;
}

.tg-alert > .tg-button {
    color: inherit !important;
}
`);

export { Alert };
