## 1.2.26 — bezpośredni Spotify i uzupełnianie dat premier

- **Udostępnij** rozwiązuje teraz utwór do bezpośredniego `open.spotify.com/track/...` zamiast starego smart-linku. Najpierw używa zapisanego mapowania, a brakujące linki są uzupełniane przez publiczny indeks ListenBrainz.
- Dla utworów bez daty premiery RadioCharts stopniowo uzupełnia **najwcześniejszą znaną datę wydania** z MusicBrainz (`first-release-date`); przy dostępności ISRC wyszukiwanie używa go jako najmocniejszego identyfikatora.
- Worker uzupełnia małe paczki co dwie godziny, priorytetowo Candidate/Watch, bez blokowania Dashboardu. W **Dane** jest też ręczny przycisk „Uzupełnij teraz”.
- Watched pokazuje teraz datę premiery tak samo jak Dashboard: dokładną datę z katalogu, a gdy jej jeszcze nie ma — przybliżenie `~YYYY/MM` z pierwszego pojawienia się na notowaniach.
- Bezpośrednie linki Spotify i nowe daty automatycznie unieważniają cache widoków po zapisie przez worker.
- Spotify może być odtwarzane przez oficjalny embed/IFrame po uzyskaniu dokładnego track ID, ale Spotify nie udostępnia surowego audio do generowania własnego waveformu. Waveform można natomiast dołożyć do istniejącego 30-sekundowego preview, które korzysta z osobnego źródła audio.
- Android: numer wydania zsynchronizowany do 1.2.26 / `versionCode = 49`.

## 1.2.25 — spójne odświeżanie Played

- Web Schedule → Played odświeża teraz **cały blok live co 5 s** jako fragment Streamlita: karta TERAZ, zielony CURRENT, historia Played i dalszy Scheduled korzystają zawsze z tej samej świeżej rewizji bazy.
- Naprawiono sytuację, w której karta „TERAZ” była już odświeżona, a playlista nadal wskazywała poprzedni element (na screenie: górny live i zielony wiersz mogły pokazywać dwie różne rzeczy).
- Odświeżenie nie przeładowuje całej strony ani filtrów Schedule; sieciowy sync Zetta2GO nadal wykonuje worker, a fragment natychmiast podchwytuje jego nowy snapshot.
- Android: numer wydania zsynchronizowany do 1.2.25 / `versionCode = 48`.

## 1.2.24 — odsłuch 30 s w Schedule

- Naprawiono przycisk ▶ w Schedule/Porównaniu: playlisty renderowane przez `st.markdown` korzystają teraz z delegowanego handlera kliknięć w dokumencie strony zamiast zawodnego inline `onclick`.
- Floating player pokazuje komunikat „Szukam podglądu…” i czytelny błąd, jeśli iTunes Preview nie zwróci 30-sekundowego fragmentu.
- Android: numer wydania zsynchronizowany do 1.2.24 / `versionCode = 47`.

## 1.2.22 — Watched i porządek głównej nawigacji

- Główne zakładki web są ułożone: **Dashboard, Notowania, Emisje, Watched, Utwór, Baza, Schedule, Ustawienia, Manual**. Techniczna strona **Dane** nadal działa pod bezpośrednim adresem `?view=data`, ale nie zajmuje miejsca w głównym pasku.
- Dotychczasowa zakładka **EMAUS** w głównym pasku nazywa się teraz **Schedule**; wewnątrz nadal pracuje na danych EMAUS/Zetta2GO.
- Nowa zakładka **Watched** łączy wspólny katalog utworów z Dashboardu i Emisji.
- Pierwsza tabela Watched pokazuje najpierw wszystkie statusy `* Candidate`, a potem `Watch`, z tymi samymi edytowalnymi statusami i metrykami co pozostałe główne tabele.
- Pod nią jest **Top 50 Popularity** spośród utworów ze statusem **Nie słuchałem**, również z połączonego świata Dashboard + Emisje.
- Członkostwo obu tabel jest zamrażane na czas bieżącej strony: po zmianie statusu np. na `Baza G1` utwór pozostaje na ekranie i znika/przenosi się dopiero po odświeżeniu strony.
- Android ma zsynchronizowany numer wydania 1.2.22 / `versionCode = 45`; etykieta EMAUS w dolnej nawigacji została zmieniona na **Schedule**.

