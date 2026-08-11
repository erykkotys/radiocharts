from datetime import date
from radiocharts.sources.eska import parse_eska


def test_parse_eska_simple_cards():
    cards = []
    for i in range(1, 21):
        cards.append(f"<div><span>{i}</span><span>▲</span><a>Title {i}</a><a>Artist {i}</a><span>Radio ESKA</span><span>Hity na czasie</span></div>")
    html = "<html><body><h1>Gorąca 20</h1>" + "".join(cards) + "<h2>PROPOZYCJE</h2></body></html>"
    data = parse_eska(html, date(2026, 8, 11))
    assert len(data["entries"]) == 20
    assert data["entries"][0] == {"position": 1, "artist": "Artist 1", "title": "Title 1"}
