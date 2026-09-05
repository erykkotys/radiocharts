# RadioCharts Android

Natywny klient Android (Kotlin + Jetpack Compose) dla prywatnego RadioCharts API po LAN/Tailscale.

## Wersja

Android 0.1.4 (`versionCode = 5`).

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

Stare 0.1.0/0.1.1 były debug APK podpisywanymi efemerycznym kluczem runnera GitHub. Przed pierwszą instalacją podpisanego release 0.1.2 trzeba było jednorazowo odinstalować starą aplikację. Od 0.1.2 kolejne wersje, w tym 0.1.4, aktualizują się w miejscu.

## 0.1.4

- Odsłuch 30 s jest utrzymywany przez globalny `PreviewPlayerVm`, więc scrollowanie listy nie zatrzymuje audio.
- Baza: odsłuch 30 s i zmiana statusu bez otwierania Utworu.
- Emisje: domyślne sortowanie po liczbie emisji w wybranym okresie.
- Emisje i Baza: dokładny zakres dat Od/Do obok presetów 7 / 28 / 90 dni.

## 0.1.3

- Dashboard i Emisje: odsłuch 30 s oraz zmiana statusu bez otwierania karty Utwór.
- Emisje: wybór konkretnych stacji radiowych albo wszystkich stacji.
