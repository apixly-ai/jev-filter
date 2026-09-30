"""Observation coverage of the page script on real public web pages (2026-09-30 audit).

Observe-only: no clicks, no typing, no Jev calls, no credentials. For each URL the real
CDPPage.observe runs; then an independent in-page oracle lists what a person could click in
the viewport (native and ARIA widgets, tabindex>=0, onclick, outermost cursor:pointer elements
that pass a hit test) and checks which of those the observation covered.

    python -m benchmarks.real_world_coverage OUT.json [--sites a,b] [--workers 4]

Results depend on network, region, browser language and the sites' bot checks. The published
summary is benchmarks/results/2026-09-30-real-world.json.
"""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from jev_context.act.browser import CDPPage

SITES = [
    # (key, category, url)
    ("bing", "search", "https://www.bing.com/"),
    ("duckduckgo", "search", "https://duckduckgo.com/"),
    ("baidu", "search-cn", "https://www.baidu.com/"),
    ("wikipedia", "reference", "https://en.wikipedia.org/wiki/Alan_Turing"),
    (
        "mdn",
        "docs",
        "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array/map",
    ),
    ("pydocs", "docs", "https://docs.python.org/3/tutorial/datastructures.html"),
    ("runoob", "docs-cn", "https://www.runoob.com/"),
    ("github", "dev-spa", "https://github.com/apixly-ai/jev-filter"),
    ("stackoverflow", "dev", "https://stackoverflow.com/questions"),
    ("hackernews", "dev", "https://news.ycombinator.com/"),
    ("npm", "dev-spa", "https://www.npmjs.com/package/react"),
    ("pypi", "dev", "https://pypi.org/project/requests/"),
    ("amazon", "shop", "https://www.amazon.com/"),
    ("ebay", "shop", "https://www.ebay.com/"),
    ("jd", "shop-cn", "https://www.jd.com/"),
    ("ikea", "shop", "https://www.ikea.com/us/en/"),
    ("booking", "travel-forms", "https://www.booking.com/"),
    ("airbnb", "travel-forms", "https://www.airbnb.com/"),
    ("ctrip", "travel-cn", "https://www.ctrip.com/"),
    ("youtube", "media-spa", "https://www.youtube.com/"),
    ("bilibili", "media-cn", "https://www.bilibili.com/"),
    ("reddit", "social", "https://www.reddit.com/"),
    ("zhihu", "social-cn", "https://www.zhihu.com/"),
    ("bbc", "news", "https://www.bbc.com/news"),
    ("netease", "news-cn", "https://www.163.com/"),
    ("gmaps", "canvas-app", "https://www.google.com/maps"),
    ("excalidraw", "canvas-app", "https://excalidraw.com/"),
    ("codepen", "editor", "https://codepen.io/pen/"),
    ("usagov", "gov", "https://www.usa.gov/"),
    ("govcn", "gov-cn", "https://www.gov.cn/"),
    ("elementplus", "ui-kit-vue", "https://element-plus.org/en-US/component/select.html"),
    ("antd", "ui-kit-react", "https://ant.design/components/select"),
    ("mui", "ui-kit-react", "https://mui.com/material-ui/react-checkbox/"),
    ("bootstrap", "ui-kit", "https://getbootstrap.com/docs/5.3/forms/checks-radios/"),
    ("shadcn", "ui-kit-react", "https://ui.shadcn.com/docs/components/select"),
    ("chakra", "ui-kit-react", "https://www.chakra-ui.com/docs/components/slider"),
    ("vuetify", "ui-kit-vue", "https://vuetifyjs.com/en/components/date-pickers/"),
    ("w3forms", "forms", "https://www.w3schools.com/html/html_forms.asp"),
    ("figma", "marketing-spa", "https://www.figma.com/"),
    ("notion", "marketing-spa", "https://www.notion.com/"),
]

