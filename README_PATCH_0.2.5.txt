RadioCharts 0.2.5

- dużo szybszy pierwszy render: metryki liczone bez tysięcy małych operacji pandas; test syntetyczny ~9000 wpisów / ~1000 utworów: ~0.09 s dla compute_scores
- init_db ma lekki fast-path i nie wykonuje pełnych migracji przy każdym odczycie
- osobna zakładka Dane; pobieranie i backfille przeniesione z sidebara
- collectors/backfille uruchamiane w osobnym procesie: UI nie czeka na zakończenie
- osobne przyciski RMF/OLIA/OLIS/ESKA/UK/BILLBOARD + Pobierz wszystkie
- osobne backfille RMF/UK/Billboard
- Stop procesu (SIGTERM na grupę procesu) + status/log ostatniego zadania
- OLiA/OLiS fail-fast: jedna próba renderu i maksymalnie jedna próba oficjalnego CSV, krótsze timeouty
- liczniki dashboardu pokazują: po filtrach / ogółem
- pozycje w tabeli są sortowane po wartości numerycznej; brak ma techniczną wartość 999, ale jest renderowany jako '-'
- Archiwum ma wszystkie rekordy, tabelę ustawioną jawnie na ok. 20 widocznych wierszy (height 770, row_height 36)
- ZET nadal ręcznie: na stronie jest jawne zastrzeżenie przeciw automatycznej eksploracji tekstów i danych
