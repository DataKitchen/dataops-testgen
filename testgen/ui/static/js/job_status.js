/**
 * Job execution status groupings, mirroring JobStatus in testgen/common/enums.py.
 *
 * A run stopped at a task boundary parks in one of two places. INTERRUPTED and
 * RESUME_REQUESTED are starting rather than running: both are queued for the next claim,
 * exactly like pending, so they reach a worker without anyone acting on them. PAUSED is
 * neither, since it is held until a resume is requested -- it is active all the same, so
 * deleting its run still has to cancel something.
 */
const STARTING_STATUSES = new Set(['pending', 'claimed', 'interrupted', 'resume_requested']);
const RUNNING_STATUSES = new Set(['running', 'cancel_requested', 'interrupt_requested', 'pause_requested']);
const ACTIVE_STATUSES = new Set([...STARTING_STATUSES, ...RUNNING_STATUSES, 'paused']);
const CANCELABLE_STATUSES = new Set([
    'pending', 'claimed', 'running', 'interrupt_requested', 'interrupted',
    'pause_requested', 'paused', 'resume_requested',
]);
const PAUSABLE_STATUSES = new Set(['running']);
const RESUMABLE_STATUSES = new Set(['paused']);

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
    pause_requested: 'grey',
    paused: 'orange',
    resume_requested: 'grey',
};

export {
    ACTIVE_STATUSES,
    CANCELABLE_STATUSES,
    PAUSABLE_STATUSES,
    RESUMABLE_STATUSES,
    RUNNING_STATUSES,
    STARTING_STATUSES,
    STATUS_COLORS,
};
