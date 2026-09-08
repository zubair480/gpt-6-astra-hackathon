# Local model: what runs, what is pinned, what is verified

This document covers the `local` mode of the private reasoning service: the model and
runtime it uses, how to provision them, how to start the service, and exactly which
properties are verified versus merely claimed. Everything here is owned by the model track
(`src/plva_private_reasoning/model/`, `scripts/provision_model.sh`, `tests/test_model_*.py`).

## Pins

| Item | Value |
| --- | --- |
| Model | Qwen3-4B-Instruct-2507 (Qwen, Apache-2.0) |
| Base model revision | `Qwen/Qwen3-4B-Instruct-2507` @ `cdbee75f17c01a7cc42f958dc650907174af0554` |
| Quantization | Q4_K_M GGUF |
| GGUF source | `unsloth/Qwen3-4B-Instruct-2507-GGUF` @ `a06e946bb6b655725eafa393f4a9745d460374c9` |
| File | `Qwen3-4B-Instruct-2507-Q4_K_M.gguf`, 2,497,281,120 bytes (2.33 GiB) |
| sha256 | `3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597` |
| Runtime | `llama-cpp-python==0.3.35` (MIT; bundles llama.cpp, MIT) |
| Sampling | temperature 0, top_k 1, seed 7, repeat_penalty 1.0, grammar-constrained |
| Context | `n_ctx` 4096 by default, hard-capped at 8192 |

The single source of truth is `src/plva_private_reasoning/model/manifest.json`. The
provisioning script reads it, and `plva-pr-local` refuses to start unless the file on disk
hashes to the manifest's sha256. Change the manifest, and both sides change together.

### Why this source

The Qwen organization publishes the 2507 4B Instruct weights in safetensors and FP8 but no
GGUF for this checkpoint (the `Qwen/...-GGUF` repo does not exist), so a third-party
quantization is unavoidable. Two well-known ones exist; both were checked through the
Hugging Face API at the pinned revisions:

- `unsloth/Qwen3-4B-Instruct-2507-GGUF`: declares `license: apache-2.0` on its model card,
  ~113k downloads, Unsloth maintains its GGUFs with the upstream chat template and is the
  quantization the reference implementation also used. **Chosen.**
- `bartowski/Qwen_Qwen3-4B-Instruct-2507-GGUF`: equally reputable, ~21k downloads, no license
  metadata on the card. A drop-in alternative; its Q4_K_M sha256 is
  `2fde00ce69dd4899c70d020845e2638353015bba0fdf161b3eb965f2bca4464e` at revision
  `ae44f08e1392f39c0e474af10c3ff8355c8b6688` if the team prefers it.

The sha256 values come from the Hub's LFS metadata (`lfs.oid` in
`/api/models/<repo>/tree/<revision>?recursive=true`), so they were pinned without
downloading and are verified again after the download. Q4_K_M was kept because the reference
project's runbook measured it as the smallest quant at which the 4B model's approval
judgment stayed reliable under grammar constraints; nothing here re-validates that claim,
see "Evaluation" below.

### License notes

- Qwen3-4B-Instruct-2507 weights: Apache-2.0 (Qwen). Redistribution is permitted with the
  license and attribution; we do not redistribute, we download from the pinned source.
- Unsloth's GGUF conversion: Apache-2.0 per the model card.
- llama-cpp-python and the vendored llama.cpp: MIT.
- Weights are never committed. `models/` is gitignored at the repository root and the
  provisioning script additionally writes `models/.gitignore` so a different checkout layout
  cannot leak them.

## Hardware

Tested target: macOS on Apple Silicon (development host: M2, 8 GB). Metal offload is the
default (`--n-gpu-layers -1`); the Q4_K_M file needs roughly 2.5 GB of unified memory for
weights plus a few hundred MB for a 4096-token KV cache. Expect low single-digit seconds per
approval or trace review and longer for a 40-item compute request.

CPU-only (`--n-gpu-layers 0`) works on any x86_64 or arm64 host with about 4 GB of free RAM;
the reference project measured roughly 27 s per approval inside a CPU-only Linux VM. An
NVIDIA build needs llama-cpp-python compiled with CUDA (`CMAKE_ARGS="-DGGML_CUDA=on"`); that
path is untested here and is not claimed.

