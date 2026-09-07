## 0.3.30 — trwała naprawa flag Bazy i równy pasek filtrów

- rekordy z realnym statusem `Baza ...` są ponownie naprawiane przez migrację v3; dodatkowo SQLite ma teraz triggery, które nie pozwalają zapisać `heard=0` lub `downloaded=0` dla aktywnej kategorii Bazy;
- widok Baza ma dodatkowy bezpiecznik odczytu, a kolumny `heard/downloaded` są jawnie konwertowane z SQLite `0/1` na boolean — to właśnie brak tej konwersji powodował, że AG Grid rysował zapisane `1` jako puste checkboxy;
- filtr Status sam renderuje etykietę i wszystkie paski filtrów (Dashboard/Emisje/Baza) są wyrównane do dołu;
- licznik `Utwory (filtr / okres)` używa natywnej kontrolki Streamlita, dzięki czemu etykieta, wysokość i linia bazowa są takie same jak w pozostałych filtrach; poprawione są też marginesy i wysokość popovera Status.

## 0.3.29 — naprawa flag Bazy i wyrównany pasek filtrów

- Dashboard wyrównuje wszystkie kontrolki w górnym pasku do jednej linii; Status ma własną etykietę i ten sam wymiar kontrolki co sąsiednie filtry.
- nowa migracja `radio_library_heard_downloaded_v2` ponownie naprawia istniejące rekordy `Baza <kategoria>`, ustawiając **Przesłuchany = ✓** i **DL = ✓** nawet wtedy, gdy marker z 0.3.28 był już zapisany;
- ręczne ustawienie dowolnego realnego statusu `Baza R2/R1/CF2/CF1/F1/G1/G2/SP1/SP2/NB` również automatycznie wymusza Przesłuchany i DL; `Baza Hold` pozostaje neutralny.

## 0.3.28 — Popularity, filtry wielokrotne i pełna synchronizacja bazy

- dodany filtr **Downloaded: Any / Yes / No** w Dashboardzie, Emisjach i Bazie;
- filtr statusów działa jako popover z checkboxami i pozwala wybrać kilka statusów naraz;
- Dashboard startuje domyślnie w widoku **Kompaktowym**;
- zakładka **Baza** obejmuje również `Baza Hold`;
- synchronizacja katalogu radia ustawia utworom zarówno **Przesłuchany**, jak i **DL**; migracja naprawia też rekordy zaimportowane przez 0.3.27;
- `Familiarity` w UI zostało przemianowane na **Chart Score**;
- dodany **Popularity**: 80% percentyl wolumenu emisji z ostatnich 28 dni + 20% bonus chartowy (OLiA 35%, OLiS 25%, RMF 20%, ZET 12%, ESKA 8%);
- dodany parametr **Emisje 7d** obok **Zasięg 7d** w głównych tabelach i na karcie Utwór;
- Manual opisuje nowy podział Chart Score / Momentum / Popularity / Radio Presence.

## 0.3.27 — audyt własnej bazy i naprawiona synchronizacja

- naprawiony jednorazowy import statusów z lokalnej bazy radia po aktualizacji z 0.3.26;
- nowa zakładka **Baza** pokazuje wszystkie utwory z aktywnym statusem `Baza ...`, także gdy mają 0 emisji w wybranym okresie;
- filtry statusu w Dashboardzie i Emisjach;
- synchronizacja bazy radia przez wklejenie pełnego TXT/TSV oraz diagnostyka liczby utworów/kategorii;
- kolejność statusów dopasowana do hierarchii CF1/CF2/R1/R2/G1/G2/SP1/SP2/NB/F1.

## 0.3.26 — synchronizacja bazy radia i czytelniejsze Emisje

