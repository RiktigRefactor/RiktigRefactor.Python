This repo implements the Python side of RiktigRefactor.
The specification is the source of truth: https://github.com/RiktigRefactor/riktigrefactor.spec
Read its `README.md`, `principles.md`, and the page for the refactoring you are changing before you change behavior.
Soundness comes before completeness: refusing is always acceptable, and wrong output never is.

When asked to "build" or "test", run `./build-and-test`.
Also run it automatically before each commit.
For a quick run while working, `python -m pytest -q` in the repo's virtual environment is fine.

## Architecture

The semantic engine is the Python standard library only: `ast` for syntax and positions, and our own scope analysis in `src/riktigrefactor/semantics.py`, cross-checked against CPython's `symtable`.
There are no third-party run-time dependencies; pytest is the only dev dependency.
Edits are text-span replacements computed from `ast` positions, so trivia outside the edits is preserved exactly.

- `protocol.py`: request and result types, `RefusalError`, and the shared refusal codes.
- `workspace.py`: loading a project root, module names, and offset/position conversion (`ast` columns are UTF-8 bytes; protocol columns are Unicode scalar values).
- `semantics.py`: the binding model; every name occurrence and the symbol it binds to.
  See [docs/semantic-model.md](docs/semantic-model.md).
- `verification.py`: re-parse, compile, and the re-binding check that every refactoring runs before returning edits.
- `rename.py` and `extract_iife.py`: the refactorings.
- `cli.py`: the `riktig-py` command; `markers.py`: test selection markers; `diff.py`: unified diffs.

Decisions already made:

- Rename v1 covers names only: locals, parameters, functions, classes, and module globals, including imports across workspace modules.
  Attributes, methods, and fields (anything reached with `obj.name` other than a workspace module) are refused with a code, and this is documented in [docs/limitations.md](docs/limitations.md).
- Extract IIFE (also called extract no-capture lambda) generates a lambda or nested function that captures nothing from enclosing function scopes: every local it reads is a parameter, and every local it writes that is read afterwards is returned and assigned back.
  Module globals and builtins are looked up by name, unless a local shadows them.
  The generated function must have no free variables (verify with `symtable`).
- The target is the latest Python (3.15 now); the code must work on 3.13 and later.
- The PyPI package is `riktigrefactor`, the import is `riktigrefactor`, and the command is `riktig-py`.

## Test cases

Cases are directories under `tests/cases/<refactoring>/<group>/<case>/`, in the [specification's test format](https://github.com/RiktigRefactor/riktigrefactor.spec/blob/main/test-format.md).
Each holds a `case.json`, an `input/` directory, and an `expected/` directory unless a refusal is expected.
The program's entry point is `main.py`; every input and expected file set is a complete program that raises (an `assert`) if its behavior is wrong.
The selection is marked with a trailing comment: `# [text]` (or `# [text]#2` for the second occurrence), `# |name` for a cursor, or whole lines between `# [` and `# ]` lines.
To create the `expected/` directory for a new case, run the tests once with `RIKTIG_WRITE_EXPECTED=1`, then read the output and confirm it is correct and behavior-preserving before keeping it.
Edge cases set `"naiveShouldFail": true`, so the tests prove the assertion can detect the problem; the naive implementations are in `tests/naive.py`.
Cases cite the Language Reference in their `spec` field; see [docs/building-and-testing.md](docs/building-and-testing.md).

## Secrets

Always obscure API keys and other secrets, especially in saved screenshots.

## Python

The most important thing about a name is that it not be misleading.
A reader should never need to look at how a variable or function is used or implemented to understand what it represents.
It is OK to make the name long to achieve this.
If you see a comment explaining what a function or variable does or is, rename it to make it more obvious.

Avoid the conditional expression (`x if c else y`) except for very simple cases.
See the `python` skill for pitfalls with `ast` positions and scopes.

## Committing

Before committing, run `./build-and-test`.
If the change has more than one thing going on, split it into multiple commits, each with a clear purpose.
Especially separate refactoring from behavior changes.
See [CONTRIBUTING.md](CONTRIBUTING.md) for the commit notation convention.

## Cloud sessions

- `gh pr create` is blocked in cloud sessions (it uses GraphQL).
  Open pull requests with `gh api repos/OWNER/REPO/pulls -f title=... -f head=... -f base=main -f body=...`.
- Cloud sessions reach the network only through an allowlisting proxy.
  Hosts needed: PyPI (`pypi.org`, `files.pythonhosted.org`).

## After every task

At the end of every task report on all of these, briefly:
- Skills used: name them.
- Skill gaps: if a skill you wished existed would have helped, propose one, even briefly.
- Prompt feedback: one concrete way the request could have been made more effectively this time — skip it only if there's genuinely nothing worth saying.
- Questions, ideas, concerns: surface them as they come up, not just at the end.
- Changes to your skills and instructions that would reduce token usage or improve efficiency.

Treat this end-of-task report as mandatory, like a checklist item — don't let it get crowded out by concise-output-style guidance; it's a small fixed addition, not a violation of terseness.

Never use Claude Code's persistent memory system for this project.
Durable guidance (conventions, process corrections, preferences) belongs in-repo instead — this file or a skill — so it's visible in version control and to every contributor, not just stored privately for one user.

## Decisions

When you need input on a decision:
- First, pick the option you think is best and propose it. Start that message with `⭐ 1: `
- Also list the alternatives you rejected, each with a brief reason why. Start each with `❌ n:`

Then have a discussion.
This formatting applies every time you present a decision, even a quick one — don't let a short or informal-feeling exchange skip it.

## To-do list

The claude.ai project "RiktigRefactor" holds the only to-do list, in its `claude/todo.md` doc.
It is the source of truth for open decisions and remaining work, across all repos.
Don't keep a copy in this repo, so there is only one list to keep current.