`llama-cpp-python` ships as an sdist, so installing it compiles llama.cpp: on macOS you need
the Xcode command-line tools; scikit-build-core fetches cmake and ninja wheels automatically
if they are not on the PATH. Budget a few minutes for the build.

## Provisioning (the only network step)

```bash
# 1. Runtime (compiles llama.cpp; no model download)
uv sync --extra local

# 2. Weights: one explicit ~2.3 GiB download, verified against the pinned sha256
scripts/provision_model.sh
#    scripts/provision_model.sh --check   # verify an existing file, never downloads
#    MODELS_DIR=/somewhere scripts/provision_model.sh   # alternate location
```

The script downloads `https://huggingface.co/<repo>/resolve/<revision>/<file>` with curl
(HTTPS only, TLS 1.2+, resumable), into `models/<file>.part`, verifies sha256, and only then
renames it into place. A mismatched file is deleted, never served. Nothing else in the module
contacts the network for model assets: the runtime loads from the local path only, the
schema-to-grammar converter runs with fetching disabled, and `HF_HUB_OFFLINE=1` /
`TRANSFORMERS_OFFLINE=1` are set defensively at startup.

## Starting the local service

```bash
uv run plva-pr-local                                   # models/<manifest filename>
uv run plva-pr-local --model-path /path/to/file.gguf   # or PLVA_PR_MODEL_PATH
uv run plva-pr-local --isolation-evidence /path/to/evidence.json   # from the isolation launcher
```

Startup order: parse arguments (non-loopback bind is refused), load and validate the
manifest, hash the model file and compare, load the model, read isolation evidence, mint the
per-launch credential into `.plva-pr/credential` (mode 0600), serve. A checksum mismatch or
missing file exits with status 2 before any credential is written.

Readiness (`GET /v1/readiness`) reports `mode: "local"`, `model_loaded: true`, and
`isolation` from the evidence file: `verified` only when the file says so with a
timezone-aware `verified_at` less than `--evidence-max-age-seconds` (default 600) old;
`failed` when it says so; `unverified` for anything else, including no file. Private values
are accepted only when isolation is `verified`; until then the service prints a banner and is
suitable for synthetic fixtures only. Binding the evidence to the running instance and the
effective sandbox policy is the isolation track's launcher's job; this reader only refuses
stale, naive, or malformed files.

## How inference is constrained

Each operation's adapter (`model/adapter.py`) sends a system prompt of trusted rules plus a
user prompt in which policy and structured request fields are trusted and every free-text
input (task context, compute instruction, item values, even policy rule text) is wrapped in
`<<<UNTRUSTED_DATA>>> ... <<<END_UNTRUSTED_DATA>>>` markers that the rules declare inert.
Delimiter fragments and control characters inside untrusted text are stripped so a value
cannot close the fence.

Decoding is constrained by a GBNF grammar built from a per-request JSON schema:

- approve: `{"decision": approve|deny, "reason_code": POLICY_MATCH|SCOPE_EXCEEDED, "ttl_seconds": int, "max_uses": int}`
- compute: `{"tokens": [<enum of exactly the request's tokens>]}` with `minItems`/`maxItems`
  fixed for sort and counted select
- review-trace: `{"action": continue|warn|halt, "reason_code": <six fixed codes>}`

Note for anyone touching the backend: in llama-cpp-python 0.3.35 `response_format` builds a
grammar only for `{"type": "json_object", "schema": ...}` and silently ignores
`"json_schema"`, so `LlamaCppBackend` passes an explicit `LlamaGrammar.from_json_schema(...)`
via `grammar=`. Integer `minimum`/`maximum` are not enforced by the grammar converter; the
parser and `operations.approve.guard` enforce them.

The grammar is a decode-time aid, not the safety boundary. Every completion is parsed
strictly (exact key set, enum membership, decision/reason pairing, integer bounds, token
membership and uniqueness); a failure is retried once with a fixed nudge, then raised so the
operations layer returns deny / error / halt with `MODEL_UNAVAILABLE`. The operations layer
independently re-validates membership, uniqueness, counts, and clamps TTL and use counts to
policy; the adapter never bypasses it.

