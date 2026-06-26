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
 * @property {string?} external_url
 * @property {object?} custom_metadata
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
import { Link } from '/app/static/js/components/link.js';

const { div, strong } = van.tags;

const isHttpUrl = (value) => typeof value === 'string' && /^https?:\/\//i.test(value.trim());

const metadataDisplayValue = (value) =>
    (value !== null && typeof value === 'object') ? JSON.stringify(value) : value;

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
                testDefinition.external_url
                    ? Attribute({
                        label: 'External URL',
                        value: isHttpUrl(testDefinition.external_url)
                            ? Link({
                                href: testDefinition.external_url,
                                label: testDefinition.external_url,
                                open_new: true,
                                underline: true,
                                right_icon: 'open_in_new',
                                right_icon_size: 16,
                            })
                            : testDefinition.external_url,
                        class: 'mt-4 external-url-attribute',
                      })
                    : '',
                testDefinition.custom_metadata && Object.keys(testDefinition.custom_metadata).length
                    ? div(
                        { class: 'flex-column fx-gap-3 mt-4' },
                        strong({}, 'Custom Metadata'),
                        div(
                            { class: 'flex-row fx-flex-wrap fx-gap-4 test-definition-attributes' },
                            Object.entries(testDefinition.custom_metadata).map(([key, value]) =>
                                Attribute({
                                    label: key,
                                    value: metadataDisplayValue(value),
                                    class: 'fx-flex',
                                })
                            ),
                        ),
                      )
                    : '',
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
.external-url-attribute .attribute-value {
    overflow-wrap: anywhere;
}
.external-url-attribute .tg-link {
    width: 100%;
    max-width: 100%;
}
.external-url-attribute .tg-link--wrapper {
    flex-wrap: wrap;
}
.external-url-attribute .tg-link--text {
    overflow-wrap: anywhere;
    word-break: break-all;
    min-width: 0;
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