- Emisje pokazują osobno **Zasięg 7d** oraz **Zasięg** dla aktualnie wybranego okresu; okresowy Zasięg jest wyświetlany jako procent raportujących stacji z liczbą stacji w nawiasie.
- RMF/ZET/OLiA/OLiS/ESKA w Emisjach używają kompaktowego zapisu pozycji z tygodniami, np. `#7 (5w)`.
- Przesłuchano, Status i DL są ustawione bezpośrednio za Odsłuchem w głównych tabelach.
- Taksonomia statusów obejmuje teraz wszystkie kategorie z lokalnej bazy radia: R2, R1, CF2, CF1, F1, G1, G2, SP1, SP2 i NB — zarówno jako `... Candidate`, jak i `Baza ...`.
- Jednorazowa migracja produkcyjna importuje do wspólnego katalogu eksport bazy radia z 2026-08-25, aktualizuje status istniejących utworów do `Baza <Cat>`, dodaje brakujące i zaznacza DL.
- W **Dane → Synchronizacja bazy radia** można później wrzucić kolejny plik TSV/TXT tego samego typu i ponownie wyrównać RadioCharts z biblioteką emisyjną.

## 0.3.2 — hotfix AG Grid / React

- usunięte renderery zwracające surowe elementy DOM (`HTMLAnchorElement` / `HTMLButtonElement`), które powodowały React error #31 w `streamlit-aggrid`;
- Szczegóły, Spotify i odsłuch 30 s są obsługiwane przez bezpieczny `onCellClicked`;
- zachowane zaznaczanie całego wiersza i edycja statusu/przesłuchania.

## Wersja 0.2.7

Aktualizacja: stabilniejsze OLiA/OLiS, live search i scalony panel backfilli/progresu.

# RadioCharts Research 0.2.3

## Zmiany 0.2.1

- cache agregacji i szybszy Dashboard bez Pandas Styler,
- zakładkowa nawigacja, klikalne tytuły, status edytowany inline,
- automatyczne scalanie aliasów tego samego utworu między źródłami,
- poprawiony parser Billboard LW/Peak/Weeks i jednorazowe czyszczenie starych błędnych metadanych,
- OLiS fallback do oficjalnego eksportu CSV,
- czytelniejszy widok źródeł i historia z filtrem.


Prototyp narzędzia do oceny **Familiarity**, **Momentum** i **Format Fit** utworów na podstawie polskich list radiowych/streamingowych.

## Wagi Familiarity

- OLiA: 30%
- RMF: 25%
- Radio ZET: 20%
- OLiS Single w streamie: 15%
- ESKA: 10%

Wynik jest normalizowany do źródeł, które są już obecne w bazie. Dashboard pokazuje również procent pokrycia źródeł.

## Co działa w 0.1

- SQLite z pełną historią notowań (nie tylko bieżącą pozycją)
- automatyczny collector bieżącej Poplisty RMF
- eksperymentalny backfill RMF po numerach notowań
- Familiarity / Momentum / Format Fit
- liczba tygodni, peak i tygodnie Top 10
- ręczne statusy: Ignore / Watch / Candidate / Current / Current Familiar / Recurrent
- notatki i status odsłuchu
- Streamlit dashboard
- worker APScheduler uruchamiany raz dziennie

## Radio ZET

Od 0.2.8 aplikacja automatycznie pobiera bieżące Top 20 ZET oraz ma eksperymentalny backfill publicznych stron archiwalnych. Ręczna zakładka Import została usunięta w 0.3.13 — bieżące dane i backfille obsługuje zakładka **Dane**. Automatyzacja nie omija logowania, CAPTCHA ani innych technicznych zabezpieczeń.

## OLiA / OLiS

Serwis OLiS oficjalnie oferuje eksporty CSV/JSON (a dla Single w streamie także Excel), a RadioCharts pobiera OLiA/OLiS automatycznie w zakładce **Dane**. Ręczna zakładka Import nie jest już używana.

## Lokalny test bez Dockera

```bash
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\\Scripts\\activate     # Windows
pip install -r requirements.txt
export PYTHONPATH=.
export RADIOCHARTS_DB=$PWD/data/radiocharts.db
python -m radiocharts.seed_demo
streamlit run radiocharts/app.py
```

Otwórz `http://localhost:8501`.


## Android / prywatne API (od 0.4.0)

RadioCharts ma teraz osobne, prywatne API na porcie **8502** przeznaczone dla natywnego klienta Android. Streamlit nadal działa na 8501 i korzysta z tej samej bazy SQLite. Android **nie otwiera pliku SQLite bezpośrednio** — wszystkie odczyty i zmiany statusu przechodzą przez API.

W TrueNAS uruchom dodatkowy serwis z tego samego obrazu:

```text
uvicorn radiocharts.api:app --host 0.0.0.0 --port 8502
```

