from radiocharts.sources.eska import parse_eska_text


def test_eska_rendered_text_shape():
    rows = ["Gorąca 20"]
    for i in range(1, 21):
        rows += [str(i), "▲" if i % 2 else "▼", f"Song {i}", f"Artist {i}"]
        if i % 2 == 0:
            rows += ["Radio ESKA", "Hity na czasie"]
    rows += ["PROPOZYCJE"]
    d = parse_eska_text("\n".join(rows))
    assert len(d["entries"]) == 20
    assert d["entries"][0]["title"] == "Song 1"
    assert d["entries"][19]["artist"] == "Artist 20"
