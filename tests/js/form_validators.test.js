import { describe, expect, it, vi } from 'vitest';
import {
    email,
    emailList,
    httpsUrl,
    jsonObject,
    maxLength,
    minLength,
    noSpaces,
    notIn,
    numberBetween,
    required,
    requiredIf,
    sizeLimit,
} from '../../testgen/ui/static/js/form_validators.js';

const REQUIRED = 'This field is required';

describe('required', () => {
    it.each(['x', []])('accepts %j', (value) => {
        expect(required(value)).toBeNull();
    });

    it.each(['', '  ', null, undefined])('rejects %j', (value) => {
        expect(required(value)).toBe(REQUIRED);
    });

    it.each([0, false])('rejects the falsy value %j (pinned)', (value) => {
        expect(required(value)).toBe(REQUIRED);
    });
});

describe('requiredIf', () => {
    it('requires the value when the condition holds', () => {
        expect(requiredIf(() => true)('')).toBe(REQUIRED);
    });

    it('allows an empty value when the condition does not hold', () => {
        expect(requiredIf(() => false)('')).toBeNull();
    });

    it('passes the value to the condition', () => {
        const condition = vi.fn(() => false);

        requiredIf(condition)('abc');

        expect(condition).toHaveBeenCalledWith('abc');
    });

    it('exposes its name and condition as args', () => {
        const condition = () => true;

        expect(requiredIf(condition).args).toEqual({ name: 'requiredIf', condition });
    });
});

describe('noSpaces', () => {
    it('rejects a value containing a space', () => {
        expect(noSpaces('a b')).toBe('Value cannot contain spaces.');
    });

    it.each(['ab', '', null, undefined])('accepts %j', (value) => {
        expect(noSpaces(value)).toBeNull();
    });
});

describe('minLength', () => {
    const validate = minLength(3);

    it('rejects a value shorter than the minimum', () => {
        expect(validate('ab')).toBe('Value must be at least 3 characters long.');
    });

    it.each(['abc', 'abcd', '', null])('accepts %j', (value) => {
        expect(validate(value)).toBeNull();
    });
});

describe('maxLength', () => {
    const validate = maxLength(3);
    const message = 'Value must be 3 characters long or shorter.';

    it.each(['abc', ''])('accepts %j', (value) => {
        expect(validate(value)).toBeNull();
    });

    it('rejects a value longer than the maximum', () => {
        expect(validate('abcd')).toBe(message);
    });

    it.each([null, undefined, 123])('rejects the non-string %j (pinned)', (value) => {
        expect(validate(value)).toBe(message);
    });
});

describe('numberBetween', () => {
    const validate = numberBetween(0, 10);

    it.each(['5', 0, 10, '0.5'])('accepts %j', (value) => {
        expect(validate(value)).toBeFalsy();
    });

    it('returns undefined rather than null for a valid value (pinned)', () => {
        expect(validate(5)).toBeUndefined();
    });

    it.each([11, -1, '10.01'])('rejects the out-of-range %j', (value) => {
        expect(validate(value)).toBe('Value must be between 0 and 10.');
    });

    it.each(['x', '', null, undefined])('rejects the non-numeric %j', (value) => {
        expect(validate(value)).toBe('Value must be a numeric type.');
    });

    describe('with precision 2', () => {
        const validatePrecise = numberBetween(0, 10, 2);

        it('accepts two decimal places', () => {
            expect(validatePrecise('1.23')).toBeFalsy();
        });

        it('rejects three decimal places', () => {
            expect(validatePrecise('1.234')).toBe('Value must have at most 2 digits after the decimal point.');
        });

        it('accepts exponent notation, which has no decimal point', () => {
            expect(validatePrecise(1e-7)).toBeFalsy();
        });
    });

    describe('with precision 0', () => {
        const validateInteger = numberBetween(0, 10, 0);

        it('accepts an integer', () => {
            expect(validateInteger('3')).toBeFalsy();
        });

        it('rejects a decimal', () => {
            expect(validateInteger('1.5')).toBe('Value must be an integer.');
        });
    });
});

