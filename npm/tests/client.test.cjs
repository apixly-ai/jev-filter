const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { createClient } = require('../client/index.cjs');

test('the package directory resolves to the public client entrypoint', () => {
  assert.equal(require('../..').createClient, createClient);
});

function fixture(t, source) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'jev-client-test-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  const file = path.join(dir, 'cli.cjs');
  fs.writeFileSync(file, source);
  return [process.execPath, file];
}

test('query preserves partial result and passes values without shell interpretation', async t => {
  const command = fixture(t, `let input=''; process.stdin.on('data', c => input+=c); process.stdin.on('end', () => { console.log(JSON.stringify({ok:true,complete:false,review_ids:['x'],args:process.argv.slice(2),records:JSON.parse(input)})); process.exitCode=2; });`);
  const client = createClient({command});
  const result = await client.query([{id:'x',text:'$(echo unsafe)'}], {task:'literal task',analysis:{required_context:['missing']}});
  assert.equal(result.exitCode, 2);
  assert.deepEqual(result.packet.review_ids, ['x']);
  assert.equal(result.packet.records[0].text, '$(echo unsafe)');
  assert.ok(result.packet.args.includes('--analysis'));
  const spec = result.packet.args[result.packet.args.indexOf('--analysis')+1];
  assert.equal(fs.existsSync(spec), false);
});

test('code search remains bounded and exposes no arbitrary exec method', async t => {
  const command = fixture(t, `console.log(JSON.stringify({ok:true,args:process.argv.slice(2)}));`);
  const client = createClient({command});
  const reply = await client.codeSearch('foo; echo unsafe', {task:'Find handler',root:'/fixture'});
  assert.ok(reply.packet.args.includes('foo; echo unsafe'));
  assert.equal(client.exec, undefined);
});

test('malformed and oversized output fail without echoing raw stdout', async t => {
  const command = fixture(t, `console.log('sensitive broken output');`);
  await assert.rejects(createClient({command}).query([], {task:'x'}), {code:'invalid_packet'});
  const oversized = fixture(t, `console.log('x'.repeat(1000));`);
  await assert.rejects(createClient({command:oversized,maxOutputBytes:100}).query([], {task:'x'}), {code:'output_budget_exceeded'});
});

test('timeout and cancellation terminate once and clean up', async t => {
  const command = fixture(t, `setInterval(()=>{},1000);`);
  await assert.rejects(createClient({command,timeoutMs:20}).query([], {task:'x'}), {code:'timeout'});
  const controller = new AbortController();
  const promise = createClient({command}).query([], {task:'x',signal:controller.signal});
  controller.abort();
  await assert.rejects(promise, {code:'cancelled'});
});

test('query preserves an explicitly supplied analysis mode', async t => {
  const command = fixture(t, `console.log(JSON.stringify({args:process.argv.slice(2)}));`);
  const result = await createClient({command}).query([], {task:'Choose one',analysis:{mode:'choose'}});
  assert.equal(result.packet.args[result.packet.args.indexOf('--mode')+1], 'choose');
});

test('timeout stops a SIGTERM-ignoring process before rejecting', {skip:process.platform==='win32'}, async t => {
  const command = fixture(t, `const fs=require('node:fs'); process.on('SIGTERM',()=>{}); fs.writeFileSync(process.env.JEV_TEST_PID,String(process.pid)); setInterval(()=>{},1000);`);
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'jev-client-pid-'));
  t.after(() => fs.rmSync(dir, {recursive:true,force:true}));
  const pidFile = path.join(dir, 'pid');
  let pid;
  t.after(() => {if(pid){try {process.kill(pid,'SIGKILL');} catch {}}});
  const client = createClient({command,timeoutMs:200,env:{JEV_TEST_PID:pidFile}});
  await assert.rejects(client.query([], {task:'x',analysis:{required_context:['scope']}}), {code:'timeout'});
  pid = Number(fs.readFileSync(pidFile, 'utf8'));
  assert.throws(() => process.kill(pid, 0), {code:'ESRCH'});
});

test('cancellation during spec preparation never leaves an unresolved child', async t => {
  const command = fixture(t, `setInterval(()=>{},1000);`);
  const promises = require('node:fs/promises');
  const original = promises.writeFile;
  const controller = new AbortController();
  promises.writeFile = async (...args) => {
    await original(...args);
    controller.abort();
  };
  t.after(() => {promises.writeFile=original;});
  const operation = createClient({command,timeoutMs:200}).query([], {
    task:'x',analysis:{required_context:['scope']},signal:controller.signal,
  });
  await assert.rejects(Promise.race([
    operation,
    new Promise((_, reject) => {const timer=setTimeout(()=>reject(new Error('unresolved child')),1500);timer.unref();}),
  ]), {code:'cancelled'});
});
