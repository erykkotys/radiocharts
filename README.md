# Emaus Hub

Webowy i androidowy zestaw narzędzi produkcyjnych oraz emisyjnych Radia Emaus.

## Co działa w wersji 0.10.1

- raport dla wybranej daty, strzałki poprzedni/następny dzień, kalendarz i przycisk „Dzisiaj”;
- zakładka `Grafik` pokazuje wybrany Kalendarz Google w kolorystyce aplikacji, w formacie 24-godzinnym i strefie `Europe/Warsaw`; ma tę samą szerokość co Sprawdzacz, responsywny widok 1 dnia, 3 dni lub tygodnia, pełną dobę, wydarzenia całodniowe, linię bieżącego czasu oraz układanie kolidujących wydarzeń obok siebie;
- ikony folderów produkcyjnych otwierają wbudowany webowy browser od razu we właściwym katalogu; pliki można odsłuchać albo przeciągnąć uchwytem `⋮⋮` do Nuendo lub Sound Forge bez dodatkowego programu EXE;
- zakładka `Played` pokazuje log emisyjny Zetta2GO: historię, wyłącznie rzeczywisty status `CURRENT`/`PAUSED` jako „teraz”, płynny postęp bieżącego elementu, przyszłe pozycje, Top of the Hour, grupy reklam, filtry oraz nawigację po godzinach;
- backend pobiera Zettę oddzielnie dla każdej godziny, utrwala surowe dane w SQLite, automatycznie odnawia wygasłą sesję i odświeża poprzednią, bieżącą oraz następną godzinę bez przeładowania strony;
- zablokowany Grafik pozwala przeglądać szczegóły wydarzeń, a ta sama kłódka i PIN co w całej aplikacji włączają dodawanie, zmianę oraz usuwanie wydarzeń Google; kliknięcie wolnego miejsca zaokrągla początek do 15 minut;
- osobne sekcje „Brakuje” i „Są”, oczekiwana ścieżka, godzina emisji i długość znalezionego audio;
- brakującą emisję można po potwierdzeniu trwale zignorować dla wybranego dnia; trafia wtedy do „Są” z czerwonym statusem `Zignorowane` i nie uruchamia późniejszych powiadomień Pushover;
- lista audycji, wyszukiwarka, dodawanie, edycja, usuwanie i aktywność; przy każdym wpisie widać również oczekiwany oraz maksymalny czas trwania;
- usunięcie audycji przenosi cały jej dedykowany folder do identycznej ścieżki w Archiwum, zatrzymuje i usuwa zadanie FTP, a dla bezpieczeństwa blokuje operację, jeżeli folder zawiera folder innej audycji;
- dezaktywowanie audycji FTP zatrzymuje automatyczną synchronizację bez kasowania zapisanej konfiguracji;
- zapis nowej lub zmienionej maski nazwy tworzy w folderze audycji odpowiadający jej plik `.wzor`; folder można utworzyć z browsera także przez menu prawego przycisku;
- osobne właściwości `PRODUKCJA` i `FTP` wyświetlane jako tagi, bez dopisków w nazwie;
- audycje oznaczone `PRODUKCJA` mogą monitorować wiele folderów wraz z podfolderami; pojawienie się nowych plików uruchamia grupowane powiadomienie Pushover tylko do odbiorców, którzy mają włączoną opcję zmian produkcyjnych;
- pierwszy skan monitorowanego folderu zapisuje trwały stan początkowy bez alarmowania o starych plikach, a stan przetrwa restart i redeploy kontenera;
- monitoring folderów produkcji reaguje wyłącznie na nowe pliki `.mp3` i `.wav` (bez rozróżniania wielkości liter), a pozostałe formaty ignoruje;
- każda audycja może mieć włączoną autoarchiwizację: pasujące pliki są po globalnie ustawionej liczbie dni przenoszone z `AUDYCJE` do identycznej ścieżki w `Archiwum`;
- wiek autoarchiwizacji jest liczony od pierwszego wykrycia konkretnej wersji pliku, a nie z zawodnego `atime` ani daty modyfikacji; pliki przywrócone z Archiwum przez aplikację lub ręcznie przez SMB są rozpoznawane po identycznej zawartości, trwale oznaczane i nie wracają automatycznie do Archiwum;
- po odblokowaniu edycji menu pliku pod prawym przyciskiem w źródle `AUDYCJE` ma akcję `Archiwizuj teraz`, która pozwala bez czekania sprawdzić przeniesienie jednego pasującego pliku;
- archiwizacja najpierw atomowo usuwa źródło spod oczekiwanej nazwy, co zabezpiecza raport przed zawieszonymi wpisami `delete pending` starego serwera SMB; zamyka też odtwarzany plik, odświeża raport i nie uznaje nieotwieralnego pliku-widma za obecny;
- każdy monitorowany folder produkcji ma osobny przełącznik autokasowania plików MP3/WAV; globalny czas autoarchiwizacji i autokasowania ustawia się w chronionych Ustawieniach;
- audycja ma osobne pola `Czas typowy` i opcjonalny `Czas maks.`; przekroczenie limitu jest wyróżniane w Sprawdzaczu, także dla sumy części audycji;
- audycje wieloczęściowe z osobnym schematem pliku dla każdej części; dotychczasowe wpisy `cz1`, `cz2`, `cz3` są scalane automatycznie;
- wiele planów premierowych i powtórek, każdy z własnymi dniami oraz dowolną liczbą godzin; kilka odtworzeń jednego pliku jest jedną pozycją raportu;
- opcjonalne, wymagane wersje YouTube z automatyczną nazwą `_yt` przed rozszerzeniem;
- wybór plików audycji zastępczej z bieżącego katalogu lub osobnego archiwum i kopiowanie ich pod oczekiwaną nazwę brakującej premiery lub powtórki;
- stały folder Google Drive dla każdej audycji, automatyczne kopiowanie gotowych plików, trwałe udostępnienie jednemu lub wielu autorom i osobna wiadomość e-mail przez SMTP do każdego z nich; gdy Google nie pozwala nadać odbiorcy imiennego dostępu, aplikacja automatycznie przechodzi na niewyszukiwalny link działający bez konta Google;
- trwały status wysyłki dla audycji i daty emisji — po sukcesie przycisk zmienia się w zielone „Wysłano” i ponowne wysłanie jest blokowane;
- automatyczne usuwanie z folderów Drive plików nieaktualizowanych od 30 dni (retencję można zmienić w Ustawieniach);
- wspólny odtwarzacz audio przyklejony do dołu ekranu, działający w Sprawdzaczu, przeglądarce plików i zakładce Odsłuch; zawsze pozostaje poza popupami, a sterowanie i przewijanie mają pełną szerokość;
- sortowanie plików w browserze alfabetycznie, od najnowszych albo od najstarszych;
- zakładka Odsłuch: streamy live są odtwarzane przez HTTPS na porcie `8443`, a pod nimi znajduje się Szpieg z listą godzinnych nagrań, ręcznymi timecode’ami `HH:MM:SS` i wycinaniem zakresów do 180 minut, także przez granicę dwóch plików lub północ;
- Szpieg preferuje bieżący format `rec_*`, ale jeśli nagranie z danej godziny jest krótsze, zaczyna się z opóźnieniem albo zostało podzielone po przerwaniu, automatycznie korzysta z pełniejszego godzinnego pliku legacy; ten sam wybór obowiązuje przy odsłuchu i wycinaniu;
- zakładka Odsłuch ma niezależny browser plików uruchamiający nagrania w głównym playerze; wszystkie przeglądarki plików korzystają ze wspólnych źródeł `AUDYCJE`, `Archiwum`, `Emaus` i `Emaus Kontakt`;
- foldery produkcji można monitorować również na udziałach `Emaus` i `Emaus Kontakt`, bez kopiowania ich do katalogu AUDYCJE;
- każdy monitorowany folder ma jawny wybór źródła (`AUDYCJE`, `Archiwum`, `Emaus`, `Emaus Kontakt`), a browser wyboru otwiera się nad formularzem edycji;
- browsery pokazują obok przycisku odtwarzania czas trwania pliku; wyniki są buforowane do momentu zmiany pliku;
- po utworzeniu aktualnych docelowych nazw FTP przycisk zmienia się w zielone `✓ Przemianowane`; ponownie uaktywnia się po zmianie pliku źródłowego;
- browser pokazuje zawartość folderu natychmiast, a czasy audio doczytuje asynchronicznie w tle, najwyżej po dwa pliki równocześnie, co nie blokuje udziałów SMB;
- foldery ze wszystkich podpiętych źródeł można oznaczać gwiazdką; wspólny widok `Ulubione` działa w obu browserach i po wejściu z niego wraca do listy ulubionych zamiast do katalogu nadrzędnego;
- menu pod prawym przyciskiem myszy pokazuje właściwości pliku lub folderu, w tym daty oraz parametry audio, a po odblokowaniu edycji pozwala też zmienić nazwę pliku;
- główny odtwarzacz rozpoczyna pracę z głośnością ustawioną na 20%;
- kompaktowa Ramówka ukrywa całkowicie puste godziny i dopasowuje wysokość każdej widocznej godziny do rzeczywistej liczby wpisów;
- tworzenie wszystkich brakujących części powtórki przez skopiowanie ostatniej zaplanowanej premiery, z listą skopiowanych plików;
- harmonogramy: dowolne dni tygodnia, 1.–5. wystąpienie dnia w miesiącu, parzyste/nieparzyste tygodnie ISO oraz konkretne daty;
- sortowanie raportu według godziny albo nazwy; data wraca do dzisiaj po ponownym otwarciu lub F5, ale jest pamiętana przy przechodzeniu między zakładkami;
- domyślne sortowanie Sprawdzacza jest alfabetyczne, a obok wybranej daty widoczny jest numer tygodnia ISO;
- stale widoczna wersja serwera, a na Androidzie także niezależna wersja APK;
- aktualizacja APK pobierana bezpośrednio z serwera Sprawdzacza, bez artefaktów GitHub Actions;
- „Kopiuj premierę” kopiuje wyłącznie ostatnią datę wynikającą z harmonogramu premier; brak jej pliku nie powoduje cofnięcia do starszej audycji;
- ręczny wybór powtórki zaczyna się w folderze audycji i wymaga osobnego pliku dla każdej części;
- wybór i tworzenie folderu oraz wybór przykładowego pliku przez bezpieczną przeglądarkę katalogu zamontowanego w kontenerze; wybór przykładowego pliku zaczyna się domyślnie w folderze edytowanej audycji;
- automatyczne rozpoznawanie masek `%Y`, `%y`, `%m`, `%d` z przykładowej nazwy i ręczna korekta;
- jeden PIN edycji wymagany przez backend (startowo `1234`) odblokowuje Sprawdzacz, Audycje, FTP, Ramówkę i Grafik;
- automatyczny import 65 wierszy z dostarczonego `audycje.xls` do 47 audycji i 17 zagnieżdżonych harmonogramów powtórek;
- responsywny interfejs WWW/PWA i aplikacja Android z trybem ciemnym zgodnym z ustawieniem systemu, mobilnymi popupami i obsługą przycisku Wstecz;
- zabezpieczony osobnym hasłem panel ustawień, wielu odbiorców Pushover i globalne progi powiadomień o brakujących audycjach;
- tytuł i treść Pushover o braku pliku zawierają nazwę audycji;
- ręczne oraz automatyczne pobieranie folderów FTP przez `lftp mirror --continue`; automat działa raz na godzinę, codziennie, niezależnie od harmonogramu emisji;
- osobna zakładka FTP z listą automatycznych zadań, ręcznymi przyciskami synchronizacji, źródłem i celem, regułami emisji, następną próbą oraz szczegółową historią ręcznych i automatycznych wyników wraz z odpowiedziami serwera i logami `lftp` (10 najnowszych prób od razu, starsze po rozwinięciu);
- osobne schematy nazw źródłowych FTP, przesunięcia daty typu `(%d-1)` i kopiowanie do nazw docelowych także dla audycji wieloczęściowych;
- pola godzin emisji używają formatu 24-godzinnego `HH:MM`, ale przyjmują też skrót bez dwukropka, np. `1810` jest zapisywane jako `18:10`;
- lista Audycje pokazuje godziny powtórek bezpośrednio w kolumnie harmonogramu, a techniczne ostrzeżenie o automatycznie poprawionej literówce starego importu jest ukrywane.
- lista Audycje pokazuje także dni tygodnia dla każdego planu premierowego oraz osobne dni i godziny powtórek;
- zakładka Ramówka ma zakres 1 dnia, 3 dni lub tygodnia oraz widok kompaktowy i pełny z siatką co 5 minut; pozwala filtrować niezależne warstwy: audycje, reklamy, wejścia prezenterskie, pogodę, serwisy, oprawę, transmisje, inne elementy i przyszłą warstwę muzyczną;
- ramówka ma zapamiętywane tryby szeroki i pełnoekranowy, regulowaną wysokość obszaru roboczego oraz czytelny zoom osi czasu `36–144 px / 5 min` (domyślnie `60 px / 5 min`);
- Ramówka korzysta ze wspólnego odblokowania edycji i tego samego PIN-u co pozostałe operacje;
- pozycje ramówki można przeciągać z przyciąganiem do 5 minut, kopiować przez `Alt` + przeciągnięcie z zachowaniem przesunięcia minutowego (np. `:03`), otwierać do dokładnej edycji, dodawać i usuwać;
- audycje w Ramówce są powiązane 1:1 z Audycjami, razem z czasem trwania; ich świadome przesunięcie aktualizuje harmonogram używany przez Sprawdzacz, a zmiana w Audycjach przebudowuje odpowiednie pozycje;
- kliknięcie audycji w Ramówce otwiera ten sam pełny formularz co w Audycjach; dezaktywowane audycje znikają z Ramówki, a aktywne nowe lub ponownie włączone pojawiają się zgodnie ze swoim harmonogramem;
- czas trwania audycji i elementów ramówki obsługuje pół minuty, np. `0,5 min`; niezależne elementy można zmieniać grupowo przez osobny wybór grup minutowych (`:20`, `:50`, wszystkie) i dni (`Pn–Pt`, `Sb–Nd`, wszystkie);
- tylko pozycje rzeczywiście zachodzące na siebie w pełnej ramówce są układane obok siebie; każdy wpis jest jednym klockiem o wysokości dokładnie odpowiadającej czasowi trwania, bez dodatkowej etykiety udającej drugi wpis;
- tekst w pełnym widoku ramówki jest większy i ma uproszczoną drugą linię (`Premiera/Powtórka · czas`), a bardzo niskie klocki pokazują opis po zwiększeniu skali lub w dymku;
- poniżej `90 px / 5 min` pełna ramówka zwiększa czytelność krótkich elementów dynamicznie: minimalna wysokość i tekst rosną przy oddalaniu, a rozszerzone zakresy są uwzględniane przy układaniu elementów obok siebie, więc bloki nie zasłaniają się;
- audycje emitowane naprzemiennie według parzystości ISO, tygodni miesiąca lub konkretnych dat mają czytelne etykiety i wspólne oznaczenie zarówno w widoku kompaktowym, jak i pełnym;
- przy zablokowanej edycji ukrywane są wszystkie przyciski wykonujące operacje na plikach: synchronizacja FTP, przemianowanie, kopiowanie powtórki i wysyłka do autora;
- pasek skrótów `06:00–23:00` przewija Ramówkę do wybranej godziny, a elementy krótsze niż pięć minut mają pasek o rzeczywistej długości oraz osobną czytelną etykietę;
- startowa ramówka Jesień 2026 zawiera 870 odczytanych wystąpień, ale powtarzalne elementy korzystają ze wspólnego katalogu, dzięki czemu np. wszystkie reklamy i wejścia nie tworzą setek definicji;
- pierwszy import ramówki uzupełnia wyłącznie puste godziny audycji. Godziny już zapisane w Audycjach pozostają nadrzędne. Dane logowania i ścieżki techniczne z arkusza nie są importowane.
- ikona `?` w nagłówku otwiera wbudowaną instrukcję opisującą codzienną obsługę oraz działające w tle mechanizmy FTP, retencji, autoarchiwizacji, `archive_restore`, produkcji i Google Drive;
- zakładki są prawdziwymi linkami z adresami `#checker`, `#shows`, `#timetable`, `#calendar`, `#played`, `#ftp` i `#spy`, dlatego można otwierać je środkowym przyciskiem myszy albo z menu prawego przycisku w nowej karcie lub oknie;
- otwarte okna modalne zatrzymują przewijanie strony pod spodem, również po dojściu do końca formularza edycji.

