/**
 * @import { TestDefinition } from '../components/test_definition_form.js';
 * 
 * @typedef Properties
 * @type {object}
 * @property {string} table_name
 * @property {TestDefinition[]} definitions
 */

import van from '../van.min.js';
import { Streamlit } from '../streamlit.js';
import { emitEvent, getValue, loadStylesheet, isEqual } from '../utils.js';
import { Button } from '../components/button.js';
import { Card } from '../components/card.js';
import { TestDefinitionForm } from '../components/test_definition_form.js';

const { div, span } = van.tags;

const monitorOptions = [
    { key: 'Freshness_Trend', label: 'Freshness' },
    { key: 'Volume_Trend', label: 'Volume' },
];

const EditTableMonitors = (/** @type Properties */ props) => {
    loadStylesheet('edit-table-monitors', stylesheet);
    window.testgen.isPage = true;

    const definitions = getValue(props.definitions);
    const selectedMonitorType = van.state('Freshness_Trend');

    const formChanges = van.state({});
    const formStates = van.state({});

    const isDirty = van.derive(() => Object.values(formStates.val).some(s => s.dirty));
    const isValid = van.derive(() => Object.values(formStates.val).every(s => s.valid));

    return div(
        div(
            { class: 'edit-monitors flex-row fx-align-stretch' },
            div(
                { class: 'edit-monitors--list' },
                monitorOptions.map(({ key, label }) => div(
                    {
                        class: () => `edit-monitors--item clickable p-2 border-radius-1 ${selectedMonitorType.val === key ? 'selected' : ''}`,
                        onclick: () => selectedMonitorType.val = key,
                    },
                    span(label),
                )),
            ),
            span({ class: 'edit-monitors--divider' }),
            () => {
                const selectedDef = definitions.find(td => td.test_type === selectedMonitorType.val);
                if (!selectedDef) {
                    return Card({
                        class: 'edit-monitors--empty flex-row fx-justify-center',
                        content: 'Monitor not configured for this table.',
                    });
                }

                return div(
                    TestDefinitionForm({
                        definition: selectedDef,
                        onChange: (changes, state) => {
                            changes.id = selectedDef.id;
                            changes.lock_refresh = true;
                            formChanges.val = { ...formChanges.val, [selectedMonitorType.val]: changes };
                            formStates.val = { ...formStates.val, [selectedMonitorType.val]: state };
                        },
                    }),
                );
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
                    const changes = Object.values(formChanges.val);
                    emitEvent('SaveTestDefinition', { payload: { definitions: changes } });
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
    flex: 180px 0 0;
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

.edit-monitors--divider {
    width: 2px;
    background-color: var(--border-color);
    margin: 0 12px;
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
