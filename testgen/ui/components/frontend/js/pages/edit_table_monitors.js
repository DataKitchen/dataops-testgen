/**
 * @import { TestDefinition } from '../components/test_definition_form.js';
 *
 * @typedef Properties
 * @type {object}
 * @property {string} table_name
 * @property {TestDefinition[]} definitions
 * @property {object} metric_test_type
 */

import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet, isEqual } from '../utils.js';
import { Button } from '../components/button.js';
import { Card } from '../components/card.js';
import { TestDefinitionForm } from '../components/test_definition_form.js';

const { div, span } = van.tags;

const defaultMonitorOptions = [
    { key: 'Freshness_Trend', label: 'Freshness' },
    { key: 'Volume_Trend', label: 'Volume' },
];

const EditTableMonitors = (/** @type Properties */ props) => {
    loadStylesheet('edit-table-monitors', stylesheet);
    window.testgen.isPage = true;

    const definitions = getValue(props.definitions);
    const metricTestType = getValue(props.metric_test_type);
    
    const updatedDefinitions = van.state({}); // { [id]: changes } - only changes for existing definitions
    const newMetrics = van.state({}); // { [tempId]: metric }
    const deletedMetricIds = van.state([]);

    const formStates = van.state({}); // { [id]: { dirty, valid } }
    const isDirty = van.derive(() => {
        return Object.values(formStates.val).some(s => s.dirty) // changes
            || Object.keys(newMetrics.val).length // adds
            || deletedMetricIds.val.length; // deletes
    });
    const isValid = van.derive(() => Object.values(formStates.val).every(s => s.valid));

    const existingMetrics = Object.fromEntries(
        definitions.filter(td => td.test_type === 'Metric_Trend').map(metric => [metric.id, metric])
    );
    const displayedMetrics = van.derive(() => {
        const existing = Object.values(existingMetrics).filter(metric => !deletedMetricIds.val.includes(metric.id));
        return [...existing, ...Object.values(newMetrics.val)];
    });
    const selectedItem = van.state({ type: 'Freshness_Trend', id: null });

    return div(
        div(
            { class: 'edit-monitors flex-row fx-align-stretch' },
            div(
                { class: 'edit-monitors--list' },
                defaultMonitorOptions.map(({ key, label }) => div(
                    {
                        class: () => `edit-monitors--item clickable p-2 border-radius-1 ${selectedItem.val.type === key ? 'selected' : ''}`,
                        onclick: () => selectedItem.val = { type: key, id: null },
                    },
                    span(label),
                )),
                div({ class: 'edit-monitors--list-divider mt-3 mb-1' }),
                div(
                    { class: 'flex-row fx-justify-space-between fx-align-center mb-2' },
                    span({ class: 'text-secondary' }, 'Metrics'),
                    Button({
                        icon: 'add',
                        label: 'Add',
                        width: 'auto',
                        color: 'primary',
                        onclick: () => {
                            const tempId = `temp_${Date.now()}`;
                            const newMetric = {
                                _tempId: tempId,
                                column_name: '',
                                custom_query: '',
                                history_calculation: 'PREDICT',
                                history_calculation_upper: null,
                                history_lookback: null,
                                ...metricTestType,
                            };
                            newMetrics.val = { ...newMetrics.val, [tempId]: newMetric };
                            selectedItem.val = { type: 'Metric_Trend', id: tempId };
                        },
                    }),
                ),
                () => displayedMetrics.val.length
                    ? div(
                        displayedMetrics.val.map(metric => {
                            const id = metric.id || metric._tempId;
                            const isNew = !metric.id;

                            return div(
                                {
                                    class: () => `edit-monitors--item clickable p-2 pr-0 border-radius-1 flex-row fx-justify-space-between ${selectedItem.val.id === id ? 'selected' : ''}`,
                                    onclick: () => selectedItem.val = { type: 'Metric_Trend', id },
                                },
                                span(
                                    { style: `text-overflow: ellipsis; ${!metric.column_name ? 'font-style: italic;' : ''}` },
                                    metric.column_name || '(Unnamed Metric)',
                                ),
                                Button({
                                    type: 'icon',
                                    icon: 'delete',
                                    onclick: (event) => {
                                        // Prevent bubbling the event and triggering the parent's onclick
                                        event.stopPropagation();
                                        if (isNew) {
                                            const { [id]: _removed, ...remaining } = newMetrics.val;
                                            newMetrics.val = remaining;
                                        } else {
                                            deletedMetricIds.val = [...deletedMetricIds.val, id];
                                            const { [id]: _removedDef, ...remainingDefs } = updatedDefinitions.val;
                                            updatedDefinitions.val = remainingDefs;
                                        }
                                        const { [id]: _removedState, ...remainingStates } = formStates.val;
                                        formStates.val = remainingStates;
                                        if (selectedItem.val.id === id) {
                                            selectedItem.val = { type: 'Freshness_Trend', id: null };
                                        }
                                    },
                                }),
                            );
                        }),
                    )
                    : div(
                        { class: 'flex-row fx-justify-center text-caption', style: 'height: 100px;' },
                        'No metrics defined yet',
                    ),
            ),
            span({ class: 'edit-monitors--divider' }),
            () => {
                const { type, id } = selectedItem.val;

                if (type === 'Metric_Trend') {
                    const isNew = id.startsWith('temp_');
                    const metricDefinition = isNew
                        ? newMetrics.rawVal[id]
                        : { ...existingMetrics[id], ...updatedDefinitions.rawVal[id] };

                    return TestDefinitionForm({
                        definition: metricDefinition,
                        class: 'edit-monitors--form',
                        onChange: (changes, state) => {
                            if (isNew) {
                                newMetrics.val = {
                                    ...newMetrics.val,
                                    [id]: { ...newMetrics.val[id], ...changes },
                                };
                            } else {
                                updatedDefinitions.val = {
                                    ...updatedDefinitions.val,
                                    [id]: { ...changes, id },
                                };
                            }
                            formStates.val = { ...formStates.val, [id]: state };
                        },
                    });
                }

                const selectedDef = definitions.find(td => td.test_type === type);
                if (!selectedDef) {
                    return Card({
                        class: 'edit-monitors--empty flex-row fx-justify-center',
                        content: 'Monitor not configured for this table.',
                    });
                }

                return TestDefinitionForm({
                    definition: { ...selectedDef, ...updatedDefinitions.rawVal[selectedDef.id] },
                    class: 'edit-monitors--form',
                    onChange: (changes, state) => {
                        updatedDefinitions.val = {
                            ...updatedDefinitions.val,
                            [selectedDef.id]: { ...changes, id: selectedDef.id },
                        };
                        formStates.val = { ...formStates.val, [selectedDef.id]: state };
                    },
                });
            },
        ),
        div(
            { class: 'edit-monitors--footer flex-row fx-justify-content-flex-end mt-4 pt-4' },
            Button({
                label: 'Save',
                color: 'primary',
                type: 'flat',
                width: 'auto',
                disabled: () => !isDirty.val || !isValid.val,
                onclick: () => {
                    const payload = {
                        updated_definitions: Object.values(updatedDefinitions.val),
                        new_metrics: Object.values(newMetrics.val),
                        deleted_metric_ids: deletedMetricIds.val,
                    };
                    emitEvent('SaveTestDefinition', { payload });
                },
            }),
        ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.edit-monitors {
    min-height: 350px;
}

.edit-monitors--list {
    flex: 200px 0 0;
}

.edit-monitors--item {
    height: 40px;
}

.edit-monitors--item:hover {
    background-color: var(--sidebar-item-hover-color);
}

.edit-monitors--item.selected {
    background-color: #06a04a17;
}

.edit-monitors--item.selected > span {
    font-weight: 500;
}

.edit-monitors--list-divider {
    height: 1px;
    background-color: var(--border-color);
}

.edit-monitors--divider {
    width: 2px;
    background-color: var(--border-color);
    margin: 0 12px;
}

.edit-monitors--form {
    flex: auto;
}

.edit-monitors--empty {
    flex: 1;
    margin: 0;
}

.edit-monitors--footer {
    border-top: 1px solid var(--border-color);
}
`);

export { EditTableMonitors };

export default (component) => {
    const { data, setTriggerValue, parentElement } = component;
    Streamlit.enableV2(setTriggerValue);

    let componentState = parentElement.state;
    if (componentState === undefined) {
        componentState = {};
        for (const [key, value] of Object.entries(data)) {
            componentState[key] = van.state(value);
        }
        parentElement.state = componentState;
        van.add(parentElement, EditTableMonitors(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => {
        parentElement.state = null;
    };
};
