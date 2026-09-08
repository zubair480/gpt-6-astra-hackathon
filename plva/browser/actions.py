"""Checked browser actions. Private values never leave this local executor."""
from __future__ import annotations

import asyncio
import math
import re

from plva.privacy import PrivacyError


# Metadata only: never read field values or page text as an observation channel.
_FIELD = """(el) => {
  const f = el && el.form;
  return {origin: location.origin, focused: el === document.activeElement,
    visible: document.visibilityState === 'visible',
    editable: !!el && el.tagName === 'INPUT' && ['text', 'email', 'tel'].includes(el.type) && !el.disabled && !el.readOnly,
    type: el?.type || '', autocomplete: el?.autocomplete || '',
    name: el?.name || '', id: el?.id || '', role: el?.getAttribute('role') || '',
    label: el?.getAttribute('aria-label') || '',
    search: !!el?.closest('[role="search"]'),
    formOrigin: f ? new URL(f.action || location.href, location.href).origin : '',
    formMethod: f ? f.method.toLowerCase() : ''};
}"""
_INSERT = """(el, arg) => {
  const inspect = INSPECT;
  if (!el?.isConnected || JSON.stringify(inspect(el)) !== JSON.stringify(arg.field))
    return false;
  const start = el.selectionStart ?? 0, end = el.selectionEnd ?? el.value.length;
  const next = el.value.slice(0, start) + arg.text + el.value.slice(end);
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  setter.call(el, next);
  try { el.setSelectionRange(start + arg.text.length, start + arg.text.length); } catch {}
  el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: arg.text}));
  return true;
}""".replace('INSPECT', _FIELD)
_AUTOCOMPLETE = {
    'email': 'EMAIL', 'tel': 'PHONE', 'tel-national': 'PHONE',
    'name': 'NAME', 'given-name': 'NAME', 'family-name': 'NAME',
    'additional-name': 'NAME', 'street-address': 'ADDRESS',
    'address-line1': 'ADDRESS', 'address-line2': 'ADDRESS', 'address-line3': 'ADDRESS',
}


def _destination(field, tokens, authorized):
    if field.get('origin') not in authorized:
        raise PrivacyError('Private token destination needs local site authorization')
    if not field.get('visible') or not field.get('focused') or not field.get('editable'):
        raise PrivacyError('Private token requires a focused editable contact field')
    identity = ' '.join(str(field.get(k, '')) for k in ('name', 'id', 'role', 'label')).lower()
    if (field.get('type') in {'search', 'url', 'password', 'hidden'}
            or field.get('search') or re.search(r'search|query|\bq\b|url|website', identity)
            or field.get('formMethod') == 'get'
            or field.get('formOrigin') not in ('', field['origin'])):
        raise PrivacyError('Private tokens cannot be used in this destination')
    autocomplete = str(field.get('autocomplete', '')).lower().split()
    permitted = _AUTOCOMPLETE.get(autocomplete[-1] if autocomplete else '')
    typed = {'email': 'EMAIL', 'tel': 'PHONE'}.get(field.get('type'))
    if typed and permitted and typed != permitted:
        raise PrivacyError('Ambiguous private token destination; choose the field locally')
    permitted = permitted or typed
    if not permitted or any(token[1:].rsplit('_', 1)[0] != permitted for token in tokens):
        raise PrivacyError('Private token field class needs local user choice')


def _number(action, key, default=None):
    value = action.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise PrivacyError('Invalid action coordinates')
    return value


