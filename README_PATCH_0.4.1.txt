RadioCharts 0.4.1

- dodaje GitHub Actions workflow .github/workflows/android-apk.yml,
- APK Androida buduje się automatycznie po zmianach w android/RadioChartsAndroid albo ręcznie przez workflow_dispatch,
- build używa Java 17, Android SDK 35 i Gradle 8.9,
- gotowy plik jest publikowany jako artefakt "RadioCharts-Android-debug" (RadioCharts-Android-debug.apk),
- Android Studio nie jest potrzebne do zbudowania testowego APK.
