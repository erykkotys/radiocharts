RadioCharts 1.2.16
==================

Poprawka kalkulacji gapów ETM po testach na realnym logu Zetta2GO.

- pełne godziny Hard/Soft nie biorą już do ogona pozycji, które STARTUJĄ dopiero jako 60+ minut poprzedniej godziny; liczy się wyłącznie element rozpoczęty przed granicą godziny;
- końcowy RESET ~59:59 korzysta z przesunięcia pierwszego elementu po RESET, a surowy Asset.gap jest tylko fallbackiem;
- „Ignoruj resety” wylicza carry z czasu pierwszego elementu po RESET względem czasu RESET (np. 08:15:34 po RESET 08:15 = +34 s) i dopiero ten lokalny carry przenosi do kolejnego Hard/Soft;
- poprawka działa także na już zapisanym cutoffie w widoku Scheduled: pełnogodzinne gapy są korygowane w pamięci, bez przepisywania snapshotu w bazie;
- usunięty efekt +17/+30/+50 min powodowany przez zliczanie kolejkowanych pozycji zaczynających się po 60:00.
