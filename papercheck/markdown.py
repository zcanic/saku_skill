from __future__ import annotations

import difflib
from dataclasses import dataclass

from markdown_it import MarkdownIt

from .util import char_byte_offsets

_MD = MarkdownIt("commonmark").enable("table")


@dataclass
class Block:
    kind: str
    order: int
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int
    raw_text: str
    content: str | None
    content_to_char: list[int] | None

    @property
    def deferred(self) -> bool:
        return self.content is None


def _line_starts(text: str) -> list[int]:
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    starts.append(len(text))
    return starts


def _map_content(raw_text: str, raw_start: int, content: str) -> list[int]:
    """Map every content character to an absolute document character index."""
    if content == "":
        return []
    map_text = raw_text[:-1] if raw_text.endswith("\n") else raw_text
    raw_lines = map_text.split("\n")
    raw_line_starts: list[int] = []
    cursor = raw_start
    for line in raw_lines:
        raw_line_starts.append(cursor)
        cursor += len(line) + 1
    content_lines = content.split("\n")
    mapping: list[int] = []

    if len(content_lines) != len(raw_lines):
        # Fall back to global alignment when the token content and source lines
        # do not line up (e.g. trailing blank lines, unusual constructs).
        matcher = difflib.SequenceMatcher(None, content, raw_text, autojunk=False)
        pos_by_content = [raw_start] * len(content)
        for a, b, size in matcher.get_matching_blocks():
            for k in range(size):
                pos_by_content[a + k] = raw_start + b + k
        last = raw_start
        for i, pos in enumerate(pos_by_content):
            if i and pos <= pos_by_content[i - 1]:
                pos = pos_by_content[i - 1] + 1
            pos_by_content[i] = min(pos, raw_start + max(len(raw_text) - 1, 0))
            last = pos_by_content[i]
        return pos_by_content

    for idx, (raw_line, cline) in enumerate(zip(raw_lines, content_lines)):
        base = raw_line_starts[idx]
        if cline == "":
            for _ in cline:
                mapping.append(base)
            if idx < len(content_lines) - 1:
                mapping.append(base + len(raw_line))
            continue
        pos = raw_line.find(cline)
        if pos >= 0:
            mapping.extend(base + pos + k for k in range(len(cline)))
        else:
            matcher = difflib.SequenceMatcher(None, cline, raw_line, autojunk=False)
            local = [base] * len(cline)
            for a, b, size in matcher.get_matching_blocks():
                for k in range(size):
                    local[a + k] = base + b + k
            last = base
            for i, p in enumerate(local):
                if i and p <= local[i - 1]:
                    p = local[i - 1] + 1
                p = min(p, base + max(len(raw_line) - 1, 0))
                local[i] = p
                last = p
            mapping.extend(local)
        if idx < len(content_lines) - 1:
            mapping.append(base + len(raw_line))
    return mapping


def _kind_from_stack(stack: list[str]) -> str:
    if "heading_open" in stack:
        return "heading"
    if "list_item_open" in stack:
        return "list_item"
    if "blockquote_open" in stack:
        return "blockquote"
    return "paragraph"


def parse_document(text: str) -> list[Block]:
    starts = _line_starts(text)
    byte_offsets = char_byte_offsets(text)
    tokens = _MD.parse(text)
    blocks: list[Block] = []
    stack: list[str] = []
    table_depth = 0
    order = 0

    def add_block(kind: str, start_line: int, end_line: int, content: str | None) -> None:
        nonlocal order
        start_line = max(0, min(start_line, len(starts) - 1))
        end_line = max(start_line, min(end_line, len(starts) - 1))
        raw_start = starts[start_line]
        raw_end = starts[end_line]
        raw_text = text[raw_start:raw_end]
        mapping = _map_content(raw_text, raw_start, content) if content is not None else None
        blocks.append(
            Block(
                kind=kind,
                order=order,
                start_line=start_line,
                end_line=end_line,
                start_byte=byte_offsets[raw_start],
                end_byte=byte_offsets[raw_end],
                raw_text=raw_text,
                content=content,
                content_to_char=mapping,
            )
        )
        order += 1

    for token in tokens:
        ttype = token.type
        if ttype == "table_open":
            table_depth += 1
            if token.map:
                add_block("table", token.map[0], token.map[1], None)
            stack.append(ttype)
            continue
        if ttype == "table_close":
            table_depth = max(0, table_depth - 1)
            if stack and stack[-1] == "table_open":
                stack.pop()
            continue
        if ttype in ("fence", "code_block", "html_block"):
            if token.map:
                kind = "code_block" if ttype in ("fence", "code_block") else "html_block"
                add_block(kind, token.map[0], token.map[1], None)
            continue
        if ttype == "inline":
            if table_depth > 0:
                continue
            if token.map and token.content.strip():
                kind = _kind_from_stack(stack)
                content = token.content
                stripped = content.strip()
                if kind != "heading" and stripped.startswith("$$") and stripped.endswith("$$"):
                    add_block("math_block", token.map[0], token.map[1], None)
                else:
                    add_block(kind, token.map[0], token.map[1], content)
            continue
        if ttype.endswith("_open"):
            stack.append(ttype)
        elif ttype.endswith("_close"):
            if stack and stack[-1] == ttype.replace("_close", "_open"):
                stack.pop()
    return blocks