i zmapuj `8502:8502`, używając tych samych volume `/app/data`, `/app/config`, `/app/logs`. Gotowy przykład jest w `compose.truenas.example.yml`.

Do połączenia z telefonu używamy Tailscale. W aplikacji Android wpisz adres w rodzaju `http://100.x.y.z:8502/` albo nazwę MagicDNS serwera. **Nie przekierowuj portu 8502 na routerze.** Tailscale szyfruje transport w swojej sieci prywatnej.

Opcjonalnie możesz ustawić `RADIOCHARTS_API_TOKEN` w usłudze API i wpisać ten sam token w aplikacji. Gdy zmienna nie jest ustawiona, API nie wymaga tokenu — jest to wariant przeznaczony wyłącznie do LAN/Tailscale. Dokumentacja testowa API jest dostępna lokalnie pod `/docs`.

Projekt Android Studio znajduje się w `android/RadioChartsAndroid`. Klient zawiera Dashboard, Emisje, Bazę, kartę Utwór, odsłuch 30 s, Spotify, zmianę Status/Downloaded/Notatki oraz wybór konkretnych stacji w emisjach utworu.

## TrueNAS SCALE – proponowany deployment

### 1. Dataset

Utwórz np.:

```text
/mnt/POOL/apps/radiocharts/
├── data
├── config
└── logs
```

Skopiuj `config/config.yml` do datasetu `config`.

### 2. Obraz

Do pierwszego testu najłatwiej zbudować obraz przez `docker compose -f compose.local.yml build`, a następnie wypchnąć go do GHCR/Docker Hub. Docelowo repo + GitHub Actions może budować `ghcr.io/.../radiocharts:<wersja>`. Plik `compose.truenas.example.yml` celowo używa obrazu z registry — nie zakłada, że TrueNAS ma dostęp do katalogu ze źródłami jako kontekstu builda.

W `compose.truenas.example.yml` podmień `ghcr.io/REPLACE_ME/radiocharts:0.1.0` na własny obraz.

### 3. Custom App

TrueNAS SCALE → Apps → Discover → menu → **Install via YAML**.

Wklej compose, po wcześniejszej zmianie:

```text
/mnt/POOL/...
```

na prawdziwą nazwę Twojego poola.

Po uruchomieniu dashboard będzie na:

```text
http://IP_TRUENAS:8501
```

## Pierwszy backfill RMF

Z konsoli kontenera/obrazu:

```bash
python -m radiocharts.collector --rmf-backfill 30
```

Na początek użyj 20–30 notowań. Jeżeli archiwalny parametr RMF okaże się stabilny, można potem zrobić np. 130 notowań (~6 miesięcy dni roboczych). Collector sprawdza, czy zwrócony numer notowania jest tym, o który prosił, żeby przypadkiem nie zapisać wielokrotnie bieżącej listy.

## Znane ograniczenia 0.1

1. Matching utworów jest celowo konserwatywny: artist + title po normalizacji. Wariant „JENNIE Remix” i wersja oryginalna mogą zostać uznane za osobne utwory.
2. Daty premier nie są jeszcze pobierane automatycznie.
3. OLiA/OLiS są jeszcze importowane ręcznie.
4. Wskaźniki nie są jeszcze skalibrowane na Twojej rzeczywistej polityce kategorii — do tego posłużą ręczne statusy.
5. Backfill RMF trzeba zweryfikować po deploymentcie, bo środowisko robocze tej paczki nie miało bezpośredniego dostępu HTTP do stron, a parser został przygotowany na podstawie aktualnej struktury widocznej publicznie.

## Kolejność dalszych prac

1. Uruchomić 0.1 i sprawdzić parser RMF.
2. Zrobić 4–8 tygodni backfillu RMF.
3. Podłączyć oficjalny eksport OLiA i OLiS.
4. Wrzucić historyczne ZET z bezpiecznego źródła/importu.
5. Dodać ekran „Candidates” i stroić progi na Twoich ręcznych decyzjach.
6. Dodać aliasy/merge utworów oraz automatyczne daty premier/ISRC.

## Najwygodniejszy obraz do TrueNAS: GitHub Container Registry

