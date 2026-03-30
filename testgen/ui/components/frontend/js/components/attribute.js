/**
 * @typedef Properties
 * @type {object}
 * @property {string} label
 * @property {string?} help
 * @property {string | number} value
 * @property {number?} width
 * @property {string?} class
 */
import { getValue, loadStylesheet } from '../utils.js';
import { PII_REDACTED } from '../display_utils.js';
import { Icon } from './icon.js';
import { withTooltip } from './tooltip.js';
import van from '../van.min.js';

const { div, code } = van.tags;

const Attribute = (/** @type Properties */ props) => {
    loadStylesheet('attribute', stylesheet);

    return div(
        { style: () => `width: ${props.width ? getValue(props.width) + 'px' : 'auto'}`, class: props.class },
        div(
            { class: 'flex-row fx-gap-1 text-caption mb-1' },
            props.label,
            () => getValue(props.help)
                ? withTooltip(
                    Icon({size: 16, classes: 'text-disabled' }, 'help'),
                    { text: props.help, position: 'top', width: 200 },
                )
                : null,
        ),
        div(
            { class: 'attribute-value' },
            () => {
                const value = getValue(props.value);
                if (value === PII_REDACTED) {
                    return withTooltip(
                        code({ class: 'attribute-pii-redacted' }, 'PII Redacted'),
                        { text: 'You do not have permission to view PII data', position: 'top-right' },
                    );
                }
                return (value || value === 0) ? value : '--';
            },
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.attribute-value {
    word-wrap: break-word;
}

.attribute-pii-redacted {
    display: inline-block;
    font-size: 12px;
    padding: 2px 6px;
    border-radius: 4px;
    background: color-mix(in srgb, var(--disabled-text-color) 15%, transparent);
    color: var(--disabled-text-color);
    overflow: visible;
}
`);

export { Attribute };
