/**
 * @typedef ScoreDefinitionFilter
 * @type {object}
 * @property {string} field
 * @property {string} value
 * @property {Array<FilterValue>?} others
 *
 * @typedef ScoreDefinition
 * @type {object}
 * @property {string} name
 * @property {string} project_code
 * @property {boolean} total_score
 * @property {boolean} cde_score
 * @property {string} category
 * @property {ScoreDefinitionFilter[]} filters
 * @property {boolean} filter_by_columns
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
 * @typedef Permissions
 * @type {object}
 * @property {boolean} can_edit
 *
 * @typedef Properties
 * @type {object}
 * @property {object} filter_values
 * @property {ScoreDefinition} definition
 * @property {ScoreCard} score_card
 * @property {ResultSet?} breakdown
 * @property {string} breakdown_category
 * @property {string} breakdown_score_type
 * @property {boolean} is_new
 * @property {Permissions} permissions
 */
import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { debounce, emitEvent, getValue, loadStylesheet, resizeFrameHeightOnDOMChange, resizeFrameHeightToElement, afterMount, getRandomId, isEqual } from '../utils.js';
import { Input } from '../components/input.js';
import { Select } from '../components/select.js';
import { Button } from '../components/button.js';
import { ScoreCard } from '../components/score_card.js';
import { Checkbox } from '../components/checkbox.js';
import { Portal } from '../components/portal.js';
import { ScoreBreakdown } from '../components/score_breakdown.js';
import { IssuesTable } from '../components/score_issues.js';
import { EmptyState, EMPTY_STATE_MESSAGE } from '../components/empty_state.js';
import { ColumnFilter } from '../components/explorer_column_selector.js';

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
    data_product: 'Data Product',
};