describe('sizeLimit', () => {
    const validate = sizeLimit(1024);

    it('accepts a file at the limit', () => {
        expect(validate({ size: 1024 })).toBeNull();
    });

    it('rejects a file over the limit', () => {
        expect(validate({ size: 2048 })).toBe('File size 2KB exceeds the 1024B limit.');
    });

    it('formats megabyte sizes', () => {
        expect(sizeLimit(2 * 1048576)({ size: 3 * 1048576 })).toBe('File size 3MB exceeds the 2MB limit.');
    });

    it.each([null, undefined])('accepts no file (%j)', (value) => {
        expect(validate(value)).toBeNull();
    });

    it('exposes its name and limit as args', () => {
        expect(validate.args).toEqual({ name: 'sizeLimit', limit: 1024 });
    });
});

describe('notIn', () => {
    it('rejects a listed value with the default message', () => {
        expect(notIn(['a', 'b'])('a')).toBe('Value cannot be any of: a, b.');
    });

    it.each(['c', '', null])('accepts %j', (value) => {
        expect(notIn(['a', 'b'])(value)).toBeNull();
    });

    it('uses a custom error message', () => {
        expect(notIn(['a'], { errorMessage: 'taken' })('a')).toBe('taken');
    });

    it('compares the formatted value', () => {
        const validate = notIn(['abc'], { formatter: (value) => value.toLowerCase() });

        expect(validate('ABC')).toBe('Value cannot be any of: abc.');
    });
});

describe('email', () => {
    it('accepts a valid address, trimming whitespace', () => {
        expect(email(' a@b.co ')).toBeNull();
    });

    it.each(['', '  ', null, undefined])('treats %j as empty and optional', (value) => {
        expect(email(value)).toBeNull();
    });

    it.each(['a@b', 'a b@c.de', 'a@b.c'])('rejects %j', (value) => {
        expect(email(value)).toBe(`${value} is not a valid email address.`);
    });
});

describe('emailList', () => {
    it.each([
        'a@b.co, c@d.io;e@f.org',
        'a@b.co\nc@d.io',
    ])('accepts the separated list %j', (value) => {
        expect(emailList(value)).toBeNull();
    });

    it.each(['', null, ' , ;'])('treats %j as empty', (value) => {
        expect(emailList(value)).toBeNull();
    });

    it('names a single invalid entry', () => {
        expect(emailList('bad, a@b.co')).toBe('bad is not a valid email address.');
    });

    it('lists several invalid entries once each, in order', () => {
        expect(emailList('bad, x@, bad')).toBe('Not valid email addresses: bad, x@.');
    });
});

describe('httpsUrl', () => {
    it.each(['https://x.com', 'HTTPS://x.com', '', null])('accepts %j', (value) => {
        expect(httpsUrl()(value)).toBeNull();
    });

    it('rejects a non-https scheme', () => {
        expect(httpsUrl()('http://x.com')).toBe('Value must start with https://.');
    });

    it.each(['https://', 'https://exa mple.com'])('rejects the malformed %j', (value) => {
        expect(httpsUrl()(value)).toBe('Value is not a valid URL.');
    });

    it('opens the message with the label', () => {
        expect(httpsUrl('Webhook URL')('ftp://x')).toBe('Webhook URL must start with https://.');
    });
});

describe('jsonObject', () => {
    it.each(['{"a":1}', '{}', '', '  ', null])('accepts %j', (value) => {
        expect(jsonObject(value)).toBeNull();
    });

    it('rejects invalid JSON', () => {
        expect(jsonObject('{')).toBe('Must be valid JSON.');
    });

    it.each(['[1]', 'null', '1', '"s"'])('rejects the non-object JSON %j', (value) => {
        expect(jsonObject(value)).toBe('Must be a JSON object of key-value pairs.');
    });
});
