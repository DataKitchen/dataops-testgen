/**
 * @typedef TestDefinitionAttribute
 * @type {object}
 * @property {string} label
 * @property {string} value
 * @property {string?} help
 * 
 * @typedef TestDefinition
 * @type {object}
 * @property {string} schema
 * @property {string} test_suite_name
 * @property {string} table_name
 * @property {string} test_focus
 * @property {string} severity
 * @property {string} active
 * @property {string} locked
 * @property {string} export_to_observability
 * @property {string?} last_manual_update
 * @property {string?} usage_notes
 * @property {Array<TestDefinitionAttribute>} attributes
 * 
 * @typedef Properties
 * @type {object}
 * @property {TestDefinition} test_definition
 */
import van from '/app/static/js/van.min.js';
import { createEmitter, getValue, isEqual, loadStylesheet } from '/app/static/js/utils.js';
import { Alert } from '/app/static/js/components/alert.js';
import { Attribute } from '/app/static/js/components/attribute.js';

const { div, strong } = van.tags;

/**
 * @param {Properties} props 
 * @returns 
 */
const TestDefinitionSummary = (props) => {
    const { emit } = props;
    loadStylesheet('test-definition-summary', stylesheet)

    const wrapperId = 'test-definition-summary';


    return div(
        {id: wrapperId},
        () => {
            const testDefinition = getValue(props.test_definition);

            return div(
                { class: 'flex-column' },
                div(
                    { class: 'flex-row fx-gap-1 fx-align-flex-start' },
                    div(
                        { class: 'flex-column fx-flex fx-gap-4 test-definition-attributes'},
                        Attribute({
                            label: 'Schema Name',
                            value: testDefinition.schema,
                            class: 'fx-flex'
                        }),
                        Attribute({
                            label: 'Test Suite Name',
                            value: testDefinition.test_suite_name,
                            class: 'fx-flex'
                        }),
                        Attribute({
                            label: 'Table Name',
                            value: testDefinition.table_name,
                            class: 'fx-flex'
                        }),
                        Attribute({
                            label: 'Test Focus',
                            value: testDefinition.test_focus,
                            class: 'fx-flex'
                        }),
                        Attribute({
                            label: 'Test Active',
                            value: testDefinition.active,
                            class: 'fx-flex'
                        }),
                        Attribute({
                            label: 'Lock Refresh',
                            value: testDefinition.locked,
                            class: 'fx-flex'
                        }),
                        Attribute({
                            label: 'Last Manual Update',
                            value: testDefinition.last_manual_update
                                ? Intl.DateTimeFormat("en-US", {dateStyle: 'long', timeStyle: 'long'}).format(Date.parse(testDefinition.last_manual_update))
                                : undefined,
                            class: 'fx-flex'
                        }),
                    ),
                    div(
                        { class: 'flex-column fx-flex fx-gap-4 test-definition-attributes'},
                        Attribute({
                            label: 'Test Result Urgency',
                            value: testDefinition.severity,
                            class: 'fx-flex'
                        }),
                        Attribute({
                            label: 'Send to Observability',
                            value: testDefinition.export_to_observability,
                            class: 'fx-flex'
                        }),
                        testDefinition.attributes.map(attribute =>
                            Attribute({
                                label: attribute.label,
                                value: attribute.value,
                                help: attribute.help,
                                class: 'fx-flex'
                            })
                        ),
                    ),
                ),
                testDefinition.usage_notes
                    ? Alert(
                        { type: 'info', class: 'mt-4' },
                        strong({class: 'mb-4'}, 'Usage Notes'),
                        testDefinition.usage_notes,
                      )
                    : '',
            );
        },
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.test-definition-attributes > div .text-caption {
    font-size: 14px;
}
.test-definition-attributes > div .attribute-value {
    font-size: 16px;
}
`);

export { TestDefinitionSummary };

export default (component) => {
    const { data, setStateValue, setTriggerValue, parentElement } = component;

    let componentState = parentElement.state;
    if (componentState === undefined) {
        componentState = {};
        for (const [key, value] of Object.entries(data)) {
            componentState[key] = van.state(value);
        }
        parentElement.state = componentState;
        componentState.emit = createEmitter(setTriggerValue);
        van.add(parentElement, TestDefinitionSummary(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => { parentElement.state = null; };
};
