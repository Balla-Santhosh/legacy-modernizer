"""Command line interface.

  modernize index    REPO                      build the AST + ChromaDB index
  modernize check    LEGACY.c CANDIDATE.cpp    verify a translation by hand (no LLM)
  modernize migrate  REPO --out DIR            migrate every program in REPO
  modernize evaluate REPO [--prompt F]         score a prompt (baselines B0/B1)
  modernize optimize REPO --rounds N --out DIR run the prompt optimization loop
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import MigrationAgent, save_result
from .chunking import chunk_source, iter_source_files
from .config import Settings
from .index import CodeIndex
from .llm import build_llm, empty_reply_count
from .optimizer import PromptOptimizer, split_units
from .prompts import SEED_SYSTEM_PROMPT
from .scoring import score_batch
from .verify import build_baseline, verify


def find_programs(repo: Path, lang: str) -> list[Path]:
    """Translation units = source files that define main()."""
    if repo.is_file():
        return [repo]
    out = []
    for p in iter_source_files(repo, lang):
        if lang == "c" and p.suffix != ".c":
            continue
        if any((c.kind == "function" and c.name == "main") or c.name.endswith(".main")
               for c in chunk_source(p.read_text(errors="replace"), p.name, lang)):
            out.append(p)
    return out


def _settings(a) -> Settings:
    s = Settings(llm=a.llm, max_repairs=getattr(a, "repairs", 2))
    s.work_dir = Path(a.workdir) / "work"
    s.index_dir = Path(a.workdir) / "index"
    return s


def _index(repo: Path, s: Settings, rebuild: bool = False) -> CodeIndex:
    ix = CodeIndex(s.index_dir)
    if rebuild or len(ix) == 0:
        n = ix.build(repo if repo.is_dir() else repo.parent, s.source_lang)
        print(f"indexed {n} chunks", file=sys.stderr)
    return ix


def _model_kwargs(a) -> dict:
    kw = {}
    if getattr(a, "max_tokens", None):
        kw["max_tokens"] = a.max_tokens
    if getattr(a, "reasoning_effort", None):
        kw["reasoning_effort"] = a.reasoning_effort
    return kw


def _cache(a) -> Path:
    """Every real model reply is recorded here; `--llm replay` answers from it with no network."""
    return Path(a.workdir) / "llm_cache"


def _prompt(a) -> str:
    return Path(a.prompt).read_text() if getattr(a, "prompt", None) else SEED_SYSTEM_PROMPT


def cmd_index(a):
    s = _settings(a)
    _index(Path(a.repo), s, rebuild=True)


def cmd_check(a):
    s = _settings(a)
    base = build_baseline(Path(a.legacy), s.work_dir / "check" / "legacy", s)
    v = verify(Path(a.candidate).read_text(), base, s.work_dir / "check" / "candidate", s)
    print(json.dumps(v.summary(), indent=2))
    print(v.feedback_text())


def cmd_migrate(a):
    s = _settings(a)
    repo = Path(a.repo)
    agent = MigrationAgent(build_llm(s.llm, s.temperature, _cache(a), **_model_kwargs(a)), s, _index(repo, s))
    results = []
    for src in find_programs(repo, s.source_lang):
        r = agent.migrate(src, _prompt(a), rel=str(src.relative_to(repo)) if repo.is_dir() else src.name)
        save_result(r, Path(a.out))
        results.append(r)
        print(f"{r.path}: {'OK' if r.succeeded else 'FAILED'} after {len(r.steps) - 1} repairs  {r.final.summary()}")
    m = score_batch([r.final for r in results], s.weights)
    print(json.dumps(m.as_dict(), indent=2))


def cmd_evaluate(a):
    s = _settings(a)
    repo = Path(a.repo)
    agent = MigrationAgent(build_llm(s.llm, s.temperature, _cache(a), **_model_kwargs(a)), s, _index(repo, s))
    results = []
    for p in find_programs(repo, s.source_lang):
        print(f"migrating {p.name} ...", file=sys.stderr, flush=True)
        r = agent.migrate(p, _prompt(a), tag=f"eval_r{a.repairs}")
        note = f" (kept attempt {r.best_index} of {len(r.steps)})" if len(r.steps) > 1 else ""
        print(f"  {p.name}: {r.final.summary()}{note}", file=sys.stderr, flush=True)
        results.append(r)
    first = score_batch([r.first for r in results], s.weights)
    final = score_batch([r.final for r in results], s.weights)
    print(json.dumps({"first_attempt": first.as_dict(), "after_repairs": final.as_dict(),
                      "llm_usage": getattr(agent.llm, "usage", None) and agent.llm.usage.as_dict(),
                      "replies_from_recording": getattr(agent.llm, "hits", 0),
                      "empty_replies": empty_reply_count(agent.llm)},
                     indent=2))


def cmd_optimize(a):
    s = _settings(a)
    repo = Path(a.repo)
    agent = MigrationAgent(build_llm(s.llm, s.temperature, _cache(a), **_model_kwargs(a)), s, _index(repo, s))
    critic = build_llm(a.critic_llm or s.llm, 0.7, _cache(a), **_model_kwargs(a))
    units = find_programs(repo, s.source_lang)
    if a.val:  # explicit held-out files, e.g. --val int_reader.c,bits.c
        names = {x.strip() for x in a.val.split(",") if x.strip()}
        unknown = names - {u.name for u in units}
        if unknown:
            raise SystemExit(f"--val: not found in {repo}: {', '.join(sorted(unknown))}")
        val = [u for u in units if u.name in names]
        train = [u for u in units if u.name not in names]
    else:
        train, val = split_units(units, a.val_fraction)
    print(f"train: {[p.name for p in train]}\nval:   {[p.name for p in val]}", file=sys.stderr)
    opt = PromptOptimizer(agent, critic, repairs_during_opt=a.opt_repairs, candidates=a.candidates)
    best, _ = opt.run(_prompt(a), train, val, a.rounds, Path(a.out))
    print(f"empty replies from the agent model: {empty_reply_count(agent.llm)}", file=sys.stderr)
    print("\n=== best prompt ===\n" + best)


def main(argv=None):
    p = argparse.ArgumentParser(prog="modernize", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--llm", default=Settings.llm, help="provider:model, a comma-separated fallback list "
                   "(e.g. 'google_genai:gemini-3.8-flash,groq:llama-3.3-70b-versatile'), "
                   "or 'replay' to reuse recorded replies offline (default %(default)s)")
    p.add_argument("--workdir", default=".modernizer")
    p.add_argument("--max-tokens", type=int, help="output token budget per reply (reasoning models need room)")
    p.add_argument("--reasoning-effort", choices=["low", "medium", "high"],
                   help="for reasoning models such as gpt-oss: less thinking leaves more room for the answer")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("index"); sp.add_argument("repo"); sp.set_defaults(fn=cmd_index)
    sp = sub.add_parser("check"); sp.add_argument("legacy"); sp.add_argument("candidate")
    sp.set_defaults(fn=cmd_check)

    for name, fn in (("migrate", cmd_migrate), ("evaluate", cmd_evaluate)):
        sp = sub.add_parser(name); sp.add_argument("repo"); sp.add_argument("--prompt")
        sp.add_argument("--repairs", type=int, default=2)
        if name == "migrate":
            sp.add_argument("--out", default="migrated")
        sp.set_defaults(fn=fn)

    sp = sub.add_parser("optimize"); sp.add_argument("repo"); sp.add_argument("--prompt")
    sp.add_argument("--rounds", type=int, default=5); sp.add_argument("--out", default="opt_runs")
    sp.add_argument("--critic-llm"); sp.add_argument("--candidates", type=int, default=2)
    sp.add_argument("--opt-repairs", type=int, default=0)
    sp.add_argument("--val-fraction", type=float, default=0.34)
    sp.add_argument("--val", help="comma-separated held-out files (overrides --val-fraction); "
                                  "include some files the seed prompt fails, or there is nothing to improve")
    sp.set_defaults(fn=cmd_optimize)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