## 1.2.20 — spójny EMAUS, ETM i live continuity

- Scheduled, Played i Porównanie mają wspólną kolorystykę: piosenki białe, linki/jingle/audycje żółte, ETM niebieskie, Top of the hour różowe, reklama/autopromocja czerwone.
- Kolejne reklamy i autopromocje są zwijane w jeden czerwony blok **REKLAMA/AUTOPROMOCJA** we wszystkich trzech widokach.
- ETM Hard/Soft z gapami mają osobną zakładkę **ETM**; mapa zawsze obejmuje cały dzień, jest chronologiczna, pionowa i ma maksymalnie trzy kolumny. „Ignoruj resety” jest domyślnie włączone.
- Własny zestaw typów elementów można zapisać jako nazwany preset i używać ponownie.
- Naprawione zostało 00:00: queued 60+ z requestu 23:00 nie może już sztucznie tworzyć kilkudziesięciominutowego carry; stare snapshoty mają dodatkową ochronę przy odczycie.
- Played po elemencie aktualnie granym pokazuje dalszy Scheduled dla ciągłości; historia Played jest lekko wyszarzona i kursywą, a bieżący element ma progress bar także w samej playliście.
- Nad playlistami są szybkie przyciski 00–23; Porównanie ma ten sam szybki wybór godziny.
- Dwuklik piosenki w Scheduled, Played i Porównaniu otwiera kartę **Utwór**.
- Android dostał odpowiadający układ EMAUS, osobną zakładkę ETM, live continuity, kolory, zwijane bloki reklamowe i nawigację 00–23.
- Android 1.2.20 / `versionCode = 43`.

## 1.2.19 — czytelniejszy EMAUS, metadane i live playout

- Scheduled i Played korzystają z zwartego widoku logu podobnego do Porównania; Porównanie pozostaje nastawione głównie na ingerencje względem cutoffu.
- Mapa ETM Hard/Soft jest zawsze całodniowa, niezależna od wybranej godziny playlisty, układana chronologicznie pionowo w maksymalnie trzech wąskich kolumnach.
- „Ignoruj resety” jest domyślnie włączone.
- Pełnodniowy log pokazuje różowe separatory „Top of the hour”.
- Scheduled/Played pokazują Mood, Opener, Texture Open/Close i właściwy kod kategorii (np. G1/R2/AUD/typ ETM), gdy dane są dostępne; Zetta może być uzupełniana ostatnim znanym kodowaniem z importów GSelectora.
- Played ma obok Runtime pole „Zagrano”; zwykłe segue/crossfade nie są liczone jako skrócenie, a duże Fade/Stopped są szacowane po rzeczywistym następnym starcie.
- Utwory w logu są powiązane z bazą RadioCharts; dwuklik otwiera kartę utworu.
- Aktualnie grany element jest wyróżniony, a web ma odświeżany co 5 s pasek postępu; Android odświeża Played co 15 s i ma analogiczne wyróżnienie/dwuklik.
- Android 1.2.19 / `versionCode = 42`.

## 1.2.7 — szybszy Dashboard

- Dashboard liczy 7-dniowy sygnał radiowy i 28-dniowy wolumen w jednym przebiegu SQL zamiast dwóch dużych agregacji.
- Domyślne „Całość” dla kolumny Emisje okres nie skanuje już archiwum stacja-po-stacji; używa indeksu po song_id i odejmuje tylko wyłączone stacje.
- Zakresy czasowe Dashboardu korzystają z nowego indeksu pokrywającego `played_at, song_id, station_id`.
- Rewizja danych emisji jest dużo tańsza i nie unieważnia ciężkich cache'y tylko dlatego, że katalog stacji został ponownie odkryty bez zmian.
- Wyszukiwanie ostatniej daty emisji używa indeksowanego `MAX(played_at)` zamiast `MAX(substr(...))`.
- Pierwszy start po aktualizacji może potrwać dłużej jednorazowo, bo SQLite buduje nowy indeks Dashboardu; kolejne wejścia powinny być wyraźnie szybsze.
- Android 1.2.7 / `versionCode = 31`.

