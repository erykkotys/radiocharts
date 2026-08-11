from radiocharts.sources.billboard import parse_billboard_text


def test_billboard_shape():
    lines = ["Billboard Hot 100™", "Week of August 15, 2026", "THIS WEEK", "LAST WEEK", "PEAK POS.", "WKS ON CHART"]
    for i in range(1, 101):
        lines += [str(i), f"Song {i}", f"Artist {i}", str(i), "1", str(i+5)]
    d = parse_billboard_text("\n".join(lines))
    assert len(d["entries"]) == 100
    assert d["chart_date"] == "2026-08-15"
    assert d["entries"][1]["previous_position"] == 2
    assert d["entries"][1]["reported_weeks"] == 7
