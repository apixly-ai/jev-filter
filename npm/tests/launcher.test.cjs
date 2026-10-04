const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { platformPackage, launch } = require('../bin/jev-filter.cjs');

test('selects only supported native platforms', () => {
  assert.equal(platformPackage('darwin', 'arm64'), '@apixly/jev-filter-darwin-arm64');
  assert.equal(platformPackage('linux', 'x64'), '@apixly/jev-filter-linux-x64');
  assert.throws(() => platformPackage('win32', 'x64'), /WSL/);
  assert.throws(() => platformPackage('linux', 'ia32'), /Unsupported/);
});

test('passes arguments and inherited stdio without a shell', () => {
  let observed;
  const child = { on: () => child, kill: () => {} };
  const result = launch(['exec', '--', 'printf', 'a b'], {
    platform: 'linux', arch: 'x64',
    resolve: () => '/fixture/native/package.json',
    spawn: (...args) => { observed = args; return child; },
    process: { on() {}, removeListener() {}, exitCode: undefined },
  });
  assert.equal(result, child);
  assert.deepEqual(observed, [path.join('/fixture/native', 'bin', 'jev-filter'), ['exec', '--', 'printf', 'a b'], { stdio: 'inherit', shell: false }]);
});

test('missing optional binary gives an actionable error', () => {
  assert.throws(() => launch([], {platform:'linux',arch:'x64',resolve:()=>{throw Error('missing');}}), /optional/);
});
