'use strict';

const { spawn } = require('node:child_process');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');

class JevFilterError extends Error {
  constructor(code, exitCode) {
    super(`Jev Filter: ${code}`);
    this.name = 'JevFilterError';
    this.code = code;
    this.exitCode = exitCode;
  }
}

function createClient(configuration = {}) {
  const command = configuration.command || [process.execPath, path.resolve(__dirname, '../bin/jev-filter.cjs')];
  if (!Array.isArray(command) || !command.length || command.some(x => typeof x !== 'string' || !x)) {
    throw new JevFilterError('invalid_command');
  }
  const maxOutputBytes = configuration.maxOutputBytes ?? 2_000_000;
  const timeoutMs = configuration.timeoutMs ?? 120_000;
  if (!Number.isSafeInteger(maxOutputBytes) || maxOutputBytes < 1 || !Number.isSafeInteger(timeoutMs) || timeoutMs < 1) {
    throw new JevFilterError('invalid_budget');
  }

  async function invoke(argv, input, options = {}) {
    if (!options.task || typeof options.task !== 'string') throw new JevFilterError('task_required');
    if (options.signal?.aborted) throw new JevFilterError('cancelled');
    let directory;
    try {
      const args = [...argv, '--task', options.task];
      if (options.analysis !== undefined) {
        directory = await fs.mkdtemp(path.join(os.tmpdir(), 'jev-filter-client-'));
        await fs.chmod(directory, 0o700);
        const spec = path.join(directory, 'analysis.json');
        await fs.writeFile(spec, JSON.stringify(options.analysis), {mode:0o600});
        args.push('--analysis', spec);
      }
      if (options.budgetChars !== undefined) {
        if (!Number.isSafeInteger(options.budgetChars) || options.budgetChars < 1) throw new JevFilterError('invalid_budget');
        args.push('--budget-chars', String(options.budgetChars));
      }
      if (options.workers !== undefined) {
        if (!Number.isInteger(options.workers) || options.workers < 1 || options.workers > 30) throw new JevFilterError('invalid_workers');
        args.push('--workers', String(options.workers));
      }
      return await new Promise((resolve, reject) => {
        let child, timer, killTimer, bytes = 0, chunks = [], settled = false, stopping;
        const signalTree = signal => {
          if (!child?.pid) return;
          if (process.platform !== 'win32') {
            try {process.kill(-child.pid, signal); return;} catch (error) {
              if (error.code === 'ESRCH') return;
            }
          }
          try {child.kill(signal);} catch {}
        };
        const finish = (error, result) => {
          if (settled) return;
          settled = true;
          clearTimeout(timer);
          clearTimeout(killTimer);
          options.signal?.removeEventListener('abort', abort);
          if (error) reject(error);
          else resolve(result);
        };
        const stop = error => {
          if (settled || stopping) return;
          stopping = error;
          clearTimeout(timer);
          if (process.platform === 'win32' && child?.pid) {
            // The trusted PID is passed as an argv value, never through a shell.
            const killer = spawn('taskkill', ['/PID', String(child.pid), '/T', '/F'], {shell:false,stdio:'ignore'});
            killer.on('error', () => signalTree('SIGKILL'));
          } else signalTree('SIGTERM');
          // SIGTERM can be ignored; reject only after the bounded process group has closed.
          killTimer = setTimeout(() => signalTree('SIGKILL'), 250);
        };
        const abort = () => stop(new JevFilterError('cancelled'));
        try {
          child = spawn(command[0], [...command.slice(1), ...args], {
            shell:false, stdio:['pipe','pipe','pipe'], cwd:configuration.cwd,
            detached:process.platform !== 'win32',
            env:configuration.env ? {...process.env, ...configuration.env} : process.env,
          });
        } catch { finish(new JevFilterError('spawn_failed')); return; }
        options.signal?.addEventListener('abort', abort, {once:true});
        timer = setTimeout(() => stop(new JevFilterError('timeout')), timeoutMs);
        child.on('error', () => finish(new JevFilterError('spawn_failed')));
        child.stdout.on('data', chunk => {
          if (stopping || settled) return;
          bytes += chunk.length;
          if (bytes > maxOutputBytes) stop(new JevFilterError('output_budget_exceeded'));
          else chunks.push(chunk);
        });
        // Drain stderr without returning arbitrary process output to the agent.
        child.stderr.on('data', () => {});
        child.stdin.on('error', () => {});
        child.on('close', code => {
          if (settled) return;
          if (stopping) {finish(stopping); return;}
          if (code !== 0 && code !== 2) { finish(new JevFilterError('cli_failed', code)); return; }
          let packet;
          try { packet = JSON.parse(Buffer.concat(chunks).toString('utf8')); }
          catch { finish(new JevFilterError('invalid_packet', code)); return; }
          if (!packet || typeof packet !== 'object' || Array.isArray(packet)) {
            finish(new JevFilterError('invalid_packet', code)); return;
          }
          finish(null, {packet, exitCode:code});
        });
        if (options.signal?.aborted) {abort(); return;}
        child.stdin.end(input === undefined ? '' : input);
      });
    } finally {
      if (directory) await fs.rm(directory, {recursive:true, force:true});
    }
  }

  return Object.freeze({
    query(records, options) {
      const mode = options?.analysis?.mode ?? 'filter';
      if (!['filter','choose','analyze','passthrough'].includes(mode)) throw new JevFilterError('invalid_mode');
      return invoke(['query','--input','-','--mode',mode], JSON.stringify(records), options);
    },
    codeSearch(pattern, options = {}) {
      const args = ['code-search', pattern];
      if (options.root) args.push('--root', options.root);
      if (options.query) args.push('--query', options.query);
      if (options.expandCallers) args.push('--expand-callers');
      return invoke(args, undefined, options);
    },
    triage(events, options = {}) {
      const args = ['triage','--input','-'];
      if (options.groupBy) args.push('--group-by', options.groupBy);
      return invoke(args, events.map(event => JSON.stringify(event)).join('\n'), options);
    },
    diffReview(options = {}) {
      const args = ['diff-review'];
      if (options.root) args.push('--root', options.root);
      const sources = [options.base !== undefined, options.staged === true, options.unstaged === true];
      if (sources.filter(Boolean).length !== 1) throw new JevFilterError('diff_source_required');
      if (options.base !== undefined) args.push('--base', options.base);
      if (options.head !== undefined) args.push('--head', options.head);
      if (options.staged) args.push('--staged');
      if (options.unstaged) args.push('--unstaged');
      return invoke(args, undefined, options);
    },
  });
}

module.exports = { createClient, JevFilterError };