## Uruchomienie przez Docker Compose

1. Trwałe dane Emaus Hub i katalogi multimedialne są montowane w `docker-compose.yml` jako:

   ```yaml
   - /mnt/NVME/apps/emaus-hub:/data
   - /mnt/vdevB/.remote/dyna/dynamix/AUDYCJE:/media/audycje:rw
   - /mnt/vdevA/archiwum/ArchiwumEmausSWDM/AUDYCJE:/media/archiwum:rw
   - /mnt/vdevB/.remote/production/nasserver/Emaus:/media/emaus:rw
   - "/mnt/vdevB/.remote/production/nasserver/Emaus Kontakt:/media/emaus-kontakt:rw"
   - /mnt/vdevB/szpieg:/media/szpieg:ro
   ```

   Po przeniesieniu plików do docelowego datasetu zmień wyłącznie ścieżkę po lewej stronie. Katalog po prawej stronie pozostaje `/media/audycje`.

   Autoarchiwizacja wymaga zapisu do `/media/archiwum`. Autokasowanie wymaga zapisu do źródła wybranego folderu produkcji. Samo `:rw` w YAML nie wystarczy, jeżeli dataset, mount CIFS albo konto SMB nadal jest tylko do odczytu.

2. Sidecar `tailscale` działa jako przezroczysty cel dla Zetta2GO: alias `emaus-zetta-srv.swdm.local` wskazuje na sidecar, a `TS_TAILNET_TARGET_IP=100.70.188.50` przekazuje ruch dalej przez tailnet. Stan Tailscale jest przechowywany w `/mnt/NVME/apps/emaus-hub/tailscale`. Prywatny certyfikat CA serwera Zetty jest czytany wyłącznie przez klienta Zetta2GO ze ścieżki `ZETTA_CA_CERT_FILE` (domyślnie `/data/emaus-root-ca.crt`); nie zmienia zaufania TLS dla Google Drive, Kalendarza ani innych integracji.