Paczka zawiera `.github/workflows/docker.yml`. Jeśli wrzucisz katalog jako repo na GitHub i zrobisz push do `main`, workflow zbuduje obraz:

```text
ghcr.io/TWOJ_LOGIN_GITHUB/radiocharts:0.1.0
```

Repo/publiczny package jest najprostszy do pierwszego testu. Przy prywatnym package trzeba dodać dane logowania registry w TrueNAS.

Potem podmień obraz w `compose.truenas.example.yml` i wklej YAML jako Custom App.

## Zmiany 0.1.3
- większa typografia interfejsu,
- diagnostyka RMF jest wyświetlana jako blok kodu z natywnym przyciskiem kopiowania,
- Familiarity / Momentum / Format Fit są jednoznacznie pokazywane jako score `0–100`, nie jako procent,
- diagnostyka RMF pozostaje widoczna w sesji po wykonaniu testu.

## Zmiany 0.1.4

- naprawione publikowanie `latest`: workflow buduje tylko z `main`, jawnie przypina `latest`, a `concurrency` anuluje starszy build gdy wpada nowszy push;
- wersja obrazu jest widoczna dyskretnie w prawym górnym rogu jako `VERSION · git SHA`;
- score'y są prezentowane jako procenty 0–100 (`65%`, nie `6.5%` ani `65/100`);
- brak pozycji na źródle jest prezentowany jako `—` i przy sortowaniu rosnącym pozycji trafia pod prawdziwe numery;
- kompaktowa typografia i lekko jaśniejsze tło;
- backfill RMF jest dostępny z UI, domyślnie 130 notowań (~pół roku dni roboczych); wynik można kopiować;
- `Pobierz dane teraz` próbuje automatycznie pobrać RMF, OLiA, OLiS Single w streamie i ESKĘ; błąd jednego źródła nie zatrzymuje pozostałych;
- OLiA/OLiS/ESKA mają diagnostykę z przyciskiem kopiowania; parsery OLiA/OLiS są oznaczone jako eksperymentalne, bo serwis może zmieniać markup;
- ZET: automatyczny bieżący collector + eksperymentalny backfill; ręczny import usunięty z UI.

### Tagi obrazu w GHCR

Workflow publikuje ten sam build pod trzema nazwami:

- `ghcr.io/<user>/radiocharts:0.1.4` — wersja aplikacji z pliku `VERSION`;
- `ghcr.io/<user>/radiocharts:latest` — ruchomy alias wskazujący najnowszy build `main`;
- `ghcr.io/<user>/radiocharts:sha-XXXXXXX` — build związany z konkretnym commitem Git.

`latest` nie jest numerem wersji ani specjalną funkcją Dockera. To zwykły tag, który można przepiąć na inny digest. Dlatego UI zawsze pokazuje też SHA commita.

## 0.1.7
- parser OLiA/OLiS dopasowany do rzeczywistego DOM po renderowaniu Playwright,
- parser ESKA oparty na parze `pozycja + trend`,
- diagnostyka pokazuje preview parsowanych pozycji.

## 0.2.0 — research UI
- Dashboard: kliknięcie wiersza otwiera kartę utworu.
- Spotify: link wyszukiwania przy każdym utworze.
- Archiwum: przegląd zapisanych notowań wszystkich źródeł.
- Status: szybka edycja na Dashboardzie.
- Bieżące `*_pos` oznacza wyłącznie najnowsze notowanie; historia służy do weeks/peak/trend.
- Backfill: RMF + UK + Billboard. OLiA/OLiS/ESKA historyczny backfill jest planowany osobno.

## 0.2.5

Wydajność i obsługa procesów: szybki agregator metryk, osobna zakładka **Dane**, collectory/backfille działające w procesie potomnym z możliwością zatrzymania, osobne pobieranie każdego źródła, fail-fast OLiA/OLiS, liczniki `filtr / ogółem` oraz numeryczne sortowanie pozycji z brakiem wyświetlanym jako `-`.

## 0.2.6

