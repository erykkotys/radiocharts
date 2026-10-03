RadioCharts 1.2.13

EMAUS / Zetta2GO — tryb „Ignoruj resety” dla gapów ETM:
- Nowy przełącznik „Ignoruj resety” w Scheduled przy filtrach ETM.
- RESET nie jest traktowany jako kotwica czasu: jego gap jest kumulowany do kolejnego HARD/SOFT.
- HARD i SOFT są w tym trybie traktowane jako dokładne kotwice czasu i zerują dalszy carry.
- Kilka RESET-ów pomiędzy kotwicami sumuje swoje odchyłki.
- Dla HH:00 nie dublujemy końcowego RESET-u, jeśli jego gap został już użyty przez mechanizm carry z 1.2.12.
- Obsłużony jest też carry przez północ na podstawie dodatkowo pobranego bloku 23:00 poprzedniego dnia.
- Przeliczenie działa przed filtrem godziny, więc RESET z wcześniejszej części godziny/dnia wpływa na kolejny HARD/SOFT także po przełączeniu widoku.
- Tabela i kafelki ETM pokazują ten sam przeliczony gap po włączeniu przełącznika.
- Snapshoty zapisane przez starszą wersję mają fallback do przeliczenia w pamięci; po kolejnym odświeżeniu Zetta2GO wartości są dodatkowo precomputowane przy imporcie.

Przykład:
08:15 RESET +00:34, 08:30 HARD +00:20 => „Ignoruj resety” pokazuje przy 08:30 HARD +00:54.

Testy: 218 passed.
