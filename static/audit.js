/* Request evidence is supplied by the local runtime, never inferred from previews. */
(() => {
  'use strict';
  const panel = document.getElementById('audit');
  const body = document.getElementById('audit-body');
  if (!panel || !body) return;
  let busy = false;
  let lastLoad = 0;
  let lastContent = null;
  let lastError = '';

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function png(value) {
    if (typeof value !== 'string' || !value) return null;
    if (/^data:image\/png;base64,[A-Za-z0-9+/=\s]+$/.test(value)) return value;
    if (/^[A-Za-z0-9+/=\s]+$/.test(value)) return `data:image/png;base64,${value}`;
    return null;
  }

  function protectedImages(request) {
    const images = [];
    const add = value => { const src = png(value); if (src && !images.includes(src)) images.push(src); };
    // Retained protected frames can also occur in the actual provider payload.
    function visit(value) {
      if (!value || typeof value !== 'object') return;
      if (value.type === 'input_image' || value.type === 'computer_screenshot') add(value.image_url);
      for (const child of Object.values(value)) if (child && typeof child === 'object') visit(child);
    }
    visit(request.payload);
    return {submitted: images, recorded: png(request.image_base64)};
  }

  function classification(request) {
    if (request.mode === 'rehearsal' || request.payload?.rehearsal === true) {
      return {label: 'Fixture rehearsal · no model call', sent: false};
    }
    switch (request.status) {
      case 'prepared': return {label: 'Prepared locally · not sent', sent: false};
      case 'sent': return {label: 'Sent · awaiting provider response', sent: true};
      case 'responded': return {label: request.response_id ? 'Responded · provider receipt recorded' : 'Responded status · provider receipt missing', sent: true};
      case 'failed': return {label: 'Failed · inspect the recorded error', sent: request.transmitted === true};
      default: return {label: 'Legacy record · transmission and provider receipt unverified', sent: false};
    }
  }

  function render(requests) {
    const fragment = document.createDocumentFragment();
    if (!requests.length) fragment.append(element('p', 'No request evidence recorded. Local previews do not make a cloud request.', 'quiet'));
    for (const request of requests.slice().reverse()) {
      const state = classification(request);
      const wrapper = element('section', undefined, 'audit-request');
      wrapper.append(element('h3', `Step ${request.step ?? '—'} · ${state.label}`));
      const facts = element('dl', undefined, 'audit-facts');
      const field = (label, value) => {
        facts.append(element('dt', label), element('dd', value === undefined || value === null || value === '' ? 'Not recorded' : String(value)));
      };
      field('Request ID', request.request_id);
      field('Frame hash', request.frame_hash);
      field('Provider response ID', request.response_id);
      field('Returned model', request.response_model);
      field('Source', request.source ?? (request.mode === 'rehearsal' ? 'fixture' : undefined));
      field('HTTP status', request.http_status);
      field('Masked regions', Array.isArray(request.manifest) ? request.manifest.length : request.masks);
      field('Processing time (ms)', request.processing_ms ?? request.latency_ms ?? request.detector?.latency_ms ?? request.timings?.total_ms);
      wrapper.append(facts);
      if (!request.response_id) wrapper.append(element('p', 'No provider response ID recorded. This entry does not verify a completed real model call.', 'quiet'));
      if (request.error) wrapper.append(element('p', String(request.error), 'audit-error'));
      const frames = protectedImages(request);
      const hasPayloadFrames = frames.submitted.length > 0;
      const images = hasPayloadFrames ? frames.submitted : (frames.recorded ? [frames.recorded] : []);
      const verifiedSubmission = state.sent && hasPayloadFrames;
      wrapper.append(element('h4', verifiedSubmission ? 'Exact protected frames in the submitted payload' : 'Recorded protected frames · submission not verified'));
      if (frames.recorded && hasPayloadFrames && !frames.submitted.includes(frames.recorded)) {
        wrapper.append(element('p', 'Evidence mismatch: the separately recorded frame differs from every payload image. Images below come from the payload; the recorded frame hash does not verify these images.', 'audit-error'));
      } else if (frames.recorded && hasPayloadFrames) {
        wrapper.append(element('p', 'Recorded frame matches a payload image. Frame hash above is supplied by the runtime.', 'quiet'));
      }
      if (!hasPayloadFrames && images.length) wrapper.append(element('p', 'Only a separately recorded image is available; no matching image was found in the request payload.', 'quiet'));
      if (!images.length) wrapper.append(element('p', 'Protected request image was not recorded. The latest preview is not a substitute for request evidence.', 'quiet'));
      images.forEach((src, index) => {
        const image = element('img');
        image.src = src;
        image.alt = `${verifiedSubmission ? 'Submitted' : 'Recorded'} protected request frame ${index + 1}`;
        image.loading = 'lazy';
        wrapper.append(image);
      });
      const details = element('details');
      details.append(element('summary', 'Protected payload, usage, masks and original provider actions'));
      const evidence = {
        status: request.status ?? 'unverified_legacy',
        transmitted: request.transmitted ?? null,
        error_kind: request.error_kind ?? null,
        usage: request.usage ?? null,
        actions: request.actions ?? null,
        manifest: request.manifest ?? null,
        timings: request.timings ?? null,
        text: request.text ?? null,
        payload: request.payload ?? null
      };
      details.append(element('pre', JSON.stringify(evidence, (key, value) => {
        if (key === 'image_base64' || (key === 'image_url' && typeof value === 'string' && value.startsWith('data:image/'))) return '[protected frame displayed above]';
        return value;
      }, 2)));
      wrapper.append(details);
      fragment.append(wrapper);
    }
    body.replaceChildren(fragment);
  }

  async function load(force = false) {
    if (!panel.open || busy || (!force && Date.now() - lastLoad < 1000)) return;
    busy = true;
    lastLoad = Date.now();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch('/api/audit', {cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw new Error('Request evidence is unavailable.');
      const data = await response.json();
      if (!Array.isArray(data.requests)) throw new Error('Request evidence has an unsupported format.');
      const requests = data.requests.filter(item => item && typeof item === 'object');
      const content = JSON.stringify(requests);
      if (content !== lastContent || lastError) render(requests);
      lastContent = content;
      lastError = '';
    } catch (error) {
      lastError = error.name === 'AbortError' ? 'Request evidence timed out. Retrying while the inspector is open.' : error.message;
      body.replaceChildren(element('p', lastError, 'quiet'));
    } finally {
      clearTimeout(timeout);
      busy = false;
    }
  }

  panel.addEventListener('toggle', () => { if (panel.open) void load(true); });
  // Receipts can change without a new observation step, including after stop.
  setInterval(() => { if (panel.open) void load(); }, 1200);
  window.PLVA_AUDIT = Object.freeze({refresh: () => { if (panel.open) void load(); }});
})();
