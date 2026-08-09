from services.sanitize import OBJECT_REPLACEMENT_CHAR, sanitize_for_speech


def test_plain_text_passes_through():
    assert sanitize_for_speech("See you at 6") == "See you at 6"


def test_url_replaced_with_a_link():
    assert (
        sanitize_for_speech("check this out https://example.com/some/very?long=path ok")
        == "check this out [a link] ok"
    )


def test_www_url_replaced():
    assert sanitize_for_speech("go to www.example.com now") == "go to [a link] now"


def test_inline_attachment_marker_replaced_by_mime_placeholder():
    text = f"look {OBJECT_REPLACEMENT_CHAR}"
    assert sanitize_for_speech(text, ["image/jpeg"]) == "look [an image]"


def test_multiple_attachments_positional():
    text = f"{OBJECT_REPLACEMENT_CHAR} and {OBJECT_REPLACEMENT_CHAR}"
    assert sanitize_for_speech(text, ["image/png", "video/mp4"]) == "[an image] and [a video]"


def test_attachment_without_inline_marker_is_appended():
    assert sanitize_for_speech("", ["audio/amr"]) == "[an audio message]"
    assert sanitize_for_speech("listen", ["audio/amr"]) == "listen [an audio message]"


def test_unknown_mime_generic_placeholder():
    assert sanitize_for_speech(OBJECT_REPLACEMENT_CHAR, ["application/pdf"]) == "[an attachment]"


def test_marker_with_no_mime_info():
    assert sanitize_for_speech(f"hi {OBJECT_REPLACEMENT_CHAR}") == "hi [an attachment]"
