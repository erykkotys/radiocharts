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
