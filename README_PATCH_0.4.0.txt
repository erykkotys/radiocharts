RadioCharts 0.4.0 — Android API + natywny klient Android

BACKEND
- FastAPI na porcie 8502, uruchamiane jako osobny serwis z tego samego obrazu.
- Endpointy Dashboard/Baza/Emisje/Utwór, historia list, emisje per stacja oraz zapis Przesłuchany/Status/DL/Notatki.
- Opcjonalny RADIOCHARTS_API_TOKEN. Bez tokenu API jest przeznaczone wyłącznie do LAN/Tailscale.
- Streamlit (8501), API (8502) i worker współdzielą tę samą SQLite.

ANDROID 0.1.0
- Kotlin + Jetpack Compose, Android-only.
- Ustawienia adresu API / tokenu. Domyślnie http://192.168.1.10:8502/.
- Dashboard z wyszukiwaniem, statusem, DL i sortowaniem.
- Emisje 7/28/90 dni.
- Baza, w tym Baza Hold.
- Utwór: podstawowe wskaźniki, historia chartów, status/heard/DL/note, preview 30 s, Spotify.
- Emisje utworu z wyborem konkretnych stacji.

TrueNAS: dodaj serwis API z compose.truenas.example.yml i port 8502. Nie wystawiaj go przez router; aplikacja łączy się przez Tailscale.
