import van from '/app/static/js/van.min.js';
import { createEmitter, isEqual, loadStylesheet } from '/app/static/js/utils.js';
import { Button } from '/app/static/js/components/button.js';
import { Icon } from '/app/static/js/components/icon.js';
import { Input } from '/app/static/js/components/input.js';
import { Textarea } from '/app/static/js/components/textarea.js';
const { div, span } = van.tags;

const RATINGS = [
    { value: 1, emoji: '\u{1F620}', label: 'Frustrated' },   // 😠
    { value: 2, emoji: '\u{1F615}', label: 'Dissatisfied' }, // 😕
    { value: 3, emoji: '\u{1F610}', label: 'Neutral' },      // 😐
    { value: 4, emoji: '\u{1F642}', label: 'Satisfied' },    // 🙂
    { value: 5, emoji: '\u{1F929}', label: 'Love it!' },     // 🤩
];

const FeedbackWidget = (props) => {
    loadStylesheet('feedback-widget', stylesheet);

    const selectedRating = van.state(0);
    const comment = van.state('');
    const email = van.state('');
    const expanded = van.state(false);
    const showSuccess = van.state(false);
    const submitting = van.state(false);

    const handleClose = () => {
        props.emit('FeedbackDismissed', {});
    };

    const handleSubmit = () => {
        if (selectedRating.val === 0 || submitting.val) return;
        submitting.val = true;
        props.emit('FeedbackSubmitted', {
            payload: {
                rating: selectedRating.val,
                comment: comment.val,
                email: email.val,
            },
        });
        showSuccess.val = true;
        setTimeout(() => {
            submitting.val = false;
            props.emit('FeedbackDismissed', {});
        }, 2000);
    };

    return div(
        { class: 'feedback-widget' },

        () => !showSuccess.val
            ? div(
                { class: 'flex-column' },
                div(
                    { class: 'flex-row fx-justify-space-between p-4 pb-0' },
                    div(
                        { class: 'flex-column fx-gap-1' },
                        div({ class: 'text-bold' }, "How's your experience?"),
                        div({ class: 'text-caption' }, 'Your feedback helps us improve TestGen'),
                    ),
                    Button({ type: 'icon', color: 'basic', icon: 'close', onclick: handleClose }),
                ),
                div(
                    { class: 'flex-row fx-justify-space-between p-4' },
                    ...RATINGS.map(rating =>
                        div(
                            {
                                class: () => `rating-option ${selectedRating.val === rating.value ? 'selected' : ''}`,
                                onclick: () => { selectedRating.val = rating.value; },
                            },
                            span({ class: 'rating-emoji' }, rating.emoji),
                            span({ class: 'text-caption' }, rating.label),
                        )
                    ),
                ),
                div(
                    { class: 'p-4 pt-0 flex-column fx-gap-3' },
                    div(
                        { class: 'expander-row flex-row fx-justify-space-between clickable', onclick: () => { expanded.val = !expanded.val; } },
                        span({ class: 'text-caption' }, 'Add a comment (optional)'),
                        Icon({ size: 18, classes: 'text-secondary' }, () => expanded.val ? 'keyboard_arrow_up' : 'keyboard_arrow_down'),
                    ),
                    div(
                        { class: 'flex-column fx-gap-3', style: () => expanded.val ? '' : 'display:none' },
                        Textarea({
                            label: 'Comment',
                            placeholder: "What's on your mind?",
                            value: comment,
                            onChange: (v) => { comment.val = v; },
                            height: 64,
                        }),
                        Input({
                            label: 'Email (optional)',
                            placeholder: 'you@company.com',
                            type: 'email',
                            value: email,
                            onChange: (v) => { email.val = v; },
                        }),
                    ),
                    div(
                        { class: 'flex-row fx-justify-flex-end' },
                        Button({
                            type: 'flat',
                            color: 'primary',
                            label: 'Submit',
                            icon: 'send',
                            width: 'auto',
                            disabled: () => selectedRating.val === 0 || submitting.val,
                            onclick: handleSubmit,
                        }),
                    ),
                ),
            )
            : div(
                { class: 'flex-column fx-align-flex-center p-5 feedback-success' },
                Icon({ size: 48, classes: 'text-green mb-3' }, 'check_circle'),
                div({ class: 'text-bold mb-1' }, 'Thanks for your feedback!'),
                div({ class: 'text-caption' }, 'We appreciate you taking the time.'),
            ),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.feedback-widget {
    position: fixed;
    bottom: 24px;
    right: 24px;
    width: 340px;
    font-family: 'Roboto', 'Helvetica Neue', sans-serif;
    font-size: 14px;
    color: var(--primary-text-color);
    background: var(--portal-background);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    box-shadow: var(--portal-box-shadow);
    overflow: hidden;
    transition: opacity .25s, transform .25s;
    transform-origin: bottom right;
    z-index: 9999;
}

.feedback-widget.hidden {
    opacity: 0;
    transform: scale(.95) translateY(8px);
    pointer-events: none;
}

.rating-option {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 4px;
    padding: 8px 4px;
    border-radius: 8px;
    cursor: pointer;
    transition: .2s;
    border: 2px solid transparent;
}

.rating-option:hover {
    background: var(--select-hover-background);
}

.rating-option.selected {
    background: var(--select-hover-background);
    border-color: var(--primary-color);
}

.rating-emoji {
    font-size: 28px;
    line-height: 1;
    filter: saturate(.8);
    transition: .15s;
}

.rating-option:hover .rating-emoji,
.rating-option.selected .rating-emoji {
    transform: scale(1.15);
    filter: saturate(1);
}

.rating-option.selected .text-caption {
    color: var(--primary-color);
    font-weight: 500;
}

.expander-row {
    padding: 4px;
    border-radius: 6px;
}

.expander-row:hover {
    background: var(--select-hover-background);
}

.feedback-success {
    text-align: center;
    min-height: 160px;
}
`);

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
        van.add(parentElement, FeedbackWidget(componentState));
    } else {
        for (const [key, value] of Object.entries(data)) {
            if (!isEqual(componentState[key].val, value)) {
                componentState[key].val = value;
            }
        }
    }

    return () => { parentElement.state = null; };
};
