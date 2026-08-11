# RadioCharts Research 0.1

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
- import CSV/JSON/XLSX dla ZET, OLiA, OLiS, ESKA i RMF
- Familiarity / Momentum / Format Fit
- liczba tygodni, peak i tygodnie Top 10
- ręczne statusy: Ignore / Watch / Candidate / Current / Current Familiar / Recurrent
- notatki i oznaczenie „przesłuchany”
- Streamlit dashboard
- worker APScheduler uruchamiany raz dziennie

## Dlaczego ZET jest importem ręcznym

W stopce serwisu Eurozet znajduje się obecnie wyraźne zastrzeżenie przeciw automatycznej eksploracji tekstów i danych. Dlatego wersja 0.1 nie odpala automatycznego scrapera ZET. Dane można wczytać z przygotowanego CSV. Jeżeli uzyskasz zgodę / znajdziemy oficjalnie udostępniony feed, podmienimy adapter bez zmiany reszty aplikacji.

## OLiA / OLiS

Serwis OLiS oficjalnie oferuje eksporty CSV/JSON (a dla Single w streamie także Excel), ale bieżące tabele są renderowane dynamicznie. W 0.1 można pobrany eksport po prostu wrzucić w zakładce **Import**. Następny krok to ustalenie stabilnego, oficjalnego URL eksportu i automatyzacja tych dwóch źródeł.

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

## Import OLiA / OLiS / ZET

Dashboard → **Import**. Minimalne kolumny:

```csv
position,artist,title
1,Artist,Song
2,Artist 2,Song 2
```

Opcjonalnie:

```csv
release_date
```

Datę i źródło wybierasz w UI.

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
- wersja obrazu nadal jest czytelna w sidebarze jako `VERSION · git SHA`;
- score'y są prezentowane jako procenty 0–100 (`65%`, nie `6.5%` ani `65/100`);
- brak pozycji na źródle jest prezentowany jako `—` i przy sortowaniu rosnącym pozycji trafia pod prawdziwe numery;
- większa typografia i lekko jaśniejsze tło;
- backfill RMF jest dostępny z UI, domyślnie 130 notowań (~pół roku dni roboczych); wynik można kopiować;
- `Pobierz dane teraz` próbuje automatycznie pobrać RMF, OLiA, OLiS Single w streamie i ESKĘ; błąd jednego źródła nie zatrzymuje pozostałych;
- OLiA/OLiS/ESKA mają diagnostykę z przyciskiem kopiowania; parsery OLiA/OLiS są oznaczone jako eksperymentalne, bo serwis może zmieniać markup;
- ZET pozostaje ręcznym importem.

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
