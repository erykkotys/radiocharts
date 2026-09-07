# RadioCharts Android

Natywny klient Android (Kotlin + Jetpack Compose) dla prywatnego RadioCharts API po LAN/Tailscale.

## Wersja

Android 1.0.1 (`versionCode = 12`).

## Release signing

Release APK jest podpisywany stałym kluczem z GitHub Actions Secrets:

- `ANDROID_KEYSTORE_BASE64`
- `ANDROID_KEYSTORE_PASSWORD`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEY_PASSWORD`

Nie commituj pliku keystore do repozytorium. Ten sam klucz musi być używany do wszystkich kolejnych wersji, inaczej Android odrzuci aktualizację.

## Aktualizacje

Aplikacja automatycznie sprawdza `GET /api/v1/android/update?current_version_code=...` przy starcie. Ręczne sprawdzenie jest w **Ustawienia → Aktualizacje**.

Gdy jest nowsza wersja, aplikacja pobiera `GET /api/v1/android/apk`, weryfikuje SHA-256 i uruchamia systemowy instalator. Po pierwszym włączeniu aktualizacji może być potrzebne jednorazowe zezwolenie **Allow from this source** dla RadioCharts.

Stare 0.1.0/0.1.1 były debug APK podpisywanymi efemerycznym kluczem runnera GitHub. Przed pierwszą instalacją podpisanego release 0.1.2 trzeba było jednorazowo odinstalować starą aplikację. Od 0.1.2 kolejne wersje, w tym 1.0.1, aktualizują się w miejscu.




## 1.0.1

- wydanie zsynchronizowane z webowym RadioCharts 1.0.1; funkcjonalność Androida pozostaje jak w 1.0.0.

## 1.0.0

- pierwsze stabilne wydanie Androida zsynchronizowane z RadioCharts 1.0.0,
- usunięty osobny checkbox Przesłuchany; status `Nie słuchałem` jest jedynym stanem nieodsłuchanego utworu,
- Status i Downloaded zapisują się automatycznie na karcie Utwór; przycisk Zapisz zapisuje tylko notatkę,
- filtr `Downloaded` zastępuje skrót `DL`,
- Emisje/Baza mają preset `1d` = dzisiaj, przy zachowaniu domyślnego `7d`,
- wykresy nie wymuszają już landscape przy wejściu: działają w pionie, reagują na auto-rotate, a przycisk `Poziomo` może wymusić landscape mimo blokady portretu; `Auto` zwalnia wymuszenie,
- zachowane są wspólny crosshair, tooltip wszystkich toplist dla wybranej daty oraz data peaku.

## 0.1.8

- W Utworze dodano „Wszystkie listy”, które otwiera wspólny wykres wszystkich toplist na jednej osi dat.
- Każda toplista ma własną linię i legendę; osobne wykresy pozostają bez zmian.
- Najazd kursorem lub dotknięcie punktu pokazuje dokładną listę, miejsce i datę.
- Wykres nadal otwiera się w landscape.

## 0.1.7

- `Baza CF1` i `Baza CF2` wracają do naturalnej kolejności statusów; szybki wybór statusu jest teraz przewijalnym dialogiem, więc końcowe pozycje nie znikają poza menu.
- W Utworze kliknięcie konkretnej pozycji w sekcji „Pozycje na listach” otwiera wykres historii tej toplisty.
- Ekran wykresu przełącza się w landscape, chowa dolną nawigację i pokazuje aktualną pozycję, peak, liczbę notowań oraz historię pozycji w czasie.

## 0.1.6

- listy statusów na Androidzie pokazują `Baza CF1` i `Baza CF2` na początku, zamiast chować je na samym dole długiego menu; dropdown ma ograniczoną wysokość i przewijanie,
- przy każdej karcie utworu jest bezpośredni przycisk Spotify obok odsłuchu 30 s.

## 0.1.5

- Emisje i Baza: filtry są w jednym niskim, poziomo przewijanym pasku zamiast kilku wysokich rzędów.
- Presety okresu są skrócone do 7d / 28d / 3m.
- Dokładne daty są schowane pod jednym przyciskiem „Daty”; pola Od/Do rozwijają się tylko na żądanie.
- Wybór stacji w Emisjach został przeniesiony do tego samego paska filtrów.
- Usunięto pełnoszeroki przycisk „Odśwież / zastosuj filtry”; wyszukiwanie ma mały przycisk OK, a pozostałe filtry stosują się bezpośrednio.

## 0.1.4

- Odsłuch 30 s jest utrzymywany przez globalny `PreviewPlayerVm`, więc scrollowanie listy nie zatrzymuje audio.
- Baza: odsłuch 30 s i zmiana statusu bez otwierania Utworu.
- Emisje: domyślne sortowanie po liczbie emisji w wybranym okresie.
- Emisje i Baza: dokładny zakres dat Od/Do obok presetów 7 / 28 / 90 dni.

## 0.1.3

- Dashboard i Emisje: odsłuch 30 s oraz zmiana statusu bez otwierania karty Utwór.
- Emisje: wybór konkretnych stacji radiowych albo wszystkich stacji.