3. Uruchom:

   ```bash
   docker compose up -d --build
   ```

4. Przed pierwszym uruchomieniem wstaw do `TS_AUTHKEY` nowy jednorazowy klucz wygenerowany specjalnie dla Emaus Hub. `TS_AUTH_ONCE=true` i trwały katalog stanu sprawiają, że po pierwszym logowaniu kolejne restarty nie używają klucza ponownie. Po udanym starcie możesz usunąć wiersz `TS_AUTHKEY` z YAML i unieważnić klucz w panelu Tailscale.

Baza SQLite znajduje się w `./data/sprawdzacz.db`. Od wersji 0.2.0 katalog audycji musi być dostępny do zapisu, ponieważ aplikacja potrafi tworzyć foldery i generować powtórki. Generator nie modyfikuje pliku źródłowego — kopiuje go do ścieżki wynikającej ze schematu powtórki. Użytkownik kontenera (UID 568) musi mieć prawo zapisu do katalogu.

Jeśli katalog źródłowy jest montowany z CIFS/SMB, opcje mounta powinny przypisać pliki użytkownikowi aplikacji, np.:

```bash
-o rw,credentials="$CREDS",vers="$SMB_VERS",iocharset=utf8,uid=568,gid=568,forceuid,forcegid,file_mode=0664,dir_mode=0775,noperm
```

