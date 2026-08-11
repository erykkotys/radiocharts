from datetime import date
from radiocharts.sources.eska import parse_eska


def test_parse_eska_simple():
    cards=[]
    for i in range(1,21):
        cards.append(f"<div><span>{i}</span><span>▲</span><a>Title {i}</a><a>Artist {i}</a></div>")
        if i % 2 == 0:
            cards.append("<div>Radio ESKA</div><div>Hity na czasie</div>")
    html="<html><body><h1>Gorąca 20</h1>"+"".join(cards)+"<h2>PROPOZYCJE</h2></body></html>"
    data=parse_eska(html, date(2026,8,11))
    assert len(data["entries"]) == 20
    assert data["entries"][0]["title"] == "Title 1"
    assert data["entries"][0]["artist"] == "Artist 1"
