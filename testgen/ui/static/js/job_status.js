/**
 * Job execution status groupings, mirroring JobStatus in testgen/common/enums.py.
 *
 * INTERRUPTED is starting rather than running: it is queued for the next claim, exactly like
 * pending, so it reaches a worker without anyone acting on it.
 */
const STARTING_STATUSES = new Set(['pending', 'claimed', 'interrupted']);
const RUNNING_STATUSES = new Set(['running', 'cancel_requested', 'interrupt_requested']);
const ACTIVE_STATUSES = new Set([...STARTING_STATUSES, ...RUNNING_STATUSES]);
const CANCELABLE_STATUSES = new Set([
    'pending', 'claimed', 'running', 'interrupt_requested', 'interrupted',
]);

const STATUS_COLORS = {
    pending: 'grey',
    claimed: 'grey',
    running: 'blue',
    completed: '',
    error: 'red',
    canceled: 'purple',
    cancel_requested: 'grey',
    interrupt_requested: 'grey',
    interrupted: 'grey',
};

export {
    ACTIVE_STATUSES,
    CANCELABLE_STATUSES,
    RUNNING_STATUSES,
    STARTING_STATUSES,
    STATUS_COLORS,
};
