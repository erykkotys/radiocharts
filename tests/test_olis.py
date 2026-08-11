from radiocharts.sources.olis import parse_olis_rendered


def test_parse_rendered_olia_live_shape():
    # Sanitized excerpt copied from the live TrueNAS/Playwright diagnostic.
    text = """
    oficjalna lista airplay
    zmień zakres od–do:
    <
    01.08.2026 07.08.2026
    >
    WYKONAWCA
    TYTUŁ
    WYDAWCA/DYSTRYBUTOR
    ARCHIWUM
    OKŁADKA
    POZYCJA
    TYTUŁ
    WYKONAWCA
    WYDAWCA / DYSTRYBUTOR
    INFORMACJE
    Tydzień 32
    1
    Nareszcie
    Męskie Granie Orkiestra, Igor Herbut, Zalia, Vito Bambino
    Universal Music Group
    15
    1
    2
    Dai Dai
    Shakira, Burna Boy
    Sony Music Entertainment
    Warner Music Group
    4
    8
    2
    3
    Na błysk
    Dawid Podsiadło
    Sony Music Entertainment
    2
    9
    2
    4
    Run Run River (Angels Above Me)
    David Guetta, Alok, Stick Figure
    Sony Music Entertainment
    12
    7
    4
    5
    Repeat it
    Martin Garrix x Ed Sheeran
    Stmpd Rcrds
    7
    10
    5
    6
    Self Aware
    Temper City
    Label
    5
    12
    3
    7
    Magnetic
    The Bausa
    Label
    6
    9
    2
    8
    Talk To You
    ANOTR, 54 Ultra
    Label
    7
    10
    4
    9
    My Body Isn't Ready
    sombr
    Label
    8
    5
    5
    10
    Fate
    Alan Walker, Ava Max
    Label
    9
    6
    5
    """
    data = parse_olis_rendered("<html></html>", text, "OLIA")
    assert data["chart_date"] == "2026-08-07"
    assert data["parser_mode"] == "rendered_text_v2"
    assert len(data["entries"]) == 10
    first = data["entries"][0]
    assert first == {
        "position": 1,
        "artist": "Męskie Granie Orkiestra, Igor Herbut, Zalia, Vito Bambino",
        "title": "Nareszcie",
        "reported_weeks": 15,
        "reported_peak": 1,
    }
    second = data["entries"][1]
    assert second["previous_position"] == 4
    assert second["reported_weeks"] == 8
    assert second["reported_peak"] == 2


def test_parse_rendered_olis_live_shape():
    text = """
    single w streamie
    zmień zakres od–do:
    <
    24.07.2026 30.07.2026
    >
    Tydzień 31
    1
    Nareszcie
    Męskie Granie Orkiestra, Igor Herbut, Zalia, Vito Bambino
    Igor Herbut
    Zalia/Vito Bambino/Live/Universal Music Group
    14
    1
    2
    CALIFORNIA LOVE
    White 2115, VVSimon, Palar, PMBTZ
    California Records
    Sony Music Entertainment
    19
    1
    3
    RED FLAG
    White 2115, PMBTZ
    California Records
    Sony Music Entertainment
    1
    3
    4
    Dai Dai
    Shakira, Burna Boy
    Sony Music Latin
    Sony Music Entertainment
    9
    4
    5
    Napalona
    David Tango, SxK
    Label
    4
    3
    3
    6
    Song 6
    Artist 6
    Label
    5
    2
    2
    7
    Song 7
    Artist 7
    Label
    6
    3
    3
    8
    Song 8
    Artist 8
    Label
    7
    4
    4
    9
    Song 9
    Artist 9
    Label
    8
    5
    5
    10
    Song 10
    Artist 10
    Label
    9
    6
    6
    """
    data = parse_olis_rendered("<html></html>", text, "OLIS")
    assert data["chart_date"] == "2026-07-30"
    assert len(data["entries"]) == 10
    assert data["entries"][0]["reported_weeks"] == 14
    assert data["entries"][1]["reported_weeks"] == 19
    assert data["entries"][3]["title"] == "Dai Dai"
    assert data["entries"][3]["reported_peak"] == 4
