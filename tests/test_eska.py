from datetime import date
from radiocharts.sources.eska import parse_eska


def test_parse_eska_simple():
    cards=[]
    for i in range(1,21):
        cards.append(f"<div><span>{i}</span><span>▲</span><a>Title {i}</a><a>Artist {i}</a></div>")
        if i % 2 == 0:
            cards.append("<div>Radio ESKA</div><div>Hity na czasie</div>")
    html="<html><body><nav>Gorąca 20</nav><h1>Gorąca 20</h1>"+"".join(cards)+"<h2>PROPOZYCJE</h2></body></html>"
    data=parse_eska(html, date(2026,8,11))
    assert len(data["entries"]) == 20
    assert data["entries"][0]["title"] == "Title 1"
    assert data["entries"][0]["artist"] == "Artist 1"


def test_parse_eska_with_ads_and_multiple_artists():
    html = """
    <html><body>
      <nav>Gorąca 20</nav>
      <h1>Gorąca 20</h1>
      <div>1</div><div>▲</div><a>Wszystkie Marzenia</a><a>Latwogang</a><a>Majko</a><a>Fundacja Cancer Fighters</a>
      <div>2</div><div>▲</div><a>Self Aware</a><a>Temper City</a><div>Radio ESKA</div><div>Hity na czasie</div>
    """ + "".join(
        f"<div>{i}</div><div>▼</div><a>Title {i}</a><a>Artist {i}</a>" +
        ("<div>Radio ESKA</div><div>Hity na czasie</div>" if i % 2 == 0 else "")
        for i in range(3, 21)
    ) + "<h2>PROPOZYCJE</h2></body></html>"
    data = parse_eska(html, date(2026,8,11))
    assert len(data["entries"]) == 20
    assert data["entries"][0]["artist"] == "Latwogang, Majko, Fundacja Cancer Fighters"
    assert data["entries"][1]["title"] == "Self Aware"
    assert data["entries"][1]["artist"] == "Temper City"
