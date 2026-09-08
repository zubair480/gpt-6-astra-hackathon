"""Validate an operator-local audit export; never treat receipts as pixel proof.

The caller supplies independently generated synthetic values, kept out of reports.
This checks evidence consistency, not authenticity of a provider response ID.
"""
import base64
import hashlib
import io

from PIL import Image


class EvidenceError(AssertionError):
    pass


def require(condition, message):
    if not condition:
        raise EvidenceError(message)


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


def validate_audit(entries, private_values, minimum_frames=2):
    """Require responded records, sanitized text, PNG/hash agreement, fresh frames.

    Input uses BROWSER-CONTRACTS audit fields plus existing payload/image_base64.
    Failure injection and pixel masking require separate tests. A mocked receipt
    can pass this structural validator and must never be labeled live evidence.
    """
    require(bool(private_values), "Independent private-value oracle is required")
    sent = [e for e in entries if e.get('status') in ('sent', 'responded')]
    require(len(sent) >= minimum_frames, "Insufficient sent observations")
    hashes, request_ids = set(), set()
    for entry in entries:
        # Audit fields are exportable: inspect metadata/actions/errors as well.
        for text in strings(entry):
            if text.startswith('data:image/') or text == entry.get('image_base64'):
                continue
            require(not any(value in text for value in private_values),
                    "Raw synthetic value found in exported text")
        if entry not in sent:
            continue
        require(entry.get('status') == 'responded', "Missing successful provider response")
        require(bool(entry.get('request_id')), "Missing local request identity")
        require(entry['request_id'] not in request_ids, "Duplicate request identity")
        request_ids.add(entry['request_id'])
        require(bool(entry.get('response_id')), "Missing provider response ID")
        require(bool(entry.get('response_model')), "Missing returned provider model")
        require(isinstance(entry.get('usage'), dict) and bool(entry['usage']),
                "Missing provider token usage")
        payload = entry.get('payload')
        require(isinstance(payload, dict), "Missing actual outbound payload")
        images = [s for s in strings(payload) if s.startswith('data:image/')]
        require(bool(images), "Payload has no protected image")
        require(bool(entry.get('image_base64')), "Missing sent image")
        current = 'data:image/png;base64,' + entry['image_base64']
        require(current in images, "Displayed sent image differs from payload")
        for encoded in images:
            require(encoded.startswith('data:image/png;base64,'), "Unexpected image encoding")
            try:
                png = base64.b64decode(encoded.split(',', 1)[1], validate=True)
                with Image.open(io.BytesIO(png)) as frame:
                    require(frame.format == 'PNG', "Payload is not PNG")
                    frame.verify()
            except Exception:
                raise EvidenceError('Invalid outbound PNG') from None
            digest = hashlib.sha256(png).hexdigest()
            if encoded == current:
                require(digest == entry.get('frame_hash'), "Sent frame hash mismatch")
                hashes.add(digest)
    require(len(hashes) >= minimum_frames, "Fresh follow-up images were not demonstrated")
    return {'responded_requests': len(sent), 'distinct_frames': len(hashes)}
