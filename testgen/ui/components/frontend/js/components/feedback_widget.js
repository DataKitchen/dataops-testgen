/**
 * @typedef Properties
 * @type {object}
 * @property {import('../van.min.js').State<boolean>} visible - Controls widget visibility
 */
import van from '../van.min.js';
import { emitEvent, getValue, loadStylesheet, getRandomId } from '../utils.js';
import { Streamlit } from '../streamlit.js';

const { button, div, i, input, label, span, textarea } = van.tags;

const RATINGS = [
    { value: 1, emoji: '\u{1F620}', label: 'Frustrated' },   // 😠
    { value: 2, emoji: '\u{1F615}', label: 'Dissatisfied' }, // 😕
    { value: 3, emoji: '\u{1F610}', label: 'Neutral' },      // 😐
    { value: 4, emoji: '\u{1F642}', label: 'Satisfied' },    // 🙂
    { value: 5, emoji: '\u{1F929}', label: 'Love it!' },     // 🤩
];

const FeedbackWidget = (/** @type Properties */ props) => {
    loadStylesheet('feedback-widget', stylesheet);

    const domId = `feedback-widget-${getRandomId()}`;

    // Position the component's iframe itself as fixed at bottom-right.
    // This avoids cross-window VanJS reactivity issues that arise from shouldRenderOutsideFrame.
    const iframe = window.frameElement;
    if (iframe) {
        Object.assign(iframe.style, {
            position: 'fixed',
            bottom: '24px',
            right: '24px',
            width: '340px',
            zIndex: '9999',
            border: 'none',
            background: 'transparent',
        });
    }

    // Internal state
    const visible = van.derive(() => getValue(props.visible) ?? false);

    // Control iframe height (and thus visibility) reactively.
    // Use 1 instead of 0 when hidden: setFrameHeight(0) causes Streamlit to stop
    // sending streamlit:render updates to the iframe, so prop changes (like visible→true
    // triggered by the "Give Feedback" help menu button) would never reach the component.
    van.derive(() => {
        const isVisible = visible.val;
        Streamlit.setFrameHeight(isVisible ? 400 : 1);
        if (iframe) {
            iframe.style.height = (isVisible ? 400 : 1) + 'px';
            iframe.style.pointerEvents = isVisible ? 'auto' : 'none';
        }
    });
    const selectedRating = van.state(0);
    const comment = van.state('');
    const email = van.state('');
    const expanded = van.state(false);
    const showSuccess = van.state(false);
    const submitting = van.state(false);

    // Reset form when widget becomes visible
    van.derive(() => {
        if (visible.val && !visible.oldVal) {
            selectedRating.val = 0;
            comment.val = '';
            email.val = '';
            expanded.val = false;
            showSuccess.val = false;
        }
    });

    const handleClose = () => {
        emitEvent('FeedbackDismissed');
    };

    const handleSubmit = () => {
        if (selectedRating.val === 0 || submitting.val) return;

        submitting.val = true;

        emitEvent('FeedbackSubmitted', {
            payload: {
                rating: selectedRating.val,
                comment: comment.val,
                email: email.val,
            },
        });

        showSuccess.val = true;

        // Auto-close after showing success
        setTimeout(() => {
            submitting.val = false;
            emitEvent('FeedbackDismissed');
        }, 2500);
    };

    const selectRating = (value) => {
        selectedRating.val = value;
    };

    const toggleExpand = () => {
        expanded.val = !expanded.val;
    };

    // Make iframe body a transparent positioning context
    document.body.style.cssText = 'margin:0;padding:0;background:transparent;position:relative;height:400px;overflow:visible;';

    return div(
        { id: domId, class: () => `feedback-widget ${visible.val ? '' : 'hidden'}` },

        // Form view
        () => !showSuccess.val ? div(
            { class: 'feedback-form' },

            // Header
            div(
                { class: 'feedback-header' },
                div(
                    { class: 'feedback-header-text' },
                    div({ class: 'feedback-title' }, "How's your experience?"),
                    div({ class: 'feedback-subtitle' }, 'Your feedback helps us improve TestGen'),
                ),
                button(
                    {
                        class: 'feedback-close',
                        onclick: handleClose,
                        title: 'Dismiss',
                    },
                    i({ class: 'material-symbols-rounded', style: 'font-size: 18px;' }, 'close'),
                ),
            ),

            // Body
            div(
                { class: 'feedback-body' },

                // Emoji rating row
                div(
                    { class: 'rating-row' },
                    ...RATINGS.map(rating =>
                        div(
                            {
                                class: () => `rating-option ${selectedRating.val === rating.value ? 'selected' : ''}`,
                                onclick: () => selectRating(rating.value),
                            },
                            span({ class: 'rating-emoji' }, rating.emoji),
                            span({ class: 'rating-label' }, rating.label),
                        )
                    ),
                ),

                // Expand toggle
                button(
                    {
                        class: () => `expand-toggle ${expanded.val ? 'expanded' : ''}`,
                        onclick: toggleExpand,
                    },
                    i({ class: 'material-symbols-rounded' }, 'expand_more'),
                    'Add a comment (optional)',
                ),

                // Expandable section
                div(
                    { class: () => `expandable-section ${expanded.val ? 'expanded' : ''}` },

                    // Comment field
                    div(
                        { class: 'feedback-field' },
                        label({ for: 'feedbackComment' }, 'Comment'),
                        textarea({
                            id: 'feedbackComment',
                            placeholder: "What's on your mind?",
                            value: comment,
                            oninput: (e) => comment.val = e.target.value,
                        }),
                    ),

                    // Email field
                    div(
                        { class: 'feedback-field' },
                        label({ for: 'feedbackEmail' }, 'Email (optional)'),
                        input({
                            id: 'feedbackEmail',
                            type: 'email',
                            placeholder: 'you@company.com',
                            value: email,
                            oninput: (e) => email.val = e.target.value,
                        }),
                    ),
                ),
            ),

            // Footer
            div(
                { class: 'feedback-footer' },
                button(
                    {
                        class: 'btn btn-primary',
                        disabled: () => selectedRating.val === 0 || submitting.val,
                        onclick: handleSubmit,
                    },
                    i({ class: 'material-symbols-rounded' }, 'send'),
                    'Submit',
                ),
            ),
        ) : null,

        // Success view
        () => showSuccess.val ? div(
            { class: 'feedback-success' },
            i({ class: 'material-symbols-rounded success-icon' }, 'check_circle'),
            div({ class: 'success-title' }, 'Thanks for your feedback!'),
            div({ class: 'success-subtitle' }, 'We appreciate you taking the time.'),
        ) : null,
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
/* Feedback Widget Container */
.feedback-widget {
    position: absolute;
    bottom: 0;
    right: 0;
    width: 340px;
    background: var(--dk-card-background, #fff);
    border-radius: 12px;
    box-shadow: rgba(0,0,0,0.12) 0 8px 32px, rgba(0,0,0,0.08) 0 2px 8px;
    overflow: hidden;
    transition: opacity 0.25s, transform 0.25s;
    transform-origin: bottom right;
}

.feedback-widget.hidden {
    opacity: 0;
    transform: scale(0.95) translateY(8px);
    pointer-events: none;
}

/* Header */
.feedback-header {
    padding: 16px 20px 12px;
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
}

.feedback-header-text {
    flex: 1;
}

.feedback-title {
    font-size: 15px;
    font-weight: 600;
    margin-bottom: 2px;
    color: var(--primary-text-color);
}

.feedback-subtitle {
    font-size: 12px;
    color: var(--secondary-text-color);
}

.feedback-close {
    width: 28px;
    height: 28px;
    border-radius: 50%;
    border: none;
    background: transparent;
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--secondary-text-color);
    transition: 0.2s;
    flex-shrink: 0;
    margin: -4px -8px 0 0;
}

.feedback-close:hover {
    background: var(--select-hover-background, rgb(240, 242, 246));
    color: var(--primary-text-color);
}

/* Body */
.feedback-body {
    padding: 0 20px;
}

/* Emoji Rating Row */
.rating-row {
    display: flex;
    justify-content: space-between;
    gap: 4px;
    margin-bottom: 4px;
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
    transition: 0.2s;
    border: 2px solid transparent;
}

.rating-option:hover {
    background: var(--select-hover-background, rgb(240, 242, 246));
}

.rating-option.selected {
    background: var(--select-hover-background, rgb(240, 242, 246));
    border-color: var(--primary-color);
}

.rating-emoji {
    font-size: 28px;
    line-height: 1;
    filter: saturate(0.8);
    transition: 0.15s;
}

.rating-option:hover .rating-emoji,
.rating-option.selected .rating-emoji {
    transform: scale(1.15);
    filter: saturate(1);
}

.rating-label {
    font-size: 10px;
    color: var(--secondary-text-color);
    text-align: center;
    white-space: nowrap;
}

.rating-option.selected .rating-label {
    color: var(--primary-color);
    font-weight: 500;
}

/* Expand Toggle */
.expand-toggle {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 8px 0;
    color: var(--secondary-text-color);
    font-size: 12px;
    cursor: pointer;
    border: none;
    background: none;
    transition: 0.2s;
    font-family: inherit;
}

.expand-toggle:hover {
    color: var(--primary-text-color);
}

.expand-toggle .material-symbols-rounded {
    font-size: 18px;
    transition: 0.2s;
}

.expand-toggle.expanded .material-symbols-rounded {
    transform: rotate(180deg);
}

/* Expandable Section */
.expandable-section {
    max-height: 0;
    overflow: hidden;
    transition: max-height 0.3s ease;
}

.expandable-section.expanded {
    max-height: 200px;
}

/* Form Fields */
.feedback-field {
    margin-bottom: 12px;
}

.feedback-field label {
    display: block;
    font-size: 12px;
    color: var(--secondary-text-color);
    margin-bottom: 4px;
}

.feedback-field textarea,
.feedback-field input {
    width: 100%;
    padding: 8px 12px;
    border: 1px solid var(--border-color, rgba(0,0,0,.12));
    border-radius: 6px;
    font-family: inherit;
    font-size: 13px;
    background: var(--form-field-color, rgb(240, 242, 246));
    color: var(--primary-text-color);
    transition: 0.2s;
    outline: none;
    box-sizing: border-box;
}

.feedback-field textarea {
    resize: vertical;
    min-height: 64px;
    max-height: 120px;
}

.feedback-field textarea:focus,
.feedback-field input:focus {
    border-color: var(--primary-color);
    box-shadow: 0 0 0 1px var(--primary-color);
}

.feedback-field textarea::placeholder,
.feedback-field input::placeholder {
    color: var(--disabled-text-color);
}

/* Footer */
.feedback-footer {
    padding: 12px 20px 16px;
    display: flex;
    justify-content: flex-end;
    gap: 8px;
}

.btn {
    padding: 8px 20px;
    border-radius: 6px;
    font-family: inherit;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: 0.2s;
    border: none;
    display: flex;
    align-items: center;
    gap: 6px;
}

.btn-primary {
    background: var(--primary-color);
    color: white;
}

.btn-primary:hover:not(:disabled) {
    filter: brightness(0.95);
}

.btn-primary:disabled {
    background: var(--disabled-text-color);
    cursor: not-allowed;
}

.btn-primary .material-symbols-rounded {
    font-size: 16px;
}

/* Success State */
.feedback-success {
    padding: 32px 20px;
    text-align: center;
}

.feedback-success .success-icon {
    font-size: 48px;
    color: var(--primary-color);
    margin-bottom: 12px;
}

.success-title {
    font-size: 15px;
    font-weight: 600;
    margin-bottom: 4px;
    color: var(--primary-text-color);
}

.success-subtitle {
    font-size: 13px;
    color: var(--secondary-text-color);
}
`);

export { FeedbackWidget };
