/**
 * @typedef Properties
 * @type {object}
 * @property {string} label
 * @property {string | number} value
 * @property {number?} width
 */
import { getValue, loadStylesheet } from '../utils.js';
import van from '../van.min.js';

const { div } = van.tags;

const Attribute = (/** @type Properties */ props) => {
    loadStylesheet('attribute', stylesheet);

    return div(
        { style: () => `width: ${props.width ? getValue(props.width) + 'px' : 'auto'}` },
        div(
            { class: 'text-caption text-capitalize mb-1' },
            props.label,
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
