RadioCharts 0.3.13
==================

UI / nawigacja
- Naprawiony React error #31 w kolumnie „Otwórz”: AG Grid nie zwraca już HTMLAnchorElement do Reacta.
- „Otwórz”: zwykły klik otwiera kartę utworu w tej samej karcie; Ctrl/Cmd/Shift+klik otwiera nową kartę/okno.
- Usunięty sidebar. Wersja + SHA są pokazywane dyskretnie w prawym górnym rogu.
- Usunięta duża pusta przestrzeń pod nawigacją: niewidoczne iframe helperów mają wysokość 1 px zamiast wartości traktowanej przez komponent jak domyślne ~150 px.
- Usunięta zakładka Import i ręczny fallback ZET z UI.

Kompaktowy layout
- Globalnie mniejsze nagłówki, przyciski, kontrolki i odstępy.
- Dashboard: okres, zakres i układ tabeli są selectboxami; filtry Familiarity/Momentum są obok siebie w jednym wierszu.
- Zwykłe wysokie st.metric zastąpione kompaktowymi paskami metryk na Dashboardzie, w Emisjach i na karcie utworu.
- Karta Utwór: tytuł, status, odsłuch, Spotify i 4 wskaźniki są znacznie ciaśniej ułożone.
- Moja ocena jest w jednym wierszu: przesłuchany / status / notatka / zapisz.
- Sterowanie wykresem historii jest kompaktowe, a wykres niższy.
- Dane: mniejsze kontrolki i 4-kolumnowy układ przycisków bieżących źródeł.

Metodologia
- Wagi Familiarity przeniesione z sidebara do Metodologii i pokazane w tabeli.

Baza / scoring / collectory
- Bez zmian w schemacie danych i algorytmach scoringu względem 0.3.12.
