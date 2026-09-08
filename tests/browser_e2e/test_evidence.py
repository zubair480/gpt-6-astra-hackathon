"""Adversarial tests of the evidence checker, using explicitly mocked receipts."""
import base64
import copy
import hashlib
import io
import unittest

from PIL import Image

try:
    from .evidence import EvidenceError, validate_audit
except ImportError:  # unittest discover -s tests/browser_e2e
    from evidence import EvidenceError, validate_audit


def record(index):
    out = io.BytesIO()
    Image.new('RGB', (20, 20), ('navy', 'teal')[index]).save(out, 'PNG')
    png = out.getvalue()
    encoded = base64.b64encode(png).decode()
    return dict(status='responded', request_id=f'local-{index}',
                response_id=f'MOCK-response-{index}', response_model='MOCK-model',
                usage={'input_tokens': 1, 'output_tokens': 1},
                frame_hash=hashlib.sha256(png).hexdigest(), image_base64=encoded,
                payload={'input': [{'image_url': 'data:image/png;base64,' + encoded,
                                    'text': '[EMAIL_1]'}]})


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.entries = [record(0), record(1)]
        self.values = ['unseen-test-91827@example.test']

    def test_consistent_mock_records_only_prove_validator_behavior(self):
        self.assertEqual(validate_audit(self.entries, self.values),
                         {'responded_requests': 2, 'distinct_frames': 2})

    def test_rejects_missing_receipt_fields(self):
        for field in ('request_id', 'response_id', 'response_model', 'usage', 'payload'):
            with self.subTest(field=field):
                entries = copy.deepcopy(self.entries)
                del entries[0][field]
                with self.assertRaises(EvidenceError):
                    validate_audit(entries, self.values)

    def test_rejects_private_text_in_every_export_channel(self):
        for field in ('title', 'url', 'error', 'actions', 'manifest', 'payload'):
            with self.subTest(field=field):
                entries = copy.deepcopy(self.entries)
                entries[0][field] = {'nested': [self.values[0]]}
                with self.assertRaises(EvidenceError):
                    validate_audit(entries, self.values)

    def test_rejects_wrong_hash_and_stale_frame(self):
        self.entries[0]['frame_hash'] = 'bad'
        with self.assertRaises(EvidenceError):
            validate_audit(self.entries, self.values)
        self.entries = [record(0), record(0)]
        self.entries[1]['request_id'] = 'different-request'
        with self.assertRaises(EvidenceError):
            validate_audit(self.entries, self.values)

    def test_rejects_preview_as_provider_evidence(self):
        self.entries[0]['status'] = 'prepared'
        with self.assertRaises(EvidenceError):
            validate_audit(self.entries, self.values)

    def test_rejects_mismatched_sent_image(self):
        self.entries[0]['image_base64'] = self.entries[1]['image_base64']
        with self.assertRaises(EvidenceError):
            validate_audit(self.entries, self.values)
