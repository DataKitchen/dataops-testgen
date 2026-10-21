/**
 * @typedef Marker
 * @type {object}
 * @property {number} line - 1-based line number
 * @property {string} message
 * @property {('error'|'warning'|'info')?} severity - defaults to 'error'
 *
 * @typedef StatusBarOptions
 * @type {object}
 * @property {string?} label
 * @property {Array<string|Node>?} items
 *
 * @typedef Properties
 * @type {object}
 * @property {string?} id
 * @property {string?} class
 * @property {string?} value
 * @property {function(string)?} onChange
 * @property {('yaml')?} language
 * @property {boolean?} readOnly
 * @property {Array<Marker>?} markers
 * @property {boolean?} toolbar
 * @property {(StatusBarOptions|false)?} statusBar
 * @property {number?} height - fixed height in px; content scrolls inside
 * @property {number?} minHeight - minimum height in px when no fixed height is set
 */
import van from '../van.min.js';
import { afterMount, getRandomId, getValue, isState, loadStylesheet } from '../utils.js';
import {
    Annotation,
    Compartment,
    EditorState,
    EditorView,
    HighlightStyle,
    Transaction,
    bracketMatching,
    defaultKeymap,
    drawSelection,
    findNext,
    findPrevious,
    forEachDiagnostic,
    foldGutter,
    foldKeymap,
    getSearchQuery,
    highlightActiveLine,
    highlightActiveLineGutter,
    highlightSpecialChars,
    history,
    historyKeymap,
    indentOnInput,
    indentWithTab,
    keymap,
    lineNumbers,
    lintGutter,
    openSearchPanel,
    search,
    SearchQuery,
    setDiagnostics,
    setSearchQuery,
    showPanel,
    syntaxHighlighting,
    tags,
    tooltips,
    yaml,
} from '../codemirror.min.js';
import { Icon } from './icon.js';

const { div, input, span } = van.tags;

const LANGUAGES = { yaml };
const DEFAULT_MIN_HEIGHT = 120;

const externalChange = Annotation.define();

const peek = (prop) => isState(prop) ? prop.rawVal : getValue(prop);

const readOnlyExtension = (readOnly) => EditorState.readOnly.of(readOnly);
const languageExtension = (name) => LANGUAGES[name]?.() ?? [];

const toDiagnostics = (state, markers) => (markers ?? [])
    .filter(marker => Number.isInteger(marker.line) && marker.line >= 1 && marker.line <= state.doc.lines)
    .map(marker => {
        const line = state.doc.line(marker.line);
        return { from: line.from, to: line.to, severity: marker.severity ?? 'error', message: marker.message ?? '' };
    });

const matchCountLabel = (state) => {
    const query = getSearchQuery(state);
    if (!query.search || !query.valid) {
        return '';
    }
    const main = state.selection.main;
    let total = 0;
    let current = 0;
    for (const match of query.getCursor(state)) {
        total++;
        if (match.from === main.from && match.to === main.to) {
            current = total;
        }
    }
    if (!total) {
        return 'No matches';
    }
    if (current) {
        return `${current} of ${total}`;
    }
    return `${total} ${total === 1 ? 'match' : 'matches'}`;
};

const SearchToolbar = (view) => {
    const field = input({
        class: 'tg-code-editor--search-input',
        type: 'text',
        placeholder: 'Search',
        'aria-label': 'Search',
        'main-field': 'true',
        'data-testid': 'code-editor-search',
        oninput: () => {
            view.dispatch({ effects: setSearchQuery.of(new SearchQuery({ search: field.value, literal: true })) });
        },
        onkeydown: (/** @type KeyboardEvent */ event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                (event.shiftKey ? findPrevious : findNext)(view);
            } else if (event.key === 'Escape') {
                event.preventDefault();
                view.focus();
            } else if ((event.ctrlKey || event.metaKey) && event.key === 'f') {
                event.preventDefault();
                field.select();
            }
        },
    });
    const count = span({ class: 'text-caption', 'data-testid': 'code-editor-search-count' });

    return {
        top: true,
        dom: div(
            { class: 'flex-row fx-align-flex-center fx-gap-2 p-1' },
            div(
                { class: 'tg-code-editor--search flex-row fx-align-flex-center fx-gap-1 border-radius-2' },
                Icon({ size: 16 }, 'search'),
                field,
            ),
            count,
        ),
        update(update) {
            const query = getSearchQuery(update.state);
            if (query.search !== field.value) {
                field.value = query.search;
            }
            count.textContent = matchCountLabel(update.state);
        },
    };
};

