from radiocharts.sources.uk import parse_uk


def test_uk_shape():
    parts = ["<html><body><h1>Official Singles Chart Top 100</h1><div>7 August 2026 - 13 August 2026</div>"]
    for i in range(1, 101):
        parts.append(f"<div>Number {i}</div><a>Song {i}</a><a>Artist {i}</a><span>LW: {i}</span><span>Peak: 1</span><span>Weeks: {i+2}</span>")
    parts.append("</body></html>")
    d = parse_uk("".join(parts))
    assert len(d["entries"]) == 100
    assert d["chart_date"] == "2026-08-13"
    assert d["entries"][0]["reported_weeks"] == 3


def test_uk_live_split_number_shape():
    parts = ["<html><body><div>7 August 2026 - 13 August 2026</div>"]
    for i in range(1, 101):
        lw = "New" if i == 4 else str(i)
        parts.append(
            f"<div><span>Number</span><span>{i}</span><a>Song {i}</a><a>Artist {i}</a>"
            f"<span>LW:</span><span>{lw}</span><span>,</span><span>Peak:</span><span>1</span>"
            f"<span>,</span><span>Weeks:</span><span>{i+2}</span></div>"
        )
    parts.append("</body></html>")
    d = parse_uk("".join(parts))
    assert len(d["entries"]) == 100
    assert d["entries"][0]["title"] == "Song 1"
    assert d["entries"][0]["artist"] == "Artist 1"
    assert d["entries"][3]["reported_peak"] == 1
    assert "previous_position" not in d["entries"][3]


def test_uk_skips_metadata_pseudo_song_pair():
    parts = ["<html><body><div>7 August 2026 - 13 August 2026</div>"]
    for i in range(1, 101):
        title, artist = ("WEEKS", "PEAK") if i == 55 else (f"Song {i}", f"Artist {i}")
        parts.append(
            f"<div><span>Number</span><span>{i}</span><a>{title}</a><a>{artist}</a>"
            f"<span>LW:</span><span>{i}</span><span>Peak:</span><span>1</span><span>Weeks:</span><span>{i+2}</span></div>"
        )
    # One pseudo row is discarded; parser still accepts a near-complete chart.
    d = parse_uk("".join(parts))
    assert len(d["entries"]) == 99
    assert all(not (x["title"].casefold() == "weeks" and x["artist"].casefold() == "peak") for x in d["entries"])