async def execute_action(session, action, privacy):
    """Execute one action; return value-free evidence and a token-use count.

    Local open() authorizes an origin. Agent navigation cannot grant that right.
    Generic type/auto-complete semantics authorize contact tokens; unclear fields
    pause rather than resolving into a guessed destination.
    """
    session.check_cancelled()
    if not isinstance(action, dict):
        raise PrivacyError('Invalid browser action')
    kind = action.get('type')
    resolved = 0
    try:
        page = await session.active_page()
        session.check_cancelled()
        if kind not in ('navigate', 'open', 'goto', 'select_tab'):
            session.validate_url(page.url)
        if kind in ('navigate', 'open', 'goto'):
            url = action.get('url')
            if not isinstance(url, str) or privacy.TOKEN.search(url) or privacy.scrub(url) != url:
                raise PrivacyError('Private data cannot be used in navigation URLs')
            await session.navigate(url, authorize=False)
        elif kind in ('back', 'forward', 'reload'):
            await getattr(session, kind)()
        elif kind == 'select_tab':
            await session.select_tab(action.get('tab_id'))
        elif kind == 'type':
            text = action.get('text')
            if not isinstance(text, str):
                raise PrivacyError('Invalid typing action')
            tokens = privacy.TOKEN.findall(text)
            if tokens:
                if any(t.startswith('[SECRET_') for t in tokens):
                    raise PrivacyError('Blocked secret token cannot be used')
                handle = await page.evaluate_handle('document.activeElement')
                try:
                    field = await handle.evaluate(_FIELD)
                    _destination(field, tokens, session.authorized_origins)
                    if session.origin(page.url) != field['origin']:
                        raise PrivacyError('Private token destination changed')
                    session.check_cancelled()
                    local_text = privacy.resolve(text)
                    # Recheck focus, origin and all metadata in the same JS turn as insertion.
                    if not await handle.evaluate(_INSERT, {'field': field, 'text': local_text}):
                        raise PrivacyError('Private token destination changed; choose the field locally')
                    resolved = len(tokens)
                finally:
                    await handle.dispose()
            else:
                session.check_cancelled()
                await page.keyboard.insert_text(text)
        elif kind in ('keypress', 'key'):
            keys = action.get('keys', [])
            if isinstance(keys, str):
                keys = keys.split('+')
            if not keys or not all(isinstance(k, str) for k in keys):
                raise PrivacyError('Invalid key action')
            normalized = [k.upper() for k in keys]
            # Browser chrome, clipboard, JS consoles and page-save paths stay local-only.
            modifiers = {'CTRL', 'CONTROL', 'CMD', 'COMMAND', 'META', 'ALT', 'SUPER', 'WIN'}
            safe_edit = len(keys) == 2 and normalized[0] in {'CTRL', 'CONTROL', 'CMD', 'META'} and normalized[1] == 'A'
            allowed = {'ENTER', 'TAB', 'BACKSPACE', 'ESC', 'ESCAPE', 'SPACE', 'ARROWDOWN', 'ARROWUP', 'ARROWLEFT', 'ARROWRIGHT', 'DELETE', 'HOME', 'END', 'PAGEUP', 'PAGEDOWN', 'SHIFT'}
            if not safe_edit and (any(k in modifiers for k in normalized) or any(k not in allowed for k in normalized)):
                raise PrivacyError('Browser shortcut requires local user control')
            mapping = {'CTRL': 'Control', 'CONTROL': 'Control', 'CMD': 'Meta', 'META': 'Meta', 'ESC': 'Escape', **{k: k.title() for k in allowed}}
            mapping.update({k.upper(): k for k in ('ArrowDown', 'ArrowUp', 'ArrowLeft', 'ArrowRight', 'Backspace', 'PageUp', 'PageDown')})
            await page.keyboard.press('+'.join(mapping.get(k, k) for k in normalized))
        elif kind in ('click', 'double_click', 'move'):
            x, y = _number(action, 'x'), _number(action, 'y')
            if kind == 'move':
                await page.mouse.move(x, y)
            else:
                button = action.get('button', 'left')
                if button not in ('left', 'middle', 'right'):
                    raise PrivacyError('Invalid mouse button')
                await page.mouse.click(x, y, button=button, click_count=2 if kind == 'double_click' else 1)
        elif kind == 'scroll':
            await page.mouse.move(_number(action, 'x', 600), _number(action, 'y', 400))
            session.check_cancelled()
            await page.mouse.wheel(_number(action, 'scroll_x', 0), _number(action, 'scroll_y', 0))
        elif kind in ('wait', 'screenshot'):
            await asyncio.sleep(0.1)
        else:
            raise PrivacyError('Unsupported browser action')
        session.check_cancelled()
        return {'type': kind, 'status': 'executed', 'resolved': resolved, 'resolved_token_count': resolved}
    except (PrivacyError, InterruptedError):
        raise
    except Exception:
        # Playwright failures can quote entered text, DOM and private URLs.
        raise PrivacyError('Browser action failed; inspect the local browser') from None
