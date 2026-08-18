RadioCharts Research 0.3.5
==========================

Najważniejsze zmiany:
- naprawione renderery AG Grid: bez literalnych <a>/<span>, bez React errorów;
- kompaktowe źródła: pogrubiona pozycja + mniejsze/przygaszone tygodnie;
- `Otwórz` przechodzi przez Streamlit/Python i otwiera szczegóły w tej samej karcie;
- `Utwór`: autocomplete przez streamlit-searchbox;
- `▶ 30s`: wybór wraca do Pythona, player jest w st.bottom na dole całej aplikacji;
- nowa zakładka Emisje (odSluchane.eu): dynamiczny katalog stacji, wybór checkboxami,
  zakres dat, suma emisji, liczba stacji, ostatnia emisja, status, odsłuch, Spotify, szczegóły;
- automatyczne pobieranie wszystkich stacji odSluchane co 2 godziny;
- wznawialny backfill wybranych lub wszystkich stacji do 5 lat;
- SQLite + airplay_daily jako agregat dzienny do szybszych zapytań; raw spiny pozostają zachowane;
- limit wyników Emisji chroni UI przy bardzo szerokim/wieloletnim zakresie.

Testy lokalne: 35 passed + compileall.
