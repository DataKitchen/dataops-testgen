/**
 * Job execution status groupings, mirroring JobStatus in testgen/common/enums.py.
 *
 * A run stopped at a task boundary parks in one of two places. INTERRUPTED and
 * RESUME_REQUESTED are starting rather than running: both are queued for the next claim,
 * exactly like pending, so they reach a worker without anyone acting on them. PAUSED is
 * neither, since it is held until a resume is requested -- it is active all the same, so
 * deleting its run still has to cancel something. QUEUED is active but not starting: a run waiting
 * for an in-process slot can wait as long as the run ahead of it, so it does not hold the runs pages
 * on the fast refresh that STARTING_STATUSES drives.
 */
const STARTING_STATUSES = new Set(['pending', 'claimed', 'interrupted', 'resume_requested']);
const RUNNING_STATUSES = new Set(['running', 'cancel_requested', 'interrupt_requested', 'pause_requested']);
const ACTIVE_STATUSES = new Set([...STARTING_STATUSES, ...RUNNING_STATUSES, 'paused', 'queued']);
const CANCELABLE_STATUSES = new Set([
    'pending', 'claimed', 'running', 'interrupt_requested', 'interrupted',
    'pause_requested', 'paused', 'resume_requested', 'queued',
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
    queued: 'grey',
};

const QUEUED_MESSAGE = 'Waiting for another run on a DuckDB or file connection to finish.'
    + ' TestGen runs a limited number of these at once.';

export {
    ACTIVE_STATUSES,
    CANCELABLE_STATUSES,
    PAUSABLE_STATUSES,
    QUEUED_MESSAGE,
    RESUMABLE_STATUSES,
    RUNNING_STATUSES,
    STARTING_STATUSES,
    STATUS_COLORS,
};
