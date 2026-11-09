from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .markdown import Block

_CN_END = set("。！？")
_CN_REPEAT = set("。！？!?")
_CLOSERS = set("”’」』）】》〉〕｝\"')]")
_ABBREV = {
    "et al", "e.g", "i.e", "fig", "figs", "eq", "eqs", "ref", "refs", "no", "nos",
    "dr", "mr", "mrs", "ms", "prof", "vs", "etc", "sec", "secs", "ch", "chap",
    "approx", "ca", "cf", "resp", "al", "u.s", "u.k", "ph.d", "st", "mt",
}


@dataclass
class Sentence:
    start_byte: int
    end_byte: int
    raw_text: str
    normalized_text: str


def _merge(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []
    ranges.sort()
    out = [ranges[0]]
    for start, end in ranges[1:]:
        if start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def protected_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            ranges.append((i, i + 2))
            i += 2
            continue
        if ch == "`":
            run = 1
            while i + run < n and text[i + run] == "`":
                run += 1
            close = text.find("`" * run, i + run)
            if close != -1:
                ranges.append((i, close + run))
                i = close + run
            else:
                i += run
            continue
        if ch == "[" or (ch == "!" and i + 1 < n and text[i + 1] == "["):
            start = i
            bracket = i + 1 if ch == "!" else i
            close = text.find("]", bracket + 1)
            if close != -1 and close + 1 < n and text[close + 1] == "(":
                end = text.find(")", close + 2)
                if end != -1:
                    ranges.append((start, end + 1))
                    i = end + 1
                    continue
            i += 1
            continue
        if ch == "$":
            run = 2 if text.startswith("$$", i) else 1
            close = text.find("$" * run, i + run)
            if close != -1:
                ranges.append((i, close + run))
                i = close + run
            else:
                i += run
            continue
        if ch == "<":
            close = text.find(">", i + 1)
            if close != -1:
                inner = text[i + 1:close]
                if "://" in inner or inner.startswith(("http", "mailto:", "/")):
                    ranges.append((i, close + 1))
                    i = close + 1
                    continue
                if inner[:1].isalpha() or inner[:1] == "/":
                    ranges.append((i, close + 1))
                    i = close + 1
                    continue
        i += 1
    return _merge(ranges)


def _in_protected(i: int, ranges: list[tuple[int, int]]) -> int | None:
    for start, end in ranges:
        if start <= i < end:
            return end
        if i < start:
            return None
    return None


def _word_before(text: str, dot: int) -> str:
    j = dot - 1
    while j >= 0 and (text[j].isalnum() or text[j] in ".-"):
        j -= 1
    return text[j + 1:dot].lower()


def _dot_is_boundary(text: str, i: int) -> bool:
    prev = text[i - 1] if i > 0 else ""
    nxt = text[i + 1] if i + 1 < len(text) else ""
    if prev.isdigit() and nxt.isdigit():
        return False
    if prev.isdigit() and nxt == "," and i + 2 < len(text) and text[i + 2].isdigit():
        return False
    word = _word_before(text, i)
    if word in _ABBREV or (len(word) == 1 and word.isalpha()):
        return False
    if nxt and not (nxt.isspace() or nxt in _CLOSERS):
        return False
    return True


def _emit(text: str, raw: str, start: int, end: int, byte_offsets: list[int], mapping: list[int], block: Block, out: list[Sentence]) -> None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if end <= start:
        return
    raw_start = mapping[start]
    raw_end = mapping[end - 1] + 1
    norm = normalize_text(text[start:end])
    if not norm:
        return
    out.append(
        Sentence(
            start_byte=byte_offsets[raw_start],
            end_byte=byte_offsets[raw_end],
            raw_text=raw[raw_start:raw_end],
            normalized_text=norm,
        )
    )


def segment_block(block: Block, document: str, byte_offsets: list[int]) -> list[Sentence]:
    content = block.content
    mapping = block.content_to_char
    if content is None or mapping is None or not content:
        return []
    out: list[Sentence] = []
    if block.kind == "heading":
        # A heading is one unit; numbered titles such as "2.1. Data" must not split at "2.1.".
        _emit(content, document, 0, len(content), byte_offsets, mapping, block, out)
        return out
    protected = protected_ranges(content)
    start = 0
    i = 0
    n = len(content)
    while i < n:
        jump = _in_protected(i, protected)
        if jump is not None:
            i = jump
            continue
        ch = content[i]
        if ch in _CN_END:
            end = i + 1
            while end < n and content[end] in _CN_REPEAT:
                end += 1
            while end < n and content[end] in _CLOSERS:
                end += 1
            _emit(content, document, start, end, byte_offsets, mapping, block, out)
            start = end
            i = end
            continue
        if ch in ".?!":
            boundary = ch != "." or _dot_is_boundary(content, i)
            if boundary:
                end = i + 1
                while end < n and content[end] in _CN_REPEAT:
                    end += 1
                while end < n and content[end] in _CLOSERS:
                    end += 1
                nxt = content[end] if end < n else ""
                if ch in ".?!" and (not nxt or nxt.isspace() or nxt in _CLOSERS):
                    _emit(content, document, start, end, byte_offsets, mapping, block, out)
                    start = end
                    i = end
                    continue
        i += 1
    _emit(content, document, start, n, byte_offsets, mapping, block, out)
    return out


_LINK_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_TAG_RE = re.compile(r"<[^>]+>")
_ESCAPE_RE = re.compile(r"\\([\\`*{}\[\]()#+\-.!_>~|])")
_EMPH_RE = re.compile(r"[*_~]+")
_WS_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    text = _LINK_RE.sub(r"\1", text)
    text = _TAG_RE.sub("", text)
    text = text.replace("`", "")
    text = text.replace("$", "")
    text = _ESCAPE_RE.sub(r"\1", text)
    text = _EMPH_RE.sub("", text)
    text = _WS_RE.sub(" ", text).strip()
    return unicodedata.normalize("NFC", text)
