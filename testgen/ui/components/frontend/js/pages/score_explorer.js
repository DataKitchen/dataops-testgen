/**
 * @typedef ScoreDefinitionFilter
 * @type {object}
 * @property {string} field
 * @property {string} value
 * 
 * @typedef ScoreDefinition
 * @type {object}
 * @property {string} name
 * @property {boolean} total_score
 * @property {boolean} cde_score
 * @property {string} category
 * @property {ScoreDefinitionFilter[]} filters
 * 
 * @typedef ScoreCardCategory
 * @type {object}
 * @property {string} label
 * @property {string} score
 * 
 * @typedef ScoreCard
 * @type {object}
 * @property {string} project_code
 * @property {string} name
 * @property {string} score
 * @property {string} cde_score
 * @property {string} profiling_score
 * @property {string} testing_score
 * @property {ScoreCardCategory[]} categories 
 * 
 * @typedef ResultSet
 * @type {object}
 * @property {Array<string>} columns
 * @property {Array<object>} items
 * 
 * @typedef Properties
 * @type {object}
 * @property {object} filter_values
 * @property {ScoreDefinition} definition
 * @property {ScoreCard} score_card
 * @property {ResultSet?} breakdown
 * @property {string} breakdown_category
 * @property {string} breakdown_score_type
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { debounce, emitEvent, getValue, loadStylesheet, resizeFrameHeightOnDOMChange, resizeFrameHeightToElement, afterMount, getRandomId } from '../utils.js';
import { Input } from '../components/input.js';
import { Select } from '../components/select.js';
import { Button } from '../components/button.js';
import { ScoreCard } from '../components/score_card.js';
import { Checkbox } from '../components/checkbox.js';
import { Portal } from '../components/portal.js';
import { ScoreBreakdown } from '../components/score_breakdown.js';
import { IssuesTable } from '../components/score_issues.js';

const { div, i, span } = van.tags;

const TRANSLATIONS = {
    table_groups_name: 'Table Group',
    data_location: 'Data Location',
    data_source: 'Data Source',
    source_system: 'Source System',
    source_process: 'Source Process',
    business_domain: 'Business Domain',
    stakeholder_group: 'Stakeholder Group',
    transform_level: 'Transform Level',
    aggregation_level: 'Aggregation Level',
    dq_dimension: 'Quality Dimension',
};

const ScoreExplorer = (/** @type {Properties} */ props) => {
    window.testgen.isPage = true;

    loadStylesheet('score-explorer', stylesheet);
    Streamlit.setFrameHeight(1);

    const domId = 'score-explorer-page';
    resizeFrameHeightToElement(domId);
    resizeFrameHeightOnDOMChange(domId);

    const isNew = van.derive(() => {
        return !getValue(props.definition).id;
    });

    return div(
        { id: domId, class: 'score-explorer' },
        Toolbar(props.filter_values, getValue(props.definition), isNew),
        span({ class: 'mb-4', style: 'display: block;' }),
        ScoreCard(props.score_card),
        span({ class: 'mb-4', style: 'display: block;' }),
        () => {
            const drilldown = getValue(props.drilldown);
            const issuesValue = getValue(props.issues);

            return (
                (issuesValue && getValue(props.drilldown))
                ? IssuesTable(
                    issuesValue?.items,
                    issuesValue?.columns,
                    getValue(props.score_card),
                    getValue(props.breakdown_score_type),
                    getValue(props.breakdown_category),
                    drilldown,
                    () => emitEvent('DrilldownChanged', { payload: null }),
                )
                : ScoreBreakdown(
                    props.score_card,
                    props.breakdown,
                    props.breakdown_category,
                    props.breakdown_score_type,
                    (project_code, name, score_type, category, drilldown) => emitEvent('DrilldownChanged', { payload: drilldown }),
                )
            );
        },
    );
};

