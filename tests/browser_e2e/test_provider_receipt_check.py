"""Mock-only validator regressions; these fixtures are NOT live API evidence."""
import base64
import hashlib
import io
import unittest

from PIL import Image

from tests.browser_e2e.evidence import EvidenceError
from tests.browser_e2e.provider_receipt_check import validate_provider_chain


def mock_record(number, color):
    buffer = io.BytesIO()
    Image.new('RGB', (8, 8), color).save(buffer, format='PNG')
    png = buffer.getvalue()
    encoded = base64.b64encode(png).decode()
    return {'status': 'responded', 'source': 'web', 'transmitted': True,
            'http_status': 200, 'request_id': f'mock-request-{number}',
            'response_id': f'mock-response-{number}', 'response_model': 'mock-model',
            'usage': {'total_tokens': 1}, 'image_base64': encoded,
            'frame_hash': hashlib.sha256(png).hexdigest(), 'response_output': [],
            'payload': {'model': 'gpt-6-astra', 'input': [{'role': 'user',
                'content': [{'type': 'input_image',
                             'image_url': 'data:image/png;base64,' + encoded}]}]}}


class MockProviderReceiptValidatorTests(unittest.TestCase):
    def setUp(self):
        self.oracle = ['verifier-only@example.com']
        self.root = mock_record(1, 'white')
        self.followup = mock_record(2, 'black')
        self.root['response_output'] = [{'type': 'computer_call',
            'call_id': 'mock-call', 'actions': [{'type': 'scroll'}]}]
        self.followup['payload']['previous_response_id'] = self.root['response_id']
        self.followup['payload']['input'].append({'type': 'computer_call_output',
            'call_id': 'mock-call', 'output': {'type': 'computer_screenshot',
            'image_url': 'data:image/png;base64,' + self.followup['image_base64']}})
        self.entries = [self.root, self.followup]

    def check_rejected(self, message):
        with self.assertRaisesRegex(EvidenceError, message):
            validate_provider_chain(self.entries, self.oracle)

    def test_mock_consistent_chain_reports_proposal_not_execution(self):
        result = validate_provider_chain(self.entries, self.oracle)
        self.assertEqual(result['responded_requests'], 2)
        self.assertEqual(result['distinct_frames'], 2)
        self.assertEqual(result['linked_followups'][0]['proposed_actions'], ['scroll'])
        self.assertTrue(result['linked_followups'][0]['frame_changed'])
        self.assertIn('requires', result['authenticity'])
        self.assertIn('requires', result['pixel_masking'])
        self.assertIn('requires', result['executed_transitions'])

    def test_rejects_missing_history_root(self):
        self.root['payload']['previous_response_id'] = 'unseen-response'
        self.check_rejected('Missing initial request')

    def test_rejects_wrong_tool_call_id(self):
        self.followup['payload']['input'][-1]['call_id'] = 'wrong-call'
        self.check_rejected('do not exactly match')

    def test_rejects_unverified_older_image_alongside_current_image(self):
        self.followup['payload']['input'][0]['content'][0]['image_url'] = (
            'data:image/png;base64,' + self.root['image_base64'])
        self.check_rejected('Additional outbound image')

    def test_rejects_raw_nested_outbound_text(self):
        self.followup['payload']['instructions'] = self.oracle[0]
        self.check_rejected('Raw synthetic value')

    def test_rejects_missing_root_usage(self):
        self.root['usage'] = {}
        self.check_rejected('Missing provider token usage')

    def test_rejects_wrong_requested_root_model(self):
        self.root['payload']['model'] = 'unexpected-model'
        self.check_rejected('Unexpected requested provider model')

    def test_rejects_missing_returned_root_model(self):
        self.root['response_model'] = ''
        self.check_rejected('Missing returned provider model')


if __name__ == '__main__':
    unittest.main()
