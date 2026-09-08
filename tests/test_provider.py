import base64
import hashlib
import io
import json
import unittest

import httpx
from PIL import Image

from plva.provider import AstraProvider, ProviderError


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        buffer = io.BytesIO()
        Image.new("RGB", (80, 40), "black").save(buffer, "PNG")
        self.png = buffer.getvalue()
        self.frame = base64.b64encode(self.png).decode()
        self.key = "unit-test-private-api-key"
        self.kwargs = dict(task="Use alice@example.test", image_base64=self.frame,
                           manifest=[dict(token="[EMAIL_1]", kind="EMAIL", label="alice@example.test",
                                          value="should-never-leave-the-vault")],
                           scrub=lambda text: text.replace("alice@example.test", "[EMAIL_1]"))

    async def test_exact_payload_and_real_receipt_fields(self):
        captured = []

        def handler(request):
            captured.append(json.loads(request.content))
            self.assertEqual(request.headers["Authorization"], "Bearer " + self.key)
            return httpx.Response(200, json={"id": "resp_test_1", "model": "gpt-6-astra",
                "usage": {"input_tokens": 123, "output_tokens": 17}, "output": [
                    {"type": "computer_call", "call_id": "call_1", "actions": [
                        {"type": "type", "text": "alice@example.test"}]}]})

        provider = AstraProvider(self.key, transport=httpx.MockTransport(handler))
        _, audit = await provider.respond(**self.kwargs)
        self.assertEqual(audit["payload"], captured[0])
        self.assertEqual(audit["response_id"], "resp_test_1")
        self.assertEqual(audit["response_model"], "gpt-6-astra")
        self.assertEqual(audit["usage"]["input_tokens"], 123)
        self.assertEqual(audit["frame_hash"], hashlib.sha256(self.png).hexdigest())
        self.assertEqual(audit["actions"][0]["text"], "[EMAIL_1]")
        self.assertEqual(audit["status"], "responded")
        self.assertTrue(audit["request_id"])
        for secret in ("alice@example.test", "should-never-leave-the-vault", self.key):
            self.assertNotIn(secret, json.dumps(audit))

    async def test_followup_rebuilds_image_and_scrubs_task_every_time(self):
        captured = []

        def handler(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "resp_2", "model": "gpt-6-astra", "output": []})

        provider = AstraProvider(self.key, transport=httpx.MockTransport(handler))
        self.kwargs["task"] += " " + self.key
        _, audit = await provider.respond(**self.kwargs, previous_response_id="resp_1",
            call_outputs=[{"call_id": "call_1", "output": {"image_url": "RAW_IMAGE"},
                           "unsafe_extra": "alice@example.test"}])
        payload = captured[0]
        self.assertEqual(payload["previous_response_id"], "resp_1")
        self.assertEqual(payload["input"][0]["output"]["image_url"],
                         "data:image/png;base64," + self.frame)
        self.assertIn("[EMAIL_1]", payload["input"][1]["content"][0]["text"])
        for secret in ("RAW_IMAGE", "alice@example.test", self.key):
            self.assertNotIn(secret, json.dumps(audit))

    async def test_http_and_network_failures_never_echo_secrets(self):
        def forbidden(request):
            return httpx.Response(401, text=self.key + " alice@example.test")

        def offline(request):
            raise httpx.ConnectError(self.key + " alice@example.test", request=request)

        for handler, status in ((forbidden, "api_error"), (offline, "network_error")):
            with self.subTest(status=status):
                provider = AstraProvider(self.key, transport=httpx.MockTransport(handler))
                with self.assertRaises(ProviderError) as caught:
                    await provider.respond(**self.kwargs)
                self.assertEqual(caught.exception.audit["status"], "failed")
                self.assertEqual(caught.exception.audit["error_kind"], status)
                self.assertTrue(caught.exception.audit["request_id"])
                text = str(caught.exception) + json.dumps(caught.exception.audit)
                self.assertNotIn(self.key, text)
                self.assertNotIn("alice@example.test", text)

    async def test_function_and_mixed_followups_keep_protected_observation(self):
        captured = []

        def handler(request):
            captured.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "resp_nav", "model": "gpt-6-astra", "output": [
                {"type": "function_call", "call_id": "nav_next", "name": "navigate_browser",
                 "arguments": '{"url":"https://example.test/?email=alice@example.test"}'}]})

        provider = AstraProvider(self.key, transport=httpx.MockTransport(handler))
        for mixed in (False, True):
            with self.subTest(mixed=mixed):
                outputs = [{"type": "function_call_output", "call_id": "nav_1",
                            "output": "Opened page for alice@example.test", "raw_extra": self.key}]
                if mixed:
                    outputs.append({"type": "computer_call_output", "call_id": "computer_1",
                                    "output": {"image_url": "UNPROTECTED_IMAGE"}})
                _, audit = await provider.respond(**self.kwargs, previous_response_id="resp_previous",
                                                   call_outputs=outputs)
                payload = captured[-1]
                self.assertEqual(payload["tools"][1]["name"], "navigate_browser")
                self.assertEqual(audit["payload"], payload)
                self.assertEqual(payload["input"][0]["type"], "function_call_output")
                self.assertEqual(payload["input"][0]["call_id"], "nav_1")
                # Follow-up user messages must stay text-only with the computer tool.
                self.assertEqual([part["type"] for part in payload["input"][-1]["content"]], ["input_text"])
                if mixed:
                    self.assertEqual(payload["input"][0]["output"], "Opened page for [EMAIL_1]")
                    image = payload["input"][1]["output"]["image_url"]
                else:
                    function_output = payload["input"][0]["output"]
                    self.assertEqual(function_output[0], {"type": "input_text", "text": "Opened page for [EMAIL_1]"})
                    self.assertEqual(function_output[1]["type"], "input_image")
                    image = function_output[1]["image_url"]
                self.assertEqual(image, "data:image/png;base64," + self.frame)
                self.assertEqual(audit["actions"][0]["name"], "navigate_browser")
                self.assertIn("[EMAIL_1]", audit["actions"][0]["arguments"])
                for secret in (self.key, "alice@example.test", "UNPROTECTED_IMAGE"):
                    self.assertNotIn(secret, json.dumps(audit))

    async def test_missing_protected_image_blocks_before_network(self):
        def must_not_send(request):
            self.fail("Invalid observations must not reach the API")

        provider = AstraProvider(self.key, transport=httpx.MockTransport(must_not_send))
        for frame in ("not base64", base64.b64encode(b"not a png").decode()):
            with self.subTest(frame=frame):
                self.kwargs["image_base64"] = frame
                with self.assertRaises(ProviderError):
                    await provider.respond(**self.kwargs)


if __name__ == "__main__":
    unittest.main()