## Data handling in this process

- Prompts and raw completions are locals in the adapter and backend; they are deleted after
  parsing and never logged, printed, cached, or placed in exception messages. JSON decode
  errors are raised without their `__context__`, because `json.JSONDecodeError.doc` holds the
  whole document.
- `Llama(verbose=False)` suppresses llama.cpp's stderr chatter (model metadata, timings).
  Access logging is off in uvicorn. No telemetry exists in llama-cpp-python 0.3.35 (verified
  by reading the package). Its network-capable code paths are `Llama.from_pretrained` and the
  multimodal chat handlers' `from_pretrained`, image-URL fetching in those same multimodal
  handlers, and the grammar converter's remote `$ref` fetcher, which `from_json_schema`
  invokes with `allow_fetch=False`. This module calls none of them: text-only messages, no
  `chat_handler`, weights from a local path.
- The compute prompt intentionally shows `token => value` pairs to the model. That is the
  bounded disclosure `/v1/compute` exists for; the result returned is tokens only.
- Ordinary Python and llama.cpp memory management is **not** cryptographic zeroization.
  Freed buffers may persist until reused; the model's KV cache retains prompt state until the
  next request overwrites it; host swap, hibernation files, and crash dumps are outside any
  process-level claim. Treat "values leave memory after the request" as best effort, not as a
  guarantee.

## What is verified and what is not

Verified (by tests that run without the model, `uv run pytest -q tests/test_model_*.py`):

- Package imports and the mock service work without llama-cpp-python installed.
- Every adapter accepts only its enum-bounded shape; free text, wrong enums, unknown or
  repeated tokens, wrong decision/reason pairings, and extra keys fail after exactly one
  retry and surface as deny / error / halt through `operations.run`.
- Model-proposed TTL and use counts above policy are clamped end to end; count mismatches
  are still caught by the operations layer.
- Prompt-injection strings in task context, instructions, and values end up only inside the
  fence and cannot change the output shape.
- No synthetic private value appears in any exception message, cause, or context, nor in a
  service response produced from a misbehaving model.
- `plva-pr-local` refuses to start on a checksum mismatch or missing file, before minting a
  credential; isolation evidence that is absent, stale, naive, future-dated, malformed, or
  not literally `verified` leaves the service unready.
- The manifest's runtime pin matches the `local` extra in `pyproject.toml`.

Not verified here:

- Judgment quality of the real model. `tests/test_model_live.py` runs a small held-out
  synthetic set (six approvals/denials, two sorts, two selects, two traces) and reports
  schema validity separately from accuracy; it skips until the weights and runtime are
  present, so no accuracy number is claimed in this document. Run it with
  `uv run pytest -q -s tests/test_model_live.py` after provisioning and paste the printed
  tallies into the handoff table.
- Network isolation of the model process. `local` mode on the host is loopback-bound and
  offline by construction, but that is a claim about this code, not an enforced boundary.
  The isolation track's sandbox and deny tests provide the enforcement evidence and set the
  `isolation` state.
- CUDA, Windows, and Linux hosts. Only macOS/Apple Silicon was exercised.
- Timing side channels: the adapter's latency depends on prompt length and therefore on
  value length. Nothing in this module labels or exports timings per request.

## Evaluation

Run after provisioning:

```bash
uv run pytest -q -s tests/test_model_live.py
```

Each case prints expected versus actual and the per-operation tally
(`schema_valid n/N, correct n/N, mean latency`). Only schema validity is asserted; a
schema-valid but wrong judgment is reported, not hidden.

## Files

- `src/plva_private_reasoning/model/backend.py`: `InferenceBackend` protocol,
  `LlamaCppBackend`, `FakeBackend`.
- `src/plva_private_reasoning/model/adapter.py`: prompts, schemas, strict parsers, retry,
  `local_backends()`.
- `src/plva_private_reasoning/model/cli.py`: `plva-pr-local`, manifest and checksum gate,
  isolation evidence reader.
- `src/plva_private_reasoning/model/manifest.json`: the pins above.
- `scripts/provision_model.sh`: the download and verification step.
- `tests/test_model_{adapter,backend,cli,live}.py`.
