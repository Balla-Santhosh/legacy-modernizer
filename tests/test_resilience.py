"""Demo-day safety: record/replay of model replies and provider fallback."""

import json
import re

import pytest
from conftest import EXAMPLES, fenced, good

import legacy_modernizer.llm as llm_mod
from legacy_modernizer.cli import main
from legacy_modernizer.llm import CachingLLM, FallbackLLM, ScriptedLLM, _cache_key


class FakeProvider:
    """Stands in for a real API model (LangChainLLM) inside the CLI."""

    calls = 0

    def __init__(self, spec, temperature=0.2, timeout_s=180, retries=5):
        self.spec = spec
        self.usage = llm_mod.UsageMeter()

    def complete(self, system, messages):
        FakeProvider.calls += 1
        stem = re.search(r"File: (\w+)\.c", messages[0]["content"]).group(1)
        return fenced(good(stem))


def _evaluate(capsys, workdir, llm):
    main(["--llm", llm, "--workdir", str(workdir), "evaluate", str(EXAMPLES), "--repairs", "0"])
    return json.loads(capsys.readouterr().out)


def test_record_then_replay_offline(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(llm_mod, "LangChainLLM", FakeProvider)
    FakeProvider.calls = 0
    live = _evaluate(capsys, tmp_path, "fake:model")
    assert FakeProvider.calls == 3
    assert live["first_attempt"]["compile_pass"] == 1.0

    replay = _evaluate(capsys, tmp_path, "replay")       # no provider at all
    assert FakeProvider.calls == 3                         # network never touched
    assert replay["replies_from_recording"] == 3
    assert replay["first_attempt"]["test_pass"] == live["first_attempt"]["test_pass"] == 1.0


def test_replay_without_recording_fails_clearly(tmp_path):
    llm = CachingLLM(None, tmp_path, replay=True)
    with pytest.raises(RuntimeError, match="no recorded reply"):
        llm.complete("sys", [{"role": "user", "content": "hi"}])


def test_cache_key_ignores_timings():
    a = [{"role": "user", "content": '{"speedup": 0.9813, "score": 0.72}'}]
    b = [{"role": "user", "content": '{"speedup": 1.7193, "score": 0.68}'}]
    assert _cache_key("s", a) == _cache_key("s", b)
    assert _cache_key("s", a) != _cache_key("other", a)


def test_fallback_uses_next_provider():
    def busy(system, messages):
        raise RuntimeError("503 UNAVAILABLE")

    backup = ScriptedLLM(["ok"])
    llm = FallbackLLM([ScriptedLLM(busy), backup])
    assert llm.complete("s", [{"role": "user", "content": "x"}]) == "ok"
    assert backup.usage.calls == 1


class _Reply:
    def __init__(self, content, finish="stop"):
        self.content = content
        self.response_metadata = {"finish_reason": finish}


class _FakeChat:
    def __init__(self, replies):
        self.replies = list(replies)

    def invoke(self, _):
        return self.replies.pop(0)


def test_empty_reply_is_retried_and_never_recorded(tmp_path):
    llm = object.__new__(llm_mod.LangChainLLM)          # skip provider setup
    llm.spec, llm.retries, llm.empty_retries, llm.empty_replies = "fake:x", 0, 2, 0
    llm.usage = llm_mod.UsageMeter()
    llm._model = _FakeChat([_Reply("", "length"), _Reply("```cpp\nint main(){}\n```")])
    assert "int main" in llm.complete("s", [{"role": "user", "content": "x"}])
    assert llm.empty_replies == 1

    llm._model = _FakeChat([_Reply("", "length")] * 3)
    cached = CachingLLM(llm, tmp_path)
    assert cached.complete("s", [{"role": "user", "content": "y"}]) == ""
    assert not list(tmp_path.glob("*.json"))               # empty reply was not saved
    assert llm_mod.empty_reply_count(cached) == 4


def test_optimize_explicit_val_split(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(llm_mod, "LangChainLLM", FakeProvider)
    import legacy_modernizer.cli as cli_mod
    seen = {}

    class Spy:
        def __init__(self, *a, **k):
            pass

        def run(self, prompt, train, val, rounds, out, log=print):
            seen["train"], seen["val"] = [p.name for p in train], [p.name for p in val]
            return prompt, []

    monkeypatch.setattr(cli_mod, "PromptOptimizer", Spy)
    main(["--llm", "fake:m", "--workdir", str(tmp_path), "optimize", str(EXAMPLES), "--val", "rpn.c"])
    assert seen["val"] == ["rpn.c"] and set(seen["train"]) == {"primes.c", "wordtool.c"}
    with pytest.raises(SystemExit):
        main(["--llm", "fake:m", "--workdir", str(tmp_path), "optimize", str(EXAMPLES), "--val", "nope.c"])
