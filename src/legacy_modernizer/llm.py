"""Provider-agnostic LLM layer.

Every agent in the system talks to an `LLM`: a system prompt plus a list of
chat turns in, text out. `LangChainLLM` wraps any chat model LangChain can
build ("openai:gpt-4o-mini", "anthropic:...", "ollama:...") and
`ScriptedLLM` is a deterministic offline double used in tests and dry runs.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable, Protocol, Sequence

Message = dict  # {"role": "user" | "assistant", "content": str}


class LLM(Protocol):
    def complete(self, system: str, messages: Sequence[Message]) -> str: ...


@dataclass
class UsageMeter:
    """Counts calls and characters so 'iterations and API cost' (slide 9) can be reported."""

    calls: int = 0
    prompt_chars: int = 0
    completion_chars: int = 0

    def record(self, system: str, messages: Sequence[Message], reply: str) -> None:
        self.calls += 1
        self.prompt_chars += len(system) + sum(len(m["content"]) for m in messages)
        self.completion_chars += len(reply)

    def as_dict(self) -> dict:
        return {
            "calls": self.calls,
            "prompt_chars": self.prompt_chars,
            "completion_chars": self.completion_chars,
            # ~4 chars/token is a rough but common estimate
            "approx_tokens": (self.prompt_chars + self.completion_chars) // 4,
        }


class LangChainLLM:
    def __init__(self, spec: str, temperature: float = 0.2, timeout_s: float = 180, retries: int = 5,
                 empty_retries: int = 2, **model_kwargs):
        """model_kwargs go straight to the provider, e.g. max_tokens=16000, reasoning_effort="low"."""
        from langchain.chat_models import init_chat_model

        provider, _, model = spec.partition(":")
        if not model:
            raise ValueError(f"LLM spec must look like 'provider:model', got {spec!r}")
        self.spec = spec
        self.retries = retries
        self.empty_retries = empty_retries
        self.empty_replies = 0  # how many empty replies were received (reported by `evaluate`)
        # timeout: give up on a single request after this many seconds, then retry (see complete())
        self._model = init_chat_model(model, model_provider=provider, temperature=temperature,
                                      timeout=timeout_s, **model_kwargs)
        self.usage = UsageMeter()

    def _invoke(self, lc):
        for attempt in range(self.retries + 1):
            try:
                return self._model.invoke(lc)
            except Exception as e:
                msg = f"{type(e).__name__} {e}"
                timed_out = "timeout" in msg.lower() or "timed out" in msg.lower()
                transient = timed_out or any(c in msg for c in (
                    "503", "429", "500", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "INTERNAL"))
                if attempt == self.retries or not transient:
                    raise
                wait = 10 * 2 ** attempt   # 10s, 20s, 40s, 80s, 160s
                why = "no reply (timed out)" if timed_out else "model busy"
                print(f"  [{self.spec}] {why}, retrying in {wait}s ...", file=sys.stderr, flush=True)
                time.sleep(wait)

    def complete(self, system: str, messages: Sequence[Message]) -> str:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        lc = [SystemMessage(system)]
        for m in messages:
            lc.append(HumanMessage(m["content"]) if m["role"] == "user" else AIMessage(m["content"]))
        text = ""
        for attempt in range(self.empty_retries + 1):
            reply = self._invoke(lc)
            text = reply.content if isinstance(reply.content, str) else "".join(
                part.get("text", "") for part in reply.content if isinstance(part, dict))
            if text.strip():
                break
            # Reasoning models can spend their whole token budget "thinking" and return no answer.
            self.empty_replies += 1
            meta = getattr(reply, "response_metadata", {}) or {}
            reason = meta.get("finish_reason") or meta.get("stop_reason") or "?"
            more = "retrying" if attempt < self.empty_retries else "giving up"
            hint = " (hit the token limit: try --max-tokens or --reasoning-effort low)" if reason in (
                "length", "max_tokens") else ""
            print(f"  [{self.spec}] empty reply, finish_reason={reason}{hint}; {more}",
                  file=sys.stderr, flush=True)
        self.usage.record(system, messages, text)
        return text


@dataclass
class ScriptedLLM:
    """Replays canned replies in order, or calls a function of (system, messages).

    Lets the whole pipeline (agent, repair loop, optimizer) run without an API key.
    """

    replies: list[str] | Callable[[str, Sequence[Message]], str] = field(default_factory=list)
    usage: UsageMeter = field(default_factory=UsageMeter)
    log: list[tuple[str, list[Message]]] = field(default_factory=list)

    def complete(self, system: str, messages: Sequence[Message]) -> str:
        self.log.append((system, list(messages)))
        if callable(self.replies):
            reply = self.replies(system, messages)
        else:
            if not self.replies:
                raise RuntimeError("ScriptedLLM ran out of replies")
            reply = self.replies.pop(0)
        self.usage.record(system, messages, reply)
        return reply


class FallbackLLM:
    """Tries each provider in order; moves to the next when one keeps failing."""

    def __init__(self, llms: list[LLM]):
        self.llms = llms
        self.usage = UsageMeter()

    def complete(self, system: str, messages: Sequence[Message]) -> str:
        last: Exception | None = None
        for llm in self.llms:
            try:
                reply = llm.complete(system, messages)
                self.usage.record(system, messages, reply)
                return reply
            except Exception as e:  # noqa: BLE001 - any provider failure -> try the next one
                last = e
                print(f"  [{getattr(llm, 'spec', llm)}] failed ({type(e).__name__}); trying next provider",
                      file=sys.stderr, flush=True)
        raise RuntimeError("all LLM providers failed") from last


_FLOAT = re.compile(r"\d+\.\d+")


def empty_reply_count(llm) -> int:
    """Total empty replies seen by an LLM, looking through cache/fallback wrappers."""
    if llm is None:
        return 0
    n = getattr(llm, "empty_replies", 0) if isinstance(llm, LangChainLLM) else 0
    n += empty_reply_count(getattr(llm, "inner", None))
    return n + sum(empty_reply_count(x) for x in getattr(llm, "llms", []))


def _cache_key(system: str, messages: Sequence[Message]) -> str:
    # Decimal numbers (timings, speedups, scores) vary run to run; mask them so a replay still matches.
    blob = json.dumps([system, [[m["role"], m["content"]] for m in messages]])
    return hashlib.sha256(_FLOAT.sub("#", blob).encode()).hexdigest()[:32]


class CachingLLM:
    """Records every successful reply to disk; in replay mode answers only from that record.

    record (default): call the real model, save the reply.
    replay          : never touch the network; answer from saved replies (for offline demos and
                      exactly reproducible re-runs). Compilation, tests and analysis still run live.
    """

    def __init__(self, inner: LLM | None, cache_dir: Path, replay: bool = False):
        self.inner = inner
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.replay = replay
        self.hits = 0
        self.usage = getattr(inner, "usage", None) or UsageMeter()

    def complete(self, system: str, messages: Sequence[Message]) -> str:
        f = self.dir / f"{_cache_key(system, messages)}.json"
        if f.exists():
            saved = json.loads(f.read_text())["reply"]
            if saved.strip():  # older versions recorded empty replies; ignore and re-ask those
                self.hits += 1
                return saved
        if self.replay or self.inner is None:
            raise RuntimeError(
                f"replay mode: no recorded reply for this request ({f.name}). "
                "Run the same command once with a real --llm to record it.")
        reply = self.inner.complete(system, messages)
        if not reply.strip():
            return reply  # never record an empty reply, so a later run asks again
        f.write_text(json.dumps({"model": getattr(self.inner, "spec", "?"), "reply": reply,
                                 "system": system, "messages": list(messages)}, indent=1))
        return reply


def build_llm(spec: str, temperature: float = 0.2, cache_dir: Path | None = None, **model_kwargs) -> LLM:
    """spec: 'provider:model', a comma-separated fallback list of those, 'replay', or 'scripted'."""
    if spec == "scripted":
        return ScriptedLLM()
    if spec == "replay":
        if cache_dir is None:
            raise ValueError("replay needs a cache directory")
        return CachingLLM(None, cache_dir, replay=True)
    specs = [x.strip() for x in spec.split(",") if x.strip()]
    if len(specs) == 1:
        llm: LLM = LangChainLLM(specs[0], temperature=temperature, **model_kwargs)
    else:  # with a backup available, give up on each provider sooner (~30 s of retries)
        llm = FallbackLLM([LangChainLLM(x, temperature=temperature, timeout_s=90, retries=2, **model_kwargs)
                           for x in specs])
    return CachingLLM(llm, cache_dir) if cache_dir is not None else llm


_FENCE = re.compile(r"```[ \t]*([A-Za-z0-9_+#-]*)[^\n]*\n(.*?)```", re.DOTALL)


def extract_code(text: str, preferred: Sequence[str] = ("cpp", "c++", "cxx", "python", "py")) -> str:
    """Return the most relevant fenced code block from a reply (or the whole text if none)."""
    blocks = _FENCE.findall(text)
    if not blocks:
        return text.strip()
    for lang, body in blocks:
        if lang.lower() in preferred:
            return body.strip() + "\n"
    # fall back to the longest block
    return max(blocks, key=lambda b: len(b[1]))[1].strip() + "\n"


def extract_tag(text: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL)
    return m.group(1).strip() if m else None
