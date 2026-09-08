"""The single protected-observation boundary for live Astra requests."""
import base64
import binascii
import hashlib
import json
import uuid

import httpx


MODEL = "gpt-6-astra"
ENDPOINT = "https://api.openai.com/v1/responses"
INSTRUCTIONS = """You operate the user's browser through PLVA using computer actions.
Follow the user's task on the available websites. Screenshots may contain private-value
tokens. Use the exact bracketed tokens when entering those values into appropriate form
fields; the local runtime resolves them. Never guess, request, or reveal underlying
private values. SECRET tokens are blocked and cannot be used. Do not type private tokens
into search, chat, address bars, or other unrelated destinations. Use navigate_browser
to open a URL because screenshots contain page content without a browser address bar.
Use visible page controls for other interactions. Never include private tokens in URLs.
Stop when the requested task is complete and describe the result honestly.
If information is unavailable because it is protected, explain the limitation."""


class ProviderError(RuntimeError):
    """A safe operator-facing failure, optionally carrying the attempted request audit."""

    def __init__(self, message, audit=None):
        super().__init__(message)
        self.audit = audit


class AstraProvider:
    def __init__(self, key, *, transport=None, timeout=90):
        if not isinstance(key, str) or not key.strip():
            raise ProviderError("Configure an Astra API key before starting a live run")
        self._key = key.strip()
        self._transport = transport
        self._timeout = timeout

    async def respond(self, *, task, image_base64, manifest, scrub,
                      previous_response_id=None, call_outputs=None):
        """Return (sanitized response, exact outgoing request plus provider receipt).

        image_base64 must come from the local privacy layer. This client does no image
        detection. Follow-ups accept computer screenshots rebuilt from this protected
        frame and scrubbed function output text. Arbitrary caller extras are discarded.
        """
        def clean(value):
            if isinstance(value, str):
                return scrub(value.replace(self._key, "[API_KEY_REDACTED]"))
            if isinstance(value, list):
                return [clean(item) for item in value]
            if isinstance(value, dict):
                return {str(key): clean(item) for key, item in value.items()}
            return value

        try:
            png = base64.b64decode(image_base64, validate=True)
        except (TypeError, ValueError, binascii.Error):
            raise ProviderError("Protected screenshot is not valid base64") from None
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ProviderError("Protected screenshot must be PNG")
        # Accept only the public manifest contract, even if the caller adds raw values.
        safe_manifest = [{key: clean(item[key]) for key in ("token", "kind", "label")
                          if key in item} for item in manifest]
        text = clean(task) + "\nAvailable private tokens: " + json.dumps(safe_manifest)
        image_url = "data:image/png;base64," + image_base64
        if previous_response_id:
            if not call_outputs:
                raise ProviderError("A follow-up request requires computer call outputs")
            inputs = []
            has_computer_output = any(item.get("type", "computer_call_output") == "computer_call_output"
                                      for item in call_outputs)
            for item in call_outputs:
                call_id = item.get("call_id")
                if not isinstance(call_id, str) or not call_id:
                    raise ProviderError("Tool output is missing its call ID")
                output_type = item.get("type", "computer_call_output")
                if output_type == "computer_call_output":
                    inputs.append({"type": "computer_call_output", "call_id": clean(call_id),
                                   "output": {"type": "computer_screenshot",
                                              "image_url": image_url, "detail": "original"}})
                elif output_type == "function_call_output":
                    if not isinstance(item.get("output"), str):
                        raise ProviderError("Function output must be text")
                    output = clean(item["output"])
                    if not has_computer_output:
                        # With the computer tool and previous_response_id, images must
                        # live in a tool result, not in a new user message (live API verified).
                        output = [{"type": "input_text", "text": output},
                                  {"type": "input_image", "image_url": image_url, "detail": "original"}]
                    inputs.append({"type": "function_call_output", "call_id": clean(call_id),
                                   "output": output})
                else:
                    raise ProviderError("Unsupported tool output type")
            content = [{"type": "input_text", "text": text}]
            inputs.append({"role": "user", "content": content})
        else:
            if call_outputs:
                raise ProviderError("Computer call outputs require a previous response ID")
            inputs = [{"role": "user", "content": [
                {"type": "input_text", "text": text},
                {"type": "input_image", "image_url": image_url, "detail": "original"}]}]
        payload = {"model": MODEL, "tools": [{"type": "computer"},
                   {"type": "function", "name": "navigate_browser",
                    "description": "Open a website URL in the current PLVA browser tab.",
                    "parameters": {"type": "object", "properties": {
                        "url": {"type": "string", "description": "The HTTP or HTTPS URL to open."}},
                        "required": ["url"], "additionalProperties": False}, "strict": True}],
                   "instructions": clean(INSTRUCTIONS), "input": inputs}
        if previous_response_id:
            payload["previous_response_id"] = clean(previous_response_id)
        audit = {"mode": "astra", "text": clean(task), "manifest": safe_manifest,
                 "request_id": str(uuid.uuid4()),
                 "image_base64": image_base64, "frame_hash": hashlib.sha256(png).hexdigest(),
                 "payload": payload, "transmitted": False, "status": "prepared"}
        def failure(message, kind):
            audit.update(status="failed", error_kind=kind, error=message)
            return ProviderError(message, audit)

        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.post(ENDPOINT,
                    headers={"Authorization": "Bearer " + self._key}, json=payload)
        except httpx.RequestError:
            # Request exceptions may contain credentials/URLs. Never echo their text.
            audit.update(transmitted=None)
            raise failure("Astra request failed; check the connection and retry", "network_error") from None
        audit.update(transmitted=True, http_status=response.status_code)
        if not response.is_success:
            # API bodies may echo request data; an HTTP status is enough for the demo.
            raise failure(f"Astra API returned HTTP {response.status_code}", "api_error")
        try:
            data = response.json()
        except ValueError:
            raise failure("Astra returned an unreadable response", "invalid_response") from None
        if not isinstance(data, dict) or not data.get("id") or not data.get("model"):
            raise failure("Astra response is missing its API receipt", "invalid_response")
        data = clean(data)
        actions = []
        for item in data.get("output", []):
            if item.get("type") == "computer_call":
                actions.extend(item.get("actions", [item["action"]] if "action" in item else []))
            elif item.get("type") == "function_call":
                actions.append({key: item[key] for key in ("type", "call_id", "name", "arguments")
                                if key in item})
        audit.update(status="responded", response_id=data["id"], response_model=data["model"],
                     usage=data.get("usage"), actions=actions, response_output=data.get("output", []))
        return data, audit