Samo `rw` oznacza zapis dla mounta, ale nie nadaje UID 568 praw wynikających z lokalnego właściciela i trybu plików.

## TrueNAS SCALE — Custom App

Utwórz dataset `NVME/apps/emaus-hub`, skopiuj do niego zawartość starego trwałego katalogu aplikacji i wklej jako Custom App cały plik `docker-compose.yml`. W Compose są dwie usługi: Emaus Hub oraz trwały sidecar Tailscale z urządzeniem `/dev/net/tun` i uprawnieniami `NET_ADMIN`/`NET_RAW`. Port `9510` publikuje Emaus Hub; sidecar obsługuje wyłącznie trasę do Zetty.

W panelu administratora Tailscale utwórz nowy, jednorazowy i nieephemeralny Auth key. Wklej go wyłącznie do prywatnej konfiguracji Custom App w miejscu:

```yaml
TS_AUTHKEY: "tskey-auth-..."
```

Nie kopiuj klucza ani plików stanu z RadioCharts i nie zapisuj prawdziwego klucza w Git. Po pierwszym połączeniu tożsamość urządzenia pozostaje w `/mnt/NVME/apps/emaus-hub/tailscale`. Alias `emaus-zetta-srv.swdm.local` jest przypisany do sidecara, który przekazuje połączenie na `100.70.188.50`, dlatego kod zachowuje poprawny hostname i SNI certyfikatu.

