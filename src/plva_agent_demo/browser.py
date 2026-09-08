"""Playwright (sync) browser control: navigate, snapshot (raw PNG + text spans + fields), act.

The raw screenshot and span text returned here are LOCAL ONLY. This module never logs page text.
"""

from __future__ import annotations

from types import TracebackType
from typing import Any, Final, Self
from urllib.parse import urlsplit

from playwright.sync_api import (
    Browser as PwBrowser,
)
from playwright.sync_api import (
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import (
    TimeoutError as PwTimeoutError,
)

from .types import Box, Field, Snapshot, TextSpan

VIEWPORT_W: Final = 1280
VIEWPORT_H: Final = 900
ALLOWED_SCHEMES: Final = frozenset({"http", "https", "file"})
SETTLE_TIMEOUT_MS: Final = 2000

# Runs in the page. Returns {spans, fields, focused_field_id, title, url, width, height}.
_EXTRACT_JS: Final = r"""
() => {
  const W = window.innerWidth, H = window.innerHeight;
  const clamp = (r) => {
    const x0 = Math.max(0, r.left), y0 = Math.max(0, r.top);
    const x1 = Math.min(W, r.right), y1 = Math.min(H, r.bottom);
    if (x1 - x0 <= 0 || y1 - y0 <= 0) return null;
    return { x: +x0.toFixed(2), y: +y0.toFixed(2), w: +(x1 - x0).toFixed(2), h: +(y1 - y0).toFixed(2) };
  };
  const visible = (el) => {
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
      if (e.hidden || e.getAttribute('aria-hidden') === 'true') return false;
    }
    return true;
  };
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'HEAD', 'TITLE', 'META', 'LINK']);

  // ---- fields -------------------------------------------------------------------------------
  const fieldEls = Array.from(document.querySelectorAll(
    'input, textarea, select, [contenteditable=""], [contenteditable="true"], [contenteditable="plaintext-only"]'));
  const NON_TEXT = new Set(['hidden', 'submit', 'button', 'reset', 'image', 'file', 'checkbox', 'radio', 'range', 'color']);
  const idOf = new Map();
  let auto = 0;
  const fields = [];
  const labelFor = (el) => {
    if (el.id) {
      const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (l && l.textContent.trim()) return l.textContent.trim();
    }
    const wrap = el.closest('label');
    if (wrap && wrap.textContent.trim()) return wrap.textContent.trim();
    const aria = el.getAttribute('aria-label');
    if (aria && aria.trim()) return aria.trim();
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const t = by.split(/\s+/).map(i => (document.getElementById(i) || {}).textContent || '').join(' ').trim();
      if (t) return t;
    }
    const ph = el.getAttribute('placeholder');
    if (ph && ph.trim()) return ph.trim();
    // Heuristic: nearest preceding <label> among siblings of the element or its ancestors.
    let node = el;
    for (let depth = 0; node && depth < 3; depth++) {
      for (let s = node.previousElementSibling; s; s = s.previousElementSibling) {
        if (s.tagName === 'LABEL' && s.textContent.trim()) return s.textContent.trim();
        const inner = s.querySelector && s.querySelector('label');
        if (inner && inner.textContent.trim()) return inner.textContent.trim();
      }
      node = node.parentElement;
    }
    return el.getAttribute('name') || el.id || '';
  };
  for (const el of fieldEls) {
    const tag = el.tagName.toLowerCase();
    let type = tag === 'input' ? (el.getAttribute('type') || 'text').toLowerCase() : tag;
    if (tag !== 'input' && tag !== 'textarea' && tag !== 'select') type = 'contenteditable';
    if (tag === 'input' && NON_TEXT.has(type)) continue;
    if (!visible(el)) continue;
    const box = clamp(el.getBoundingClientRect());
    const fid = el.id || el.getAttribute('name') || ('auto-' + (++auto));
    idOf.set(el, fid);
    if (!box) continue;
    fields.push({ field_id: fid, label: labelFor(el), box, input_type: type,
                  focused: document.activeElement === el });
  }
  const active = document.activeElement;
  const focused_field_id = active && idOf.has(active) ? idOf.get(active) : null;

  // ---- text spans ---------------------------------------------------------------------------
  const spans = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => {
      const p = n.parentElement;
      if (!p || SKIP.has(p.tagName)) return NodeFilter.FILTER_REJECT;
      if (!n.nodeValue || !n.nodeValue.trim()) return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    }
  });
  const norm = (s) => s.replace(/\s+/g, ' ').trim();
  let node;
  while ((node = walker.nextNode())) {
    if (!visible(node.parentElement)) continue;
    const range = document.createRange();
    range.selectNodeContents(node);
    const rects = Array.from(range.getClientRects()).filter(r => r.width > 0 && r.height > 0);
    if (rects.length === 0) continue;
    const text = node.nodeValue;
    if (rects.length === 1) {
      const box = clamp(rects[0]);
      if (box) spans.push({ text: norm(text), box });
      continue;
    }
    // Multi-rect (wrapped) node: group characters by their line rect.
    const lines = [];  // {top, bottom, left, right, chars: []}
    const cr = document.createRange();
    for (let i = 0; i < text.length; i++) {
      cr.setStart(node, i); cr.setEnd(node, i + 1);
      const r = cr.getBoundingClientRect();
      if (r.width === 0 && /\s/.test(text[i])) { if (lines.length) lines[lines.length - 1].chars.push(text[i]); continue; }
      if (r.height === 0) continue;
      const mid = r.top + r.height / 2;
      let line = lines.length ? lines[lines.length - 1] : null;
      if (!line || mid < line.top || mid > line.bottom) {
        line = { top: r.top, bottom: r.bottom, left: r.left, right: r.right, chars: [] };
        lines.push(line);
      }
      line.top = Math.min(line.top, r.top); line.bottom = Math.max(line.bottom, r.bottom);
      line.left = Math.min(line.left, r.left); line.right = Math.max(line.right, r.right);
      line.chars.push(text[i]);
    }
    for (const line of lines) {
      const t = norm(line.chars.join(''));
      if (!t) continue;
      const box = clamp({ left: line.left, top: line.top, right: line.right, bottom: line.bottom });
      if (box) spans.push({ text: t, box });
    }
  }
  // Input / textarea values as spans (password values included, on purpose: classified as PASSWORD).
  for (const el of fieldEls) {
    const tag = el.tagName.toLowerCase();
    if (tag !== 'input' && tag !== 'textarea') continue;
    if (!idOf.has(el)) continue;
    const value = el.value;
    if (!value || !value.trim()) continue;
    const box = clamp(el.getBoundingClientRect());
    if (!box) continue;
    const type = tag === 'input' ? (el.getAttribute('type') || 'text').toLowerCase() : 'textarea';
    spans.push({ text: norm(value), box, field_id: idOf.get(el), input_type: type });
  }
  return { spans, fields, focused_field_id, title: document.title || '', url: location.href, width: W, height: H };
}
"""


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme == "file":
        return "file://"
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    return f"{parts.scheme}://{host}{port}"


def _box(d: dict[str, Any]) -> Box:
    return Box(float(d["x"]), float(d["y"]), float(d["w"]), float(d["h"]))


class Browser:
    """Headless Chromium at 1280x900, DSF 1 (CSS px == screenshot px). Use as a context manager."""

    def __init__(self, headless: bool = True) -> None:
        self._headless = headless
        self._pw: Playwright | None = None
        self._browser: PwBrowser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    # -- lifecycle ------------------------------------------------------------------------------

    def __enter__(self) -> Self:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        self._context = self._browser.new_context(
            viewport={"width": VIEWPORT_W, "height": VIEWPORT_H},
            device_scale_factor=1,
            java_script_enabled=True,
        )
        self._page = self._context.new_page()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        for closer in (self._context, self._browser):
            try:
                if closer is not None:
                    closer.close()
            except Exception:  # noqa: BLE001 - best-effort teardown
                pass
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:  # noqa: BLE001
                pass
        self._pw = self._browser = self._context = self._page = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Browser is not started; use it as a context manager")
        return self._page

    # -- navigation -----------------------------------------------------------------------------

    def navigate(self, url: str) -> None:
        scheme = urlsplit(url).scheme.lower()
        if scheme not in ALLOWED_SCHEMES:
            raise ValueError(f"refusing to navigate to scheme {scheme or '(none)'!r}")
        self.page.goto(url, wait_until="load")
        self.wait_settled()

    def wait_settled(self) -> None:
        try:
            self.page.wait_for_load_state("networkidle", timeout=SETTLE_TIMEOUT_MS)
        except PwTimeoutError:
            pass

    # -- observation ----------------------------------------------------------------------------

    def snapshot(self) -> Snapshot:
        page = self.page
        data: dict[str, Any] = page.evaluate(_EXTRACT_JS)
        png = page.screenshot(type="png", full_page=False)
        spans = [
            TextSpan(
                text=s["text"],
                box=_box(s["box"]),
                field_id=s.get("field_id"),
                input_type=s.get("input_type"),
            )
            for s in data["spans"]
        ]
        fields = [
            Field(
                field_id=f["field_id"],
                label=f["label"],
                box=_box(f["box"]),
                input_type=f["input_type"],
                focused=bool(f["focused"]),
            )
            for f in data["fields"]
        ]
        url = data["url"] or page.url
        return Snapshot(
            url=url,
            origin=_origin_of(url),
            title=data["title"],
            width=int(data["width"]),
            height=int(data["height"]),
            png=png,
            spans=spans,
            fields=fields,
            focused_field_id=data.get("focused_field_id"),
        )

    # -- actions --------------------------------------------------------------------------------

    def click(self, x: float, y: float) -> None:
        self.page.mouse.click(x, y)

    def type_text(self, text: str) -> None:
        self.page.keyboard.type(text)

    def press(self, key: str) -> None:
        self.page.keyboard.press(key)

    def scroll(self, dy: int) -> None:
        self.page.mouse.wheel(0, dy)
        self._next_frames()

    def _next_frames(self) -> None:
        """Wheel scrolling is applied asynchronously; wait two animation frames so layout settles."""
        try:
            self.page.evaluate(
                "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
            )
        except Exception:  # noqa: BLE001 - page may be navigating; snapshot() re-reads anyway
            self.page.wait_for_timeout(50)


__all__ = ["ALLOWED_SCHEMES", "VIEWPORT_H", "VIEWPORT_W", "Browser"]
