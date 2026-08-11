RadioCharts 0.2.0
=================

Najważniejsze zmiany:
- kliknięcie wiersza na Dashboardzie/Archiwum otwiera szczegóły utworu,
- linki Spotify (wyszukiwanie wykonawca + tytuł) na Dashboardzie, w szczegółach i archiwum,
- usunięty przycisk danych demonstracyjnych; stary demonstracyjny wpis ZET jest automatycznie czyszczony,
- RMF_pos/ZET_pos/... oznacza wyłącznie pozycję w najnowszym notowaniu źródła; historia nadal liczy weeks/peak/momentum/familiarity,
- nowy widok Archiwum do przeglądania zapisanych starych notowań,
- szybka edycja statusu i znacznika „Przesłuchany” bezpośrednio z Dashboardu,
- backfill UK Official Singles Chart i Billboard Hot 100,
- RMF backfill pozostaje bez zmian,
- OLiA/OLiS/ESKA: automatyczny backfill historycznych pozycji jest kolejnym etapem; publikowane weeks/peak już są używane.

Po deployu sprawdź: Build 0.2.0 · <SHA>

Uwaga przy aktualizacji patchem:
- stare pliki radiocharts/seed_demo.py i sample_imports/ mogą pozostać fizycznie w repo po rozpakowaniu patcha; aplikacja już ich nie importuje ani nie używa.
- Dockerfile 0.2.0 nie kopiuje sample_imports, więc nie wpływają na obraz.
