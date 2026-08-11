RadioCharts 0.2.1
=================

Najważniejsze zmiany:
- Dashboard jest szybszy: agregacje są cache'owane do czasu zmiany bazy,
  a Pandas Styler został usunięty z dużych tabel.
- Nawigacja ma formę zakładek (linków), a tytuł utworu na Dashboardzie i w
  Archiwum prowadzi bezpośrednio do szczegółów.
- Status i znacznik "przesłuchany" są edytowalne bezpośrednio w głównej tabeli
  i zapisują się od razu.
- Automatyczna migracja łączy duplikaty tego samego utworu wynikające z różnych
  zapisów creditów (np. "Martin Garrix x Ed Sheeran" vs "Martin Garrix, Ed Sheeran"
  oraz skrócone/pełne credits Męskiego Grania).
- Billboard: parser korzysta z sekwencyjnego układu THIS WEEK / LW / PEAK / WEEKS zamiast mieszać liczby z responsywnych kontenerów DOM. Stare błędne metadane są jednorazowo czyszczone.
- OLiS, podobnie jak OLiA, ma fallback do oficjalnego eksportu CSV, jeśli
  wyrenderowana strona pokazuje tylko 12 pozycji.
- Widok źródeł w szczegółach został rozdzielony na polskie źródła Familiarity
  oraz UK/Billboard; wykres historii ma filtr źródeł i więcej miejsca.
- ZET pozostaje importem ręcznym; Import pokazuje teraz wyraźnie, czemu baza ZET
  jest pusta i daje przycisk do otwarcia oficjalnej strony listy.

Po aktualizacji:
1. sprawdź Build: 0.2.1,
2. samo wejście w aplikację wykona jednorazową migrację aliasów/duplikatów i wyczyści stare błędne metadane Billboardu,
3. kliknij Pobierz dane teraz — OLiS powinien wrócić do 100 pozycji, a bieżące LW/Peak/Weeks Billboardu zostaną odbudowane poprawnym parserem,
4. istniejący backfill UK/Billboard możesz rozszerzyć później, jeśli chcesz dłuższą krzywą Momentum.
