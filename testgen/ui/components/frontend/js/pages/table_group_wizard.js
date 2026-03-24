import van from '/app/static/js/van.min.js';
import { isEqual } from '/app/static/js/utils.js';
import { Streamlit } from '/app/static/js/streamlit.js';
import { TableGroupWizard } from '/app/static/js/components/table_group_wizard.js';

export { TableGroupWizard };

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
    van.add(parentElement, TableGroupWizard(componentState));
  } else {
    for (const [ key, value ] of Object.entries(data)) {
      if (!isEqual(componentState[key].val, value)) {
        componentState[key].val = value;
      }
    }
  }

  return () => {
    parentElement.state = null;
  };
};
