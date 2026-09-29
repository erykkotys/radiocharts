RadioCharts 1.2.0

- Nowa zakładka „Nasze radio”: Scheduled, Played, Porównanie, Utwory, Import.
- Osobny backend SQLite dla własnej emisji; nie miesza danych z rynkowym airplay_plays.
- Ręczny importer eksportów GSelector TSV/TXT, także wielodniowych i z pełnym miksem elementów.
- Snapshoty są wersjonowane: nowszy import dnia staje się aktywny, starszy zostaje w historii.
- Porównanie Scheduled↔Played: OK / Przesunięte / Pominięte / Dodane, z czasami i deltą.
- Statystyki utworów: sloty/emisje, dni, średnia/dzień, max/dzień, najczęstsza godzina.
- Seed danych: Scheduled 30.09–12.10.2026 (11 791 wierszy) oraz Played 28.09.2026 (1 002 wiersze).
- API read-only dla own-radio: dates, events, compare, song-stats.
- Android 1.2.0 / versionCode 25 (bez nowego ekranu Nasze radio w tej iteracji).
- 192 testy przechodzą.
