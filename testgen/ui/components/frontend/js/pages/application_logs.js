import van from '/app/static/js/van.min.js';
import { Streamlit } from '/app/static/js/streamlit.js';
import { emitEvent, getValue, isEqual } from '/app/static/js/utils.js';
import { ApplicationLogsDialog } from '../shared/application_logs_dialog.js';

const ApplicationLogs = (props) => {
    return ApplicationLogsDialog({
        logsData: props.logs_data,
        onClose: () => emitEvent('LogsDialogClosed', {}),
        onDateChanged: (dateString) => emitEvent('DateChanged', { payload: dateString }),
        onRefresh: () => emitEvent('Refresh', {}),
    });
};

export default (component) => {
    const { data, setStateValue, setTriggerValue, parentElement } = component;

    Streamlit.enableV2(setTriggerValue);

    let componentState = parentElement.state;
    if (componentState === undefined) {
        componentState = {};
        for (const [key, value] of Object.entries(data)) {
            componentState[key] = van.state(value);
        }
        parentElement.state = componentState;
        van.add(parentElement, ApplicationLogs(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => {
        parentElement.state = null;
        Streamlit.disableV2(setTriggerValue);
    };
};