ORACLE = r"""
((observedIds, pageLimit) => {
  const cache = window.__jevFilterAct;
  const observed = observedIds.map(id => cache && cache.nodes.get(id)).filter(Boolean);
  const roots = [], crossFrames = [];
  const addRoot = (root, depth) => {
    if (depth > 6) return;
    roots.push(root);
    for (const h of root.querySelectorAll('*')) if (h.shadowRoot) addRoot(h.shadowRoot, depth + 1);
    for (const f of root.querySelectorAll('iframe,frame')) {
      let d = null; try { d = f.contentDocument; } catch (_) { d = null; }
      if (d && d.documentElement) addRoot(d, depth + 1); else crossFrames.push(f);
    }
  };
  addRoot(document, 0);
  const W = innerWidth, H = innerHeight;
  const frameOffset = e => {
    let x = 0, y = 0, w = e.ownerDocument.defaultView;
    while (w && w !== window && w.frameElement) {
      const f = w.frameElement, r = f.getBoundingClientRect();
      x += r.left + f.clientLeft; y += r.top + f.clientTop; w = f.ownerDocument.defaultView;
    }
    return [x, y];
  };
  const rectOf = e => { const r = e.getBoundingClientRect(), [dx, dy] = frameOffset(e); return {x: r.x + dx, y: r.y + dy, w: r.width, h: r.height}; };
  const deepHit = (x, y) => {
    let doc = document, ox = 0, oy = 0, el = null;
    for (let depth = 0; depth < 8; depth++) {
      el = doc.elementFromPoint(x - ox, y - oy);
      while (el && el.shadowRoot) { const inner = el.shadowRoot.elementFromPoint(x - ox, y - oy); if (!inner || inner === el) break; el = inner; }
      if (el && el.tagName === 'IFRAME') {
        let inner = null; try { inner = el.contentDocument; } catch (_) { inner = null; }
        if (!inner) return el;
        const r = el.getBoundingClientRect(); ox += r.left + el.clientLeft; oy += r.top + el.clientTop; doc = inner; continue;
      }
      return el;
    }
    return el;
  };
  const within = (outer, inner) => { for (let n = inner; n; n = n.parentNode || n.host || null) if (n === outer) return true; return false; };
  const vis = e => {
    if (e.closest && e.closest('[aria-hidden="true"],[inert]')) return false;
    return e.checkVisibility ? e.checkVisibility({checkVisibilityCSS: true}) : true;
  };
  const WIDGET = new Set(['button','link','checkbox','radio','switch','tab','menuitem','menuitemradio','menuitemcheckbox',
    'option','treeitem','gridcell','combobox','textbox','searchbox','spinbutton','slider']);
  const LISTED = new Set(['button','link','checkbox','radio','switch','tab','menuitem','menuitemradio','menuitemcheckbox',
    'option','treeitem','gridcell','combobox','textbox','searchbox','spinbutton']);
  const nativeSel = 'a[href],button,input,select,textarea,summary,[contenteditable="true"],[contenteditable=""]';
  const isNative = e => e.matches(nativeSel) || WIDGET.has(e.getAttribute('role'));
  const cursorOf = e => { try { return getComputedStyle(e).cursor; } catch (_) { return ''; } };
  const all = roots.flatMap(r => [...r.querySelectorAll('*')]);
  const cands = new Map();
  const add = (e, type) => { if (!cands.has(e)) cands.set(e, type); };
  for (const e of all) {
    if (e.nodeType !== 1) continue;
    if (isNative(e)) { add(e, 'native'); continue; }
    const tab = e.getAttribute('tabindex');
    if (tab !== null && +tab >= 0 && !['BODY','HTML','MAIN','SECTION','ARTICLE','DIALOG'].includes(e.tagName) && !e.getAttribute('role')?.match(/^(dialog|region|main|document|application|grid|list|listbox|tablist|menu|menubar|tree|tabpanel|group|toolbar|presentation|none)$/)) { add(e, 'tabindex'); continue; }
    if (e.hasAttribute('onclick')) { add(e, 'onclick'); continue; }
  }
  // Outermost pointer-cursor elements that do not wrap a native control.
  for (const e of all) {
    if (e.nodeType !== 1 || cands.has(e)) continue;
    if (cursorOf(e) !== 'pointer') continue;
    const p = e.parentElement || (e.getRootNode && e.getRootNode().host);
    if (p && cursorOf(p) === 'pointer') continue;
    if (e.querySelector(nativeSel + ',[role]')) continue;
    add(e, 'pointer');
  }
  const covered = e => observed.some(o => o === e || within(e, o) || within(o, e) ||
    (e.tagName === 'LABEL' && e.control === o));
  const disabled = e => e.matches(':disabled') || !!e.closest('[aria-disabled="true"]');
  const stats = {candidates: 0, covered: 0, occluded: 0, offscreen: 0, hidden: 0, disabled: 0, by_design: 0};
  const misses = {}, examples = [];
  const reason = (e, type) => {
    const tag = e.tagName.toLowerCase(), role = e.getAttribute('role');
    if (tag === 'input' && ['range','color'].includes(e.type)) return 'input_' + e.type;
    if (role && !LISTED.has(role) && WIDGET.has(role)) return 'role_' + role;
    if (tag === 'input' || tag === 'select' || tag === 'textarea' || tag === 'button' || tag === 'a' || role) {
      const s = getComputedStyle(e); if (+s.opacity === 0) return 'transparent_native';
      return 'native_other';
    }
    if (tag === 'label') return 'label_custom_control';
    if (type === 'tabindex') return 'tabindex_no_role';
    if (type === 'onclick') return 'onclick_no_role';
    return 'pointer_no_role';
  };
  for (const [e, type] of cands) {
    if (e.tagName === 'INPUT' && ['hidden','password','file'].includes(e.type)) { stats.by_design++; continue; }
    if (!vis(e)) { stats.hidden++; continue; }
    const r = rectOf(e);
    if (r.w < 4 || r.h < 4) { stats.hidden++; continue; }
    const cx = r.x + r.w / 2, cy = r.y + r.h / 2;
    if (cx < 0 || cy < 0 || cx >= W || cy >= H) { stats.offscreen++; continue; }
    if (disabled(e)) { stats.disabled++; continue; }
    const hit = deepHit(cx, cy);
    if (!hit || !(within(e, hit) || (e.tagName === 'INPUT' && hit.tagName === 'LABEL' && hit.control === e))) { stats.occluded++; continue; }
    stats.candidates++;
    if (covered(e)) { stats.covered++; continue; }
    const why = reason(e, type);
    misses[why] = (misses[why] || 0) + 1;
    if (examples.filter(x => x.why === why).length < 4) examples.push({why, tag: e.tagName.toLowerCase(),
      role: e.getAttribute('role') || '', type: e.type || '', cls: String(e.className && e.className.baseVal !== undefined ? e.className.baseVal : e.className).slice(0, 60),
      text: ((e.innerText || e.getAttribute('aria-label') || e.getAttribute('title') || e.value || '') + '').replace(/\s+/g, ' ').trim().slice(0, 60)});
  }
  const area = els => els.filter(vis).map(rectOf).reduce((s, r) => {
    const w = Math.max(0, Math.min(r.x + r.w, W) - Math.max(r.x, 0)), h = Math.max(0, Math.min(r.y + r.h, H) - Math.max(r.y, 0));
    return s + w * h; }, 0) / (W * H);
  const canvases = roots.flatMap(r => [...r.querySelectorAll('canvas')]);
  return {stats, misses, examples, canvas_pct: Math.round(Math.min(1, area(canvases)) * 100),
    cross_frame_pct: Math.round(Math.min(1, area(crossFrames)) * 100), cross_frames: crossFrames.length,
    total_elements: all.length};
})
"""


