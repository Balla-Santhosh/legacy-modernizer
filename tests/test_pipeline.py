import json
import re
from pathlib import Path

from conftest import EXAMPLES, FIXTURES, fenced, good

from legacy_modernizer.agent import MigrationAgent
from legacy_modernizer.chunking import chunk_source
from legacy_modernizer.cli import find_programs, main
from legacy_modernizer.index import CodeIndex
from legacy_modernizer.llm import ScriptedLLM, extract_code, extract_tag
from legacy_modernizer.optimizer import PromptOptimizer, split_units
from legacy_modernizer.prompts import SEED_SYSTEM_PROMPT
from legacy_modernizer.scoring import score_batch
from legacy_modernizer.verify import build_baseline, verify


# ---------------------------------------------------------------- chunking / index
def test_chunker_finds_c_units():
    chunks = chunk_source((EXAMPLES / "rpn.c").read_text(), "rpn.c", "c")
    kinds = {(c.kind, c.name) for c in chunks}
    assert {("struct", "node"), ("function", "push"), ("function", "pop"), ("function", "main")} <= kinds
    main_chunk = next(c for c in chunks if c.name == "main")
    assert {"push", "pop", "strtok", "strtod"} <= set(main_chunk.refs)


def test_chunker_java():
    src = "class Acc { int total; void add(int x){ total += x; log(x);} static void log(int v){} }"
    names = {c.name for c in chunk_source(src, "Acc.java", "java")}
    assert names == {"Acc.total", "Acc.add", "Acc.log"}