const Toolbar = (
    /** @type object */ filterValues,
    /** @type ScoreDefinition */ definition,
    /** @type boolean */ isNew,
) => {
    const addFilterButtonId = 'score-explorer--add-filter-btn';
    const categories = [
        'table_groups_name',
        'data_location',
        'data_source',
        'source_system',
        'source_process',
        'business_domain',
        'stakeholder_group',
        'transform_level',
        'dq_dimension',
    ];
    const filters = van.state(definition.filters.map((f, idx) => ({key: `${f.field}-${idx}-${getRandomId()}`, field: f.field, value: van.state(f.value) })));
    const filterSelectorOpened = van.state(false);
    const displayTotalScore = van.state(definition.total_score ?? true);
    const displayCategory = van.state(!!definition.category);
    const selectedCategory = van.state(definition.category ?? undefined);
    const scoreName = van.state(definition.name ?? '');
    const disableSave = van.derive(() => getValue(scoreName)?.length <= 0 || getValue(filters)?.length <= 0);
    const renderedFilters = {};

    let isInitialized = getValue(filters).length > 0;
    const addEmptyFilter = (field) => {
        isInitialized = false;
        filters.val = [ ...filters.val, { key: `${field}-${filters.val.length}-${getRandomId()}`, field, value: van.state(undefined) } ];
        filterSelectorOpened.val = false;
    };
    const removeFilter = (/** @type number */ position) => {
        filters.val = [ ...filters.val.slice(0, position), ...filters.val.slice(position + 1) ];
    };
    const setFilterValue = (/** @type number*/ position, /** @type string */ value) => {
        filters.val[position].value.val = value
        filters.val = [ ...filters.val ];
    };
    const refresh = debounce((payload) => emitEvent('ScoreUpdated', { payload }), 300);

    van.derive(() => {
        refresh({
            name: getValue(scoreName),
            filters: getValue(filters)
                .map((filter) => ({ ...filter, value: getValue(filter.value) }))    
                .filter((f) => f.field && f.value),
            category: getValue(displayCategory) ? getValue(selectedCategory) : null,
            total_score: getValue(displayTotalScore),
        });
    });

    van.derive(() => {
        let staleKeys = Object.keys(renderedFilters);
        for (const filter of getValue(filters)) {
            staleKeys = staleKeys.filter(key => key !== filter.key);
        }
        for (const key of staleKeys) {
            delete renderedFilters[key];
        }
    });

    return div(
        { class: 'flex-column score-explorer--toolbar' },
        div(
            { class: 'flex-column' },
            span({ class: 'text-caption mb-1' }, 'Filter By'),
            div(
                { class: 'flex-row fx-flex-wrap fx-gap-4' },
                () => {
                    const filters_ = getValue(filters);
                    const filterValues_ = getValue(filterValues);
                    if (filters_?.length <= 0) {
                        return '';
                    }

                    return div(
                        { class: 'flex-row fx-flex-wrap fx-gap-4' },
                        getValue(filters).map(({ key, field, value }, idx) => {
                            renderedFilters[key] = renderedFilters[key] ?? Filter(idx, field, value, filterValues_[field], setFilterValue, removeFilter, !isInitialized);
                            return renderedFilters[key];
                        }),
                    );
                },
                Button({
                    id: addFilterButtonId,
                    icon: 'add',
                    label: 'Add Filter',
                    type: 'basic',
                    color: 'primary',
                    style: 'width: auto;',
                    onclick: () => filterSelectorOpened.val = true,
                }),
                Portal(
                    { target: addFilterButtonId, style: '',  opened: filterSelectorOpened},
                    FilterFieldSelector(categories, undefined, addEmptyFilter),
                ),
            )
        ),
        div(
            { class: 'flex-row' },
            div(
                { class: 'flex-column fx-flex' },
                span({ class: 'text-caption mb-1 mt-1' }, 'Display on scorecard'),
                div(
                    { class: 'flex-row' },
                    Checkbox({
                        label: 'Total Score',
                        checked: displayTotalScore,
                        width: 150,
                        onChange: (checked) => displayTotalScore.val = checked,
                    }),
                    // Checkbox({
                    //     label: 'CDE Score',
                    //     checked: false,
                    //     width: 150,
                    // }),
                    Checkbox({
                        label: 'Category:',
                        checked: displayCategory,
                        onChange: (checked) => displayCategory.val = checked,
                    }),
                    Select({
                        style: 'margin-left: 4px;',
                        height: 40,
                        value: selectedCategory,
                        options: categories.map((c) => ({ value: c, label: TRANSLATIONS[c] })),
                        disabled: van.derive(() => !getValue(displayCategory)),
                    })
                ),
            ),
            div(
                { class: 'flex-row fx-align-flex-end' },
                Input({
                    label: 'Score Name',
                    height: 40,
                    style: 'margin-right: 16px;',
                    value: scoreName,
                    onChange: debounce((name) => scoreName.val = name, 300),
                }),
                () => {
                    const isNew_ = getValue(isNew);
                    return Button({
                        icon: isNew_ ? 'star' : undefined,
                        label: isNew_ ? 'Add to Quality Dashboard' : 'Save Changes',
                        type: 'stroked',
                        color: 'primary',
                        style: 'width: auto;',
                        disabled: disableSave,
                        onclick: () => emitEvent('ScoreDefinitionSaved', {}),
                    });
                },
            ),
        ),
    );
};


