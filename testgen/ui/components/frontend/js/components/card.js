/**
 * @typedef Properties
 * @type {object}
 * @property {string} title
 * @property {object} content
 * @property {object?} actionContent
 */
import { loadStylesheet } from '../utils.js';
import van from '../van.min.js';

const { div, h3 } = van.tags;

const Card = (/** @type Properties */ props) => {
    loadStylesheet('card', stylesheet);

    return div(
        { class: 'tg-card mb-4' },
        div(
            { class: 'flex-row fx-justify-space-between fx-align-flex-start' },
            h3(
                { class: 'tg-card--title' },
                props.title,
            ),
            props.actionContent,
        ),
        props.content,
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-card {
    border-radius: 8px;
    background-color: var(--dk-card-background);
    padding: 16px;
}

.tg-card--title {
    margin: 0 0 16px;
    color: var(--secondary-text-color);
    font-size: 16px;
    font-weight: 500;
    text-transform: capitalize;
}
`);

export { Card };
