"""AST-based chunking of legacy source (slide 7, step 2; after cAST, 2025).

Each chunk is one syntactic unit: a function, a struct/typedef, a global,
or a Java method/field. Small adjacent top-level items (includes, macros)
are merged into a single "preamble" chunk. Every chunk records the
identifiers it defines and the ones it references, so retrieval can pull in
the definitions a file depends on.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from tree_sitter import Language, Node, Parser

SUFFIXES = {"c": (".c", ".h"), "java": (".java",)}


@lru_cache(maxsize=None)
def _parser(lang: str) -> Parser:
    if lang == "c":
        import tree_sitter_c as ts
    elif lang == "java":
        import tree_sitter_java as ts
    else:
        raise ValueError(f"unsupported source language: {lang}")
    return Parser(Language(ts.language()))


@dataclass
class Chunk:
    path: str
    lang: str
    kind: str
    name: str
    start_line: int
    end_line: int
    text: str
    defines: list[str] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        h = hashlib.sha1(f"{self.path}:{self.start_line}:{self.text}".encode()).hexdigest()[:12]
        return f"{Path(self.path).name}:{self.name}:{h}"

    def header(self) -> str:
        return f"// {self.path} lines {self.start_line}-{self.end_line} ({self.kind} {self.name})"


def _text(node: Node) -> str:
    return node.text.decode("utf-8", errors="replace")


def _walk(node: Node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def _declarator_name(node: Node | None) -> str | None:
    """Dig through C declarators (pointer, function, array) to the identifier."""
    while node is not None:
        if node.type in ("identifier", "field_identifier", "type_identifier"):
            return _text(node)
        node = node.child_by_field_name("declarator") or next(
            (c for c in node.named_children if "declarator" in c.type or c.type == "identifier"), None
        )
    return None


def _refs(node: Node, lang: str) -> list[str]:
    seen: dict[str, None] = {}
    for n in _walk(node):
        if lang == "c":
            if n.type == "call_expression":
                fn = n.child_by_field_name("function")
                if fn is not None and fn.type == "identifier":
                    seen[_text(fn)] = None
            elif n.type == "type_identifier":
                seen[_text(n)] = None
        else:
            if n.type == "method_invocation":
                nm = n.child_by_field_name("name")
                if nm is not None:
                    seen[_text(nm)] = None
            elif n.type == "type_identifier":
                seen[_text(n)] = None
    return list(seen)


def _c_item(node: Node) -> tuple[str, str] | None:
    """Classify a top-level C node -> (kind, name), or None for preamble material."""
    t = node.type
    if t == "function_definition":
        return "function", _declarator_name(node.child_by_field_name("declarator")) or "anon"
    if t == "type_definition":
        return "typedef", _declarator_name(node.child_by_field_name("declarator")) or "anon"
    if t in ("struct_specifier", "union_specifier", "enum_specifier"):
        nm = node.child_by_field_name("name")
        return t.split("_")[0], _text(nm) if nm else "anon"
    if t == "declaration":
        spec = node.child_by_field_name("type")
        if spec is not None and spec.type in ("struct_specifier", "union_specifier", "enum_specifier") \
                and spec.child_by_field_name("body") is not None:
            nm = spec.child_by_field_name("name")
            return spec.type.split("_")[0], _text(nm) if nm else "anon"
        # prototypes and globals
        decl = node.child_by_field_name("declarator")
        is_proto = decl is not None and any(n.type == "function_declarator" for n in _walk(decl)) \
            and decl.type != "init_declarator"
        return ("prototype" if is_proto else "global"), _declarator_name(decl) or "anon"
    if t == "preproc_function_def":
        return "macro", _text(node.child_by_field_name("name"))
    return None  # includes, simple #defines, comments


def _split_large(chunk: Chunk, max_lines: int) -> list[Chunk]:
    lines = chunk.text.splitlines()
    if len(lines) <= max_lines:
        return [chunk]
    out = []
    for i in range(0, len(lines), max_lines):
        part = lines[i:i + max_lines]
        out.append(Chunk(chunk.path, chunk.lang, chunk.kind, f"{chunk.name}#part{i // max_lines + 1}",
                         chunk.start_line + i, chunk.start_line + i + len(part) - 1, "\n".join(part),
                         chunk.defines if i == 0 else [], chunk.refs))
    return out


def chunk_source(source: str, path: str, lang: str, max_lines: int = 120) -> list[Chunk]:
    tree = _parser(lang).parse(source.encode("utf-8"))
    root = tree.root_node
    chunks: list[Chunk] = []

    if lang == "c":
        preamble: list[Node] = []

        def flush():
            if preamble:
                chunks.append(Chunk(path, lang, "preamble", "preamble",
                                    preamble[0].start_point[0] + 1, preamble[-1].end_point[0] + 1,
                                    "\n".join(_text(n) for n in preamble),
                                    [], []))
                preamble.clear()

        for node in root.named_children:
            item = _c_item(node)
            if item is None:
                preamble.append(node)
                continue
            flush()
            kind, name = item
            chunks.append(Chunk(path, lang, kind, name, node.start_point[0] + 1, node.end_point[0] + 1,
                                _text(node), [name], _refs(node, lang)))
        flush()
    else:  # java
        for cls in (n for n in _walk(root) if n.type in ("class_declaration", "interface_declaration",
                                                          "enum_declaration", "record_declaration")):
            cname = _text(cls.child_by_field_name("name"))
            body = cls.child_by_field_name("body")
            for member in (body.named_children if body else []):
                if member.type in ("method_declaration", "constructor_declaration"):
                    nm = _text(member.child_by_field_name("name"))
                    kind = "method" if member.type == "method_declaration" else "constructor"
                elif member.type == "field_declaration":
                    nm = _declarator_name(member.child_by_field_name("declarator")) or "field"
                    kind = "field"
                else:
                    continue
                chunks.append(Chunk(path, lang, kind, f"{cname}.{nm}", member.start_point[0] + 1,
                                    member.end_point[0] + 1, _text(member), [nm, f"{cname}.{nm}"],
                                    _refs(member, lang)))

    out: list[Chunk] = []
    for c in chunks:
        out.extend(_split_large(c, max_lines))
    return out


def iter_source_files(repo: Path, lang: str):
    for p in sorted(repo.rglob("*")):
        if p.is_file() and p.suffix in SUFFIXES[lang] and ".modernizer" not in p.parts:
            yield p


def chunk_repo(repo: Path, lang: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for p in iter_source_files(repo, lang):
        chunks.extend(chunk_source(p.read_text(errors="replace"), str(p.relative_to(repo)), lang))
    return chunks