## 1.2.6 — EMAUS: szybkie podwidoki, czytelne różnice i diagnostyka ETM

- EMAUS nie renderuje już pięciu zakładek naraz: Scheduled / Played / Porównanie / Utwory / Import są ładowane dopiero po wybraniu, co usuwa największy koszt pierwszego wejścia do widoku.
- Odczyty dzienne EMAUS są cache'owane po rewizji importów; filtry działają w pamięci, a Porównanie wykorzystuje jeden wynik całego dnia również dla wybranej godziny.
- Scheduled i Played mają jeden wspólny scroll oraz wiersze ustawione parami. Po stronie Played niezagrany element planu zostaje jako mocno wyszarzony ghost.
- Statusy porównania: zielone ✓ = zgodne, czerwone ✕ = niezagrane/usunięte, czerwone + = dodane, ↻ = zmieniona kolejność, ✂ = wykryte ścięcie/fade.
- Podsumowanie ETM Hard/Soft jest teraz jednoznacznie opisane jako gap z planu GSelectora. Segmenty z RESET-em lub traffic bez runtime są oznaczane ⚠, bo nie da się z samego eksportu GSelectora odtworzyć dokładnego gapu Zetty po załadowaniu realnych spotów.
- Android 1.2.6 / `versionCode = 30` (synchronizacja numeru wydania).

## 1.2.5 — EMAUS: wspólny scroll porównania i szybszy start

- Porównanie Scheduled/Played ma jeden wspólny pionowy scrollbar; rolka myszy przewija oba logi równocześnie.
- Podsumowanie 24 godzin ładuje Scheduled i Played tylko raz na dzień, zamiast ponownie czytać pełny log dla każdej z 24 godzin.
- Start Dashboard/Emisje/Baza nie wykonuje już seedowania EMAUS ani pełnego relinkowania utworów EMAUS; te operacje są ładowane dopiero w EMAUS/Utwór i cache'owane.
- Dashboard przekazuje już odczytaną rewizję airplay do agregatów, więc nie wykonuje zbędnego dodatkowego odczytu rewizji.
- Android 1.2.5 / `versionCode = 29` (bez osobnego ekranu EMAUS w tej iteracji).

## 1.2.4 — EMAUS: ETM gaps i presety filtrów

- Scheduled pokazuje zwięzłe podsumowanie całego dnia dla wszystkich ETM Hard/Soft: czas, typ i gap +/- z GSelectora.
- Kolumna **Gap** pokazuje teraz wartość +/- na każdym ETM; dla zwykłych elementów nadal pokazuje nadczas 60+ minutes/hour.
- Dodane presety elementów oraz osobny filtr ETM: Hard, Soft, Reset, Hit, Hard+Soft, Reset+Hit lub własna kombinacja.
- Android 1.2.4 / `versionCode = 28` (bez osobnego ekranu EMAUS w tej iteracji).

## 1.2.3 — EMAUS: porównanie godzinowe Scheduled vs Played

