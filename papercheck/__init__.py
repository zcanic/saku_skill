"""papercheck: deterministic text tracking for Markdown papers."""

__version__ = "0.3.0"
SCHEMA_VERSION = "1.1.0"
PARSER_VERSION = "1.0.0"
SEGMENTER_VERSION = "1.1.0"
CANONICALIZER_VERSION = "1.0.0"

BLOCK_KINDS = frozenset(
    {
        "paragraph",
        "heading",
        "list_item",
        "blockquote",
        "math_block",
        "code_block",
        "table",
        "html_block",
        "other",
    }
)