def test_index_retrieves_cross_file_definition(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.c").write_text("int scale(int);\nint main(void){ return scale(2); }\n")
    (repo / "util.c").write_text("int scale(int x){ return x * 3; }\nint unrelated(void){ return 0; }\n")
    ix = CodeIndex(tmp_path / "ix")
    assert ix.build(repo, "c") == 4
    ctx = ix.context_for((repo / "main.c").read_text(), "main.c", "c", k=1)
    assert len(ctx) == 1 and "scale(int x)" in ctx[0]


def test_find_programs():
    assert {p.name for p in find_programs(EXAMPLES, "c")} == {"wordtool.c", "rpn.c", "primes.c"}


# ---------------------------------------------------------------- verification / scoring
def test_reference_migrations_pass(settings):
    for stem in ("wordtool", "rpn", "primes"):
        base = build_baseline(EXAMPLES / f"{stem}.c", settings.work_dir / stem / "legacy", settings)
        v = verify(good(stem), base, settings.work_dir / stem / "cand", settings)
        assert v.compile.ok and v.tests.rate == 1.0, v.feedback_text()


def test_compile_error_and_semantic_drift_detected(settings):
    base = build_baseline(EXAMPLES / "wordtool.c", settings.work_dir / "legacy", settings)
    broken = verify(good("wordtool").replace("return 2;", "return 2"), base, settings.work_dir / "b", settings)
    assert not broken.compile.ok and broken.compile.errors >= 1
    assert "COMPILE FAILED" in broken.feedback_text()

    drift = verify(good("wordtool").replace("return 2;", "return 1;"), base, settings.work_dir / "d", settings)
    assert drift.compile.ok and drift.tests.passed == 5
    assert "exit 1 != expected 2" in drift.feedback_text()


def test_static_analysis_flags_legacy_idioms(settings):
    base = build_baseline(EXAMPLES / "primes.c", settings.work_dir / "legacy", settings)
    c_style = (EXAMPLES / "primes.c").read_text()  # C compiles as C++, but analyzers should complain
    v = verify(c_style, base, settings.work_dir / "c", settings)
    assert v.compile.ok and v.tests.rate == 1.0
    tidy = next(a for a in v.analysis if a.tool == "clang-tidy")
    assert any("malloc" in f or "owning" in f or "calloc" in f for f in tidy.findings), tidy.findings


def test_score_formula(settings):
    w = settings.weights
    base = build_baseline(EXAMPLES / "rpn.c", settings.work_dir / "legacy", settings)
    ok = verify(good("rpn"), base, settings.work_dir / "ok", settings)
    bad = verify("int main( {", base, settings.work_dir / "bad", settings)
    m = score_batch([ok, bad], w)
    assert m.compile_pass == 0.5 and m.test_pass == 0.5
    assert abs(m.score - (w.compile_pass * 0.5 + w.test_pass * 0.5 + w.speedup * m.speedup_term
                          - w.warnings * m.warning_term)) < 1e-3


# ---------------------------------------------------------------- llm helpers
def test_extract_helpers():
    assert extract_code("x\n```c\nint a;\n```\n```cpp\nint b;\n```") == "int b;\n"
    assert extract_tag("blah <prompt> new </prompt>", "prompt") == "new"


# ---------------------------------------------------------------- agent
def test_agent_repairs_after_compile_error(settings):
    broken = good("rpn").replace("return 0;\n}", "return 0\n}")
    llm = ScriptedLLM([fenced(broken), fenced(good("rpn"))])
    agent = MigrationAgent(llm, settings, CodeIndex(settings.index_dir))
    r = agent.migrate(EXAMPLES / "rpn.c", SEED_SYSTEM_PROMPT)
    assert r.succeeded and len(r.steps) == 2
    assert not r.first.compile.ok
    # the second call carried the compiler output back to the model
    repair_turn = llm.log[1][1][-1]["content"]
    assert "COMPILE FAILED" in repair_turn and "expected" in repair_turn


def test_agent_stops_at_repair_budget(settings):
    llm = ScriptedLLM(lambda system, msgs: fenced("int main( {"))
    r = MigrationAgent(llm, settings).migrate(EXAMPLES / "primes.c", SEED_SYSTEM_PROMPT, max_repairs=1)
    assert not r.succeeded and len(r.steps) == 2 and llm.usage.calls == 2


# ---------------------------------------------------------------- optimizer
MARKER = "Preserve exit codes and stderr/stdout separation exactly."


def _task_llm(system, msgs):
    """Toy 'model': only produces behaviour-preserving code once the prompt contains MARKER."""
    stem = re.search(r"File: (\w+)\.c", msgs[0]["content"]).group(1)
    code = good(stem)
    if MARKER not in system:
        code = code.replace("return 1;", "return 0;", 1).replace("return 2;", "return 0;", 1)
    return fenced(code)


def _critic(system, msgs):
    if system.startswith("You review"):  # critic call; editor calls start "You improve"
        assert "exit" in msgs[0]["content"]  # critic sees the differential-test feedback
        return "<gradient>1. Failures come from changed exit codes; tell the agent to keep them.</gradient>"
    current = re.search(r"<current_prompt>\n(.*?)\n</current_prompt>", msgs[0]["content"], re.S).group(1)
    return f"<prompt>{current}\n{MARKER}</prompt>"


def test_optimizer_improves_prompt(settings, tmp_path):
    agent = MigrationAgent(ScriptedLLM(_task_llm), settings)
    opt = PromptOptimizer(agent, ScriptedLLM(_critic), candidates=1)
    train, val = split_units(find_programs(EXAMPLES, "c"))
    assert train and val and not set(train) & set(val)
    logs = []
    best, history = opt.run(SEED_SYSTEM_PROMPT, train, val, rounds=2, out_dir=tmp_path / "opt", log=logs.append)
    assert MARKER in best
    assert history[0].accepted
    data = json.loads((tmp_path / "opt" / "history.json").read_text())
    assert data["curve"][-1]["val"]["score"] > data["curve"][0]["val"]["score"]


def test_cli_check(capsys, tmp_path):
    main(["--workdir", str(tmp_path), "check", str(EXAMPLES / "wordtool.c"), str(FIXTURES / "wordtool_good.cpp")])
    out = capsys.readouterr().out
    assert '"tests_passed": 6' in out


def test_hard_benchmark_builds_and_is_deterministic(settings):
    hard = EXAMPLES.parent / "legacy_c_hard"
    programs = find_programs(hard, "c")
    assert len(programs) == 13
    for src in programs:
        a = build_baseline(src, settings.work_dir / src.stem / "a", settings)
        b = build_baseline(src, settings.work_dir / src.stem / "b", settings)
        assert [(r.stdout, r.returncode) for r in a.runs] == [(r.stdout, r.returncode) for r in b.runs], src.name


def test_agent_keeps_best_attempt_and_flags_empty_reply(settings):
    drift = good("rpn").replace('std::printf("error\\n");', 'std::printf("ERR\\n");')
    broken = good("rpn").replace("return 0;\n}", "return 0\n}")
    llm = ScriptedLLM([fenced(drift), "", fenced(broken)])
    r = MigrationAgent(llm, settings).migrate(EXAMPLES / "rpn.c", SEED_SYSTEM_PROMPT, max_repairs=2)
    assert len(r.steps) == 3
    assert r.best_index == 0 and r.final.compile.ok and 0 < r.final.tests.rate < 1
    assert not r.steps[1].verification.compile.ok
    assert "no code" in llm.log[2][1][-1]["content"]          # model was told its reply had no code
    assert not r.steps[2].verification.compile.ok and r.steps[2].verification.compile.errors >= 1