- Porównanie działa osobno dla każdego bloku godzinnego 00–23; ten sam utwór z innej godziny nie może zostać błędnie sparowany.
- Zgodność jest oparta na zawartości i kolejności, nie na sekundach startu. Jeżeli elementy są te same i w tej samej kolejności, blok jest OK.
- Widok porównania pokazuje pełny log Scheduled po lewej i Played po prawej, w rzeczywistej kolejności.
- Różnice raportują tylko: Niezagrane, Dodane, zmienioną kolejność oraz wykryte ścięcie/fade.
- Delta startu jest pomocnicza i ma format +M:SS / -M:SS; nie wpływa sama w sobie na status.
- Wykrywanie fade korzysta z tekstowego kodu fade (jeżeli eksport go udostępnia) albo z runtime Played krótszego od Scheduled o ponad 5 s.
- Kolory logu: Song biały, reklamy/spoty czerwone, pozostałe elementy żółte na czarnym tle; niezagrane elementy są szare.
- Techniczne wpisy `Zetta Play Asset` są domyślnie ukryte z porównania.
- Reklamowe grupy o wspólnym Air Time są klasyfikowane razem, również dla już istniejących importów.
- Import można usunąć z historii; po skasowaniu bieżącego snapshotu wcześniejszy snapshot tego dnia jest automatycznie przywracany.
- Pole z wartościami typu `CLOSER` / `LONG SONG 4:30+` jest pokazywane jako Sound Code.
- Android 1.2.3 / `versionCode = 27` (bez osobnego ekranu EMAUS w tej iteracji).

## 1.2.1 — EMAUS: pełne kolumny GSelectora, gap time i powiązanie z kartą utworu

- zakładka **Nasze radio** została nazwana **EMAUS**;
- timeline Scheduled/Played ma wybór widocznych kolumn, w tym **Mood, Opener, Timing, Content, Energy, Texture Close/Open, Edit Code, Exact Time, Failure Code, Vocal** oraz pola techniczne; **ID** pozostaje dostępne do diagnostyki, ale nie jest już domyślnie eksponowane;
- typ `Utwór` w EMAUS jest prezentowany jako **Song**; Song zachowuje zwykłe tło, a Audycje, Jingle, Reklamy, Informacje, Podkłady i ETM-y dostają subtelne kolory dla szybszego czytania logu;
- zapis GSelectora **60+ minutes/hour** nie jest traktowany jako błąd: np. `08:62:47.3` pozostaje w godzinie 08 i pokazuje `Gap +02:47.3`; prawdziwie uszkodzone czasy nadal dostają ostrzeżenie;
- istniejące i przyszłe wpisy EMAUS są wiązane z canonical `song_id` RadioCharts; scalanie duplikatów zachowuje link, a brakujące powiązania są ponownie sprawdzane po starcie;
- karta **Utwór** ma sekcję **EMAUS** z liczbą Scheduled/Played, średnią Played/dzień, następnym planem oraz tabelą dzienną; dane pojawią się automatycznie wraz z kolejnymi importami Played;
- API dostało `/api/v1/local-radio/song/{song_id}` pod późniejszy Android/automat;
- Android 1.2.1 / `versionCode = 26` (bez osobnego ekranu EMAUS w tej iteracji).

## 1.2.0 — Nasze radio: GSelector Scheduled / Played

- nowa zakładka **Nasze radio** z widokami **Scheduled**, **Played**, **Porównanie**, **Utwory** i **Import**;
- osobny backend SQLite dla własnej stacji, niezależny od zewnętrznych `airplay_plays`;
- ręczny importer aktualnego eksportu GSelectora TSV/TXT, także wielodniowego; rozpoznaje utwory, jingle, audycje, podkłady, informacje, ETM-y, reklamy/traffic, komendy Zetta i inne elementy;
- kolejne importy tego samego dnia tworzą nowy bieżący snapshot, a poprzedni zostaje w historii;
- porównanie Scheduled↔Played dopasowuje przede wszystkim po stabilnym ID i pokazuje `OK`, `Przesunięte`, `Pominięte` oraz `Dodane`;
- statystyki utworów obejmują liczbę slotów/emisji, dni, średnią na dzień, maksimum dzienne i najczęstszą godzinę;
- release zawiera początkowy Scheduled **30.09–12.10.2026** oraz próbny/realny Played **28.09.2026**, więc po wdrożeniu dane są od razu widoczne;
- dodane endpointy API `/api/v1/local-radio/...` pod przyszły Android i automatyczny import;
- Android 1.2.0 / `versionCode = 25` (bez nowego ekranu Nasze radio w tej iteracji).

