from autosub.core.languages import iso639_2, name_of
from autosub.core.subtitles import Segment, clean, format_ts, merge, parse_srt, parse_ts, split, to_srt


def test_timestamps_roundtrip():
    assert format_ts(3725.5) == "01:02:05,500"
    assert parse_ts("01:02:05,500") == 3725.5
    assert parse_ts("02:05.25") == 125.25
    assert parse_ts("7.5") == 7.5


def test_srt_roundtrip():
    segs = [Segment(0, 1.5, "Hello"), Segment(2, 3.25, "Two\nlines")]
    back = parse_srt(to_srt(segs))
    assert [(s.start, s.end, s.text) for s in back] == [(0, 1.5, "Hello"), (2, 3.25, "Two\nlines")]


def test_srt_skips_empty_and_handles_bom():
    text = "﻿1\n00:00:01,000 --> 00:00:02,000\nHi\n\n2\n00:00:03,000 --> 00:00:04,000\n\n"
    assert len(parse_srt(text)) == 2
    assert to_srt([Segment(0, 1, "  ")]) == ""


def test_merge_and_split():
    segs = [Segment(0, 1, "one two"), Segment(1, 2, "three"), Segment(2, 4, "four")]
    m = merge(segs, 0, 1)
    assert len(m) == 2 and m[0].text == "one two three" and m[0].end == 2
    s = split(m, 0)
    assert len(s) == 3
    assert s[0].start == 0 and s[1].end == 2 and s[0].end == s[1].start
    assert (s[0].text + " " + s[1].text) == "one two three"


def test_clean_removes_markers_and_overlaps():
    segs = [Segment(0, 3, "a"), Segment(2, 4, "b"), Segment(5, 6, "[BLANK_AUDIO]")]
    out = clean(segs)
    assert [s.text for s in out] == ["a", "b"]
    assert out[0].end <= out[1].start


def test_language_tags():
    assert iso639_2("ja") == "jpn" and iso639_2("en") == "eng" and iso639_2("de") == "ger"
    assert iso639_2(None) == "und" and iso639_2("xx") == "und"
    assert name_of("ja") == "Japanese"


def test_find_loops_detects_stuck_whisper():
    from autosub.core.subtitles import collapse_loops, find_loops
    good = [Segment(i * 3, i * 3 + 2, f"line {i}") for i in range(5)]
    stuck = [Segment(15 + i * 3, 17 + i * 3, "Thank you for watching!") for i in range(20)]
    segs = good + stuck + [Segment(80, 82, "the end")]
    assert find_loops(segs) == [(5, 24)]
    out = collapse_loops(segs, find_loops(segs))
    assert [s.text for s in out].count("Thank you for watching!") == 1 and len(out) == 7


def test_find_loops_leaves_real_dialogue_alone():
    from autosub.core.subtitles import find_loops
    segs = [Segment(0, 1, "No."), Segment(1, 2, "No!"), Segment(2, 3, "No."), Segment(3, 4, "Okay")]
    assert find_loops(segs) == []
    assert find_loops([Segment(0, 9, "go " * 20)]) == [(0, 0)]
    assert find_loops([Segment(0, 9, "I said go, go, go and then we ran to the car fast")]) == []
