RadioCharts 1.2.11

Naprawa pełnego pobierania logu Zetta2GO:
- Zetta2GO/GetLog jest teraz pobierany dokładnie tak jak w webowym Zetta2GO: osobno dla każdej z 24 godzin dnia;
- odpowiedzi godzinowe są scalane w jeden dzienny snapshot z deduplikacją po ID wpisu;
- naprawia sytuację, w której zapytanie 00:00–23:59 zwracało tylko początkową część dnia (w praktyce ok. pierwszych 2 godzin);
- każda godzina wnosi własny TOH, więc parser poprawnie rozdziela 00, 01, 02... zamiast tworzyć błędne czasy typu 00:68, 00:119;
- zachowane zostaje celowe 60+ minutes/hour, jeśli wpis naprawdę należy do poprzedniej godziny planistycznej i przechodzi przez granicę godziny.

EMAUS / Scheduled:
- podsumowanie ETM Hard/Soft respektuje wybraną godzinę; wcześniej tabela była filtrowana godziną, ale kafelki ETM nadal pokazywały markery z całego dnia;
- ponowne odświeżenie Scheduled po aktualizacji zastępuje aktywny snapshot poprawnie pobranym pełnym dniem.

Played:
- minutowy live sync również korzysta z pełnego, 24-godzinnego pobrania dnia, więc bieżący obraz dnia nie kończy się na pierwszych godzinach;
- historyczny backfill Played nie jest jeszcze automatycznie uruchamiany w tej wersji — dodamy go po potwierdzeniu poprawności pełnego dziennego importu.

Wersja:
- web/backend 1.2.11
- Android versionCode 35 / versionName 1.2.11
