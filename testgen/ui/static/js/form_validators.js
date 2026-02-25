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
    numberBetween,
    noSpaces,
    required,
    requiredIf,
    sizeLimit,
};
