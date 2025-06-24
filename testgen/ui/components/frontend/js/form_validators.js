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
 * 
 * @param {number} min 
 * @returns {Validator}
 */
function minLength(min) {
    return (value) => {
        if (typeof value !== 'string' || value.length < min) {
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
 * To use with FileInput, enforce a cap on file size
 * allowed to upload.
 * 
 * @param {number} size
 * @returns {Validator}
 */
function sizeLimit(limit) {
    /**
     * @import {FileValue} from './components/file_input.js';
     * @param {FileValue} value
     */
    const validator = (value) => {
        if (value != null && value.size > limit) {
            return `Uploaded file must be smaller than ${limit}.`;
        }
        return null;
    };
    validator['args'] = { name: 'sizeLimit', limit };

    return validator;
}

export {
    maxLength,
    minLength,
    required,
    sizeLimit,
};
