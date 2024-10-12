import {Streamlit} from "../streamlit.js";
import van from '../van.min.js';

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

    let defaultDirection = "ASC";

    if (!window.testgen.loadedStylesheets.sortingSelector) {
        document.adoptedStyleSheets.push(stylesheet);
        window.testgen.loadedStylesheets.sortSelector = true;
    }

    const columns = props.columns.val;
    const prevComponentState = props.state.val || [];

    const columnLabel = columns.reduce((acc, [colLabel, colId]) => ({ ...acc, [colId]: colLabel}), {});

    Streamlit.setFrameHeight(100 + 30 * columns.length);

    const componentState = columns.reduce(
        (state, [colLabel, colId]) => (
            { ...state, [colId]: van.state(prevComponentState[colId] || { direction: "ASC", order: null })}
        ),
        {}
    );

    const selectedDiv = div(
        {
            class: 'tg-sort-selector--column-list',
            style: `flex-grow: 1`,
        },
    );

    const directionIcons = {
        ASC: `arrow_downward`,
        DESC: `arrow_upward`,
    }

    const activeColumnItem = (colId) => {
        const state = componentState[colId];
        const directionIcon = van.derive(() => directionIcons[state.val.direction]);
        return button(
            {
                onclick: () => {
                    state.val = { ...state.val, direction: state.val.direction === "DESC" ? "ASC" : "DESC" };
                },
            },
            i(
                { class: `material-symbols-rounded` },
                directionIcon,
            ),
            span(columnLabel[colId]),
        )
    }

    const selectColumn = (colId, direction) => {
        componentState[colId].val = { direction: direction, order: selectedDiv.childElementCount }
        van.add(selectedDiv, activeColumnItem(colId));
    }

    prevComponentState.forEach(([colId, direction]) => selectColumn(colId, direction));

    const reset = () => {
        columns.map(
            ([colLabel, colId]) => (
                componentState[colId].val = { direction: defaultDirection, order: null }
            )
        );
        selectedDiv.innerHTML = ``;
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

    const optionsDiv = div(
        {
            class: 'tg-sort-selector--column-list',
        },
        columns.map(([colLabel, colId]) => van.derive(() => columnItem(colId))),
    )

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
        selectedDiv,
        div(
            { class: `tg-sort-selector--header` },
            span("Available columns")
        ),
        optionsDiv,
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


@media (prefers-color-scheme: dark) {
    .tg-sort-selector--column-list button:hover {
        background: #FFFFFF20;
    }
}

`);

export { SortingSelector };
