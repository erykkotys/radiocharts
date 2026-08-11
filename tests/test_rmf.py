from radiocharts.sources.rmf import parse_rmf


def _chart_html(issue_markup: str) -> str:
    rows = "".join(
        f"<div><span>{i}</span><b>Artist {i}</b><em>Title {i}</em></div>"
        for i in range(1, 21)
    )
    return f"<html><body><h1>POPLISTA</h1>{issue_markup}{rows}<h2>PROPOZYCJE</h2></body></html>"


def test_parse_rmf_issue_in_one_node():
    data = parse_rmf(_chart_html("<div>6182 / 2026-08-10</div>"))
    assert data["issue_key"] == "6182"
    assert str(data["chart_date"]) == "2026-08-10"
    assert len(data["entries"]) == 20
    assert data["entries"][0] == {"position": 1, "artist": "Artist 1", "title": "Title 1"}


def test_parse_rmf_issue_split_by_markup():
    data = parse_rmf(_chart_html("<div><span>6182</span> / <time>2026-08-10</time></div>"))
    assert data["issue_key"] == "6182"
    assert len(data["entries"]) == 20


def test_parse_current_rmf_shape():
    html = """
    <html><head><title>RMF</title></head><body>
    <h1>POPLISTA</h1><div>6182 / 2026-08-10</div>
    """ + "".join(
        f"<div><span>{i}</span><span>Artist {i}</span><span>Title {i}</span></div>"
        for i in range(1, 21)
    ) + "<h2>PROPOZYCJE</h2></body></html>"
    parsed = parse_rmf(html)
    assert parsed["issue_key"] == "6182"
    assert parsed["chart_date"].isoformat() == "2026-08-10"
    assert len(parsed["entries"]) == 20
    assert parsed["entries"][0]["artist"] == "Artist 1"
