RadioCharts 1.2.9

EMAUS / Zetta2GO:
- dodany natywny klient Zetta2GO (ASP.NET Session + POST /Zetta/Go + /Logs/GetLog);
- logowanie używa pól userName, pwText="", password, isSmallFormFactor=0; hasło nie jest zapisywane w repo;
- Zetta2GO jest źródłem pełnego logu: AssetID, UniversalIdentifier, statusy PLAYED/NOT_PLAYED/CURRENT/READY,
  EditCode, runtime, reklamy z rozwiniętych Spot Blocków i ETM-y wraz z gapami Zetty;
- Scheduled może pochodzić bezpośrednio z Zetty, a nie tylko z eksportu GSelectora;
- worker odświeża przyszłe logi Scheduled codziennie o 23:59; snapshot na następny dzień jest CUTOFF-em;
- po cutoff Scheduled dla bieżącego dnia nie jest już odświeżany, więc każda późniejsza zmiana logu jest traktowana
  jako ingerencja i widoczna w Porównaniu;
- dalsze dni (domyślnie 14) są odświeżane codziennie jako forecast aż do ich własnego cutoff 23:59;
- Played/live jest odświeżany co minutę; jedna dzienna migawka jest aktualizowana w miejscu zamiast tworzyć 1440 importów;
- identyczny minutowy poll nie zapisuje nic do SQLite i nie unieważnia cache UI;
- o 00:03 wykonywany jest jeszcze finalny odczyt poprzedniego dnia, żeby złapać końcówkę 23:59;
- po starcie workera wykonywany jest od razu live sync i refresh forecastów, ale bez oznaczania przedwczesnego cutoff.

Porównanie Scheduled vs live:
- gdy obie strony są z Zetta2GO, dopasowanie używa stabilnego UniversalIdentifier/log-event GUID;
- READY/WAITING są przechowywane, ale nie liczą się jako emisje w widoku Played; w Porównaniu dostają status „Oczekuje”;
- CURRENT/PENDING_PLAYED/PAUSED są widoczne jako „W trakcie”;
- NOT_PLAYED/EVENT_ERROR są „Niezagrane” i pokazują powód z EditCode (np. 302: dropped due to future ETM);
- podmiana assetu po cutoff przy tym samym wpisie logu jest oznaczana jako „Zmieniony” (≠);
- + oznacza element dodany po cutoff, ✕ usunięty/niezagrany, ↻ zmianę kolejności, ✓ zgodność;
- ETM gap dla danych Zetta2GO jest pokazywany bezpośrednio z Zetty, bez aproksymacji GSelectora.

Konfiguracja (zalecane zmienne środowiskowe / sekrety TrueNAS):
  ZETTA2GO_USERNAME=...
  ZETTA2GO_PASSWORD=...
Opcjonalnie:
  ZETTA2GO_URL=https://emaus-zetta-srv.swdm.local/Zetta2GO
  ZETTA2GO_STATION_ID=3658ac9a-335e-4839-ac18-2159ba1e4a16
  ZETTA2GO_VERIFY_TLS=true|false
  ZETTA2GO_CA_BUNDLE=/sciezka/do/ca.pem
  ZETTA2GO_SCHEDULE_HORIZON_DAYS=14
  ZETTA2GO_LIVE_ENABLED=true
  ZETTA2GO_SCHEDULE_ENABLED=true

W zakładce EMAUS > Import są przyciski testu połączenia oraz ręcznego odświeżenia live/forecastów.
Ręczny importer GSelectora zostaje jako fallback/archiwum.

Kod klienta radiocharts/zetta2go.py jest odseparowany od bazy RadioCharts i można go wykorzystać ponownie
w Sprawdzaczu Audycji (ten sam login/sesja/GetLog, osobna logika biznesowa aplikacji).

Wersja:
- web/backend 1.2.9
- Android versionCode 33 / versionName 1.2.9
