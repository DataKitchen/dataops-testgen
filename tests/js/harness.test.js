import { expect, it } from 'vitest';

it('pins the process time zone to UTC', () => {
    expect(new Date(0).getTimezoneOffset()).toBe(0);
});

it('pins the locale to en-US number formatting', () => {
    expect((1234.5).toLocaleString()).toBe('1,234.5');
});
