from radiocharts.sources.zet import parse_zet_text


def test_zet_pasted_text():
    lines = ["Lista przebojów", "Notowanie z dnia 2026-08-10"]
    for i in range(1, 21):
        lines += [str(i), f"Artist {i}", f"Song {i}", "Lubię to"]
    lines += ["Propozycje"]
    d = parse_zet_text("\n".join(lines))
    assert len(d["entries"]) == 20
    assert d["chart_date"] == "2026-08-10"
    assert d["entries"][4]["title"] == "Song 5"