- mniejszy górny margines nad tytułem aplikacji,
- automatyczny pasek postępu procesów przez `st.fragment(run_every=1)` — bez ręcznego „Odśwież status”,
- każdy bieżący collector ma twardy limit czasu; OLiA/OLiS kończą próbę szybko zamiast blokować UI,
- OLiA/OLiS używają jednej sesji Chromium do widoku + oficjalnego CSV, bez uruchamiania drugiej przeglądarki,
- przycisk „Backfill wszystkie 3” dla RMF + UK + Billboard,
- eksperymentalny backfill OLiA i OLiS po tygodniach, przez oficjalną nawigację archiwum i CSV; błędne tygodnie są pomijane,
- wyszukiwarka w widoku „Utwór” jest zwykłym polem tekstowym i ignoruje polskie znaki (`e=ę`, `l=ł`, itd.),
- szybki import bieżącej listy ZET jest dostępny bezpośrednio w zakładce Dane.

## Zmiany 0.2.8
Dashboard pokazuje stan świeżości każdego źródła. Pozycje zawsze pochodzą z najnowszego poprawnie zapisanego notowania; osobny status informuje, czy źródło zostało sprawdzone dzisiaj i czy ostatnia próba się udała. Worker sprawdza źródła o 07:30 i 20:30 Europe/Warsaw.

ZET ma automatyczny collector bieżącego Top 20 oraz eksperymentalny backfill po publicznych adresach archiwalnych. OLiA/OLiS wróciły do dłuższego, sprawdzonego mechanizmu renderowania/kliknięcia pełnej listy z wersji 0.1.9; zadania nadal działają w osobnym, zatrzymywalnym procesie.

## 0.3.1 — interaktywny research
- Kliknięcie w tabeli zaznacza cały wiersz; status i odsłuch pozostają dostępne bez opuszczania Dashboardu.
- Odsłuch 30 s bezpośrednio z tabeli (preview pobierane na żądanie) + link Spotify.
- `Archiwum` zmienione na `Notowania`, z najnowszymi i historycznymi listami oraz metrykami utworu.
- Wskaźniki można przeliczać dla wybranego horyzontu czasu.
- Backfill do ok. 5 lat i wyższy/nieliniowy wykres historii pozycji.

## 0.3.4 — responsywny Dashboard i player
- Dashboard: `Auto / Pełny / Kompaktowy`; Auto składa tygodnie do kolumn źródeł na węższym ekranie (`#7  5t`), a na szerokim zachowuje osobne kolumny.
- W trybie Auto/Kompaktowym wykonawca i tytuł są przypięte z lewej.
- Wyszukiwarka utworów otwiera szczegóły w tym samym oknie.
- Kliknięcie `▶ 30s` pokazuje pływający player z przewijaniem 30-sekundowego podglądu i szybkim linkiem do Spotify.

## 0.3.6 — stabilna nawigacja, player globalny i Emisje
- Kompaktowy Dashboard używa bezpiecznego tekstowego formatu pozycji `#7 · 5w`, bez surowego HTML w komórkach.
- Spotify w AG Grid jest obsługiwane przez kliknięcie komórki; kartę Utworu otwierasz dwuklikiem na tytule lub wykonawcy, a wyszukiwarka Utwór przechodzi do szczegółów w tej samej karcie.
- Browser Back/Forward wymusza odświeżenie widoku, jeśli Streamlit nie zareaguje sam na zmianę query string.
- Jeden wspólny player preview 30 s jest przyklejony do dołu całego viewportu, można go przewijać i zamknąć; przycisk odsłuchu jest również w widoku Utwór.
- Nowa zakładka **Emisje**: automatyczne odkrywanie stacji z publicznego katalogu odSluchane.eu, zapis konkretnych emisji z bloków 2h, filtrowanie stacji checkboxami i agregacja dla dowolnego zapisanego zakresu dat.
- Emisje pokazują: łączną liczbę spinów, liczbę stacji, średnią/stację, maksimum na jednej stacji, najmocniejszą stację, ostatnią emisję, status, odsłuch, Spotify i szczegóły dopasowanego utworu.
- Worker emisji pobiera poprzedni zakończony blok 2h co dwie godziny o `:12`. Backfill jest resumable/idempotentny i ma limit 100 000 okien 2h na jeden proces.