Nie ustawiaj w aplikacji pełnej ścieżki TrueNAS ani starej ścieżki `K:\dynamix\AUDYCJE`. Kontener widzi katalog główny jako `/media/audycje`, a w konfiguracji audycji zapisuje wyłącznie ścieżki względne, np. `Credo` albo `! Zewnętrzne/Costam`. Zagnieżdżone katalogi, spacje, wykrzykniki i polskie znaki są obsługiwane.

## Played i Zetta2GO

Połączenie konfiguruje się w chronionych Ustawieniach: URL Zetta2GO, Station ID, login i hasło. Hasło pozostaje w bazie po stronie backendu i nie jest odsyłane do przeglądarki. Przycisk `Test połączenia` loguje nową sesję i pobiera bieżącą godzinę.

Zetta udostępnia log godzinami, dlatego pełny dzień jest pobierany jako 24 osobne zapytania i scalany dopiero przez Emaus Hub. Po pierwszej synchronizacji dane są przechowywane w SQLite. W tle co minutę odświeżana jest poprzednia, bieżąca i następna godzina, a co 30 minut cały dzień. Wygaśnięcie `ASP.NET_SessionId` powoduje automatyczne ponowne zalogowanie i powtórzenie zapytania.

Jako aktualnie emitowane są traktowane wyłącznie statusy `CURRENT = 2` i `PAUSED = 9`. `PENDING_PLAYED = -3` jest stanem przejściowym. Interfejs zachowuje też niezagrane pozycje i powody `EditCode`, a w bazie pozostawia surowy wiersz oraz JSON zasobu do późniejszych analiz.