def probe(key, category, url, settle=3.0):
    out = {"key": key, "category": category, "url": url}
    page = None
    started = time.perf_counter()
    try:
        page = CDPPage(url=url, headless=True, viewport=(1280, 900))
        time.sleep(settle)
        t = time.perf_counter()
        state = page.observe(limit=1000)
        out["observe_ms"] = round((time.perf_counter() - t) * 1000)
        actions = [a for a in state["actions"] if "node" in a]
        nodes = sorted({a["node"] for a in actions})
        labels = {}
        for a in actions:
            labels.setdefault(a["node"], (a.get("role"), a.get("label")))
        unlabeled = sum(1 for role, label in labels.values() if not label or label == role)
        oracle = page.evaluate(f"({ORACLE})({json.dumps(nodes)}, 250)")
        out.update(
            final_url=state.get("url"),
            title=(state.get("title") or "")[:80],
            challenge=state.get("challenge"),
            password_fields=state.get("password_fields"),
            dialogs=state.get("dialogs"),
            actions=len(actions),
            controls=len(nodes),
            over_default_cap=max(0, len(actions) - 250),
            unlabeled=unlabeled,
            text_chars=len(state.get("text") or ""),
            state_bytes=len(json.dumps(state["actions"], ensure_ascii=False).encode()),
            frames=state.get("frames"),
            **oracle,
        )
        s = oracle["stats"]
        out["recall"] = round(s["covered"] / s["candidates"], 3) if s["candidates"] else None
        out["ok"] = True
    except Exception as error:  # a site that fails to load is itself a data point
        out.update(ok=False, error=f"{type(error).__name__}: {str(error)[:200]}")
    finally:
        out["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
        if page is not None:
            try:
                page.close(close_browser=True)
            except Exception:
                pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("output")
    ap.add_argument("--sites", default="")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()
    chosen = [s for s in SITES if not args.sites or s[0] in args.sites.split(",")]
    rows = []
    with ThreadPoolExecutor(args.workers) as pool:
        futures = {pool.submit(probe, *s): s for s in chosen}
        for f in as_completed(futures):
            row = f.result()
            rows.append(row)
            if row.get("ok"):
                print(
                    f"{row['key']:12} recall={row['recall']} cand={row['stats']['candidates']} "
                    f"misses={row['misses']} canvas={row['canvas_pct']}% ms={row['observe_ms']}",
                    flush=True,
                )
            else:
                print(f"{row['key']:12} FAILED {row['error']}", flush=True)
    rows.sort(key=lambda r: r["key"])
    json.dump(
        {"generated": time.strftime("%Y-%m-%dT%H:%M:%S"), "rows": rows},
        open(args.output, "w", encoding="utf-8"),
        ensure_ascii=False,
        indent=1,
    )


if __name__ == "__main__":
    main()
