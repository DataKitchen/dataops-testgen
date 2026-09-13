import { humanReadableSize } from './display_utils.js';

/**
 * @typedef Validator
 * @type {Function}
 * @param {any} value
 * @param {object} form
 * @returns {string}
 */

function required(value) {
    if (!value) {
        return 'This field is required'
    }
    return null;
}

/**
 * @param {(v: any) => bool} condition
 * @returns {Validator}
 */
function requiredIf(condition) {
    const validator = (value) => {
        if (condition(value)) {
            return required(value);
        }
        return null;
    }
    validator['args'] = { name: 'requiredIf', condition };

    return validator;
}

function noSpaces(value) {
    if (value?.includes(' ')) {
        return `Value cannot contain spaces.`;
    }
    return null;
}

/**
 *
 * @param {number} min
 * @returns {Validator}
 */
function minLength(min) {
    return (value) => {
        if (value && value.length < min) {
            return `Value must be at least ${min} characters long.`;
        }
        return null;
    };
}

/**
 *
 * @param {number} max
 * @returns {Validator}
 */
function maxLength(max) {
    return (value) => {
        if (typeof value !== 'string' || value.length > max) {
            return `Value must be ${max} characters long or shorter.`;
        }
        return null;
    };
}

/**
 * @param {number} min
 * @param {number} max
 * @param {number} [precision]
 * @returns {Validator}
 */
function numberBetween(min, max, precision = null) {
    return (value) => {
        const valueNumber = parseFloat(value);
        if (isNaN(valueNumber)) {
            return 'Value must be a numeric type.';
        }

        if (valueNumber < min || valueNumber > max) {
            return `Value must be between ${min} and ${max}.`;
        }

        if (precision !== null) {
            const strValue = value.toString();
            const decimalPart = strValue.includes('.') ? strValue.split('.')[1] : '';

            if (decimalPart.length > precision) {
                if (precision === 0) {
                    return 'Value must be an integer.';
                } else {
                    return `Value must have at most ${precision} digits after the decimal point.`;
                }
            }
        }
    };
}


/**
 * To use with FileInput, enforce a cap on file size
 * allowed to upload.
 *
 * @param {number} limit
 * @returns {Validator}
 */
function sizeLimit(limit) {
    /**
     * @import {FileValue} from './components/file_input.js';
     * @param {FileValue} value
     */
    const validator = (value) => {
        if (value != null && value.size > limit) {
            return `File size ${humanReadableSize(value.size)} exceeds the ${humanReadableSize(limit)} limit.`;
        }
        return null;
    };
    validator['args'] = { name: 'sizeLimit', limit };

    return validator;
}

/**
 * @typedef NotInOptions
 * @type {object}
 * @property {string?} errorMessage
 * @property {((v: any) => any)?} formatter
 * @property {string} a
 * 
 * @param {any[]} values
 * @param {NotInOptions?} options
 * @returns {Validator}
 */
function notIn(values, options) {
    return (value) => {
        if (value && values.includes(!!options?.formatter ? options.formatter(value) : value)) {
            return options?.errorMessage ?? `Value cannot be any of: ${values.join(', ')}.`;
        }
        return null;
    };
}

// Mirrors the server-side rule in ``common/models/notification_settings._EMAIL_REGEX``.
// The two must agree, or an address passes here and is rejected on save.
const EMAIL_PATTERN = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;

/**
 * Validate that the value is empty (optional) or a single well-formed email address.
 *
 * @param {any} value
 * @returns {string}
 */
function email(value) {
    const trimmed = String(value ?? '').trim();
    if (!trimmed) {
        return null;
    }
    return EMAIL_PATTERN.test(trimmed) ? null : `${trimmed} is not a valid email address.`;
}

/**
 * Validate a comma-, semicolon- or whitespace-separated list of email addresses,
 * naming the entries that do not parse.
 *
 * @param {any} value
 * @returns {string}
 */
function emailList(value) {
    const invalid = [...new Set(
        String(value ?? '')
            .split(/[,;\s]+/)
            .map((token) => token.trim())
            .filter((token) => token && !EMAIL_PATTERN.test(token))
    )];
    if (invalid.length <= 0) {
        return null;
    }
    if (invalid.length === 1) {
        return `${invalid[0]} is not a valid email address.`;
    }
    return `Not valid email addresses: ${invalid.join(', ')}.`;
}

/**
 * Validate that the value is empty (optional) or an HTTPS URL with a host.
 *
 * @param {string} [label] Field name used to open the message, e.g. "Webhook URL".
 * @returns {Validator}
 */
function httpsUrl(label = 'Value') {
    return (value) => {
        const trimmed = String(value ?? '').trim();
        if (!trimmed) {
            return null;
        }
        if (!trimmed.toLowerCase().startsWith('https://')) {
            return `${label} must start with https://.`;
        }
        try {
            if (!new URL(trimmed).hostname) {
                return `${label} is not a valid URL.`;
            }
        } catch {
            return `${label} is not a valid URL.`;
        }
        return null;
    };
}

/**
 * Validate that the value is empty (optional) or a well-formed JSON object of key-value pairs.
 *
 * @param {any} value
 * @returns {string}
 */
function jsonObject(value) {
    if (!value || !String(value).trim()) {
        return null;
    }
    let parsed;
    try {
        parsed = JSON.parse(value);
    } catch {
        return 'Must be valid JSON.';
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        return 'Must be a JSON object of key-value pairs.';
    }
    return null;
}

export {
    email,
    emailList,
    httpsUrl,
    maxLength,
    minLength,
    numberBetween,
    noSpaces,
    required,
    requiredIf,
    sizeLimit,
    notIn,
    jsonObject,
};
