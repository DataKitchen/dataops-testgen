// @vitest-environment happy-dom
import { afterEach, describe, expect, it } from 'vitest';
import van from '../../testgen/ui/static/js/van.min.js';
import { Tooltip } from '../../testgen/ui/static/js/components/tooltip.js';

describe('Tooltip', () => {
    afterEach(() => {
        document.body.innerHTML = '';
    });

    it('renders backtick-enclosed text as code', () => {
        const tooltip = Tooltip({ text: "Example: `region = 'EMEA'`.", show: true });
        van.add(document.body, tooltip);

        const codes = [...tooltip.querySelectorAll('code')].map(element => element.textContent);
        expect(codes).toEqual(["region = 'EMEA'"]);
        expect(tooltip.textContent).toBe("Example: region = 'EMEA'.");
    });

    it('leaves a lone backtick as text', () => {
        const tooltip = Tooltip({ text: 'Quote with ` here', show: true });
        van.add(document.body, tooltip);

        expect(tooltip.querySelector('code')).toBeNull();
        expect(tooltip.textContent).toBe('Quote with ` here');
    });
});