## FTP

Dane logowania nie są zapisywane w repozytorium, obrazie Docker ani SQLite. Kontener czyta plik `/data/forum_ftp_credentials` z trwałego datasetu aplikacji:

```text
host=ftp.example.org
username=uzytkownik
password=...
```

Opcjonalnie można dopisać `port=21` oraz `charset=UTF-8`. Jeżeli serwer zwraca uszkodzone polskie znaki, ustaw np. `charset=WINDOWS-1250` i zrestartuj aplikację. Plik musi być czytelny dla UID 568 kontenera.

Parser przyjmuje też pliki w stylu skryptu shell, np. `export FTP_HOST=...`, `FTP_USER=...`, `FTP_PASS=...`, a także aliasy `user`, `login`, `pass` i pliki z BOM.

Na TrueNAS plik znajduje się na hoście jako `/mnt/NVME/apps/emaus-hub/forum_ftp_credentials`, ponieważ cały katalog `/mnt/NVME/apps/emaus-hub` jest mapowany na `/data`. Nie wymaga osobnego Storage i pozostaje po pullu, restarcie oraz redeployu aplikacji. Nie należy usuwać trwałego datasetu `/data` podczas przebudowy aplikacji.

Po zaznaczeniu właściwości FTP w audycji można wybrać zdalny folder, uruchomić ręczne pobieranie i włączyć automat. Automat wykonuje najwyżej jedną synchronizację na godzinę, codziennie, bez ograniczania jej do dnia lub godziny emisji. Synchronizacja nie usuwa lokalnych plików.

Opcja „Inny schemat nazwy pliku źródłowego” dodaje po jednym schemacie źródłowym na każdą część audycji. `%d-3` oznacza datę emisji minus trzy dni; obsługiwany pozostaje też zapis `(%d-3)`. Przesunięcie obejmuje prawidłowo również miesiąc oraz rok. Przycisk „Przemianuj” zachowuje plik źródłowy i tworzy lub aktualizuje kopię o nazwie docelowej.

## Import danych

Przy pustej bazie plik `seed/audycje.xls` jest importowany automatycznie. Kolejne uruchomienia nie duplikują wpisów. Import zamienia wartość z kolumny `MONTAŻ` na właściwość `PRODUKCJA` i zachowuje wszystkie używane typy harmonogramów. Dopiski zawierające `FTP` są przenoszone do właściwości FTP, wpisy `powtórka`/`potórka` są wchłaniane przez audycję główną, a wpisy zakończone `cz1`, `cz2`, `cz3` stają się częściami jednej audycji. Istniejąca baza ze starszej wersji migruje się automatycznie; od wersji 0.4.0 dawny harmonogram i pojedyncza godzina stają się pierwszym planem premierowym.

## PIN i HTTPS

Startowy PIN edycji to `1234`. Ten sam PIN odblokowuje wszystkie operacje edycyjne, w tym Ramówkę, i można go zmienić w chronionych hasłem Ustawieniach, w sekcji Bezpieczeństwo. W bazie przechowywany jest hash PBKDF2, nie jawny PIN. Sesja edycji trwa 8 godzin. Przy dostępie przez HTTPS ustaw `COOKIE_SECURE=true`.

