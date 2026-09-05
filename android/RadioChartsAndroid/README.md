# RadioCharts Android

Natywny klient Android (Kotlin + Jetpack Compose) dla prywatnego RadioCharts API po LAN/Tailscale.

## Wersja

Android 0.1.2 (`versionCode = 3`).

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

Stare 0.1.0/0.1.1 były debug APK podpisywanymi efemerycznym kluczem runnera GitHub. Przed pierwszą instalacją podpisanego release 0.1.2 trzeba jednorazowo odinstalować starą aplikację. Potem kolejne wersje aktualizują się w miejscu.