const firstError = (state) => {
    let count = 0;
    let first = null;
    forEachDiagnostic(state, (diagnostic, from) => {
        if (diagnostic.severity === 'error') {
            count++;
            first = first === null ? from : Math.min(first, from);
        }
    });
    return { count, first };
};

const StatusBar = (view) => {
    const label = span({ 'data-testid': 'code-editor-status-label' });
    const items = span({ class: 'flex-row fx-gap-3', 'data-testid': 'code-editor-status-items' });
    const position = span({ 'data-testid': 'code-editor-position' });
    const selection = span({ 'data-testid': 'code-editor-selection' });
    const readOnly = span({ class: 'tg-code-editor--badge border-radius-1', 'data-testid': 'code-editor-readonly' }, 'Read-only');
    const jumpToFirstError = () => {
        const { first } = firstError(view.state);
        if (first !== null) {
            view.dispatch({ selection: { anchor: first }, scrollIntoView: true });
            view.focus();
        }
    };
    const errors = span({
        class: 'tg-code-editor--errors',
        role: 'button',
        tabindex: '0',
        'data-testid': 'code-editor-errors',
        onclick: jumpToFirstError,
        onkeydown: (/** @type KeyboardEvent */ event) => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                jumpToFirstError();
            }
        },
    });

    const show = (element, visible) => element.style.display = visible ? '' : 'none';

    const refresh = (state) => {
        const main = state.selection.main;
        const line = state.doc.lineAt(main.head);
        position.textContent = `Ln ${line.number}, Col ${main.head - line.from + 1}/${line.length}`;

        const selected = main.to - main.from;
        selection.textContent = `(${selected} selected)`;
        show(selection, selected > 0);

        show(readOnly, state.readOnly);

        const { count } = firstError(state);
        errors.textContent = `${count} ${count === 1 ? 'error' : 'errors'}`;
        show(errors, count > 0);
    };
    refresh(view.state);

    return {
        top: false,
        dom: div(
            { class: 'flex-row fx-justify-space-between fx-align-flex-center fx-gap-3 pl-2 pr-2 text-caption tg-code-editor--status' },
            div({ class: 'flex-row fx-align-flex-center fx-gap-3' }, label, items),
            div({ class: 'flex-row fx-align-flex-center fx-gap-3' }, errors, readOnly, selection, position),
        ),
        update: (update) => refresh(update.state),
        setCaller: (text, entries) => {
            label.textContent = text ?? '';
            show(label, !!text);
            items.replaceChildren(...(entries ?? []).map(entry => span(entry)));
        },
    };
};

