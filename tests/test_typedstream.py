from tests.fixtures import make_attributed_body

from services.typedstream import extract_text


def test_decodes_short_ascii_body():
    assert extract_text(make_attributed_body("Hey, running late!")) == "Hey, running late!"


def test_decodes_unicode_and_emoji():
    text = "Café tonight? 🎉👍"
    assert extract_text(make_attributed_body(text)) == text


def test_decodes_long_body_two_byte_length():
    text = "word " * 100  # > 0x80 bytes forces the 0x81 length encoding
    assert extract_text(make_attributed_body(text)) == text


def test_decodes_very_long_body_four_byte_length():
    text = "x" * 70_000  # > 0xFFFF forces the 0x82 length encoding
    assert extract_text(make_attributed_body(text)) == text


def test_none_and_empty_blob_return_none():
    assert extract_text(None) is None
    assert extract_text(b"") is None


def test_non_typedstream_blob_returns_none():
    assert extract_text(b"definitely not a typedstream blob") is None


def test_truncated_blob_returns_none():
    blob = make_attributed_body("hello world, this will be cut off")
    assert extract_text(blob[:40]) is None
