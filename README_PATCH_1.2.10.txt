RadioCharts 1.2.10

Ustawienia Zetta2GO:
- login i hasło Zetta2GO ustawia się teraz bezpośrednio w nowej zakładce Ustawienia;
- konfiguracja jest zapisywana lokalnie w współdzielonej bazie RadioCharts (app_meta), więc widzą ją web i worker;
- hasło nie trafia do repozytorium Git ani do paczki aktualizacji;
- UI ma pola login, hasło, URL, Station ID, TLS, horyzont Scheduled oraz włączniki live/cutoff;
- przycisk „Zapisz i testuj” zapisuje dane i od razu sprawdza logowanie/GetLog;
- można wyczyścić login i hasło jednym przyciskiem;
- ustawienia zapisane z UI mają pierwszeństwo przed starszymi env/YAML; jeśli UI nigdy nie było zapisane, dotychczasowe env/YAML nadal działają jako fallback.

Worker:
- zadania Zetta2GO są rejestrowane zawsze, nawet jeśli worker wystartował bez loginu/hasła;
- każde wykonanie czyta najnowsze ustawienia ze wspólnej bazy i tanio kończy pracę, jeśli integracja jest wyłączona/niekompletna;
- dzięki temu po wpisaniu loginu/hasła w Ustawieniach synchronizacja live zaczyna działać przy następnym cyklu minutowym bez restartu kontenera;
- Scheduled/cutoff 23:59 i finalizacja poprzedniego dnia 00:03 zachowują działanie z 1.2.9.

EMAUS > Import:
- komunikat o braku konfiguracji kieruje teraz do zakładki Ustawienia zamiast do zmiennych środowiskowych TrueNAS.

Wersja:
- web/backend 1.2.10
- Android versionCode 34 / versionName 1.2.10