## 1.1.5 — większy limit backfillu emisji

- limit jednego backfillu odSluchane został zwiększony z **100 000 do 500 000 okien 2h**;
- przy ok. 65 aktywnych stacjach pozwala to objąć jednorazowo około **1,75 roku** pełnej historii, o ile odSluchane ma te dane;
- backfill nadal hurtowo sprawdza zapisane okna i pomija kompletne bloki, więc ponowne wskazanie częściowo pobranego zakresu jest bezpieczne;
- domyślny zakres w UI nie został zmieniony.

## 1.1.4 — bezpieczniejsze duplikaty i scalanie prosto z Emisji

- automat pozostaje konserwatywny, ale rozpoznaje teraz częsty wariant RDS, w którym lista gości jest dopisana w nawiasie bez `Feat.`, np. `Nareszcie (Herbut & Zalia & Vito Bambino)`, `Tańczę (Igor Herbut, Zalia, Vito Bambino)` i `Świt (Gośc.: …)`;
- warianty `Remix`, `Live`, `Acoustic`, `Edit`, `Instrumental` itd. nadal nie są automatycznie scalane;
- jednorazowy lekki skan `song_alias_merge_v4` porządkuje istniejące rekordy spełniające te wąskie reguły;
- ręczne scalanie przeniesiono z karty **Utwór** do tabeli **Emisje**: ostatnia kolumna `Scal` zawiera checkboxy, a przycisk `Scal zaznaczone` otwiera okno potwierdzenia;
- po ręcznym scaleniu RadioCharts zachowuje dokładne stare sygnatury `wykonawca + tytuł` w `song_identity_aliases` oraz stare ID w `song_id_redirects`; kolejne importy z dawną nazwą trafiają więc automatycznie do rekordu głównego zamiast odtwarzać duplikat;
- rekord główny przy ręcznym scalaniu jest wybierany automatycznie na podstawie jakości historii: preferowany jest rekord obecny na toplistach, następnie ten z większą liczbą emisji.

## 1.1.3 — hotfix startu po migracji duplikatów

- Web i worker nie blokują już sobie startu przez `radiocharts.db.init.lock`, gdy jedyną brakującą operacją jest konserwacyjny skan `song_alias_merge_v3`. Drugi proces może wtedy wystartować po krótkim sprawdzeniu, podczas gdy pierwszy kończy porządkowanie katalogu.
- Skan v3 nie grupuje już całego katalogu po pierwszym słowie tytułu. Kandydaci są generowani tylko dla identycznego tytułu po normalizacji lub bezpiecznego wariantu skróconego o jeden końcowy wyraz.
- Liczniki toplist/emisji używane do wyboru rekordu głównego są agregowane jednym przebiegiem zamiast osobnych zapytań dla każdego utworu.
- Funkcjonalność scalania z 1.1.2 pozostaje bez zmian, ale pierwsze uruchomienie na dużej bazie powinno być znacząco szybsze i nie powinno kończyć się `filelock._error.Timeout`.

## 1.1.2 — skuteczniejsze scalanie duplikatów RDS

- nowa migracja `song_alias_merge_v3` ponownie analizuje **już istniejący katalog**, więc poprawiony matcher działa również na duplikaty utworzone przed aktualizacją;
- tytuły z dopiskiem `(Feat. …)`, `(Ft. …)` lub podobnym są traktowane jako ten sam tytuł, jeśli zgadza się powiązany kredyt wykonawców;
- bezpiecznie obsługiwane jest typowe skrócenie RDS o jeden końcowy wyraz, np. `I Ciebie Też` ↔ `I Ciebie Też, Bardzo`; warianty typu `Remix`, `Live`, `Acoustic`, `Edit` itp. są celowo wykluczone;
- obsługiwane są błędne rekordy, w których całe `wykonawcy - tytuł` trafiło do pola Tytuł, np. `Męskie Granie Orkiestra 2018, ... - Początek`;
- ten sam matcher działa przy nowych importach, więc po migracji te warianty nie powinny ponownie tworzyć oddzielnych rekordów;
- ręczne **Duplikaty / scalanie utworu** pokazuje teraz również kandydatów z powyższymi wariantami tytułu, a nie tylko idealnie identyczny tytuł.

