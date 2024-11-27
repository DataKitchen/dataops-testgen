/**
 * @typedef Falvor
 * @type {object}
 * @property {string} label
 * @property {string} value
 * @property {string} icon
 * @property {(boolean|null)} selected
 * 
 * @typedef Properties
 * @type {object}
 * @property {Array.<Flavor>} flavors
 * @property {((number|null))} selected
 * @property {(number|null)} columns
 */

import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { loadStylesheet } from '../utils.js';

const headerHeight = 35;
const rowGap = 16;
const rowHeight = 67;
const columnSize = '200px';
const { div, span, img, h3 } = van.tags;

const DatabaseFlavorSelector = (/** @type Properties */props) => {
    loadStylesheet('databaseFlavorSelector', stylesheet);

    const flavors = props.flavors?.val ?? props.flavors;
    const numberOfColumns = props.columns?.val ?? props.columns ?? 3;
    const numberOfRows = Math.ceil(flavors.length / numberOfColumns);
    const selectedIndex = van.state(props.selected?.val ?? props.selected);

    window.testgen.isPage = true;
    Streamlit.setFrameHeight(
        headerHeight
        + rowHeight * numberOfRows
        + rowGap * (numberOfRows - 1)
    );

    return div(
        {class: 'tg-flavor-selector-page'},
        h3(
            {class: 'tg-flavor-selector-header'},
            'Select your database type'
        ),
        () => {
            return div(
                {
                    class: 'tg-flavor-selector',
                    style: `grid-template-columns: ${Array(numberOfColumns).fill(columnSize).join(' ')}; row-gap: ${rowGap}px;`
                },
                flavors.map((flavor, idx) =>
                    DatabaseFlavor(
                        {
                            label: van.state(flavor.label),
                            value: van.state(flavor.value),
                            icon: van.state(flavor.icon),
                            selected: van.derive(() => selectedIndex.val == idx),
                        },
                        () => {
                            selectedIndex.val = idx;
                            Streamlit.sendData({index: idx, value: flavor.value});
                        },
                    )
                ),
            );
        },
    );
};

const DatabaseFlavor = (
    /** @type Falvor */ props,
    /** @type Function */ onClick,
) => {
    return div(
        {
            class: () => `tg-flavor ${props.selected.val ? 'selected' : ''}`,
            onclick: onClick,
        },
        span({class: 'tg-flavor-focus-state-indicator'}, ''),
        img(
            {class: 'tg-flavor--icon', src: props.icon},
        ),
        span(
            {class: 'tg-flavor--label'},
            props.label
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
    .tg-flavor-selector-header {
        margin: unset;
        margin-bottom: 16px;
        font-weight: 400;
    }

    .tg-flavor-selector {
        display: grid;
        grid-template-rows: auto;
        column-gap: 32px;
    }

    .tg-flavor {
        display: flex;
        align-items: center;
        padding: 16px;
        border: 1px solid var(--border-color);
        border-radius: 4px;
        cursor: pointer;
        position: relative;
    }

    .tg-flavor .tg-flavor-focus-state-indicator::before {
        content: "";
        opacity: 0;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        position: absolute;
        pointer-events: none;
        border-radius: inherit;
        background: var(--button-primary-hover-state-background);
    }

    .tg-flavor.selected {
        border-color: var(--primary-color);
    }

    .tg-flavor:hover .tg-flavor-focus-state-indicator::before,
    .tg-flavor.selected .tg-flavor-focus-state-indicator::before {
        opacity: var(--button-hover-state-opacity);
    }

    .tg-flavor--icon {
        margin-right: 16px;
    }

    .tg-flavor--label {
        font-weight: 500;
    }
`);

export { DatabaseFlavorSelector };
