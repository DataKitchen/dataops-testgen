# JavaScript unit tests

Unit tests for the frontend modules under `testgen/ui/static/js/`, run with [Vitest](https://vitest.dev/) and
[happy-dom](https://github.com/capricorn86/happy-dom).

## Running

From the repository root (the directory holding `vitest.config.mjs` and `pyproject.toml`):

```bash
npm ci
npm test
```

Run a single file by passing its path: `npm test -- tests/js/utils.test.js`. For watch mode, run `npx vitest`.
`npm test` never downloads anything: without `npm ci` it fails, where a bare `npx vitest` would fetch the latest
release instead of the pinned one.

- **Node 22.12 or later** is required by Vitest 5.
- **`npm ci` installs exactly what `package-lock.json` lists** into `node_modules/` (ignored by git). Run it again
  after the lockfile changes.
- **Run it from this repository's root.** From any other directory Vitest finds neither the config nor the tests, and
  exits with "No test files found".
- **The lockfile pins every package**, dependencies of dependencies included, so a new upstream release cannot
  change what the tests run with. To upgrade, change the versions in `package.json` and run `npx -y npm@11 install`,
  which rewrites `package-lock.json`; commit both. Regenerating the lockfile needs npm 11 or later: npm 10, which
  Node 22 ships, fails to resolve this dependency tree.

`vitest.config.mjs` sets the process time zone to UTC and the locale to `en_US.UTF-8`, so date and number assertions
behave the same on every machine. `tests/js/harness.test.js` checks both.

## Layout and naming

- One test file per module, named after it: `axis_utils.js` → `tests/js/axis_utils.test.js`.
- Import the module under test by relative path: `import { niceBounds } from '../../testgen/ui/static/js/axis_utils.js';`
- Import `describe`, `it`, `expect`, `vi`, and the hooks from `'vitest'`. Globals are not enabled.
- Use `it.each` for tables of inputs and outputs.

## Environments

Test files run in the `node` environment by default. That is faster, and it is enough for pure logic.
`van.state` and `van.derive` work there too.

A file that needs a DOM (`window`, `document`, elements, `CSSStyleSheet`, `ResizeObserver`) opts in with a docblock
on its **first line**:

```js
// @vitest-environment happy-dom
```

The whole file then runs under happy-dom. Use happy-dom rather than jsdom: jsdom has no
`document.adoptedStyleSheets`, so any component that loads a stylesheet at import time cannot be imported.

## Shared setup

`tests/js/setup.js` runs before every test file. Under happy-dom, it gives each test a fresh
`window.testgen = { loadedStylesheets: {}, portals: {} }`, which is the registry components read. Add a stub there
only if every DOM test needs it. Anything narrower belongs in the test file that needs it.

Some state is not reset for you:

- `document.adoptedStyleSheets` persists across tests in a file. Assert on its change in length, not its length.
- A module's own module-level state (for example, the page registry in `page_lifecycle.js`) persists for the whole
  file. Use unique keys per test, or `vi.resetModules()` and a dynamic `import()`.
- A module that does work at import time (`scripts.js`) needs `vi.resetModules()` before each test, and the
  listeners it adds must be removed afterwards. See `scripts.test.js`.

## Timers

Use fake timers for anything scheduled (`setTimeout`, `setInterval`, `debounce`, and van's deferred `derive`
updates), never real waits:

```js
beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());
```

For async work that a dispatched event starts, `await vi.waitFor(() => expect(...))`.

## happy-dom gaps

| Missing | Workaround |
|---|---|
| `window.frameElement` (undefined) | `Object.defineProperty(window, 'frameElement', { value: el, configurable: true })`, and `delete` it afterwards |
| `document.execCommand` | Assign `document.execCommand = vi.fn()`, and `delete` it afterwards |
| An `<iframe>` attached to the document logs a page-load error | Build the tree detached, or don't use an iframe |

## Pinning current behavior

These tests describe what the code does today. When a behavior looks wrong, the test still asserts it, its name
ends in `(pinned)`, and the fix is a separate change that updates that test. Search for `(pinned)` to find them
all.

## Checking that a test can fail

A test written against existing code passes the first time it runs, which proves nothing about whether it can
fail. After writing a file, break one line of the module it covers, such as a flipped comparison or a deleted
statement, and confirm that at least one test fails. Then revert the change.
