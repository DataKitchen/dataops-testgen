/**
 * @typedef Properties
 * @type {object}
 * @property {string} source - the document shown on the left
 * @property {string} target - the document shown on the right
 * @property {string} sourceLabel
 * @property {string} targetLabel
 * @property {('yaml')?} language
 * @property {number?} height - fixed height in px; the comparison scrolls inside
 */
import van from '../van.min.js';
import { loadStylesheet } from '../utils.js';
import {
    EditorState,
    EditorView,
    MergeView,
    lineNumbers,
    syntaxHighlighting,
    yaml,
} from '../codemirror.min.js';
import { codeEditorStylesheet, editorTheme, highlightStyle } from './code_editor.js';

const { div, span } = van.tags;

const LANGUAGES = { yaml };

const diffTheme = EditorView.theme({
    '&.cm-editor .cm-collapsedLines': {
        background: 'var(--tg-code-active-line)',
        color: 'var(--secondary-text-color)',
        borderTop: '1px solid var(--border-color)',
        borderBottom: '1px solid var(--border-color)',
        fontSize: '12px',
    },
});
const DEFAULT_HEIGHT = 480;

const CodeDiff = (/** @type Properties */ props) => {
    loadStylesheet('code-editor', codeEditorStylesheet);
    loadStylesheet('code-diff', stylesheet);

    const extensions = [
        lineNumbers(),
        syntaxHighlighting(highlightStyle),
        editorTheme,
        diffTheme,
        EditorState.readOnly.of(true),
        EditorView.editable.of(false),
        LANGUAGES[props.language]?.() ?? [],
    ];

    const body = div({ class: 'tg-code-diff--body', style: `height: ${props.height ?? DEFAULT_HEIGHT}px;` });
    const root = div(
        { class: 'tg-code-editor tg-code-diff border-radius-2', 'data-testid': 'code-diff' },
        div(
            { class: 'tg-code-diff--labels flex-row text-caption' },
            span({ class: 'fx-flex pl-2' }, props.sourceLabel),
            span({ class: 'fx-flex pl-2' }, props.targetLabel),
        ),
        body,
    );

    const view = new MergeView({
        a: { doc: props.source ?? '', extensions },
        b: { doc: props.target ?? '', extensions },
        parent: body,
        collapseUnchanged: { margin: 3, minSize: 6 },
        // The default scan limit gives up on a contract's whole document and marks it all as changed
        diffConfig: { scanLimit: 100000, timeout: 2000 },
    });
    // The view holds document-level listeners, so it is destroyed once its root has been on the page and left it
    let mounted = false;
    const removalObserver = new MutationObserver(() => {
        mounted ||= root.isConnected;
        if (mounted && !root.isConnected) {
            removalObserver.disconnect();
            view.destroy();
        }
    });
    removalObserver.observe(document.body, { childList: true, subtree: true });

    return root;
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-code-diff--labels {
    padding: 6px 0;
    border-bottom: 1px solid var(--border-color);
}

.tg-code-diff--body {
    overflow: auto;
}

.tg-code-diff--body .cm-mergeView {
    min-height: 100%;
}
`);

export { CodeDiff };