## 1.1.1 — tożsamość utworów, ręczne scalanie i szybszy resumable backfill

- automatyczne scalanie wariantów jednego nagrania zostało rozszerzone o charakterystyczny tytuł i graf powiązanych kredytów wykonawców;
- po scaleniu zapamiętywane są stare sygnatury wykonawca+tytuł oraz stare ID, więc późniejszy import nie powinien odtworzyć tego samego duplikatu;
- karta **Utwór → Duplikaty / scalanie utworu** pozwala ręcznie scalić przypadki niejednoznaczne; scalanie zachowuje emisje, notowania, status, Downloaded i notatki;
- backfill odSluchane przed startem hurtowo wczytuje już poprawnie zapisane bloki `stacja + data + 2h`, dzięki czemu roczny backfill może szybko pominąć miesiące, które już są w bazie;
- ponowne zapisanie jednego bloku pozostaje atomowe i odporne na duplikaty;
- Manual w aplikacji został zaktualizowany o `1d`, obecny mechanizm Spotify, scalanie duplikatów oraz dokładne zasady wznawiania backfillu.

### Aktualny manual

Najbardziej aktualna dokumentacja użytkowa jest w zakładce **Manual** samej aplikacji. README zachowuje również historię zmian starszych wersji; opisy dawnych wersji poniżej są changelogiem, a nie bieżącym stanem funkcji.

## 1.0.7 — zmiana kategorii F1 → F3

- Kategoria radia `F1` została zastąpiona przez `F3` w statusach, filtrach, API i synchronizacji bazy.
- Istniejące `Baza F1` i `F1 Candidate` są automatycznie migrowane odpowiednio do `Baza F3` i `F3 Candidate`.
- Stare eksporty zawierające jeszcze `F1` są kompatybilnie normalizowane do `F3`.

## 1.0.6 — hotfix Spotify / React #31

- web: naprawiono błąd komponentu `Minified React error #31` po zmianie Spotify z 1.0.5; AG Grid nie zwraca już `HTMLAnchorElement` do Reacta;
- `Spotify ↗` jest ponownie bezpiecznie renderowany jako tekst komórki, a otwieranie linku obsługuje `onCellClicked`;
- Ctrl/Cmd+klik i środkowy przycisk nadal otwierają kolejne wyniki Spotify w nowych kartach bez nawigowania bieżącej tabeli.

## 1.0.5 — status dropdown, Spotify i udostępnianie

- web: lista Status ma ograniczoną wysokość i własny scroll, a strona ma większy dolny margines, więc końcowe statusy CF1/CF2 są wygodnie dostępne bez zmiany kolejności;
- web: Spotify jest prawdziwym linkiem `<a>`, więc Ctrl/Cmd+klik lub środkowy przycisk otwiera kolejne wyniki w nowych kartach bez przełączania widoku;
- web: dawne „Kopiuj Spotify” zastąpiono „Udostępnij ↗” — dokładny utwór jest dopasowywany przez iTunes, a potem otwierany jako smart-link Songlink/Odesli;
- Android: wersja zsynchronizowana do 1.0.5 (bez zmian funkcjonalnych).

## 1.0.4 — checkboxy Przesłuchany / Downloaded

- **Przesłuchany** korzysta z natywnego checkboxa AG Grid, ale jego aktywny kolor jest ustawiany przez oficjalną zmienną `--ag-checkbox-checked-color` na czerwony; checkbox pozostaje tylko wskaźnikiem wynikającym ze Statusu;
- **Downloaded** korzysta z tego samego natywnego renderera, lecz ma zielony `--ag-checkbox-checked-color`, dzięki czemu obie kolumny są natychmiast rozróżnialne;
- oba checkboxy mają neutralny szary stan niezaznaczony i ciemne tło; Przesłuchany nie jest już renderowany jako `disabled`, a interakcja z nim jest blokowana przez `pointer-events`, więc zachowuje mocny kolor bez możliwości ręcznego rozjechania ze Statusem;
- zmiana Statusu nadal odświeża Przesłuchany natychmiast po stronie przeglądarki.

