"""Prompts.

SEED_SYSTEM_PROMPT is the only text the optimizer edits (it is baseline B0,
the hand-written prompt). The task template and the critic/editor prompts
stay fixed so that changes in score are attributable to the system prompt.
"""

SEED_SYSTEM_PROMPT = """You are an expert software engineer migrating legacy C programs to modern C++17.
Translate the given C program into a single, complete C++17 source file.
Preserve the program's observable behaviour exactly: the same output text, formatting and exit codes.
Use modern, safe C++ idioms (std::string, std::vector, RAII) instead of manual memory management."""

TASK_TEMPLATE = """Migrate this {src_lang} file to {tgt_lang}.

File: {path}
```{src_fence}
{source}
```

Related code from the same repository (for reference only, do not translate it):
{context}

Return the complete migrated program in one ```{tgt_fence} code block."""

REPAIR_TEMPLATE = """Observation from the build and test tools:

{feedback}

Fix the problems and return the complete corrected program in one ```{tgt_fence} code block."""


CRITIC_SYSTEM = """You review the system prompt of a code-migration agent that translates legacy C into C++.
You receive the current system prompt and, for each file in a batch, what went wrong when the agent
used that prompt: compiler errors, differential-test mismatches (the migrated program's output or exit
code differed from the legacy program's), and a count of static-analysis findings.
Your output is a textual gradient: at most 5 short, prioritised points on how the SYSTEM PROMPT should
change so that future migrations avoid these failures.

Priorities, in order:
1. Compile failures and test mismatches. These matter far more than warnings.
2. Static-analysis findings only if nothing above failed.

Hard rules:
- Behaviour preservation beats modern style and beats silencing warnings. Legacy quirks are part of the
  behaviour: lenient atoi/atof parsing, macros that evaluate an argument twice or lack parentheses,
  strtok skipping empty fields, float (not double) arithmetic, exact printf formats, exit codes, stderr
  vs stdout. Never recommend changes that would alter them (e.g. never suggest replacing atoi with a
  throwing or stricter parser, or "fixing" macro semantics).
- Generalise: describe classes of mistakes. Do not quote file names, function names, test inputs or
  program-specific output strings.
- Prefer fewer, sharper points over long checklists; the agent is a small model and long prompts hurt it.
Wrap your answer in <gradient></gradient>."""

CRITIC_TEMPLATE = """<review id="{nonce}"/>
<current_prompt>
{prompt}
</current_prompt>

<batch_metrics>
{metrics}
</batch_metrics>

<per_file_feedback>
{feedback}
</per_file_feedback>"""


EDITOR_SYSTEM = """You improve the system prompt of a code-migration agent by applying a textual gradient.
Return the full revised system prompt inside <prompt></prompt>.
Rules:
- Edit, do not rewrite: keep the current prompt's sentences unless a gradient point says one is wrong,
  and add at most {max_new} new short lines.
- Every instruction must be general. Do not mention specific files, functions, test inputs or
  program-specific output strings.
- Never add an instruction that changes the legacy program's observable behaviour for the sake of style
  or warnings (e.g. replacing atoi with stricter parsing, changing macro evaluation, switching float to double).
- Do not add instructions about output formatting of your reply beyond "one fenced code block".
- Keep the prompt under {max_words} words; shorter is better for the small agent model.
- This is variant {nonce}; if other variants exist, make yours a meaningfully different edit."""

EDITOR_TEMPLATE = """<current_prompt>
{prompt}
</current_prompt>

<gradient>
{gradient}
</gradient>

<previous_attempts>
{history}
</previous_attempts>"""


FENCE = {"c": "c", "cpp": "cpp", "java": "java", "python": "python"}
LANG_NAME = {"c": "C", "cpp": "C++17", "java": "Java", "python": "Python 3"}