## 0.3.9 — naprawa emisji i wspólny katalog utworów
- Naprawiona migracja starych tabel Emisji: `airplay_stations.station_id` jest ponownie prawdziwym kluczem głównym, więc znika błąd SQLite `foreign key mismatch` przy `airplay_windows`/`airplay_plays`. Migracja przebudowuje tylko tabele airplay i zachowuje dotychczasowe dane.
- Emisje i notowania pozostają osobnymi **miarami**, ale korzystają z jednego katalogu `songs`. Ten sam utwór ma ten sam `song_id`, status, notatkę i odsłuch niezależnie od tego, czy trafiono na niego przez listę przebojów czy emisję.
- Utwór obecny wyłącznie w emisjach także trafia do wspólnego katalogu, ale nie wpływa na `chart_revision`, Familiarity, Momentum ani Dashboard dopóki nie pojawi się w `chart_entries`.
- Ranking Emisji pokazuje obok liczby odtworzeń bieżące pozycje RMF/ZET/OLiA/OLiS/ESKA oraz pozwala bezpośrednio odsłuchać, otworzyć kartę i edytować status.
- Widok Utwór obsługuje także utwory znane tylko z emisji; wtedy metryki z notowań są pokazane jako brak danych, a nie jako `0%`.
- Wyszukiwarka Utworu ponownie ignoruje polskie znaki (`meskie` → `Męskie`) przez normalizowany filtr przed natywnym wyborem Streamlita.
- Dwuklik na tytule lub wykonawcy w tabeli przechodzi na kartę utworu i wymusza pozycję na górze strony zamiast zachowywać scroll z Dashboardu.

## 0.3.10 — kompletność emisji w blokach 2h

odSluchane.eu udostępnia dobę w 12 blokach po 2 godziny. RadioCharts pokazuje teraz pokrycie tych bloków dla wybranego zakresu. Bieżące uzupełnienie sprawdza ostatnie 24h i pobiera brakujące bloki, a backfill nie zapisuje bloków, które jeszcze się nie zakończyły.

## 0.3.11 — pełne logi procesów

Każdy collector i backfill dostaje trwały log `/app/data/jobs/<job_id>.log`. Log nie jest limitowany do ostatnich 50 komunikatów: zapisuje cały progres, stdout/stderr collectorów, tracebacki i końcowe podsumowanie. Po zakończeniu joba również jego plik JSON zachowuje pełne `messages`, a backfill dodaje `source_summary` per źródło (`requested`, `ok`, `errors`, `reported_messages`). W UI można podejrzeć końcówkę logu w sekcji **Log procesu**.


### 0.3.31
Dashboard pokazuje również Emisje okres, odpowiadające wybranemu Okresowi wskaźników. Dashboard, Emisje i Baza mają kolumnę L.p. działającą jako numer wiersza po sortowaniu. Na karcie Utwór wykresy są domyślnie rozwinięte, a status można zmieniać również w tabeli Emisji radiowych.

### 0.3.32
Kolumna L.p. w Dashboardzie, Emisjach i Bazie działa jak numeracja widocznych wierszy: po dowolnym sortowaniu lub filtrowaniu zawsze pokazuje 1, 2, 3, 4... od góry.

### 0.3.33
Na karcie **Utwór → Emisje radiowe** można wybrać **Wszystkie stacje** albo **Wybrane stacje** i wskazać konkretne rozgłośnie. Filtr stacji obejmuje dane dla wybranego zakresu oraz szczegóły per stacja/dzień; globalne **Zasięg 7d** i **Emisje 7d** zachowują dotychczasowe znaczenie.

### 0.4.2 — szybszy Android i pełniejsze sortowanie
- endpoint mobilny Emisje/Baza używa lekkiej agregacji SQLite i cache zależnego od rewizji emisji, stacji i zakresu dat; nie wykonuje już dwóch pełnych agregacji wszystkich utworów na każde sortowanie/filtr;
- karta Utwór liczy liczbę raportujących stacji osobnym lekkim zapytaniem zamiast uruchamiać pełny Radio Presence dla całego katalogu;
- mobilne metryki bazowe są cache'owane, ale Przesłuchany/Status/DL/Notatka nadal są nakładane na żywo;
- Android 0.1.1 pobiera po 120 pozycji i ma **Pokaż kolejne**, dłuższy timeout dla wolniejszego pierwszego przeliczenia oraz retry po chwilowym zerwaniu połączenia;
- sortowanie Androida obejmuje m.in. Emisje/Zasięg/Rotację/Radio Presence okresu, Popularity, Chart Score, Momentum, Zasięg/Emisje/Radio Presence 7d, średnią pozycję, RMF/ZET/OLiA/OLiS/ESKA, wykonawcę, tytuł i status; kierunek można odwrócić przyciskiem ↑/↓.

