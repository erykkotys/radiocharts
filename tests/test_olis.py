from radiocharts.sources.olis import parse_olis_rendered


def test_parse_rendered_olia_cards():
    text = """
    oficjalna lista airplay
    01.08.2026
    07.08.2026
    Tydzień 32
    1 (1)
    BEZ ZMIAN NA LIŚCIE
    TYGODNIE NA DANEJ LIŚCIE
    15
    Nareszcie
    Męskie Granie Orkiestra, Igor Herbut, Zalia, Vito Bambino
    Sony Music
    2 (3)
    WZROST
    TYGODNIE NA DANEJ LIŚCIE
    9
    Dai Dai
    Shakira, Burna Boy
    Sony Music
    3 (2)
    SPADEK
    TYGODNIE NA DANEJ LIŚCIE
    10
    Na błysk
    Dawid Podsiadło
    Pur Pur
    4 (5)
    WZROST
    TYGODNIE NA DANEJ LIŚCIE
    8
    Run Run River
    David Guetta, Alok, Stick Figure
    Warner
    5 (6)
    TYGODNIE NA DANEJ LIŚCIE
    7
    Self Aware
    Temper City
    Label
    6 (7)
    TYGODNIE NA DANEJ LIŚCIE
    6
    Magnetic
    The Bausa
    Label
    7 (8)
    TYGODNIE NA DANEJ LIŚCIE
    5
    Talk To You
    ANOTR, 54 Ultra
    Label
    8 (9)
    TYGODNIE NA DANEJ LIŚCIE
    4
    My Body Isn't Ready
    sombr
    Label
    9 (10)
    TYGODNIE NA DANEJ LIŚCIE
    3
    Mi Chico
    DJ Goja, Jason Derulo
    Label
    10 (11)
    TYGODNIE NA DANEJ LIŚCIE
    2
    Fate
    Alan Walker, Ava Max
    Label
    """
    data = parse_olis_rendered("<html></html>", text, "OLIA")
    assert data["chart_date"] == "2026-08-07"
    assert len(data["entries"]) == 10
    assert data["entries"][0]["title"] == "Nareszcie"
    assert data["entries"][0]["reported_weeks"] == 15