const CodeEditor = (/** @type Properties */ props) => {
    loadStylesheet('code-editor', stylesheet);

    const readOnlyConfig = new Compartment();
    const languageConfig = new Compartment();
    const withToolbar = !!peek(props.toolbar);
    const withStatusBar = !!peek(props.statusBar);
    let statusPanel = null;

    const root = div({
        id: props.id ?? `code-editor-${getRandomId()}`,
        class: () => `tg-code-editor border-radius-2 ${getValue(props.class) ?? ''}`,
        style: () => {
            const height = getValue(props.height);
            return height
                ? `height: ${height}px;`
                : `min-height: ${getValue(props.minHeight) ?? DEFAULT_MIN_HEIGHT}px;`;
        },
        'data-testid': 'code-editor',
    });

    const extensions = [
        lineNumbers(),
        foldGutter(),
        lintGutter(),
        highlightActiveLineGutter(),
        highlightSpecialChars(),
        history(),
        drawSelection(),
        indentOnInput(),
        bracketMatching(),
        highlightActiveLine(),
        syntaxHighlighting(highlightStyle),
        keymap.of([...defaultKeymap, ...historyKeymap, ...foldKeymap, indentWithTab]),
        tooltips({ parent: document.body }),
        editorTheme,
        readOnlyConfig.of(readOnlyExtension(!!peek(props.readOnly))),
        languageConfig.of(languageExtension(peek(props.language))),
        EditorView.updateListener.of((update) => {
            if (!update.docChanged || update.transactions.some(tr => tr.annotation(externalChange))) {
                return;
            }
            const onChange = isState(props.onChange) ? props.onChange.val : props.onChange;
            onChange?.(update.state.doc.toString());
        }),
    ];

    if (withToolbar) {
        extensions.push(
            search({ top: true, literal: true, createPanel: SearchToolbar }),
            keymap.of([{ key: 'Mod-f', run: openSearchPanel, preventDefault: true }]),
        );
    }

    if (withStatusBar) {
        extensions.push(showPanel.of((panelView) => {
            const options = peek(props.statusBar) || {};
            statusPanel = StatusBar(panelView);
            statusPanel.setCaller(options.label, options.items);
            return statusPanel;
        }));
    }

    const createView = (state) => new EditorView({ parent: root, state });
    let view = createView(EditorState.create({ doc: peek(props.value) ?? '', extensions }));
    // Only on the first build: the panel's open state carries over a rebuild, and on an open panel this call
    // focuses the field and replaces its text with the selection
    if (withToolbar) {
        openSearchPanel(view);
    }

    // Prop changes that arrive while the view is destroyed, applied when it is rebuilt
    const pending = new Map();
    const whenLive = (apply) => (input) => {
        if (view.destroyed) {
            pending.set(apply, input);
        } else {
            apply(input);
        }
    };

    const applyMarkers = whenLive((markers) => {
        view.dispatch(setDiagnostics(view.state, toDiagnostics(view.state, markers)));
    });
    const applyValue = whenLive((rawValue) => {
        const value = (rawValue ?? '').replace(/\r\n?/g, '\n');
        if (value === view.state.doc.toString()) {
            return;
        }
        view.dispatch({
            changes: { from: 0, to: view.state.doc.length, insert: value },
            annotations: [externalChange.of(true), Transaction.addToHistory.of(false)],
        });
        applyMarkers(peek(props.markers));
    });
    const applyReadOnly = whenLive((readOnly) => {
        view.dispatch({ effects: readOnlyConfig.reconfigure(readOnlyExtension(!!readOnly)) });
    });
    const applyLanguage = whenLive((language) => {
        view.dispatch({ effects: languageConfig.reconfigure(languageExtension(language)) });
    });

    van.derive(() => applyValue(getValue(props.value)));
    van.derive(() => applyMarkers(getValue(props.markers)));
    van.derive(() => applyReadOnly(getValue(props.readOnly)));
    van.derive(() => applyLanguage(getValue(props.language)));
    van.derive(() => {
        const options = getValue(props.statusBar) || {};
        statusPanel?.setCaller(options.label, options.items);
    });

    // Destroying the view releases its document-level listeners but empties the root, so a root that is
    // inserted again is rebuilt from the last state. The ResizeObserver watches only the root, so it is
    // collected along with it and needs no cleanup.
    const removalObserver = new MutationObserver(() => {
        if (!root.isConnected) {
            release();
        }
    });
    const release = () => {
        removalObserver.disconnect();
        view.destroy();
        // Re-observing resets the last reported size, so an insertion at the same size still fires
        insertionObserver.unobserve(root);
        insertionObserver.observe(root);
    };
    const insertionObserver = new ResizeObserver(() => {
        if (!root.isConnected || !view.destroyed) {
            return;
        }
        view = createView(view.state);
        const changes = [...pending];
        pending.clear();
        changes.forEach(([apply, input]) => apply(input));
        removalObserver.observe(document.body, { childList: true, subtree: true });
    });

    afterMount(() => {
        if (root.isConnected) {
            removalObserver.observe(document.body, { childList: true, subtree: true });
        } else {
            release();
        }
    });

    return root;
};

