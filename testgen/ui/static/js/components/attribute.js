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
import { Icon } from './icon.js';
import { withTooltip } from './tooltip.js';
import van from '../van.min.js';

const { div } = van.tags;

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
`);

export { Attribute };
