"""Backend and manifest tests. No model weights and no llama-cpp-python required."""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

from plva_private_reasoning.model.backend import (
    MAX_COMPLETION_CHARS,
    FakeBackend,
    InferenceBackend,
    InferenceError,
    LlamaCppBackend,
)
from plva_private_reasoning.model.cli import MANIFEST_PATH, Manifest

ROOT = Path(__file__).resolve().parents[1]
LLAMA_INSTALLED = importlib.util.find_spec("llama_cpp") is not None


def test_package_imports_without_llama_cpp() -> None:
    # The import above already proves it; this documents the intent.
    import plva_private_reasoning.model.adapter
    import plva_private_reasoning.model.cli

    assert callable(plva_private_reasoning.model.cli.main_local)
    assert callable(plva_private_reasoning.model.adapter.local_backends)


def test_fake_backend_replays_script_and_records_calls() -> None:
    fake = FakeBackend(["one", "two"])
    assert isinstance(fake, InferenceBackend)
    assert fake.complete(system_prompt="s", user_prompt="u", json_schema={}, max_tokens=5) == "one"
    assert (
        fake.complete(
            system_prompt="s",
            user_prompt="u",
            json_schema=None,
            max_tokens=5,
            history=[("user", "q"), ("assistant", "a")],
        )
        == "two"
    )
    with pytest.raises(InferenceError):
        fake.complete(system_prompt="s", user_prompt="u", json_schema={}, max_tokens=5)
    assert [call.max_tokens for call in fake.calls] == [5, 5, 5]
    assert fake.calls[0].history == () and fake.calls[0].json_schema == {}
    assert fake.calls[1].history == (("user", "q"), ("assistant", "a"))
    assert fake.calls[1].json_schema is None


@pytest.mark.parametrize(
    "history",
    [
        [("assistant", "a")],
        [("user", "q")],
        [("user", "q"), ("user", "q")],
        [("system", "x"), ("assistant", "a")],
    ],
)
def test_backends_reject_malformed_history(history: list[tuple[str, str]]) -> None:
    fake = FakeBackend(["one"])
    with pytest.raises(InferenceError, match="history"):
        fake.complete(
            system_prompt="s", user_prompt="u", json_schema=None, max_tokens=5, history=history
        )
    assert fake.calls == []


@pytest.mark.parametrize("bad", ["", "   ", "x" * (MAX_COMPLETION_CHARS + 1)])
def test_fake_backend_applies_completion_bounds(bad: str) -> None:
    fake = FakeBackend([bad])
    with pytest.raises(InferenceError):
        fake.complete(system_prompt="s", user_prompt="u", json_schema={}, max_tokens=5)


def test_llama_backend_requires_an_existing_file(tmp_path: Path) -> None:
    with pytest.raises(InferenceError, match="missing"):
        LlamaCppBackend(tmp_path / "absent.gguf")


def test_llama_backend_rejects_unbounded_context(tmp_path: Path) -> None:
    fake_model = tmp_path / "fake.gguf"
    fake_model.write_bytes(b"not a model")
    with pytest.raises(InferenceError, match="n_ctx"):
        LlamaCppBackend(fake_model, n_ctx=1 << 20)


def test_llama_backend_fails_with_fixed_message_without_extra_or_with_bad_file(
    tmp_path: Path,
) -> None:
    fake_model = tmp_path / "fake.gguf"
    fake_model.write_bytes(b"not a model")
    with pytest.raises(InferenceError) as info:
        LlamaCppBackend(fake_model)
    message = str(info.value)
    if LLAMA_INSTALLED:
        assert message.startswith("model failed to load")
    else:
        assert "local" in message
    assert str(fake_model) not in message


def test_manifest_pins_are_complete_and_consistent() -> None:
    manifest = Manifest.load(MANIFEST_PATH)
    assert manifest.model_name == "Qwen3-1.7B"
    assert manifest.source_repo == "Qwen/Qwen3-1.7B-GGUF"  # the official Qwen GGUF
    assert manifest.filename.endswith("Q8_0.gguf")
    assert re.fullmatch(r"[0-9a-f]{40}", manifest.source_revision)
    assert re.fullmatch(r"[0-9a-f]{64}", manifest.sha256)
    assert manifest.license == "Apache-2.0"
    assert manifest.runtime.startswith("llama-cpp-python==")
    raw = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    assert raw["size_bytes"] == 1_834_426_016
    assert raw["base_model"] == "Qwen/Qwen3-1.7B"
    assert re.fullmatch(r"[0-9a-f]{40}", raw["base_model_revision"])


def test_manifest_runtime_pin_matches_pyproject_extra() -> None:
    manifest = Manifest.load(MANIFEST_PATH)
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r"^local = \[(.*)\]$", pyproject, re.MULTILINE)
    assert match is not None
    assert f'"{manifest.runtime}"' in match.group(1)


def test_provision_script_reads_the_same_manifest() -> None:
    script = (ROOT / "scripts" / "provision_model.sh").read_text(encoding="utf-8")
    assert "src/plva_private_reasoning/model/manifest.json" in script
    assert "huggingface.co/$repo/resolve/$revision/$filename" in script
    assert "sha256" in script
