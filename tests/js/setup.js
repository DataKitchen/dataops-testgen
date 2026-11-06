import { beforeEach } from 'vitest';

if (typeof window !== 'undefined') {
    beforeEach(() => {
        window.testgen = { loadedStylesheets: {}, portals: {} };
    });
}
