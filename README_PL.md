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
- notatki i oznaczenie „przesłuchany”
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
- `Otwórz` i `Spotify` w AG Grid są obsługiwane przez kliknięcie komórki; wyszukiwarka Utwór przechodzi do szczegółów w tej samej karcie.
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
- Kliknięcie `Otwórz` w tabeli przechodzi na kartę utworu i wymusza pozycję na górze strony zamiast zachowywać scroll z Dashboardu.

## 0.3.10 — kompletność emisji w blokach 2h

odSluchane.eu udostępnia dobę w 12 blokach po 2 godziny. RadioCharts pokazuje teraz pokrycie tych bloków dla wybranego zakresu. Bieżące uzupełnienie sprawdza ostatnie 24h i pobiera brakujące bloki, a backfill nie zapisuje bloków, które jeszcze się nie zakończyły.

## 0.3.11 — pełne logi procesów

Każdy collector i backfill dostaje trwały log `/app/data/jobs/<job_id>.log`. Log nie jest limitowany do ostatnich 50 komunikatów: zapisuje cały progres, stdout/stderr collectorów, tracebacki i końcowe podsumowanie. Po zakończeniu joba również jego plik JSON zachowuje pełne `messages`, a backfill dodaje `source_summary` per źródło (`requested`, `ok`, `errors`, `reported_messages`). W UI można podejrzeć końcówkę logu w sekcji **Log procesu**.
