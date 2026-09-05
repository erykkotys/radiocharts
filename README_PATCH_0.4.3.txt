RadioCharts 0.4.3 / Android 0.1.2

- stały podpis release Androida przez GitHub Actions secrets; kolejne APK mogą instalować się jako aktualizacja tej samej aplikacji,
- pierwszy release 0.1.2 ma versionCode 3; po obecnych debug APK 0.1.0/0.1.1 wymagane jest jednorazowe odinstalowanie starej aplikacji,
- Android automatycznie sprawdza aktualizację po uruchomieniu oraz ma ręczne „Sprawdź aktualizacje” w Ustawieniach,
- przycisk „Aktualizuj” pobiera APK bezpośrednio z prywatnego API RadioCharts przez LAN/Tailscale, sprawdza SHA-256 i otwiera systemowy instalator,
- API: /api/v1/android/update i /api/v1/android/apk,
- workflow Docker + Android release buduje podpisane APK, wkłada je do obrazu Docker i publikuje latest/version/SHA do GHCR,
- Docker image zawiera bieżące APK i update.json; po redeployu TrueNAS aplikacja mobilna widzi nową wersję,
- osobny workflow Android APK pozostaje jako ręczny build release/fallback.

Wymagane GitHub Actions secrets:
ANDROID_KEYSTORE_BASE64
ANDROID_KEYSTORE_PASSWORD
ANDROID_KEY_ALIAS
ANDROID_KEY_PASSWORD