## Pushover i powiadomienia

Koło zębate w nagłówku otwiera panel chroniony osobnym hasłem `SETTINGS_PASSWORD`. W panelu można zapisać wielu odbiorców Pushover, wysłać wiadomość testową oraz dodać globalne progi w minutach, godzinach lub dniach przed emisją. Aplikacja sprawdza harmonogram co 30 sekund. Powiadomienie jest wysyłane tylko wtedy, gdy w danym progu brakuje całej audycji lub którejkolwiek jej części; nazwa audycji znajduje się zarówno w tytule, jak i treści wiadomości. Audycja albo powtórka musi mieć ustawioną godzinę emisji. Wysłane progi są zapisywane w SQLite, aby nie tworzyć duplikatów po restarcie aplikacji.

## Google Drive, Kalendarz Google i wysyłka do autora

Konfiguracja znajduje się w chronionych Ustawieniach. Sekrety i osobne tokeny Drive oraz Kalendarza są zapisywane w `/data/delivery_config.json`, a więc w trwałym datasecie aplikacji, nie w repozytorium ani obrazie Docker.

W Google Cloud należy włączyć **Google Drive API** oraz **Google Calendar API** i skonfigurować ekran zgody OAuth. Dla Drive pozostaje klient typu **TVs and Limited Input devices**; jego Client ID i Client Secret obsługują dotychczasowe logowanie kodem. Dla Grafiku trzeba utworzyć drugi klient OAuth typu **Web application** i dodać dokładny Authorized redirect URI `https://sprawdzacz-oauth.soundcode.pl/`. Jego osobne Client ID i Client Secret wpisuje się w sekcji Kalendarza. Po zatwierdzeniu konta Google należy skopiować cały końcowy adres z paska przeglądarki do Sprawdzacza. Device Flow Google nie obsługuje zakresów Kalendarza, dlatego oba połączenia muszą być niezależne.

Po połączeniu osobnego konta Kalendarza wybierz kalendarz używany jako Grafik i zapisz ustawienia. Konto Drive może być inne. Kalendarze oznaczone jako „tylko odczyt” można przeglądać, ale nie zmieniać. Konfiguracja i oba tokeny pozostają w `/data/delivery_config.json`, więc nie znikają po restarcie ani redeployu kontenera.

W tej samej sekcji trzeba podać serwer SMTP. Dla Gmaila typowe ustawienia to `smtp.gmail.com`, port `587`, `STARTTLS`; przy weryfikacji dwuetapowej jako hasła użyj hasła aplikacji Google. Przycisk testu wysyła wiadomość na adres nadawcy.

Pierwsze użycie „Wyślij autorowi” tworzy folder audycji na Drive i udostępnia go adresom zapisanym w audycji. Adresy można oddzielać przecinkiem lub średnikiem; każdy odbiorca dostaje osobną wiadomość, więc adresy nie są ujawniane pozostałym. Sprawdzacz najpierw próbuje nadać imienne uprawnienie Google. Jeżeli Google odrzuci odbiorcę z powodu braku konta Google, aplikacja automatycznie włącza niewyszukiwalny dostęp „każdy, kto ma link” i nadal wysyła wiadomość SMTP. Odbiorca nie musi się wtedy logować, ale link może przekazać dalej. Następne wysyłki aktualizują ten sam folder. Zmiana listy autorów zeruje status „Wysłano”, a kolejna wysyłka uzgadnia imienne uprawnienia folderu Drive z bieżącą listą i zapisuje powodzenie oddzielnie dla każdego odbiorcy.

## Odsłuch, Szpieg i odtwarzacz

Pliki Szpiega są odczytywane z `/media/szpieg` i mogą mieć bieżące nazwy typu `rec_20260924-120000.mp3` albo starsze nazwy typu `2026 09 24 12 00 00 1790244000.mp3`. Dla każdej godziny Sprawdzacz wybiera `rec_*`, jeżeli jest ciągły i obejmuje co najmniej ten sam zakres co plik legacy. Przy pliku krótszym, opóźnionym albo podzielonym na fragmenty używa pełniejszego pliku legacy. Jeżeli legacy nie istnieje, pozostawia dostępne fragmenty `rec_*`.

