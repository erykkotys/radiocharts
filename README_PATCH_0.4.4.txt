RadioCharts 0.4.4 / Android 0.1.2

- naprawa GitHub Actions: apksigner nie był dostępny w PATH mimo zainstalowanego Android Build Tools,
- oba workflowy używają teraz jawnej ścieżki $ANDROID_HOME/build-tools/35.0.0/apksigner,
- build release 0.1.2 pozostaje bez zmian; po ponownym uruchomieniu workflow powinien przejść weryfikację podpisu i zbudować Docker image z APK.
