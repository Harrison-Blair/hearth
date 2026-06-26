from assistant.tui.logcolor import colorize_line, colorize_message


def _style_over(text, substring):
    """Return the style of the span exactly covering ``substring`` in ``text``."""
    start = text.plain.index(substring)
    end = start + len(substring)
    for span in text.spans:
        if span.start == start and span.end == end:
            return span.style
    return None


def test_colorize_line_round_trips_plain_text():
    for line in (
        "12:34:56 INFO    assistant.core.pipeline: Listening for wake word...",
        '  File "x.py", line 3, in <module>',
        '[GIN] 2026/06/26 - 12:00:00 | 200 | GET "/api/tags"',
    ):
        assert colorize_line(line).plain == line


def test_error_level_styled_white_on_red():
    line = "12:34:56 ERROR   assistant.core.pipeline: boom"
    text = colorize_line(line)
    # The level token keeps its 7-char padding from "%(levelname)-7s".
    assert _style_over(text, "ERROR  ") == "bold white on red"


def test_info_level_styled_green():
    line = "12:34:56 INFO    assistant.core.pipeline: ok"
    assert _style_over(colorize_line(line), "INFO   ") == "bold bright_green"


def test_timestamp_and_logger_styled():
    line = "12:34:56 INFO    assistant.core.pipeline: ok"
    text = colorize_line(line)
    assert _style_over(text, "12:34:56") == "bold bright_cyan"
    assert _style_over(text, "assistant.core.pipeline") == "bold bright_blue"


def test_quoted_content_highlighted():
    line = "12:00:00 INFO    assistant.core.pipeline: Reply: 'it is noon'"
    assert _style_over(colorize_line(line), "'it is noon'") == "bold bright_green"


def test_llm_message_tag_and_label():
    text = colorize_message("[classify] response: hi")
    assert _style_over(text, "[classify]") == "bold bright_cyan"
    assert _style_over(text, "response:") == "bold"
    assert text.plain == "[classify] response: hi"


def test_freeform_level_keyword_and_status_code():
    line = '[GIN] ERROR | 500 | failed "/api/chat"'
    text = colorize_line(line)
    assert _style_over(text, "ERROR") == "bold white on red"
    assert _style_over(text, "500") == "bold bright_blue"
    assert _style_over(text, '"/api/chat"') == "bold bright_green"


def test_freeform_warn_keyword_maps_to_warning_style():
    text = colorize_line("[GIN] level=WARN msg=slow")
    assert _style_over(text, "WARN") == "bold bright_yellow"
