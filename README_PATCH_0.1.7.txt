RadioCharts 0.1.7
=================

Zmiany:
- OLiA/OLiS: nowy parser rendered_text_v2 dopasowany do realnego innerText
  zwracanego przez Playwright na TrueNAS.
- OLiA/OLiS: odczyt: pozycja, tytuł, wykonawca, reported_weeks,
  reported_peak oraz previous_position, gdy jest publikowana numerycznie.
- Diagnostyka OLiA/OLiS pokazuje preview pierwszych 5 sparsowanych pozycji.
- ESKA: parser przepisany tak, aby wykrywać kartę po parze "pozycja + trend"
  i ignorować wstawki "Radio ESKA / Hity na czasie".
- Diagnostyka ESKA zawiera fragment tokenów od początku listy.
- RMF/backfill bez zmian (0.1.6: potwierdzone 5/5).

Testy lokalne:
  python -m pytest -q
  9 passed

Po wdrożeniu sprawdź:
1. Build: 0.1.7
2. "Pobierz dane teraz"
3. Oczekiwane: OLIA 100 pozycji, OLIS 100 pozycji, ESKA 20 pozycji.
4. Jeśli któreś źródło nie przejdzie, skopiuj jego diagnostykę.
