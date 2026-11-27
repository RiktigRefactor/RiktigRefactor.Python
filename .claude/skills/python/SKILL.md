---
name: python
description: Use whenever writing or changing Python code in this repo, especially the scope analysis in semantics.py or anything that converts between ast positions and text offsets.
---

# Python in this repo

- Target the latest Python (the `.mise.toml` pin); code must also run on 3.13.
- The standard library only at run time: `ast` for syntax and positions, `symtable` to cross-check scopes. Pytest is the only dev dependency.
- `ast` columns are UTF-8 byte offsets. Never use `col_offset` as an index into a `str`; use `SourceFile.offset_of_ast_position`, `start_offset`, and `end_offset`.
- Never split source with `str.splitlines()`; Python's tokenizer ends lines only at `\n`, `\r\n` and `\r`.
- The parser NFKC-normalizes identifiers, so a name in the tree can be spelled differently in the text; use the spelling from the text for edits.
- `ast` stores some names without positions (`def` and `class` names, `global` and `nonlocal` names, import aliases, `except ... as` names, match captures); find them with `name_locations.py`.
- Private names (`__x`) are mangled inside classes; compare `Symbol.name`, not the spelling.
- A function named `top` confuses `symtable.Symbol.is_global` (it treats the function as the module); see `symtable_check.py`.
- Do not import a refactoring function into a package namespace under the module's own name.
- Use `python -m pytest -q` for a quick run; `./build-and-test` before committing.
