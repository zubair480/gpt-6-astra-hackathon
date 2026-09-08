# curl examples (synthetic values only)

Start the mock in one terminal; it prints the credential file path and stays in the foreground:

```sh
uv run plva-pr-mock            # MODE=mock bind=127.0.0.1:18555 credential_file=.plva-pr/credential
```

In another terminal, read the per-launch credential and call the three APIs. The service
checks the `Host` header, rejects any `Origin` header, requires `Content-Type: application/json`,
and caps bodies at 65536 bytes. Everything except `/health` needs the bearer credential.

```sh
BASE=http://127.0.0.1:18555
TOKEN="$(cat .plva-pr/credential)"
AUTH="Authorization: Bearer ${TOKEN}"
JSON="Content-Type: application/json"

# Liveness (unauthenticated) and readiness (authenticated).
curl -s "$BASE/health"
curl -s -H "$AUTH" "$BASE/v1/readiness"

# 1. Approve: recommends approve/deny for one private action. No secret value is sent.
curl -s -H "$AUTH" -H "$JSON" "$BASE/v1/approve" -d @contracts/v1/examples/approve-request.json

# 2. Compute: bounded sort/select over explicitly supplied values; the answer is tokens only.
#    Only send real values when readiness says ready_for_private_values=true (never to mock).
curl -s -H "$AUTH" -H "$JSON" "$BASE/v1/compute" -d @contracts/v1/examples/compute-request.json

# 3. Review-trace: continue/warn/halt over a value-free event trace.
curl -s -H "$AUTH" -H "$JSON" "$BASE/v1/review-trace" \
  -d @contracts/v1/examples/review-trace-request.json
```

Expected mock output (identifiers echoed from the request):

```json
{"schema_version":"1.0","session_id":"demo-session","request_id":"approval-001","decision":"approve","reason_code":"POLICY_MATCH","scope":{"token":"API_KEY_1_a3f9","tool_name":"type","argument_path":"text","origin":"https://service.example","field_id":"api-key-input","ttl_seconds":30,"max_uses":1}}
{"schema_version":"1.0","session_id":"demo-session","request_id":"compute-001","status":"ok","tokens":["NAME_2_a3f9","NAME_1_a3f9"],"reason_code":"COMPLETED"}
{"schema_version":"1.0","session_id":"demo-session","request_id":"trace-001","action":"halt","reason_code":"BLOCKED_CLASS_ATTEMPT"}
```

Repeating a call with the same `session_id` + `request_id` returns `409`
`{"schema_version":"1.0","error_code":"DUPLICATE_REQUEST"}`; change `request_id` between calls.

Error bodies are always exactly `{"schema_version":"1.0","error_code":"<CODE>"}` and never echo input:

```sh
curl -s -i "$BASE/v1/readiness"                                   # 401 UNAUTHORIZED
curl -s -i -H "$AUTH" -H "Origin: https://evil.example" "$BASE/v1/readiness"   # 403 FORBIDDEN_ORIGIN
curl -s -i -H "$AUTH" -H "Host: evil.example" "$BASE/v1/readiness"             # 403 FORBIDDEN_HOST
curl -s -i -H "$AUTH" -H "$JSON" "$BASE/v1/compute" -d '{"schema_version":"1.0"'  # 400 SCHEMA_INVALID
```

The same flow against the local service changes only `BASE` and the credential path.
