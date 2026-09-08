"""Inference backends: one protocol, a llama.cpp implementation, and a scripted fake.

The backend is the only code that talks to a model. It receives a system prompt (trusted
rules), optional prior turns, a user prompt (rules plus delimited untrusted data), an optional
JSON schema, and a token budget, and returns the raw completion string. It never logs, prints,
or stores the prompt or the completion; both live only in the caller's frame.

``llama_cpp`` is imported lazily so the package imports (and the mock service runs) without
the optional ``local`` extra installed.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final, Protocol, runtime_checkable

# Fixed sampling parameters. Determinism is part of the audit story: the same request
# against the same weights yields the same completion.
SEED: Final = 7
TEMPERATURE: Final = 0.0
DEFAULT_N_CTX: Final = 4096
MAX_N_CTX: Final = 8192
DEFAULT_MAX_TOKENS: Final = 512
MAX_COMPLETION_CHARS: Final = 16384

# Qwen3 is a hybrid thinking model. Thinking must stay off: it is slow and a grammar-bound
# completion cannot spend tokens inside a ``<think>`` block. Two documented switches exist and
# both are applied when the loaded chat template supports them: the ``enable_thinking``
# template variable (rendered as an empty think block in the generation prompt) and the
# ``/no_think`` soft switch appended to the final user turn.
NO_THINK_SWITCH: Final = "/no_think"
_THINKING_TEMPLATE_VARIABLE: Final = "enable_thinking"

# (role, content) pairs preceding the final user turn; roles alternate user/assistant.
Turn = tuple[str, str]


class InferenceError(RuntimeError):
    """The backend could not produce a completion. Messages never carry prompt content."""


@runtime_checkable
class InferenceBackend(Protocol):
    """Anything that turns (system, history, user, schema, budget) into a completion string.

    ``json_schema=None`` asks for an unconstrained completion; a mapping is compiled into a
    decode-time grammar. ``history`` supplies earlier turns of the same conversation.
    """

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: Mapping[str, Any] | None,
        max_tokens: int,
        history: Sequence[Turn] = (),
    ) -> str: ...


def _bounded_completion(content: object) -> str:
    """Accept only a non-empty string of bounded size; anything else is a backend failure."""
    if not isinstance(content, str) or not content.strip():
        raise InferenceError("model returned an empty or non-text completion")
    if len(content) > MAX_COMPLETION_CHARS:
        raise InferenceError("model completion exceeded the size bound")
    return content


def _check_history(history: Sequence[Turn]) -> None:
    expected = "user"
    for role, content in history:
        if role != expected or not isinstance(content, str):
            raise InferenceError("conversation history must alternate user/assistant turns")
        expected = "assistant" if role == "user" else "user"
    if expected != "user":
        raise InferenceError("conversation history must end with an assistant turn")


def _no_think_handler(llama: Any, template: str) -> Any:
    """A chat handler that renders the model's own template with ``enable_thinking=False``.

    ``Llama.create_chat_completion`` has a fixed signature and cannot forward template
    variables, so the only way to reach the switch is a handler built from the same template
    llama-cpp-python itself would have used (mirrors ``Llama.__init__``'s default handler).
    """
    from llama_cpp.llama_chat_format import (  # type: ignore[import-not-found,unused-ignore]
        Jinja2ChatFormatter,
    )

    formatter_base: Any = Jinja2ChatFormatter

    class NoThinkFormatter(formatter_base):  # type: ignore[misc]
        def __call__(self, **kwargs: Any) -> Any:
            return super().__call__(**kwargs, enable_thinking=False)

    eos_id = llama.token_eos()
    bos_id = llama.token_bos()
    eos = llama.detokenize([eos_id], special=True).decode("utf-8", "replace")
    bos = llama.detokenize([bos_id], special=True).decode("utf-8", "replace") if bos_id >= 0 else ""
    return NoThinkFormatter(
        template=template, eos_token=eos, bos_token=bos, stop_token_ids=[eos_id]
    ).to_chat_handler()


class LlamaCppBackend:
    """Grammar-constrained, fully offline llama.cpp inference over a local GGUF file.

    Constrained decoding is applied through an explicit ``LlamaGrammar`` built from the JSON
    schema. In llama-cpp-python 0.3.35 ``response_format`` only builds a grammar for
    ``{"type": "json_object", "schema": ...}`` and silently ignores ``"json_schema"``, so
    passing ``grammar=`` directly is the unambiguous path. The grammar is a decode-time
    constraint, not a proof: callers still validate every parsed field.
    """

    def __init__(
        self,
        model_path: str | Path,
        *,
        n_ctx: int = DEFAULT_N_CTX,
        n_gpu_layers: int = -1,
        n_threads: int | None = None,
        use_mlock: bool = False,
        disable_thinking: bool = True,
    ) -> None:
        path = Path(model_path)
        if not path.is_file():
            raise InferenceError("model file is missing")
        if not 512 <= n_ctx <= MAX_N_CTX:
            raise InferenceError("n_ctx is outside the supported bound")
        try:
            import llama_cpp  # type: ignore[import-not-found,unused-ignore]
        except ImportError:
            raise InferenceError(
                "llama-cpp-python is not installed; install the 'local' extra"
            ) from None
        module: Any = llama_cpp
        self._grammar_cls: Any = module.LlamaGrammar
        self._lock = threading.Lock()
        # verbose=False silences llama.cpp's load/eval chatter (which would otherwise print
        # model metadata to stderr). Nothing here reads the network: the weights come from
        # ``model_path`` only and the schema-to-grammar converter runs with fetching off.
        try:
            self._llama: Any = module.Llama(
                model_path=str(path),
                n_ctx=n_ctx,
                n_gpu_layers=n_gpu_layers,
                n_threads=n_threads,
                use_mlock=use_mlock,
                seed=SEED,
                verbose=False,
                logits_all=False,
                embedding=False,
            )
        except Exception as exc:
            raise InferenceError(f"model failed to load: {type(exc).__name__}") from None
        self.n_ctx = n_ctx
        self.thinking_switch = ""
        self.thinking_template_variable = False
        if disable_thinking:
            metadata: Mapping[str, str] = getattr(self._llama, "metadata", None) or {}
            template = metadata.get("tokenizer.chat_template", "")
            if _THINKING_TEMPLATE_VARIABLE in template:
                try:
                    self._llama.chat_handler = _no_think_handler(self._llama, template)
                    self.thinking_template_variable = True
                except Exception as exc:
                    raise InferenceError(
                        f"could not install the no-think chat handler: {type(exc).__name__}"
                    ) from None
            self.thinking_switch = NO_THINK_SWITCH

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: Mapping[str, Any] | None,
        max_tokens: int,
        history: Sequence[Turn] = (),
    ) -> str:
        if not 1 <= max_tokens <= self.n_ctx:
            raise InferenceError("max_tokens is outside the context bound")
        _check_history(history)
        grammar: Any = None
        if json_schema is not None:
            try:
                grammar = self._grammar_cls.from_json_schema(json.dumps(json_schema), verbose=False)
            except Exception as exc:
                raise InferenceError("could not build a grammar from the response schema") from exc
        switch = f" {self.thinking_switch}" if self.thinking_switch else ""
        messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
        messages.extend({"role": role, "content": content} for role, content in history)
        messages.append({"role": "user", "content": user_prompt + switch})
        failure = ""
        try:
            with self._lock:  # a Llama context is single-threaded
                result = self._llama.create_chat_completion(
                    messages=messages,
                    temperature=TEMPERATURE,
                    top_k=1,
                    top_p=1.0,
                    min_p=0.0,
                    repeat_penalty=1.0,
                    seed=SEED,
                    max_tokens=max_tokens,
                    grammar=grammar,
                    stream=False,
                )
        except Exception as exc:
            # The library's own message may quote prompt fragments; replace it wholesale.
            failure = type(exc).__name__
            result = None
        finally:
            del messages
        if result is None:
            raise InferenceError(f"inference failed: {failure}")
        content: object = None
        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            content = None
        finally:
            del result
        if content is None:
            raise InferenceError("model returned an unexpected completion shape")
        return _bounded_completion(content)


@dataclass(frozen=True, slots=True)
class FakeCall:
    """One recorded backend call. Tests inspect prompts; production never records them."""

    system_prompt: str
    user_prompt: str
    json_schema: Mapping[str, Any] | None
    max_tokens: int
    history: tuple[Turn, ...] = ()


@dataclass(slots=True)
class FakeBackend:
    """Returns scripted completions in order. Running out of script means "unavailable"."""

    completions: Sequence[str] = ()
    calls: list[FakeCall] = field(default_factory=list)

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        json_schema: Mapping[str, Any] | None,
        max_tokens: int,
        history: Sequence[Turn] = (),
    ) -> str:
        _check_history(history)
        self.calls.append(
            FakeCall(
                system_prompt,
                user_prompt,
                None if json_schema is None else dict(json_schema),
                max_tokens,
                tuple(history),
            )
        )
        index = len(self.calls) - 1
        if index >= len(self.completions):
            raise InferenceError("fake backend has no scripted completion left")
        return _bounded_completion(self.completions[index])
