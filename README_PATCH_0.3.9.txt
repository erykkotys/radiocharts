RadioCharts 0.3.9
=================

Najważniejsze poprawki po 0.3.8:

1. Dashboard / Otwórz
   - przejście na kartę utworu nie zachowuje już pozycji scrolla z tabeli;
   - po nawigacji karta jest przewijana na górę.

2. Wyszukiwarka Utwór
   - wyszukiwanie ignoruje polskie znaki i wielkość liter;
   - np. "meskie" znajduje "Męskie";
   - katalog obejmuje również utwory znalezione tylko w emisjach.

3. Emisje / SQLite foreign key mismatch
   - pierwsze uruchomienie 0.3.9 sprawdza realny schemat tabel airplay;
   - stare eksperymentalne airplay_stations z dodanym zwykłym station_id są
     przebudowywane do kanonicznego station_id INTEGER PRIMARY KEY;
   - airplay_plays i airplay_windows są przebudowywane razem, z zachowaniem
     istniejącej historii i odtworzeniem poprawnych kluczy obcych;
   - nie trzeba kasować radiocharts.db ani robić backfillu od zera.

4. Wspólny utwór, osobne metryki
   - cofnięto zbyt dalekie rozdzielenie z 0.3.8;
   - ten sam utwór w notowaniach i emisjach ma jeden song_id, wspólny status,
     notatkę, odsłuch i kartę;
   - liczba emisji NIE wchodzi do Familiarity/Momentum i NIE zmienia pozycji
     ani kolejności Dashboardu;
   - utwory znane wyłącznie z emisji mogą być oceniane ręcznie, ale ich
     chartowe wskaźniki pozostają puste do czasu pojawienia się w notowaniach.

5. Widok Emisji
   - ranking najczęściej granych ma Otwórz, odsłuch 30 s, Spotify, ✓ i Status;
   - obok emisji pokazuje bieżące pozycje RMF/ZET/OLiA/OLiS/ESKA;
   - zakładka Sprawdź utwór pokazuje pozycje z notowań i ma szybkie przejście
     do wspólnej karty utworu.

Testy: 38/38.
