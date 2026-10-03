RadioCharts 1.2.8

Dashboard / dalsza optymalizacja:
- Dashboard „Całość” nie skanuje już całej tabeli airplay_plays przy liczeniu „Emisje okres”;
- dodany jest mały rollup station/song, utrzymywany automatycznie triggerami SQLite;
- rollup respektuje aktywne/nieaktywne stacje i aktualizuje się przy odświeżaniu okien oraz relinkach song_id;
- kosztowny merge Chart Score + 28d/7d airplay + Popularity jest cache'owany jako gotowa baza Dashboardu;
- zmiany filtrów, suwaków, wyszukiwania i statusów nie przebudowują już tego merge'a;
- nakładanie statusów/notatek jest wektorowe (jeden merge pandas) zamiast pętli po każdym utworze.

Uwaga:
- pierwszy start po wdrożeniu 1.2.8 wykona jednorazowy backfill małej tabeli rollup z istniejących emisji;
- kolejne wejścia w Dashboard „Całość” korzystają już z rollupu.

Wersja:
- web/backend 1.2.8
- Android versionCode 32 / versionName 1.2.8
