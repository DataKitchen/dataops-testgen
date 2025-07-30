import {Streamlit} from "../streamlit.js";
import van from '../van.min.js';
import { loadStylesheet } from '../utils.js';

/**
 * @typedef ColDef
 * @type {Array.<string, string>}
 *
 * @typedef StateItem
 * @type {Array.<string, string>}
 *
 *  @typedef Properties
 * @type {object}
 * @property {Array.<ColDef>} columns
 * @property {Array.<StateItem>} state
 */
const { button, div, i, span } = van.tags;

const SortingSelector = (/** @type {Properties} */ props) => {
    loadStylesheet('sortingSelector', stylesheet);

    let defaultDirection = "ASC";

    const columns = props.columns.val;
    const prevComponentState = props.state.val || [];

    const columnLabel = columns.reduce((acc, [colLabel, colId]) => ({ ...acc, [colId]: colLabel}), {});

    if (!window.testgen.isPage) {
        Streamlit.setFrameHeight(100 + 30 * columns.length);
    }

    const componentState = columns.reduce(
        (state, [colLabel, colId]) => (
            { ...state, [colId]: van.state(prevComponentState[colId] || { direction: "ASC", order: null })}
        ),
        {}
    );

    const directionIcons = {
        ASC: `arrow_upward`,
        DESC: `arrow_downward`,
    }

    const activeColumnItem = (colId) => {
        const state = componentState[colId];
        const directionIcon = van.derive(() => directionIcons[state.val.direction]);
        return button(
            {
                class: 'flex-row',
                onclick: () => {
                    state.val = { ...state.val, direction: state.val.direction === "DESC" ? "ASC" : "DESC" };
                },
            },
            i(
                { class: `material-symbols-rounded` },
                directionIcon,
            ),
            span(columnLabel[colId]),
            i(
                {
                    class: `material-symbols-rounded clickable dismiss-button`,
                    style: `margin-left: auto;`,
                    onclick: (event) => {
                        event?.preventDefault();
                        event?.stopPropagation();

                        componentState[colId].val = { direction: defaultDirection, order: null };
                    },
                },
                'close',
            ),
        )
    }

    const selectColumn = (colId, direction) => {
        const activeColumnsCount = Object.values(componentState).filter((columnState) => columnState.val.order != null).length;
        componentState[colId].val = { direction: direction, order: activeColumnsCount };
    }

    prevComponentState.forEach(([colId, direction]) => selectColumn(colId, direction));

    const reset = () => {
        columns.map(
            ([colLabel, colId]) => (
                componentState[colId].val = { direction: defaultDirection, order: null }
            )
        );
    }

    const externalComponentState = () => Object.entries(componentState).filter(
        ([colId, colState]) => colState.val.order !== null
    ).sort(
        ([colIdA, colStateA], [colIdB, colStateB]) => colStateA.val.order - colStateB.val.order
    ).map(
        ([colId, colState]) => [colId, colState.val.direction]
    )

    const apply = () => {
        Streamlit.sendData(externalComponentState());
    }

    const columnItem = (colId) => {
        const state = componentState[colId];
        return button(
            {
                onclick: () => selectColumn(colId, defaultDirection),
                hidden: state.val.order !== null,
            },
            i(
                {
                    class: `material-symbols-rounded`,
                    style: `color: var(--disabled-text-color);`,
                },
                `expand_all`
            ),
            span(columnLabel[colId]),
        )
    }

    const resetDisabled = () => Object.entries(componentState).filter(
        ([colId, colState]) => colState.val.order != null
    ).length === 0;

    const applyDisabled = () => externalComponentState().toString() === (props.state.val || []).toString();

    return div(
        { class: 'tg-sort-selector' },
        div(
            {
                class: `tg-sort-selector--header`,
            },
            span("Selected columns")
        ),
        () => div(
            {
                class: 'tg-sort-selector--column-list',
                style: `flex-grow: 1`,
            },
            Object.entries(componentState)
                .filter(([, colState]) => colState.val.order != null)
                .sort(([, colState]) => colState.val.order)
                .map(([colId,]) => activeColumnItem(colId))
        ),
        div(
            { class: `tg-sort-selector--header` },
            span("Available columns")
        ),
        div(
            {
                class: 'tg-sort-selector--column-list',
            },
            columns.map(([colLabel, colId]) => van.derive(() => columnItem(colId))),
        ),
        div(
            { class: `tg-sort-selector--footer` },
            button(
                {
                    onclick: reset,
                    style: `color: var(--button-text-color);`,
                    disabled: van.derive(resetDisabled),
                },
                span(`Reset`),
            ),
            button(
                { onclick: apply, disabled: van.derive(applyDisabled) },
                span(`Apply`),
            )
        )
    );
};


const stylesheet = new CSSStyleSheet();
stylesheet.replace(`

.tg-sort-selector {
    height: 100vh;
    display: flex;
    flex-direction: column;
    align-content: flex-end;
    justify-content: space-between;
}

.tg-sort-selector--column-list {
    display: flex;
    flex-direction: column;
}

.tg-sort-selector--column-list button {
    margin: 0;
    border: 0;
    padding: 5px 0;
    text-align: left;
    background: transparent;
    color: var(--button-text-color);
}

.tg-sort-selector--column-list button:hover {
    background: #00000010;
}

.tg-sort-selector--column-list button * {
    vertical-align: middle;
}

.tg-sort-selector--column-list button i {
    font-size: 20px;
}


.tg-sort-selector--column-list {
    border-bottom: 3px dotted var(--disabled-text-color);
    padding-bottom: 8px;
    margin-bottom: 8px;
}

.tg-sort-selector--header {
    text-align: right;
    text-transform: uppercase;
    font-size: 70%;
    color: var(--secondary-text-color);
}

.tg-sort-selector--footer {
    display: flex;
    flex-direction: row;
    justify-content: space-between;
    margin-top: 8px;
}

.tg-sort-selector--footer button {
    background-color: var(--button-stroked-background);
    color: var(--button-stroked-text-color);
    border: var(--button-stroked-border);
    padding: 5px 20px;
    border-radius: 5px;
}

.tg-sort-selector--footer button[disabled] {
    color: var(--disabled-text-color) !important;
}

.dismiss-button {
    margin-left: auto;
    color: var(--disabled-text-color);
}
.dismiss-button:hover {
    color: var(--button-text-color);
}

@media (prefers-color-scheme: dark) {
    .tg-sort-selector--column-list button:hover {
        background: #FFFFFF20;
    }
}

`);

export { SortingSelector };