const highlightStyle = HighlightStyle.define([
    { tag: [tags.definition(tags.propertyName), tags.propertyName], color: 'var(--tg-code-key)' },
    { tag: [tags.string, tags.special(tags.string), tags.content], color: 'var(--tg-code-string)' },
    { tag: [tags.lineComment, tags.comment], color: 'var(--tg-code-comment)', fontStyle: 'italic' },
    { tag: [tags.separator, tags.punctuation, tags.squareBracket, tags.brace], color: 'var(--tg-code-punctuation)' },
    { tag: [tags.meta, tags.keyword, tags.typeName, tags.labelName, tags.attributeValue], color: 'var(--tg-code-meta)' },
]);

const editorTheme = EditorView.theme({
    '&': {
        flex: '1',
        minHeight: '0',
        color: 'var(--primary-text-color)',
        backgroundColor: 'var(--dk-card-background)',
        fontSize: '13px',
    },
    '&.cm-focused': { outline: 'none' },
    '.cm-scroller': { overflow: 'auto' },
    '.cm-content': { caretColor: 'var(--primary-text-color)' },
    '.cm-cursor, .cm-dropCursor': { borderLeftColor: 'var(--primary-text-color)' },
    '&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground': {
        backgroundColor: 'var(--tg-code-selection)',
    },
    '.cm-gutters': {
        backgroundColor: 'var(--dk-card-background)',
        color: 'var(--secondary-text-color)',
        borderRight: '1px solid var(--border-color)',
    },
    '.cm-activeLine, .cm-activeLineGutter': { backgroundColor: 'var(--tg-code-active-line)' },
    '.cm-searchMatch': { backgroundColor: 'var(--tg-code-match)' },
    '.cm-searchMatch.cm-searchMatch-selected': { backgroundColor: 'var(--tg-code-match-selected)' },
    '.cm-panels': { backgroundColor: 'var(--dk-card-background)', color: 'var(--primary-text-color)' },
    '.cm-panels.cm-panels-top': { borderBottom: '1px solid var(--border-color)' },
    '.cm-panels.cm-panels-bottom': { borderTop: '1px solid var(--border-color)' },
    // Tooltips are parented to document.body and are short-lived, so they sit above Streamlit's st.dialog (1000060)
    '.cm-tooltip': {
        zIndex: '1000061',
        backgroundColor: 'var(--dk-card-background)',
        color: 'var(--primary-text-color)',
        border: '1px solid var(--border-color)',
    },
});

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-code-editor {
    display: flex;
    flex-direction: column;
    box-sizing: border-box;
    overflow: hidden;
    border: 1px solid var(--border-color);
    background-color: var(--dk-card-background);
}

.tg-code-editor--search {
    width: 260px;
    padding: 2px 8px;
    border: 1px solid transparent;
    background-color: var(--form-field-color);
}

.tg-code-editor--search:focus-within {
    border-color: var(--primary-color);
}

.tg-code-editor--search-input {
    flex: 1;
    min-width: 0;
    border: none;
    outline: none;
    background: transparent;
    color: var(--primary-text-color);
    font-size: 13px;
    padding: 2px 0;
}

.tg-code-editor--search-input::placeholder {
    font-style: italic;
    color: var(--disabled-text-color);
}

.tg-code-editor--status {
    min-height: 24px;
}

.tg-code-editor--badge {
    padding: 0 6px;
    border: 1px solid var(--border-color);
}

.tg-code-editor--errors {
    color: var(--error-color);
    cursor: pointer;
}

.tg-code-editor--errors:hover {
    text-decoration: underline;
}
`);

export { CodeEditor };
