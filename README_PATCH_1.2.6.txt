RadioCharts 1.2.6

1. EMAUS / szybkość
- podwidoki EMAUS są teraz leniwe: renderuje się tylko aktualnie wybrany Scheduled / Played / Porównanie / Utwory / Import, zamiast wszystkich pięciu naraz;
- seed danych EMAUS i relink katalogu nie blokują już globalnego startu aplikacji;
- Scheduled/Played używają jednego cache'owanego odczytu całego dnia, a filtry godziny/typu działają w pamięci;
- Porównanie liczy dzień raz i wykorzystuje ten sam wynik dla wybranej godziny, bez dodatkowego odczytu i dekodowania SQLite.

2. Scheduled vs Played
- jeden wspólny pionowy scroll dla obu stron;
- wiersze są ustawiane parami po tożsamości elementu;
- niezagrane pozycje planu są widoczne po stronie Played jako mocno wyszarzone ghost rows;
- oznaczenia: zielone ✓ = zgodne, czerwone ✕ = niezagrane/usunięte, czerwone + = dodane w Played, ↻ = zmieniona kolejność, ✂ = fade/ścięcie.

3. ETM
- podsumowanie Hard/Soft zostało nazwane zgodnie ze źródłem: pokazuje gap zapisany w eksporcie GSelectora, a nie gap wyliczony przez Zettę;
- segmenty z RESET-em lub blokiem traffic bez runtime dostają ostrzeżenie ⚠;
- dokładnego gapu Zetty nie da się odtworzyć z obecnego eksportu GSelectora, ponieważ placeholdery reklamowe nie zawierają rzeczywistych długości spotów załadowanych w Zettcie.

4. Wersja
- web/backend: 1.2.6
- Android: versionCode 30 / versionName 1.2.6
