from papercheck.markdown import parse_document
from papercheck.segment import segment_block
from papercheck.util import char_byte_offsets


def sentences(text: str):
    offsets = char_byte_offsets(text)
    out = []
    for block in parse_document(text):
        for sentence in segment_block(block, text, offsets):
            out.append(sentence)
    return out


def test_chinese_and_english_boundaries() -> None:
    text = "该模型有效。然而其跨期性能并不稳定。\nThe estimate was 0.05, e.g. in the baseline specification.\n"
    got = [s.normalized_text for s in sentences(text)]
    assert got == [
        "该模型有效。",
        "然而其跨期性能并不稳定。",
        "The estimate was 0.05, e.g. in the baseline specification.",
    ]


def test_closing_quote_belongs_to_sentence() -> None:
    text = "作者写道：“它并未证明因果关系。”我们只讨论相关性。\n"
    got = [s.normalized_text for s in sentences(text)]
    assert got == ["作者写道：“它并未证明因果关系。”", "我们只讨论相关性。"]


def test_links_code_and_math_are_protected() -> None:
    text = "As shown in [Fig. 2](https://example.org/a.b), the difference remains.\n"
    got = [s.normalized_text for s in sentences(text)]
    assert len(got) == 1
    assert got[0].startswith("As shown in Fig. 2")

    text2 = "请参考 `x.y` 与 [Fig. 2](https://example.org/a.b)，其中 $\\alpha=0.05$。\n"
    got2 = [s.normalized_text for s in sentences(text2)]
    assert len(got2) == 1


def test_decimal_and_abbreviation_do_not_split() -> None:
    text = "The value 3.14 is close to 0.05, e.g. in Fig. 2 and Eq. 3.\n"
    got = [s.normalized_text for s in sentences(text)]
    assert len(got) == 1


def test_raw_text_matches_bytes() -> None:
    text = "中文句子。Second sentence.\n"
    raw = text.encode("utf-8")
    for sentence in sentences(text):
        assert raw[sentence.start_byte:sentence.end_byte].decode("utf-8") == sentence.raw_text


def test_deferred_blocks_have_no_sentences() -> None:
    text = "```py\ncode. here\n```\n\n$$\nx = 1.\n$$\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"
    blocks = parse_document(text)
    kinds = {block.kind for block in blocks if block.content is None}
    assert {"code_block", "math_block", "table"} <= kinds
