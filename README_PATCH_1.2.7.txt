RadioCharts 1.2.7

Dashboard / wydajność:
- 7d radio presence + 28d popularity liczone jednym zapytaniem SQL i jednym cache'em;
- Emisje okres dla Całość używają szybkiego grupowania po song_id zamiast skanu po wszystkich stacjach;
- zakresy czasowe używają indeksu pokrywającego played_at/song_id/station_id;
- airplay revision nie robi już COUNT(*) całej tabeli okien na każdej nawigacji;
- ponowne odkrycie identycznej listy stacji nie unieważnia cache'y;
- MAX daty emisji korzysta z indeksu.

Uwaga: pierwszy start po wdrożeniu może jednorazowo zbudować nowy indeks SQLite.

Wersja:
- web/backend 1.2.7
- Android versionCode 31 / versionName 1.2.7
