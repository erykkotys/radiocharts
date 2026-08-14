RadioCharts 0.3.1
=================

Najważniejsze zmiany:
- Dashboard i Notowania używają interaktywnej tabeli AG Grid: kliknięcie komórki zaznacza cały wiersz, bez checkboxa selekcji.
- W tabelach dostępny jest przycisk Odsłuch z 30-sekundowym preview wyszukiwanym na żądanie w iTunes Search API; link Spotify pozostaje obok.
- Backfill: limity bezpieczeństwa zwiększone do ok. 5 lat: RMF 1300 notowań, ZET 1825 notowań, UK/Billboard/OLiA/OLiS 260 tygodni.
- Archiwum przemianowane na Notowania; najnowsze notowanie jest dostępne tak samo jak historyczne.
- Notowania pokazują Poprzednio, Tygodnie, Peak, Familiarity, Momentum, Format Fit, status i przesłuchanie; brakujące metadane są wyliczane z zapisanej historii.
- Dashboard ma okres obliczeń wskaźników: 1/2/4 tyg., 2/4/6 mies. lub całość.
- Historia pozycji jest wyższa i ma opcjonalną nieliniową skalę, która daje więcej miejsca Top 20.
- Osobna tabela Rising/do przesłuchania została usunięta jako redundantna; do tego służy filtrowanie/sortowanie Momentum i statusu.

Uwaga o odsłuchu:
Preview jest uruchamiane dopiero po kliknięciu konkretnego utworu. Nie wykonujemy automatycznie zapytań dla całej tabeli.