W zakładce Szpieg można odsłuchać plik, pobrać bieżącą pozycję playera do pola początku lub końca albo wpisać oba timecode’y ręcznie. Wycinek jest składany przez `ffmpeg` do MP3 192 kb/s i pobierany na urządzenie użytkownika; plik tymczasowy na serwerze jest usuwany po pobraniu.

## Android

Projekt znajduje się w katalogu `android`. Jest to lekka aplikacja WebView korzystająca z tego samego interfejsu i API, dzięki czemu ma wszystkie funkcje WWW bez utrzymywania dwóch różnych edytorów harmonogramów.

Menu pod trzema kropkami zawiera bezpośrednie pozycje „Edycja / kłódka” i „Ustawienia”, więc są dostępne także wtedy, gdy webowy nagłówek nie mieści się na ekranie.

Domyślny adres serwera to `https://hub.emaus`. W oknie adresu wystarczy wpisać `hub.emaus` — brakujący protokół HTTPS zostanie dodany automatycznie. Aktualizacja 0.10.0 automatycznie zamienia wcześniej zapisane dokładne `https://sprawdzacz.emaus` na nowy adres. Aplikacja ufa certyfikatom systemowym oraz certyfikatom CA zainstalowanym przez użytkownika Androida, dlatego prywatny certyfikat EMAUS wymaga wcześniejszego zainstalowania EMAUS Root CA na telefonie. Jawnie wpisany awaryjny adres HTTP, np. stary adres 4via6, nadal jest obsługiwany. Adres można później zmienić z menu. Interfejs WWW ładuje się z serwera i odświeża automatycznie po wdrożeniu. Aplikacja sprawdza również dostępność nowszego APK na tym samym serwerze, pobiera je i otwiera systemowy instalator Androida. Pierwsza aktualizacja wymaga udzielenia Emaus Hub systemowego zezwolenia na instalowanie nieznanych aplikacji.

APK jest dołączany do obrazu serwera i dostępny pod adresem `/api/android/apk`. Nie jest już publikowany jako artefakt GitHub Actions. Aby kolejne APK mogły aktualizować poprzednią instalację, muszą być podpisane tym samym prywatnym kluczem. Jednorazowa konfiguracja:

1. Uruchom w PowerShellu `scripts/create-android-signing-key.ps1`. Skrypt tworzy klucz poza repozytorium, w `%USERPROFILE%\sprawdzacz-audycji-signing`, i kopiuje jego zapis Base64 do schowka.
2. W repozytorium GitHub otwórz `Settings` → `Secrets and variables` → `Actions` → `New repository secret`.
3. Utwórz `ANDROID_KEYSTORE_BASE64` i wklej zawartość schowka.
4. Utwórz `ANDROID_KEYSTORE_PASSWORD` i wpisz hasło wybrane podczas tworzenia klucza.
5. Zachowaj kopię pliku JKS i hasła. Utrata klucza wymusi odinstalowanie aplikacji przy kolejnej zmianie podpisu.

Workflow `Server and Android update` buduje podpisany APK, wkłada go do obrazu Docker i publikuje obraz `latest`. Pierwszą podpisaną wersję należy zainstalować ręcznie z `https://hub.emaus/api/android/apk`; późniejsze wersje aplikacja wykryje sama. Ze względu na zmianę z losowego klucza debug poprzednią wersję APK może być konieczne najpierw odinstalować. Dane Emaus Hub są na serwerze, więc odinstalowanie klienta Android nie usuwa bazy ani konfiguracji audycji.

## Obraz Docker z GitHub Actions

Workflow `.github/workflows/docker.yml` po każdym pushu do `main`, który zmienia aplikację lub Dockerfile, buduje obraz i publikuje go jako:

```text
ghcr.io/erykkotys/sprawdzacz-audycji:latest
```

Ten adres można wkleić w polu `Image repository` aplikacji niestandardowej w TrueNAS SCALE. Jeżeli repozytorium albo pakiet GHCR jest prywatny, TrueNAS wymaga danych logowania do rejestru; najprościej ustawić pakiet jako publiczny w ustawieniach pakietu na GitHubie.

## Testy

Testy logiki nie wymagają działającego serwera:

```bash
python -m unittest discover -s tests -v
```

Sprawdzają harmonogramy, migrację istniejącej bazy, polskie sortowanie, automatyczną aktywność, import wszystkich 65 wierszy, generowanie powtórek, ochronę ścieżek i raport obecności pliku.
