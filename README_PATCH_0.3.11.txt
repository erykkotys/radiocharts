RadioCharts Research 0.3.11

- Każdy job zapisuje trwały pełny log tekstowy do /app/data/jobs/<job_id>.log.
- Log ma timestampy UTC, poziom wpisu, każdy komunikat progresu, pełne stdout/stderr collectorów oraz traceback przy nieobsłużonym wyjątku.
- JSON joba nie ucina już historii po zakończeniu: pole messages zawiera pełny przebieg. Podczas pracy nadal trzymane jest tylko ostatnie 30 wpisów, żeby częste odświeżanie nie przepisywało wielkiego JSON-a.
- Backfill zapisuje source_summary per źródło: requested / ok / errors / reported_messages.
- W UI statusu procesu jest rozwijana sekcja „Log procesu” z końcówką pełnego pliku i ścieżką do logu.
- Start procesu nie wyrzuca już stdout/stderr do /dev/null — trafiają awaryjnie do tego samego pliku .log.
