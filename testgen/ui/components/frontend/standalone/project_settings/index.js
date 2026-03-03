/**
 * @import {VanState} from '/app/static/js/van.min.js';
 */
import van from '/app/static/js/van.min.js';
import { Streamlit } from '/app/static/js/streamlit.js';
import { Card } from '/app/static/js/components/card.js';
import { Input } from '/app/static/js/components/input.js';
import { Button } from '/app/static/js/components/button.js';
import { required } from '/app/static/js/form_validators.js';
import { Alert } from '/app/static/js/components/alert.js';
import { emitEvent, getValue, isEqual } from '/app/static/js/utils.js';

const { div, span } = van.tags;

/**
 * @typedef ObsTestResults
 * @type {object}
 * @property {boolean} successful
 * @property {string} message
 * @property {string?} details
 * 
 * @typedef Properties
 * @type {object}
 * @property {VanState<string>} name
 * @property {VanState<string?>} observability_api_url
 * @property {VanState<string?>} observability_api_key
 * @property {VanState<ObsTestResults?>} observability_test_results
 * 
 * @param {Properties} props
 */
const ProjectSettings = (props) => {
    const /** @type Properties */ form = {
        name: van.state(props.name.rawVal ?? ''),
        observability_api_key: van.state(props.observability_api_key.rawVal ?? ''),
        observability_api_url: van.state(props.observability_api_url.rawVal ?? ''),
    };
    const formValidity = {
        name: van.state(!!form.name.rawVal),
        observability_api_key: van.state(true),
        observability_api_url: van.state(true),
    };
    const saveDisabled = van.derive(() => !formValidity.name.val || !formValidity.observability_api_url.val || !formValidity.observability_api_key.val);
    const testObservabilityDisabled = van.derive(() => form.observability_api_url.val.length <= 0 || form.observability_api_key.val.length <= 0);

    return div(
        { class: 'flex-column fx-gap-3' },
        div(
            { class: 'flex-column fx-gap-1' },
            span({ class: 'body m' }, 'Project Info'),
            Card({
                class: 'mb-0',
                border: true,
                content: div(
                    { class: 'flex-column fx-gap-3'},
                    Input({
                        label: 'Project Name',
                        value: form.name,
                        validators: [ required ],
                        onChange: (value, validity) => {
                            form.name.val = value;
                            formValidity.name.val = validity.valid;
                        },
                    }),
                ),
            }),
        ),
        div(
            { class: 'flex-column fx-gap-1' },
            span({ class: 'body m' }, 'Observability Integration'),
            Card({
                class: 'mb-0',
                border: true,
                content: div(
                    { class: 'flex-column fx-gap-3'},
                    Input({
                        label: 'API URL',
                        value: form.observability_api_url,
                        onChange: (value, validity) => {
                            form.observability_api_url.val = value;
                            formValidity.observability_api_url.val = validity.valid;
                        },
                    }),
                    Input({
                        label: 'API Key',
                        value: form.observability_api_key,
                        onChange: (value, validity) => {
                            form.observability_api_key.val = value;
                            formValidity.observability_api_key.val = validity.valid;
                        },
                    }),
                    div(
                        { class: 'flex-row' },
                        Button({
                            type: 'stroked',
                            color: 'basic',
                            label: 'Test Observability Connection',
                            width: 'auto',
                            disabled: testObservabilityDisabled,
                            onclick: () => emitEvent('TestObservabilityClicked', {
                                payload: {
                                    observability_api_url: form.observability_api_url.rawVal,
                                    observability_api_key: form.observability_api_key.rawVal,
                                },
                            }),
                        }),
                    ),
                    () => {
                        const results = getValue(props.observability_test_results) ?? {};
                        return Object.keys(results).length > 0
                            ? Alert(
                                { type: results.successful ? 'success' : 'error' },
                                div(
                                    { class: 'flex-column' },
                                    span(results.message),
                                    results.details ? span(results.details) : '',
                                ),
                            )
                            : '';
                    },
                ),
            }),
        ),
        div(
            { class: 'flex-row fx-justify-content-flex-end' },
            Button({
                type: 'stroked',
                color: 'primary',
                label: 'Save',
                width: 'auto',
                disabled: saveDisabled,
                onclick: () => emitEvent('SaveClicked', {
                    payload: Object.fromEntries(Object.entries(form).map(([fieldName, value]) => [fieldName, value.rawVal]))
                }),
            }),
        ),
    );
};

export default (component) => {
  const { data, setStateValue, setTriggerValue, parentElement } = component;

  Streamlit.enableV2(setTriggerValue);

  let componentState = parentElement.state;
  if (componentState === undefined) {
    componentState = {};
    for (const [ key, value ] of Object.entries(data)) {
      componentState[key] = van.state(value);
    }

    parentElement.state = componentState;
    van.add(parentElement, ProjectSettings(componentState));
  } else {
    for (const [ key, value ] of Object.entries(data)) {
      if (!isEqual(componentState[key].val, value)) {
        componentState[key].val = value;
      }
    }
  }

  return () => {
    Streamlit.disableV2(setTriggerValue);
    parentElement.state = null;
  };
};
