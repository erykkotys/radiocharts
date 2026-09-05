# RadioCharts Android 0.1.0

Natywny klient Android (Kotlin + Jetpack Compose) do prywatnego `RadioCharts API`.

## Połączenie przez Tailscale
1. Zainstaluj/uruchom Tailscale na telefonie.
2. Na serwerze RadioCharts uruchom usługę API na porcie `8502`.
3. W aplikacji otwórz **Ustawienia** i wpisz np. `http://100.x.y.z:8502/` albo MagicDNS `http://nazwa-serwera:8502/`.
4. Portu 8502 nie trzeba przekierowywać na routerze ani wystawiać publicznie.

HTTP jest dozwolone w aplikacji celowo: transport między urządzeniami Tailscale jest szyfrowany przez Tailscale. Jeśli kiedyś API zostanie wystawione poza prywatną sieć, użyj HTTPS i tokenu.

## Co jest w MVP
- Dashboard z wyszukiwaniem, sortowaniem, filtrami status/DL;
- Emisje z zakresem 7/28/90 dni;
- Baza, w tym `Baza Hold`;
- karta Utwór: Popularity, Chart Score, Momentum, Zasięg 7d, Emisje 7d;
- pozycje RMF/ZET/OLiA/OLiS/ESKA;
- status, Przesłuchany, DL i notatka zapisujące się do tej samej bazy co Streamlit;
- podgląd 30 s i Spotify;
- emisje utworu z wyborem konkretnych stacji.

## Build
Otwórz katalog `android/RadioChartsAndroid` w Android Studio. Przy pierwszym Sync Android Studio pobierze Gradle/Android dependencies. Następnie **Build > Build APK(s)**.
