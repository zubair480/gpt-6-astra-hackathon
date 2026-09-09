# PLVA Cloudflare application

The working application is separate from the four-click presentation. Its interface is hosted on Cloudflare, and its authenticated outbound connector runs the repository's real Windows browser runtime.

Application: https://plva-app.zubairzafar480.workers.dev/ · Presentation: https://plva-demo.zubairzafar480.workers.dev/

## What works

- Open ordinary HTTPS websites in the dedicated local Edge browser.
- Inspect the actual locally masked screenshot, detected tokens, and browser tabs.
- Start and stop actual Astra computer-use tasks.
- Inspect actual provider response IDs, protected request evidence, and results.
- Save reviewed procedures in durable Cloudflare storage, and attach them to a new task with fresh inputs.
- Keep a short protected history of completed tasks.

There are no scripted task responses or preset customer records in this application. Procedures are edited and reviewed by the operator; this does not claim the independent automatic skill-learning module has been integrated.

## Architecture and access

Cloudflare hosts the interface, signed session authentication, and one SQLite-backed Durable Object for this owner's workspace. The Windows connector polls over authenticated outbound HTTPS; there is no public tunnel or inbound port. Only a fixed list of browser/task/evidence API routes can cross the bridge.

The connector removes raw screenshots and private state before responding. Browser tab URLs expose their origin only. Raw screenshots, the local value vault, and the OpenAI API key remain in the Windows process. The cloud receives protected previews, locally scrubbed runtime text, user-entered task instructions, and procedures the user explicitly saves. The existing detector is a hackathon detector, so inspect previews before sending observations to Astra.

This is a single-owner application connected to one computer, not a public multi-tenant service. A workspace key grants control of that computer's dedicated PLVA browser. Browser sessions use an HttpOnly, Secure, SameSite=Strict signed cookie that expires after eight hours. Mutating requests require the app's exact Origin. The separate bridge key is never sent to the frontend. Closing the connector or turning off the computer makes the app show its offline state; reconnecting restores browser access.

## Run and deploy

From `web-app`:

```powershell
npm run setup
npm run build
npm run dev
```

Setup creates private random credentials and an `Open PLVA.html` launcher in `%LOCALAPPDATA%\PLVA\CloudWorkspace`. The launcher signs in through a URL fragment which the app immediately clears. Credentials and `.dev.vars` are excluded from Git; do not commit or share the launcher publicly.

Publish the app with `npm run deploy`, then upload the generated credentials through Wrangler secret bulk using the private `secrets.json` path. The Worker denies workspace access until configured. The Worker name is `plva-app`; the four-click presentation remains `plva-demo`.

Start the computer connector from the repository root:

```powershell
powershell -File web-app/start-connector.ps1
```

To load an existing local API key file, pass `-ApiKeyFile` with that file's path. Alternatively use `OPENAI_API_KEY` or configure the key in the local runtime at http://127.0.0.1:18080. Keep the connector running while using the cloud app.

No model call is made by sign-in, previews, or procedure management. Selecting Run task makes real provider calls using the local API key.

## Validation

`node --test web-app/tests/auth.test.mjs` checks signed sessions and secrets. `python -m unittest tests.test_cloud_bridge -v` checks the connector boundary. `node web-app/tests/integration.mjs http://127.0.0.1:18641` exercises the running Worker with its private local credential file, without printing secrets.

WebMCP is optional and feature-detected. It exposes read-only task status and a task-staging action that does not start execution. Registration failures leave the ordinary UI working.

See [QA.md](QA.md) for the deployed integration results and remaining validation limits.
