/**
 * @import {InputState} from './input.js';
 * @import {Validator} from '../form_validators.js';
 * 
 * @typedef FileValue
 * @type {object}
 * @property {string} name
 * @property {string} content
 * @property {number} size
 * 
 * @typedef Options
 * @type {object}
 * @property {string} label
 * @property {string?} placeholder
 * @property {string} name
 * @property {string} value
 * @property {string?} class
 * @property {Array<Validator>?} validators
 * @property {function(FileValue?, InputState)?} onChange
 * 
 */
import van from '../van.min.js';
import { getRandomId, getValue, loadStylesheet } from "../utils.js";
import { Icon } from './icon.js';
import { Button } from './button.js';
import { humanReadableSize } from '../display_utils.js';

const { div, input, label, span } = van.tags;

/**
 * File uploader component that emits change events with a base64
 * encoding of the uploaded file.
 * 
 * @param {Options} options
 * @returns {HTMLElement}
 */
const FileInput = (options) => {
    loadStylesheet('file-uploader', stylesheet);

    const value = van.state(getValue(options.value));
    const inputId = `file-uploader-${getRandomId()}`;
    const fileOver = van.state(false);
    const cssClass = van.derive(() => `tg-file-uploader flex-column fx-gap-2 ${getValue(options.class) ?? ''}`)
    const showLoading = van.state(false);
    const loadingIndicatorProgress = van.state(0);
    const loadingIndicatorStyle = van.derive(() => `width: ${loadingIndicatorProgress.val}%;`);
    const errors = van.derive(() => {
        const validators = getValue(options.validators) ?? [];
        return validators.map(v => v(value.val)).filter(error => error);
    });

    let sizeLimit = undefined;
    let sizeLimitValidator = (getValue(options.validators) ?? []).filter(v => v.args.name === 'sizeLimit')[0];
    if (sizeLimitValidator) {
        sizeLimit = sizeLimitValidator.args.limit;
    }

    van.derive(() => {
        if (options.onChange && (value.val !== value.oldVal || errors.val.length !== errors.oldVal.length)) {
            options.onChange(value.val, { errors: errors.val, valid: errors.val.length <= 0 });
        }
    });

    const browseFile = () => {
        document.getElementById(inputId).click();
    };

    const loadFile = (event) => {
        const selectedFile = event.target.files[0];
        if (!selectedFile) {
            value.val = null;
            showLoading.val = false;
            loadingIndicatorProgress.val = 0;
            return;
        }

        const fileReader = new FileReader();
        fileReader.addEventListener('loadstart', (event) => {
            loadingIndicatorProgress.val = 0;
            showLoading.val = event.lengthComputable;
        });
        fileReader.addEventListener('progress', (event) => {
            if (showLoading.val) {
                loadingIndicatorProgress.val = event.loaded / event.total;
            }
        });
        fileReader.addEventListener('loadend', (event) => {
            loadingIndicatorProgress.val = 100;
            value.val = {
                name: selectedFile.name,
                content: fileReader.result,
                size: event.loaded,
            };
        });

        fileReader.readAsDataURL(selectedFile);
    };

    const unloadFile = (event) => {
        event.stopPropagation();
        value.val = null;
        showLoading.val = false;
        loadingIndicatorProgress.val = 0;
    };

    return div(
        { class: cssClass },
        label(
            { class: 'tg-file-uploader--label' },
            options.label,
        ),
        div(
            { class: () => `tg-file-uploader--dropzone flex-column clickable ${fileOver.val ? 'on-dragover' : ''}` },
            div(
                {
                    onclick: browseFile,
                    ondragenter: (event) => {
                        event.preventDefault();
                        fileOver.val = true;
                    },
                    ondragleave: (event) => {
                        if (!event.currentTarget.contains(event.relatedTarget)) {
                            fileOver.val = false;
                        }
                    },
                    ondragover: (event) => event.preventDefault(),
                    ondrop: (/** @type {DragEvent} */event) => {
                        event.preventDefault();
                        fileOver.val = false;

                        let files = [...(event.dataTransfer.items ?? [])].filter((item) => item.kind === 'file').map((item) => item.getAsFile());
                        if (!event.dataTransfer.items) {
                            files = [...(event.dataTransfer.files ?? [])];
                        }

                        loadFile({ target: { files }});
                    },
                },
                input({
                    id: inputId,
                    type: 'file',
                    name: options.name,
                    tabindex: '-1',
                    onchange: loadFile,
                }),
                () => value.val
                    ? FileSummary(value.val, unloadFile)
                    : FileSelectionDropZone(options.placeholder ?? 'Drop file here or browse files', sizeLimit)
            ),
            () => showLoading.val
                ? div({ class: 'tg-file-uploader--loading', style: loadingIndicatorStyle }, '')
                : '',
        ),
    );
};

/**
 * 
 * @param {string} placeholder
 * @param {number} sizeLimit
 * @returns 
 */
const FileSelectionDropZone = (placeholder, sizeLimit) => {
    return div(
        { class: 'flex-row fx-gap-4' },
        Icon({size: 48}, 'cloud_upload'),
        div(
            { class: 'flex-column fx-gap-1' },
            span({}, placeholder),
            span({ class: 'text-secondary text-caption' }, `Limit ${humanReadableSize(sizeLimit)} per file`),
        ),
    );
};

const FileSummary = (value, onFileUnload) => {
    const fileName = getValue(value).name;
    const fileSize = humanReadableSize(getValue(value).size);

    return div(
        { class: 'flex-row fx-gap-4' },
        Icon({size: 48}, 'draft'),
        div(
            { class: 'flex-column fx-gap-1' },
            span({}, fileName),
            span({ class: 'text-secondary text-caption' }, `Size: ${fileSize}`),
        ),
        span({ style: 'margin: 0px auto;'}),
        Button({
            type: 'icon',
            color: 'basic',
            icon: 'close',
            onclick: onFileUnload,
        }),
    );
};

const stylesheet = new CSSStyleSheet();
stylesheet.replace(`
.tg-file-uploader {
}

.tg-file-uploader--dropzone {
    border-radius: 8px;
    background: var(--form-field-color);
    padding: 16px;
    position: relative;
    border: 1px transparent dashed;
}

.tg-file-uploader--dropzone.on-dragover {
    border-color: var(--primary-color);
}

.tg-file-uploader--dropzone input[type="file"] {
    display: none;
}

.tg-file-uploader--loading {
    height: 3px;
    background: var(--primary-color);
    position: absolute;
    width: 0%;
    left: 0;
    bottom: 0;
    border-bottom-left-radius: 8px;
    border-bottom-right-radius: 8px;
    transition: 200ms width ease-in;
}
`);

export { FileInput };
