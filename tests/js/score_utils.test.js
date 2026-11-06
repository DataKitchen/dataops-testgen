import { describe, expect, it } from 'vitest';
import { colorMap } from '../../testgen/ui/static/js/display_utils.js';
import { getScoreColor } from '../../testgen/ui/static/js/score_utils.js';

describe('getScoreColor', () => {
    it.each([
        [100, 'green'],
        [96, 'green'],
        [95.9, 'yellow'],
        [91, 'yellow'],
        [90.9, 'orange'],
        [86, 'orange'],
        [85.9, 'red'],
        [0, 'red'],
        [-5, 'red'],
    ])('maps the numeric score %s to %s', (score, color) => {
        expect(getScoreColor(score)).toBe(colorMap[color]);
    });

    it.each([
        ['97', 'green'],
        ['50', 'red'],
    ])('maps the numeric string %s to %s', (score, color) => {
        expect(getScoreColor(score)).toBe(colorMap[color]);
    });

    it.each([
        ['>99', 'green'],
        ['<1', 'red'],
    ])('maps the bounded string %s to %s', (score, color) => {
        expect(getScoreColor(score)).toBe(colorMap[color]);
    });

    it.each([null, undefined, NaN, '', '--'])('falls back to grey for %s', (score) => {
        expect(getScoreColor(score)).toBe(colorMap.grey);
    });
});
