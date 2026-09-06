RadioCharts 0.4.11 / Android 0.1.9

Wykresy toplist — web + Android:
- poprawiono błędne wartości pozycji w tooltipie webowym: custom data są teraz przypisane per seria, nie globalnie,
- wspólny crosshair działa po dacie; pionowa linia pokazuje wszystkie realne punkty toplist zapisane tego dnia,
- tooltip pokazuje wyłącznie datę (bez godziny) oraz lista → #miejsce dla wszystkich punktów z wybranego dnia,
- Android wybiera datę po osi X, a nie najbliższy punkt geometrycznie, więc ruch kursora/tap nie przeskakuje do złej serii,
- Peak pokazuje datę pierwszego osiągnięcia najlepszej zapisanej pozycji; na Androidzie jest widoczna od razu w metryce Peak,
- webowa tabela źródeł pokazuje datę obok Peak, jeśli peak jest obecny w naszym archiwum.

Wydajność web:
- revision chart/airplay jest liczony tylko raz na rerun,
- lista stacji, coverage i coverage per stacja są cache'owane po revision + zakresie,
- katalog Baza jest cache'owany po revision,
- zapytania Baza i Emisje nie robią już pełnego GROUP BY całego archiwum chartów tylko po to, aby ustalić first_chart_date.
