import van from '/app/static/js/van.min.js';
import { createEmitter, isEqual } from '/app/static/js/utils.js';
import { ApplicationLogsDialog } from '../shared/application_logs_dialog.js';

const ApplicationLogs = (props) => {
    const { emit } = props;
    return ApplicationLogsDialog({
        logsData: props.logs_data,
        onClose: () => emit('LogsDialogClosed', {}),
        onDateChanged: (dateString) => emit('DateChanged', { payload: dateString }),
        onRefresh: () => emit('Refresh', {}),
    });
};

export default (component) => {
    const { data, setTriggerValue, parentElement } = component;

    let componentState = parentElement.state;
    if (componentState === undefined) {
        componentState = {};
        for (const [key, value] of Object.entries(data)) {
            componentState[key] = van.state(value);
        }
        parentElement.state = componentState;
        componentState.emit = createEmitter(setTriggerValue);
        van.add(parentElement, ApplicationLogs(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => { parentElement.state = null; };
};
