// No imports: the tests run through `npx` with nothing installed, so `vitest/config` cannot resolve.
process.env.TZ = 'UTC';
process.env.LC_ALL = 'en_US.UTF-8';

export default {
    test: {
        include: ['tests/js/**/*.test.js'],
        setupFiles: ['tests/js/setup.js'],
    },
};