const Filter = (
    /** @type number */ position,
    /** @type string */ field,
    /** @type (string|undefined) */ value,
    /** @type string[] */ options,
    /** @type Function */ onChange,
    /** @type Function */ onRemove,
    /** @type boolean */ openOnRender = true,
) => {
    const id = `score-explorer-filter-${position}-${field}`;
    const opened = van.state(false);
    if (openOnRender) {
        afterMount(() => opened.val = true);
    }

    const onValueSelected = (selected) => {
        opened.val = false;
        onChange(position, selected);
    };

    return div(
        { id, class: 'flex-row score-explorer--filter' },
        span({ class: 'text-secondary mr-1' }, `${TRANSLATIONS[field]} =`),
        div(
            { class: 'flex-row clickable', onclick: () => opened.val = true },
            () => span({}, getValue(value) ?? '(Empty)'),
            i({class: 'material-symbols-rounded'}, 'arrow_drop_down'),
        ),
        Portal(
            {target: id, opened: opened},
            () => FilterFieldSelector(getValue(options), getValue(value), onValueSelected),
        ),
        i(
            {
                class: 'material-symbols-rounded clickable text-secondary',
                onclick: () => onRemove(position),
            },
            'clear',
        ),
    );
};

const FilterFieldSelector = (/** @type string[] */ options, /** @type string */ value, /** @type Function */ onSelect) => {
    return div(
        { class: 'flex-column score-explorer--selector mt-1' },
        (options?.length ?? 0) > 0
            ? options.map((v) =>
                span({ class: () => `pr-4 pl-4 pt-3 pb-3 ${getValue(value) === v ? 'selected' : ''}`, style: 'cursor: pointer;', onclick: () => onSelect(v) }, TRANSLATIONS[v] ?? v)
            )
            : span({ class: 'pr-4 pl-4 pt-3 pb-3 text-disabled disabled', style: 'cursor: not-allowed;' }, '(Empty)'),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.score-explorer {
    min-height: 600px;
}

.score-explorer--toolbar {
    border: 1px solid var(--border-color);
    border-radius: 8px;
    height: auto;
    padding: 16px;
}

.score-explorer--filter {
    background: var(--form-field-color);
    border-radius: 8px;
    padding: 8px 12px;
}

.score-explorer--selector {
    min-height: 41px;
    overflow-y: auto;
    background: var(--select-portal-background);
    box-shadow: rgba(0, 0, 0, 0.16) 0px 4px 16px;
    border-radius: 8px;

    z-index: 99;
}

.score-explorer--selector > span {
    padding: 12px 16px;
}

.score-explorer--selector > span:first-child {
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
}

.score-explorer--selector > span:last-child {
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
}

.score-explorer--selector > span:not(.disabled):hover {
    cursor: pointer;
    background: var(--select-hover-background);
}

.score-explorer--selector > span.selected {
    background: var(--select-hover-background);
    color: var(--primary-color);
}
`);

export { ScoreExplorer };
