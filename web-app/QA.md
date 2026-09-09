# Application validation

September 8, 2026. Deployed to `plva-app.zubairzafar480.workers.dev`.

- Signed session tests passed: exact secret matching, signature validation, tampering, expiry, and key rotation.
- Connector boundary tests passed: originals, vault values, API configuration, and unknown commands are excluded; runtime text is scrubbed; tab URLs are reduced to their origin.
- Production Worker integration passed: static assets, unauthenticated denial, strict-origin mutation checks, route restrictions, connection status, durable procedure create/read/delete, and logout.
- Actual Edge opened `https://example.com`; its locally protected PNG reached the authenticated Cloudflare workspace with no raw frame or API key in the response.
- A real task asked Astra to read that page's heading without navigating or acting. It completed with one model call and the result: `The page’s main heading is “Example Domain.”` The provider receipt returned model `gpt-6-astra` and response ID `resp_05568f8fdbf2ed13006aa0a494953c87d0b03d5270150a4d38`.
- The initial WebSocket transport disconnected during testing. The shipped connector uses authenticated outbound HTTPS polling; the real task above completed through that transport.
- The website input starts empty. No task is automatically submitted after sign-in or navigation.

This verifies one read-only live task, not every website or the detector's recall. Existing local browser restrictions and protection limitations still apply. Saved procedures are operator-reviewed instructions, not an automatically learned skill module. WebMCP registration and frontend layout have not been exercised through browser automation in this pass; backend APIs, asset build, and JavaScript syntax were checked.