const ScoreExplorer = (/** @type {Properties} */ props) => {
    window.testgen.isPage = true;

    loadStylesheet('score-explorer', stylesheet);
    Streamlit.setFrameHeight(1);

    const domId = 'score-explorer-page';
    const userCanEdit = getValue(props.permissions)?.can_edit ?? false;
    const updateToolbarFilters = van.derive(() => {
        const oldFilters = props.definition.oldVal.filters;
        const newFilters = props.definition.val.filters;
        const oldFilterByColumns = props.definition.oldVal.filter_by_columns;
        const newFilterByColumns = props.definition.val.filter_by_columns;

        if (!isEqual(oldFilters, newFilters) || oldFilterByColumns !== newFilterByColumns) {
            return {filters: newFilters, filter_by_columns: newFilterByColumns};
        }

        return null;
    });

    resizeFrameHeightToElement(domId);
    resizeFrameHeightOnDOMChange(domId);

    return div(
        { id: domId, class: 'score-explorer' },
        Toolbar(props.filter_values, getValue(props.definition), props.is_new, userCanEdit, updateToolbarFilters),
        span({ class: 'mb-4', style: 'display: block;' }),
        () => {
            const isEmpty = getValue(props.is_new) && getValue(props.definition)?.filters?.length <= 0;

            if (isEmpty) {
                return EmptyState({
                    class: 'explorer-empty-state',
                    label: 'No filters or columns selected yet',
                    icon: 'readiness_score',
                    message: EMPTY_STATE_MESSAGE.explorer,
                });
            }
            
            return div(
                {class: 'flex-column'},
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
        },
    );
};

const Toolbar = (
    /** @type object */ filterValues,
    /** @type ScoreDefinition */ definition,
    /** @type boolean */ isNew,
    /** @type boolean */ userCanEdit,
    /** @type ... */ updates,
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
        'data_product',
    ];
    const filterableFields = categories.filter((c) => c !== 'dq_dimension');
    const filters = van.state(definition.filters.map((f, idx) => ({key: `${f.field}-${idx}-${getRandomId()}`, field: f.field, value: van.state(f.value), others: f.others ?? [] })));
    const filterByColumns = van.state(definition.filter_by_columns);
    const filterSelectorOpened = van.state(false);
    const displayTotalScore = van.state(definition.total_score ?? true);
    const displayCDEScore = van.state(definition.cde_score ?? true);
    const displayCategory = van.state(!!definition.category);
    const selectedCategory = van.state(definition.category ?? undefined);
    const scoreName = van.state(definition.name ?? '');
    const disableSave = van.derive(() => {
        const appliedFilters = getValue(filters);

        return getValue(scoreName)?.length <= 0
            || appliedFilters?.length <= 0
            || appliedFilters?.every(({ value }) => !value.rawVal)
            || (
                !getValue(displayTotalScore)
                && !getValue(displayCDEScore)
                && (!getValue(displayCategory) || !getValue(selectedCategory))
            )
    });
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
        filterByColumns.val = false;
        filters.val[position].value.val = value
        filters.val = [ ...filters.val ];
    };
    const refresh = debounce((payload) => emitEvent('ScoreUpdated', { payload }), 300);

    van.derive(() => {
        const previous = {
            name: scoreName.oldVal,
            filters: filters.oldVal
                .map((filter) => ({ ...filter, value: filter.value.oldVal }))
                .filter((f) => f.field && f.value),
            category: displayCategory.oldVal ? selectedCategory.oldVal : null,
            total_score: displayTotalScore.oldVal,
            cde_score: displayCDEScore.oldVal,
            filter_by_columns: filterByColumns.oldVal,
        };
        const current = {
            name: getValue(scoreName),
            filters: getValue(filters)
                .map((filter) => ({ ...filter, value: getValue(filter.value) }))
                .filter((f) => f.field && f.value),
            category: getValue(displayCategory) ? getValue(selectedCategory) : null,
            total_score: getValue(displayTotalScore),
            cde_score: getValue(displayCDEScore),
            filter_by_columns: getValue(filterByColumns),
        };

        if (!isEqual(current, previous)) {
            if (current.filter_by_columns && !previous.filter_by_columns) {
                emitEvent('ColumnSelectorOpened', {});
            } else if (!current.filter_by_columns && previous.filter_by_columns) {
                filterSelectorOpened.val = true;
            } else {
                refresh(current);
            }
        }
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

    van.derive(() => {
        const updatesValue = getValue(updates);
        if (updatesValue != null) {
            const simplifiedFilters = (filters.rawVal ?? []).map(f => ({ field: f.field, value: f.value.rawVal, others: f.others ?? []}))
            if (!isEqual(updatesValue.filters, simplifiedFilters)) {
                filters.val = updatesValue.filters.map((f, idx) => ({key: `${f.field}-${idx}-${getRandomId()}`, field: f.field, value: van.state(f.value), others: f.others ?? [] }));
            }

            if (updatesValue.filter_by_columns !== filterByColumns.rawVal) {
                filterByColumns.val = updatesValue.filter_by_columns;
            }
        }
    });

    return div(
        { class: 'flex-column score-explorer--toolbar' },
        div(
            { class: 'flex-column' },
            div(
                { class: 'flex-column' },
                span({ class: 'text-caption mb-1' }, 'Filter by'),
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
                            filters_.map(({ key, field, value, others }, idx) => {
                                renderedFilters[key] = renderedFilters[key] ?? (
                                    filterByColumns.val
                                        ? ColumnFilter({field, value, others})
                                        : Filter(idx, field, value, filterValues_[field], setFilterValue, removeFilter, !isInitialized && !value.val)
                                );
                                return renderedFilters[key];
                            }),
                        );
                    },
                    () => {
                        const filters_ = getValue(filters);
                        const filterByColumns_ = getValue(filterByColumns);

                        const fieldFilterTrigger = Button({
                            id: addFilterButtonId,
                            icon: 'add',
                            label: 'Add Filter',
                            type: 'basic',
                            color: 'primary',
                            style: 'width: auto;',
                            onclick: () => filterSelectorOpened.val = true,
                        });
                        const columnsSelectorTrigger = Button({
                            id: addFilterButtonId,
                            label: 'Select Columns',
                            type: 'basic',
                            color: 'primary',
                            style: 'width: auto;',
                            onclick: () => emitEvent('ColumnSelectorOpened', {}),
                        });
                        const combinedTrigger = div(
                            {class: 'flex-row fx-gap-3'},
                            fieldFilterTrigger,
                            span({class: 'text-caption'}, 'Or'),
                            columnsSelectorTrigger,
                        );
    
                        if (filters_?.length <= 0 && filterByColumns_ == undefined) {
                            return combinedTrigger;
                        }
    
                        if (filterByColumns_) {
                            return columnsSelectorTrigger;
                        }
    
                        return fieldFilterTrigger;
                    },
                    Portal(
                        { target: addFilterButtonId, style: '',  opened: filterSelectorOpened},
                        FilterFieldSelector(filterableFields, undefined, addEmptyFilter),
                    ),
                )
            ),
            div(
                { class: 'flex-row fx-justify-content-flex-end', style: 'width: 100%;' },
                () => {
                    if (filterByColumns.val == undefined) {
                        return '';
                    }

                    const switchToColumnSelectorTrigger = Button({
                        label: 'Switch to Column Selector',
                        type: 'basic',
                        color: 'primary',
                        style: 'width: auto;',
                        onclick: () => emitEvent('FilterModeChanged', {payload: true}),
                    });
                    const switchToCategoryFilterTrigger = Button({
                        label: 'Switch to Category Filters',
                        type: 'basic',
                        color: 'primary',
                        style: 'width: auto;',
                        onclick: () => emitEvent('FilterModeChanged', {payload: false}),
                    });

                    if (filterByColumns.val) {
                        return switchToCategoryFilterTrigger;
                    }
                    return switchToColumnSelectorTrigger;
                }
            ),
        ),
        div(
            { class: 'flex-row fx-align-flex-end fx-flex-wrap fx-gap-5' },
            div(
                { class: 'flex-column fx-flex' },
                span({ class: 'text-caption mt-3 mb-1' }, 'Display on scorecard'),
                div(
                    { class: 'flex-row fx-gap-4 fx-flex-wrap' },
                    Checkbox({
                        label: 'Total Score',
                        checked: displayTotalScore,
                        testId: 'include-total-score',
                        onChange: (checked) => displayTotalScore.val = checked,
                    }),
                    Checkbox({
                        label: 'CDE Score',
                        checked: displayCDEScore,
                        testId: 'include-cde-score',
                        onChange: (checked) => displayCDEScore.val = checked,
                    }),
                    div(
                        { class: 'flex-row fx-gap-4' },
                        Checkbox({
                            label: 'Category:',
                            checked: displayCategory,
                            testId: 'include-category',
                            onChange: (checked) => displayCategory.val = checked,
                        }),
                        Select({
                            style: 'margin-left: -8px;',
                            height: 40,
                            value: selectedCategory,
                            options: categories.map((c) => ({ value: c, label: TRANSLATIONS[c] })),
                            disabled: van.derive(() => !getValue(displayCategory)),
                            testId: 'category-selector',
                        }),
                    ),
                ),
            ),
            userCanEdit ? div(
                { class: 'flex-row fx-align-flex-end' },
                Input({
                    label: 'Scorecard Name',
                    height: 40,
                    style: 'margin-right: 16px;',
                    value: scoreName,
                    testId: 'scorecard-name-input',
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
                () => {
                    const isNew_ = getValue(isNew);
                    let href = 'quality-dashboard';
                    let params = {project_code: definition.project_code};
                    if (!isNew_) {
                        href = 'quality-dashboard:score-details';
                        params = {definition_id: definition.id};
                    }

                    return Button({
                        label: 'Cancel',
                        type: 'stroked',
                        color: 'warn',
                        style: 'width: auto; margin-left: 16px;',
                        onclick: () => emitEvent('LinkClicked', { href, params }),
                    });
                },
            ) : '',
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
        { id, class: 'flex-row score-explorer--filter', 'data-testid': 'explorer-filter' },
        span({ class: 'text-secondary mr-1', 'data-testid': 'explorer-filter-label' }, `${TRANSLATIONS[field]} =`),
        div(
            { class: 'flex-row clickable', 'data-testid': 'explorer-filter-trigger', onclick: () => opened.val = true },
            () => span({'data-testid': 'explorer-filter-selected'}, getValue(value) ?? '(Empty)'),
            i({class: 'material-symbols-rounded'}, 'arrow_drop_down'),
        ),
        Portal(
            {target: id, opened: opened},
            () => FilterFieldSelector(getValue(options), getValue(value), onValueSelected),
        ),
        i(
            {
                class: 'material-symbols-rounded clickable text-secondary',
                'data-testid': 'explorer-filter-remove',
                onclick: () => onRemove(position),
            },
            'clear',
        ),
    );
};

const FilterFieldSelector = (/** @type string[] */ options, /** @type string */ value, /** @type Function */ onSelect) => {
    return div(
        { class: 'flex-column score-explorer--selector mt-1', 'data-testid': 'explorer-filter-field-selector' },
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
    min-height: 1100px;
}

.explorer-empty-state {
    margin-top: unset !important;
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
    background: var(--portal-background);
    box-shadow: var(--portal-box-shadow);
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
