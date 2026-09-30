// Program-owned page observation, freshness guards and target resolution for hosted execution.
// Adapted from browser-use/jev-ultrafast snapshot.js (MIT, Copyright (c) 2026 Browser Use), with
// open shadow roots, same-origin frames, observe-time occlusion, value privacy and extraction.
// Jev only ever sees the returned tables; it never supplies selectors, coordinates or script.
(request => {
  const op = request.op;
  const cache = window.__jevFilterAct ||= {ids: new WeakMap(), nodes: new Map(), next: 1};
  for (const [id, e] of cache.nodes) if (!e.isConnected) cache.nodes.delete(id);
  const identity = e => {
    if (!cache.ids.has(e)) cache.ids.set(e, cache.next++);
    const id = cache.ids.get(e); cache.nodes.set(id, e); return id;
  };
  const SENSITIVE = /^(cc-|one-time-code|current-password|new-password)/;
  const skipped = e => ['password', 'file', 'hidden'].includes(e.type);
  const sensitive = e => SENSITIVE.test((e.getAttribute('autocomplete') || '').trim().toLowerCase());
  const visible = e => {
    if (e.closest('[aria-hidden="true"],[inert]')) return false;
    if (e.checkVisibility) return e.checkVisibility({checkOpacity: true, checkVisibilityCSS: true});
    const s = getComputedStyle(e);
    return s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
  };
  const frameOffset = e => {
    let x = 0, y = 0, w = e.ownerDocument.defaultView;
    while (w && w !== window && w.frameElement) {
      const f = w.frameElement, r = f.getBoundingClientRect();
      x += r.left + f.clientLeft; y += r.top + f.clientTop; w = f.ownerDocument.defaultView;
    }
    return [x, y];
  };
  const rectOf = e => {
    const r = e.getBoundingClientRect(), [dx, dy] = frameOffset(e);
    return {x: r.x + dx, y: r.y + dy, w: r.width, h: r.height};
  };
  // Hit-test through open shadow roots and same-origin frames, then walk the composed tree up.
  const deepHit = (x, y) => {
    let doc = document, ox = 0, oy = 0, el = null;
    for (let depth = 0; depth < 8; depth++) {
      el = doc.elementFromPoint(x - ox, y - oy);
      while (el && el.shadowRoot) {
        const inner = el.shadowRoot.elementFromPoint(x - ox, y - oy);
        if (!inner || inner === el) break;
        el = inner;
      }
      if (el && el.tagName === 'IFRAME') {
        let inner = null;
        try { inner = el.contentDocument; } catch (_) { inner = null; }
        if (!inner) return el;
        const r = el.getBoundingClientRect();
        ox += r.left + el.clientLeft; oy += r.top + el.clientTop; doc = inner; continue;
      }
      return el;
    }
    return el;
  };
  const composedContains = (target, hit) => {
    for (let n = hit; n; n = n.parentNode || n.host || null) if (n === target) return true;
    return false;
  };
  const name = (e, seen = new Set()) => {
    if (!e || seen.has(e)) return '';
    seen.add(e);
    const doc = e.getRootNode ? e.getRootNode() : document;
    const referenced = (e.getAttribute && e.getAttribute('aria-labelledby') || '').split(/\s+/)
      .filter(Boolean).map(id => name((doc.getElementById ? doc.getElementById(id) : null) || document.getElementById(id), seen))
      .filter(Boolean).join(' ');
    return (referenced || e.getAttribute('aria-label') ||
      [...(e.labels || [])].map(l => name(l, seen)).filter(Boolean).join(' ') ||
      (['button', 'submit', 'reset'].includes(e.type) ? e.value : '') || e.getAttribute('alt') ||
      (e.tagName === 'INPUT' ? '' : [...e.childNodes].map(n => n.nodeType === 3 ? n.textContent :
        n.nodeType === 1 && n.getAttribute('aria-hidden') !== 'true' ? name(n, seen) : '').join(' ')
        .replace(/\s+/g, ' ').trim()) ||
      e.getAttribute('title') || e.getAttribute('placeholder') || '').trim().slice(0, 200);
  };
  const ROLES = ['button', 'link', 'checkbox', 'radio', 'switch', 'tab', 'menuitem', 'menuitemradio',
    'menuitemcheckbox', 'option', 'treeitem', 'gridcell', 'combobox', 'textbox', 'searchbox', 'spinbutton'];
  const SELECTOR = 'a[href],button,input,textarea,select,summary,[contenteditable="true"],[contenteditable=""],' +
    ROLES.map(r => '[role="' + r + '"]').join(',');
  const role = e => {
    const explicit = e.getAttribute('role');
    if (ROLES.includes(explicit)) return explicit;
    if (e.tagName === 'BUTTON' || e.tagName === 'SUMMARY') return 'button';
    if (e.tagName === 'A') return 'link';
    if (e.tagName === 'SELECT') return 'combobox';
    if (e.tagName === 'TEXTAREA' || e.isContentEditable) return 'textbox';
    if (e.tagName === 'INPUT') {
      if (['checkbox', 'radio'].includes(e.type)) return e.type;
      if (['button', 'submit', 'reset', 'image'].includes(e.type)) return 'button';
      if (e.type === 'search') return 'searchbox';
      if (e.type === 'number') return 'spinbutton';
      if (['text', 'email', 'url', 'tel', ''].includes(e.type) || !e.type) return 'textbox';
      if (['date', 'time', 'datetime-local', 'month', 'week'].includes(e.type)) return 'textbox';
    }
    return null;
  };
  const section = e => {
    const p = e.closest('dialog,[role="dialog"],form,fieldset,section,nav,header,footer,aside,main,article,li,tr,[role="row"]');
    if (!p) return '';
    return (p.getAttribute('aria-label') ||
      (p.querySelector('legend,h1,h2,h3,h4,caption') || {}).innerText || p.tagName.toLowerCase()).trim().slice(0, 120);
  };
  const rowText_ = row => {
    if (row.tagName === 'TR' || row.getAttribute('role') === 'row') {
      return [...row.children].map(c => (c.innerText || '').replace(/\s+/g, ' ').trim()).filter(Boolean).join(' | ');
    }
    return (row.innerText || '').replace(/\s+/g, ' ').trim();
  };
  const valueOf = e => {
    if (sensitive(e)) return ('value' in e && e.value) ? '[filled]' : '';
    if ('value' in e && e.tagName !== 'BUTTON') return String(e.value).slice(0, 200);
    if (e.isContentEditable || e.getAttribute('role') === 'combobox') return e.innerText.trim().slice(0, 200);
    return '';
  };
  // Collect from the document, open shadow roots and same-origin frames.
  const roots = [];
  const frames = {same_origin: 0, cross_origin: 0};
  const addRoot = (root, depth) => {
    if (depth > 6) return;
    roots.push(root);
    for (const host of root.querySelectorAll('*')) if (host.shadowRoot) addRoot(host.shadowRoot, depth + 1);
    for (const f of root.querySelectorAll('iframe,frame')) {
      let d = null;
      try { d = f.contentDocument; } catch (_) { d = null; }
      if (d && d.documentElement) { frames.same_origin++; addRoot(d, depth + 1); } else frames.cross_origin++;
    }
  };
  const all = sel => roots.flatMap(r => [...r.querySelectorAll(sel)]);

  cache.pageKey = () => [performance.timeOrigin, location.href, scrollX, scrollY, innerWidth, innerHeight,
    all('input,textarea,select').filter(e => !skipped(e))
      .map(e => [identity(e), sensitive(e) ? Boolean(e.value) : e.value, e.checked, e.selectedIndex, e.disabled, e.readOnly])];
  cache.guard = e => {
    if (!e || !e.isConnected || !visible(e)) return null;
    const scope = e.closest('form,dialog,[role="dialog"],article,li,tr,[role="row"]') || e.parentElement;
    return [identity(e), role(e), name(e), sensitive(e) ? Boolean(e.value) : (e.value ?? null),
      e.checked ?? null, e.selectedIndex ?? null, e.readOnly ?? null, e.matches(':disabled'),
      e.getAttribute('aria-disabled'), e.getAttribute('aria-expanded'), e.getAttribute('aria-checked'),
      e.getAttribute('aria-selected'), e.getAttribute('href'), (scope && scope.innerText || '').slice(0, 4000)];
  };

  if (op === 'guard') {
    addRoot(document, 0);
    return [cache.pageKey(), cache.guard(cache.nodes.get(request.node))];
  }

  if (op === 'resolve') {
    const a = request.action, e = cache.nodes.get(a.node);
    if (!e || !e.isConnected || !visible(e) || e.matches(':disabled') ||
        e.closest('[aria-disabled="true"],[inert]')) return {ok: false, reason: 'target_changed'};
    if (a.kind === 'fill' && (e.readOnly || e.getAttribute('aria-readonly') === 'true'))
      return {ok: false, reason: 'target_changed'};
    const r = rectOf(e), x = r.x + r.w / 2, y = r.y + r.h / 2;
    if (!r.w || !r.h || x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return {ok: false, reason: 'offscreen'};
    const hit = deepHit(x, y);
    if (!hit || !composedContains(e, hit)) return {ok: false, reason: 'covered'};
    if (a.kind === 'select') {
      if (e.tagName !== 'SELECT') return {ok: false, reason: 'target_changed'};
      const option = [...e.options].find(o => o.value === a.value && !o.disabled && !o.closest('optgroup[disabled]'));
      if (!option) return {ok: false, reason: 'target_changed'};
      e.value = a.value;
      e.dispatchEvent(new Event('input', {bubbles: true}));
      e.dispatchEvent(new Event('change', {bubbles: true}));
      return {ok: true, applied: true, x, y};
    }
    if (request.tag) {
      const key = 'a' + a.node + '-' + Math.floor(performance.now());
      e.setAttribute('data-jev-act', key);
      return {ok: true, x, y, selector: '[data-jev-act="' + key + '"]'};
    }
    return {ok: true, x, y};
  }

  if (op === 'readback') {
    const e = cache.nodes.get(request.node);
    if (!e || !e.isConnected) return null;
    return {value: sensitive(e) ? '[filled]' : ('value' in e ? String(e.value) : e.innerText || ''),
      focused: document.activeElement === e || composedContains(e, document.activeElement)};
  }

  if (op === 'settle') {
    const a = request.action || {}, field = cache.nodes.get(a.node);
    const auto = a.kind === 'fill' && field && field.getAttribute('role') === 'combobox';
    return new Promise(resolve => {
      let frames = 0, stopped = false;
      const finish = () => { stopped = true; resolve(true); };
      setTimeout(finish, auto ? 200 : 50);
      const ready = () => {
        if (stopped) return;
        const ids = (field && (field.getAttribute('aria-controls') || field.getAttribute('aria-owns')) || '')
          .split(/\s+/).filter(Boolean);
        const scopes = ids.length ? ids.map(id => document.getElementById(id)).filter(Boolean) : [document];
        const options = scopes.flatMap(s => [...s.querySelectorAll('[role="option"]')]);
        if (++frames >= 2 && (!auto || options.some(o => { const r = o.getBoundingClientRect();
          return r.width && r.height && r.bottom > 0 && r.top < innerHeight && visible(o); }))) finish();
        else requestAnimationFrame(ready);
      };
      requestAnimationFrame(ready);
    });
  }

  if (op === 'extract') {
    if (!document.body) return null;
    addRoot(document, 0);
    const limit = Math.max(1, Math.min(request.limit || 500, 5000));
    const records = [];
    let omitted = 0;
    const heading = e => {
      let n = e;
      while (n && n !== document.body) {
        let s = n.previousElementSibling;
        while (s) { if (/^H[1-6]$/.test(s.tagName)) return s.innerText.trim().slice(0, 160); s = s.previousElementSibling; }
        n = n.parentElement;
      }
      return '';
    };
    const push = (kind, e, text, extra) => {
      text = (text || '').replace(/\s+/g, ' ').trim();
      if (!text) return;
      if (records.length >= limit) { omitted++; return; }
      records.push({id: kind[0] + (records.length + 1), kind, text: text.slice(0, 2000), section: heading(e), ...extra});
    };
    const scope = request.scope ? document.querySelector(request.scope) : document.body;
    if (!scope) return {records: [], scope_missing: true, url: location.href};
    for (const table of scope.querySelectorAll('table')) {
      if (!visible(table)) continue;
      const headers = [...table.querySelectorAll('thead th, tr:first-child th')].map(h => h.innerText.trim());
      for (const tr of table.querySelectorAll('tbody tr, tr')) {
        if (tr.querySelector('th') && !tr.querySelector('td')) continue;
        const cells = [...tr.querySelectorAll('td,th')].map(c => c.innerText.replace(/\s+/g, ' ').trim());
        const text = cells.map((c, i) => headers[i] ? headers[i] + ': ' + c : c).join(' | ');
        push('row', tr, text, {caption: (table.querySelector('caption') || {}).innerText || ''});
      }
    }
    const blocks = 'h1,h2,h3,h4,h5,h6,p,li,dt,dd,blockquote,pre,figcaption,[role="listitem"],[role="article"]';
    for (const e of scope.querySelectorAll(blocks)) {
      if (!visible(e) || e.closest('table') || e.querySelector(blocks)) continue;
      push(/^H[1-6]$/.test(e.tagName) ? 'heading' : 'block', e, e.innerText);
    }
    for (const a of scope.querySelectorAll('a[href]')) {
      if (!visible(a)) continue;
      push('link', a, name(a), {href: a.href});
    }
    return {records, omitted, url: location.href, title: document.title, frames};
  }

  if (op !== 'observe' && op !== 'marker') throw Error('unknown_operation');
  if (!document.body) return null;
  addRoot(document, 0);
  const scopeRoot = request.scope ? document.querySelector(request.scope) : null;
  if (request.scope && !scopeRoot) return {scope_missing: true, url: location.href};
  const actions = [];
  let covered = 0, below = 0;
  for (const e of all(SELECTOR)) {
    if (scopeRoot && !composedContains(scopeRoot, e)) continue;
    if (skipped(e) || !visible(e) || e.matches(':disabled') || e.closest('[aria-disabled="true"]')) continue;
    const rname = role(e);
    if (!rname) continue;
    const r = rectOf(e), x = r.x + r.w / 2, y = r.y + r.h / 2;
    if (r.w <= 0 || r.h <= 0) continue;
    if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) { if (y >= innerHeight) below++; continue; }
    if (rname === 'gridcell' && e.querySelector('button,[role="button"]')) continue;
    const hit = deepHit(x, y);
    if (!hit || !composedContains(e, hit)) { covered++; continue; }
    const base = {node: identity(e), role: rname, label: name(e) || rname, section: section(e)};
    const row = e.closest('tr,[role="row"],li,article,[role="listitem"],[role="article"]');
    if (row) {
      const rowText = rowText_(row);
      if (rowText && rowText !== base.label) base.row = rowText.slice(0, 240);
    }
    for (const key of ['checked', 'selected', 'expanded', 'pressed']) {
      const v = e.getAttribute('aria-' + key);
      if (v !== null) base[key] = v;
    }
    if (['checkbox', 'radio'].includes(e.type)) base.checked = String(e.checked);
    if (e.tagName === 'A' && e.href) base.href = e.href;
    if (e.ownerDocument !== document) base.frame = true;
    if (e.tagName === 'SELECT') {
      const current = [...e.selectedOptions].map(o => o.label).join(', ');
      for (const o of e.options) if (!o.selected && !o.disabled && !o.closest('optgroup[disabled]'))
        actions.push({...base, kind: 'select', value: o.value, current_value: current, label: base.label + ' → ' + o.label});
    } else {
      const editable = !e.readOnly && e.getAttribute('aria-readonly') !== 'true' &&
        (['textbox', 'searchbox', 'spinbutton'].includes(rname) ||
          (rname === 'combobox' && ['INPUT', 'TEXTAREA'].includes(e.tagName)));
      const value = valueOf(e);
      actions.push({...base, kind: editable ? 'fill' : 'click', value, sensitive: sensitive(e) || undefined});
      if (editable) actions.push({...base, kind: 'click', value, label: 'Open ' + base.label});
    }
  }
  const words = [];
  let lastRow = null;
  let length = 0;
  const textLimit = request.text_limit || 6000;
  for (const root of roots) {
    const body = root.body || root;
    if (!body || !body.nodeType) continue;
    const owner = body.ownerDocument || document, range = owner.createRange();
    const walker = owner.createTreeWalker(body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode()) && length < textLimit) {
      const value = node.textContent.trim(), parent = node.parentElement;
      if (!value || !parent || parent.closest('script,style,noscript,template') || !visible(parent)) continue;
      range.selectNodeContents(node);
      const r = range.getBoundingClientRect(), [dx, dy] = frameOffset(parent);
      if (r.width > 0 && r.height > 0 && r.bottom + dy > 0 && r.top + dy < innerHeight && r.right + dx > 0 && r.left + dx < innerWidth) {
        const rowEl = parent.closest('tr,[role="row"]');
        if (rowEl && rowEl === lastRow && words.length) { words[words.length - 1] += ' | ' + value; }
        else { words.push(value); }
        lastRow = rowEl;
        length += value.length + 3;
      }
    }
  }
  const text = words.join('\n').slice(0, textLimit), height = document.documentElement.scrollHeight;
  const pageKey = cache.pageKey(), guards = {};
  for (const a of actions) if (!(a.node in guards)) guards[a.node] = cache.guard(cache.nodes.get(a.node));
  // Copies: ids assigned below must not leak into the freshness marker.
  const semantics = actions.map(a => ({...a}));
  const marker = [performance.timeOrigin, location.href, scrollX, scrollY, innerWidth, innerHeight,
    document.title, text, semantics, pageKey[6]];
  if (op === 'marker') return marker;
  const limit = Math.max(1, Math.min(request.limit || 250, 1000));
  const omitted = Math.max(0, actions.length - limit);
  actions.splice(limit);
  actions.forEach((a, i) => a.id = 'e' + (i + 1));
  if (scrollY + innerHeight < height - 2) actions.push({id: 'scroll_down', kind: 'scroll', label: 'Scroll down', delta: Math.round(innerHeight * 0.7)});
  if (scrollY > 0) actions.push({id: 'scroll_up', kind: 'scroll', label: 'Scroll up', delta: -Math.round(innerHeight * 0.7)});
  const active = document.activeElement;
  if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.isContentEditable) && !skipped(active))
    actions.push({id: 'press_enter', kind: 'key', key: 'Enter', label: 'Press Enter in the focused field (' + (name(active) || role(active) || 'field') + ')'});
  if (history.length > 1) actions.push({id: 'back', kind: 'back', label: 'Go back to the previous page'});
  actions.push({id: 'wait', kind: 'wait', label: 'Wait for the page to update'});
  const dialogs = all('dialog[open],[role="dialog"],[role="alertdialog"],[aria-modal="true"]').filter(visible)
    .map(d => name(d) || (d.querySelector('h1,h2,h3') || {}).innerText || 'dialog').slice(0, 5);
  // Deterministic hand-back signals: verification challenges are never solved, and password
  // fields are never observed or filled, so a visible one means a sign-in the user must do.
  const challenge = Boolean(document.querySelector(
      'iframe[src*="recaptcha"],iframe[src*="hcaptcha"],iframe[src*="challenges.cloudflare.com"],' +
      '#cf-challenge-running,.g-recaptcha,.h-captcha,[data-sitekey]')) ||
    /^(just a moment|attention required|verify you are human)/i.test(document.title);
  const passwords = all('input[type="password"]').filter(visible).length;
  return {url: location.href, origin: location.origin, title: document.title, w: innerWidth, h: innerHeight,
    text, scroll: {y: scrollY, height}, actions, marker, page_key: pageKey, guards, omitted_actions: omitted,
    covered_actions: covered, below_fold: below, dialogs, frames, challenge, password_fields: passwords};
})