### 0.4.3 — aktualizacje Androida przez RadioCharts API
- Android 0.1.2 przechodzi z efemerycznego debug-signingu na stały klucz release trzymany wyłącznie w GitHub Actions Secrets. Obecne debug APK 0.1.0/0.1.1 trzeba **jednorazowo odinstalować** przed instalacją pierwszego release 0.1.2; późniejsze wersje instalują się już jako normalne aktualizacje.
- po uruchomieniu Android automatycznie sprawdza `/api/v1/android/update`; w **Ustawienia → Aktualizacje** jest też ręczne **Sprawdź aktualizacje**;
- **Aktualizuj** pobiera APK z `/api/v1/android/apk` po tym samym LAN/Tailscale, weryfikuje SHA-256 i przekazuje plik systemowemu instalatorowi Androida. Za pierwszym razem Android może poprosić o `Allow from this source` dla RadioCharts;
- workflow **Docker + Android release** buduje podpisane APK przed obrazem Dockera, zapisuje APK + `update.json` w obrazie i publikuje obraz do GHCR. Po redeployu TrueNAS nowa wersja APK staje się dostępna dla telefonu bez ręcznego pobierania z GitHuba;
- wymagane sekrety repozytorium: `ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS`, `ANDROID_KEY_PASSWORD`. Klucza `.jks` nie należy commitować do repozytorium.


### 0.4.4 — poprawka CI Androida

Naprawiono krok weryfikacji podpisanego APK w GitHub Actions. `apksigner` jest teraz uruchamiany z jawnej ścieżki Android Build Tools 35.0.0, więc workflow nie zależy od obecności narzędzia w `PATH`. Android pozostaje w wersji 0.1.2, ponieważ poprzedni release nie został opublikowany.


### 0.4.5 — szybsza praca z listy w Androidzie

Android 0.1.3 pozwala bez otwierania karty Utwór odsłuchać 30-sekundowy preview i zmienić status bezpośrednio z Dashboardu oraz Emisji. W Emisjach dodano wybór konkretnych stacji radiowych; wybrane stacje są przekazywane do API i zawężają emisje, liczbę stacji, zasięg oraz pozostałe metryki okresowe.

### 0.4.6 — Android: trwały odsłuch, Baza i dokładne daty

Android 0.1.4 przenosi odtwarzacz 30-sekundowych preview poza wiersze `LazyColumn`, więc scrollowanie nie zatrzymuje audio. W Bazie są teraz te same szybkie kontrolki odsłuchu i zmiany statusu co na Dashboardzie/Emisjach. Emisje startują domyślnie posortowane malejąco po liczbie emisji w wybranym okresie. W Emisjach i Bazie, obok presetów 7/28/90 dni, dodano wybór dokładnych dat **Od** i **Do**.


### 0.4.7 — Android: kompaktowe filtry list

Android 0.1.5 zmniejsza panel filtrów w Emisjach i Bazie. Status, DL, sortowanie, kierunek, presety okresu, dokładne daty i stacje są w jednym poziomo przewijanym pasku. Dokładne pola Od/Do rozwijają się dopiero po naciśnięciu przycisku Daty. Usunięto pełnoszerokie przyciski Stacje i Odśwież / zastosuj filtry, dzięki czemu lista utworów dostaje wyraźnie więcej wysokości.


### 0.4.8 — Android: Baza CF i Spotify przy utworach

Android 0.1.6 przypina `Baza CF1` i `Baza CF2` na początku rozwijanych list statusów (zarówno filtra, jak i szybkiej zmiany statusu na karcie) i ogranicza wysokość dropdownu, żeby przewijanie było jednoznaczne. Każda karta utworu dostała też bezpośredni przycisk Spotify obok odsłuchu 30 s.


### 0.4.9 — Android: poprawione statusy i wykresy toplist

