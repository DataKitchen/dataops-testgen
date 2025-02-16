/**
 * @typedef Properties
 * @type {object}
 * @property {string} label
 * @property {string?} help
 * @property {string | number} value
 * @property {number?} width
 */
import { getValue, loadStylesheet } from '../utils.js';
import { TooltipIcon } from './tooltip_icon.js';
import van from '../van.min.js';

const { div } = van.tags;

const Attribute = (/** @type Properties */ props) => {
    loadStylesheet('attribute', stylesheet);

    return div(
        { style: () => `width: ${props.width ? getValue(props.width) + 'px' : 'auto'}` },
        div(
            { class: 'flex-row fx-gap-1 text-caption text-capitalize mb-1' },
            props.label,
            () => getValue(props.help) ? TooltipIcon({
                icon: 'help',
                iconSize: 16,
                classes: 'text-disabled',
                tooltip: props.help,
                tooltipPosition: 'top',
                tooltipWidth: 200,
            }) : null,
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
