from pathlib import Path

import radiocharts.db as db


def _reset_db(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "radiocharts.db")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()


def test_v4_merges_parenthetical_guest_lists_but_not_live_version(monkeypatch, tmp_path):
    _reset_db(monkeypatch, tmp_path)
    rows = [
        ("Męskie Granie Orkiestra 2026", "Nareszcie"),
        ("Męskie Granie Orkiestra 2026", "Nareszcie (Herbut & Zalia & Vito Bambino)"),
        ("Męskie Granie Orkiestra 2026", "Nareszcie (Igor Herbut, Zalia, Vito Bambino)"),
        ("Męskie Granie Orkiestra 2026", "Nareszcie (Live)"),
        ("Męskie Granie Orkiestra 2026", "Tańczę"),
        ("Męskie Granie Orkiestra 2026", "Tańczę (Igor Herbut, Zalia, Vito Bambino)"),
        ("Męskie Granie Orkiestra", "Świt"),
        ("Męskie Granie Orkiestra 2020", "Świt (Gośc.: Daria Zawiałow, Król, Igo)"),
    ]
    with db.connect() as con:
        now = db._utcnow()
        for artist, title in rows:
            con.execute(
                "INSERT INTO songs(artist,title,artist_key,title_key,created_at) VALUES(?,?,?,?,?)",
                (artist, title, db.normalize(artist), db.normalize(title), now),
            )
        con.execute("DELETE FROM app_meta WHERE key='song_alias_merge_v4'")
    monkeypatch.setattr(db, "_INITIALIZED_DB_PATH", None)
    db.init_db()
    with db.connect() as con:
        songs = con.execute("SELECT artist,title FROM songs ORDER BY id").fetchall()
    titles = [str(r["title"]) for r in songs]
    assert sum(db._identity_title_anchor(t) == db.normalize("Nareszcie") for t in titles) == 1
    assert any(db.normalize(t) == db.normalize("Nareszcie (Live)") for t in titles)
    assert sum(db._identity_title_anchor(t) == db.normalize("Tańczę") for t in titles) == 1
    assert sum(db._identity_title_anchor(t) == db.normalize("Świt") for t in titles) == 1


def test_manual_grid_merge_keeps_exact_alias_for_future_imports(monkeypatch, tmp_path):
    _reset_db(monkeypatch, tmp_path)
    with db.connect() as con:
        now = db._utcnow()
        main = db.get_or_create_song(con, "Męskie Granie Orkiestra 2026", "Nareszcie")
        # Insert a historical duplicate directly so the test exercises the
        # manual path rather than the automatic matcher.
        artist = "Męskie Granie Orkiestra 2026"
        old_title = "Nareszcie (Herbut & Zalia & Vito Bambino)"
        con.execute(
            "INSERT INTO songs(artist,title,artist_key,title_key,created_at) VALUES(?,?,?,?,?)",
            (artist, old_title, db.normalize(artist), db.normalize(old_title), now),
        )
        dup = int(con.execute("SELECT last_insert_rowid()").fetchone()[0])
        con.execute(
            "INSERT OR IGNORE INTO airplay_stations(station_id,name,slug,source_url,active,discovered_at,updated_at) VALUES(1,'Test','','',1,?,?)",
            (now, now),
        )
        con.execute(
            "INSERT INTO airplay_plays(station_id,played_at,artist,title,artist_key,title_key,song_id,retrieved_at) VALUES(?,?,?,?,?,?,?,?)",
            (1, "2026-09-18T10:00", artist, old_title, db.artist_anchor(artist), db.normalize(old_title), dup, now),
        )
    result = db.merge_song_group([main, dup])
    assert result["merged"] == 1
    canonical = int(result["canonical_song_id"])
    assert db.canonical_song_id(dup) == canonical
    with db.connect() as con:
        alias = con.execute(
            "SELECT canonical_song_id FROM song_identity_aliases WHERE artist_key=? AND title_key=?",
            (db.normalize(artist), db.normalize(old_title)),
        ).fetchone()
        assert alias is not None and int(alias["canonical_song_id"]) == canonical
        # Future arrival with the retired exact signature must go straight to
        # the canonical row and must not recreate the deleted song.
        again = db.get_or_create_song(con, artist, old_title)
        assert again == canonical
        assert con.execute("SELECT 1 FROM songs WHERE id=?", (dup,)).fetchone() is None


def test_emisje_grid_has_far_right_manual_merge_and_song_detail_tool_is_removed():
    app = Path("radiocharts/app.py").read_text(encoding="utf-8")
    assert 'show["_merge_select"]' in app
    assert '"_merge_select", "Scal"' in app
    assert "Scal zaznaczone" in app
    assert "merge_select_mode=True" in app
    assert "@st.dialog(\"Scal utwory\")" in app
    assert "Duplikaty / scalanie utworu" not in app
    assert app.index('gb.configure_column("note", "Notatka"') < app.index('"_merge_select", "Scal"')


def test_v4_is_maintenance_marker_not_schema_blocker():
    text = Path("radiocharts/db.py").read_text(encoding="utf-8")
    assert '"song_alias_merge_v4"' in text
    assert 'maintenance_markers = {"song_alias_merge_v3", "song_alias_merge_v4"}' in text
