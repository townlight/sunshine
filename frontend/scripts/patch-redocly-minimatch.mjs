// Redocly 1.x calls minimatch's former CommonJS function export. Keep its
// existing generator API while using the patched matcher (GHSA-g3hv-75wg-m249).
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const generatorRequire = createRequire(require.resolve('openapi-typescript'));
const coreRequire = createRequire(generatorRequire.resolve('@redocly/openapi-core'));
const core = coreRequire('./../package.json');
assert.equal(core.version, '1.34.21', 'Review the minimatch compatibility adjustment when Redocly changes');
const path = coreRequire.resolve('./utils.js');
const before = 'const minimatch = require("minimatch");';
const after = 'const { minimatch } = require("minimatch");';
const source = readFileSync(path, 'utf8');
assert(source.includes(before) || source.includes(after), 'Unexpected Redocly matcher import');
if (source.includes(before)) writeFileSync(path, source.replace(before, after));

// Exercise the consumer, including the configured HTTP-header matching path.
const { readFileFromUrl } = coreRequire('./utils.js');
for (const [url, pattern, expected] of [
  ['https://example.test/schema.json', 'example.test/*', true],
  ['https://other.test/schema.json', 'example.test/*', false],
  ['https://example.test/schema.json', 'https://example.test/*', true],
  ['http://example.test/schema.json', 'https://example.test/*', false],
]) {
  await readFileFromUrl(url, {
    headers: [{ matches: pattern, name: 'X-Test', value: 'matched' }],
    customFetch: async (_url, { headers }) => {
      assert.equal(headers['X-Test'] === 'matched', expected);
      return new Response('{}', { headers: { 'content-type': 'application/json' } });
    },
  });
}
console.log('Redocly patched matcher compatibility verified');