Android 0.1.7 przywraca `Baza CF1` i `Baza CF2` do naturalnej kolejności statusów zwracanej przez API. Szybka zmiana statusu korzysta teraz z przewijalnego okna wyboru, dzięki czemu wszystkie pozycje — także końcowe CF1/CF2 — są dostępne bez przepinania ich na początek. W ekranie Utwór wiersze sekcji **Pozycje na listach** są klikalne i otwierają pełny wykres historii wybranej toplisty. Ekran wykresu przełącza Androida w orientację poziomą, chowa dolną nawigację, pokazuje aktualną pozycję, peak, liczbę notowań i przebieg pozycji w czasie.

### 0.4.11 — wspólny crosshair toplist + szybsza nawigacja

Web i Android pokazują teraz po jednej dacie wszystkie realne punkty toplist na wspólnym pionowym crosshairze. Tooltip nie pokazuje godziny, tylko datę oraz listę i miejsce. Naprawiono też błąd webowego tooltipa, który przy wielu seriach potrafił wyświetlać pozycję z innego wiersza niż wskazywany punkt. Peak ma datę pierwszego osiągnięcia najlepszej zapisanej pozycji. Web cache'uje metadane airplay/Bazy i używa lżejszych zapytań `first_chart_date`, dzięki czemu przełączanie Dashboard → Emisje/Baza jest szybsze po pierwszym wejściu.

### 0.4.10 — Android: wspólny wykres toplist i szczegóły punktów

Android 0.1.8 dodaje w Utworze wspólny wykres wszystkich toplist obok pozostawionych osobnych wykresów RMF/ZET/ESKA/OLIA/OLIS. Wspólny widok używa jednej osi dat, osobnej linii i legendy dla każdej listy. Na punktach wykresu po najechaniu kursorem lub dotknięciu pokazywane są dokładna lista, miejsce i data. Ekran wykresu nadal działa w orientacji poziomej.



### 1.0.2 — natychmiastowy stan Przesłuchany i rozróżnione checkboxy

Kolumna **✓ (Przesłuchany)** reaguje teraz od razu po zmianie Statusu w tabeli: **Nie słuchałem** odznacza checkbox, a każdy inny status zaznacza go bez czekania na kolejne przeładowanie widoku. Stan nadal jest pochodny od Statusu i nie może zostać ustawiony sprzecznie ręcznie.

Dla szybszego odczytu wizualnego oba checkboxy mają osobne kolory: **Przesłuchany = czerwony**, **Downloaded = zielony**. Niezaznaczone pola pozostają neutralne.

### 1.0.1 — prostsze otwieranie utworu i czytelny stan przesłuchania

Usunięto osobną kolumnę **Otwórz** z tabel. Kartę konkretnego utworu otwiera teraz **dwuklik na tytule lub wykonawcy**, dzięki czemu odzyskane miejsce zostaje dla właściwych danych.

Do tabel wraca kompaktowa kolumna **✓ (Przesłuchany)**. Checkbox jest wskaźnikiem tylko do odczytu i wynika bezpośrednio ze Statusu: **Nie słuchałem** = niezaznaczony, każdy inny status = zaznaczony. Pole `heard` nadal pozostaje w bazie dla zgodności, ale UI nie pozwala już stworzyć stanu sprzecznego ze Statusem.

### 1.0.0 — pierwsze stabilne wydanie

RadioCharts wychodzi z etapu MVP i dostaje stabilne wersjonowanie 1.x. Osobny checkbox **Przesłuchany** został usunięty z interfejsu; pole pozostaje w bazie dla zgodności, ale jego stan wynika teraz ze statusu — każdy status poza **Nie słuchałem** oznacza przesłuchany utwór. **Downloaded** pozostaje osobną flagą.

Na karcie **Utwór** zmiana Statusu oraz Downloaded zapisuje się automatycznie, a przycisk **Zapisz** służy wyłącznie do zapisania notatki. W Emisjach i Bazie dodano preset **Dzisiaj (1d)** obok dotychczasowych zakresów, przy zachowaniu domyślnego 7d.

Android 1.0.0 otwiera wykresy w bieżącej orientacji — typowo pionowej — i pozwala normalnie obracać telefon przy włączonym auto-rotate. Dodatkowy przycisk **Poziomo** wymusza landscape także przy systemowej blokadzie portretu; **Auto** zwalnia wymuszenie.
