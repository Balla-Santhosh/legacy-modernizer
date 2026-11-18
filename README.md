# legacy.c — Optimization-Driven Multi-Agent Assistant for Legacy Code Modernization

Migrates legacy C to modern C++17 with an LLM agent, checks every translation by **differential testing**
against the original program, and uses compiler and test failures in two ways:

- **Repair:** the failures go back to the agent, which fixes its own output.
- **Prompt optimization:** a critic model turns the failures into a *textual gradient* that edits the agent's
  system prompt; an edit is kept only if the score on held-out programs rises.

## Results (13-program hard benchmark, agent gpt-oss-20b)

| Baseline | What it is | Model calls | Compile pass | Test pass | Warnings per file | Score S |
|---|---|---|---|---|---|---|
| B0 | Hand-written prompt, one attempt | 13 | 85% | 82% | 1.6 | 0.65 |
| B1 | B0 + up to 2 repairs from compiler and test feedback | 17 | 100% | 96% | 1.5 | 0.77 |
| B2 | Optimized prompt, one attempt | 13 | 100% | 100% | 2.8 | 0.77 |

`S = 0.4·compile_pass + 0.4·test_pass + 0.1·speedup_term − 0.1·warning_term`

- The optimized prompt passes every test on the first attempt, matching the repair loop's score with fewer calls.
- On the 4 held-out programs, S rose 0.759 → 0.775 → 0.780 over two accepted rounds (tests 92% → 100%).
- Warnings rose because the optimizer added "ignore static-analysis warnings unless they break the build or a
  test"; S weights warnings at only 10%.
- Limits: one run per baseline, a small benchmark we built, and 9 of the 13 programs were used for training.

Settings for all runs: agent `groq:openai/gpt-oss-20b`, critic and editor `groq:openai/gpt-oss-120b`,
`--reasoning-effort low`, `--max-tokens 16000`; held-out files `int_reader.c, bits.c, csv_fields.c, float_accum.c`.

## Reproduce the results offline

Every model reply from the final runs is recorded in `.mod_low/llm_cache/`. Replay mode reuses those replies
with no API key or network, while compiling, testing and scoring run live.

```bash
# B0
modernize --workdir .mod_low --llm replay --max-tokens 16000 --reasoning-effort low evaluate examples/legacy_c_hard --repairs 0
# B1
modernize --workdir .mod_low --llm replay --max-tokens 16000 --reasoning-effort low evaluate examples/legacy_c_hard --repairs 2
# B2
modernize --workdir .mod_low --llm replay --max-tokens 16000 --reasoning-effort low evaluate examples/legacy_c_hard --repairs 0 --prompt opt_runs/low_val/best_prompt.txt
```

Speedup is timed live, so it varies slightly (about 0.97–1.02); everything else matches exactly.

## Setup

Linux or WSL (Ubuntu) on Windows, Python 3.10+:

```bash
sudo apt install -y build-essential clang-tidy cppcheck python3-venv
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,google]" langchain-groq
pytest -q          # 21 tests, run offline with a scripted fake model
```

For new (non-replay) runs, set a key: `export GROQ_API_KEY=...` (free at console.groq.com).

## Commands

```bash
modernize check LEGACY.c CANDIDATE.cpp                 # verify a translation by hand, no LLM
modernize --llm <provider:model> evaluate REPO --repairs N [--prompt FILE]
modernize --llm <provider:model> optimize REPO --rounds N --candidates K --critic-llm <provider:model> --val a.c,b.c
modernize --llm <provider:model> migrate REPO --out DIR
```

`--llm` accepts any LangChain `provider:model`, a comma-separated fallback list, or `replay`.
Reasoning models: use `--max-tokens` and `--reasoning-effort` (empty replies are retried and counted).

## How it works

| Stage | Module | What it does |
|---|---|---|
| Index | `chunking.py`, `index.py` | tree-sitter AST chunks of C/Java in ChromaDB, plus a symbol table for definitions a file calls |
| Migrate | `agent.py`, `prompts.py` | the LLM writes the C++17 file from the source and retrieved context |
| Verify | `verify.py` | g++ build, differential tests against the legacy binary (stdout and exit code), speedup, clang-tidy, cppcheck |
| Repair | `agent.py` | compiler errors and test mismatches go back to the model; the best attempt is kept |
| Optimize | `optimizer.py` | critic writes a textual gradient, editor proposes prompts, accepted only if held-out S rises |
| Score | `scoring.py` | composite score S |
| Models | `llm.py` | LangChain models, retries, timeouts, fallback, record and replay |

## Benchmarks

- `examples/legacy_c/`: 3 easy programs (sanity check).
- `examples/legacy_c_hard/`: 13 programs, each built around a translation trap: exact `printf` formats,
  float vs double, `strtok` skipping empty fields, lenient `atoi`, 32-bit unsigned wraparound, macros that
  evaluate twice, static locals, `goto` cleanup with exit codes, integer promotion, `scanf` stopping rules,
  ring-buffer overwrite, first-seen output order, and a compute-heavy `matmul`. All checked with ASan and
  UBSan to be free of undefined behaviour; 79 test cases in `<name>.tests.json`.

## Repository layout

```
src/legacy_modernizer/   the package
examples/                benchmarks and their test cases
tests/                   pytest suite and reference translations
opt_runs/                optimizer histories (low_val = final run; earlier runs kept as findings)
results/                 B0, B1, B2 outputs
.mod_low/llm_cache/      recorded model replies for offline replay
docs/                    slides, prep guide, project log
```

## Findings from building it

1. Feedback-driven repair works: S 0.65 → 0.77 with 4 extra model calls.
2. An unconstrained critic optimizes what's easiest to measure: early runs told the model to replace `atoi`
   with `std::stoi` and "fix" macros to silence warnings, breaking legacy behaviour. Explicit
   behaviour-preservation rules fixed it.
3. Reasoning models can return empty replies when thinking uses up the token budget; these looked like compile
   failures until counted separately.
4. The held-out set needs headroom: if every held-out program already passes, no prompt can show improvement.

## Next steps

Repeated runs to measure variance, a real open-source C repository, the Java → Python toolchain, and DSPy
(MIPROv2 or GEPA) as baseline B3.

## Team

Balla Santhosh — B.Tech CSE (AI & ML), PES University. *(Add teammates here.)*