## 1.0.3 — checkboxy o stałym, czytelnym wyglądzie

- webowy **Przesłuchany** nadal wynika automatycznie ze Statusu, ale jego checkbox nie jest już wizualnie wyszarzany przez AG Grid: zaznaczenie ma mocny czerwony kolor;
- **Downloaded** pozostaje edytowalny i dostaje osobny zielony kolor zaznaczenia;
- kolory są nakładane bezpośrednio na glyph checkboxa (`::after`), czyli na element, który faktycznie rysuje AG Grid, a nie na zewnętrzny wrapper;
- po zmianie Statusu kolumna Przesłuchany nadal odświeża się natychmiast po stronie przeglądarki.

## 0.3.30 — trwała naprawa flag Bazy i równy pasek filtrów

- rekordy z realnym statusem `Baza ...` są ponownie naprawiane przez migrację v3; dodatkowo SQLite ma teraz triggery, które nie pozwalają zapisać `heard=0` lub `downloaded=0` dla aktywnej kategorii Bazy;
- widok Baza ma dodatkowy bezpiecznik odczytu, a kolumny `heard/downloaded` są jawnie konwertowane z SQLite `0/1` na boolean — to właśnie brak tej konwersji powodował, że AG Grid rysował zapisane `1` jako puste checkboxy;
- filtr Status sam renderuje etykietę i wszystkie paski filtrów (Dashboard/Emisje/Baza) są wyrównane do dołu;
- licznik `Utwory (filtr / okres)` używa natywnej kontrolki Streamlita, dzięki czemu etykieta, wysokość i linia bazowa są takie same jak w pozostałych filtrach; poprawione są też marginesy i wysokość popovera Status.

## 0.3.29 — naprawa flag Bazy i wyrównany pasek filtrów

- Dashboard wyrównuje wszystkie kontrolki w górnym pasku do jednej linii; Status ma własną etykietę i ten sam wymiar kontrolki co sąsiednie filtry.
- nowa migracja `radio_library_heard_downloaded_v2` ponownie naprawia istniejące rekordy `Baza <kategoria>`, ustawiając **Przesłuchany = ✓** i **DL = ✓** nawet wtedy, gdy marker z 0.3.28 był już zapisany;
- ręczne ustawienie dowolnego realnego statusu `Baza R2/R1/CF2/CF1/F3/G1/G2/SP1/SP2/NB` również automatycznie wymusza Przesłuchany i DL; `Baza Hold` pozostaje neutralny.

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
- kolejność statusów dopasowana do hierarchii CF1/CF2/R1/R2/G1/G2/SP1/SP2/NB/F3.

## 0.3.26 — synchronizacja bazy radia i czytelniejsze Emisje

- Emisje pokazują osobno **Zasięg 7d** oraz **Zasięg** dla aktualnie wybranego okresu; okresowy Zasięg jest wyświetlany jako procent raportujących stacji z liczbą stacji w nawiasie.
- RMF/ZET/OLiA/OLiS/ESKA w Emisjach używają kompaktowego zapisu pozycji z tygodniami, np. `#7 (5w)`.
- Przesłuchano, Status i DL są ustawione bezpośrednio za Odsłuchem w głównych tabelach.
- Taksonomia statusów obejmuje teraz wszystkie kategorie z lokalnej bazy radia: R2, R1, CF2, CF1, F3, G1, G2, SP1, SP2 i NB — zarówno jako `... Candidate`, jak i `Baza ...`.
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
- Worker emisji pobiera poprzedni zakończony blok 2h co dwie godziny o `:12`. Backfill jest resumable/idempotentny i ma limit 500 000 okien 2h na jeden proces.

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
