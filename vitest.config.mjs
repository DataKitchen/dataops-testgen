process.env.TZ = 'UTC';
process.env.LC_ALL = 'en_US.UTF-8';

export default {
    test: {
        include: ['tests/js/**/*.test.js'],
        setupFiles: ['tests/js/setup.js'],
    },
};
