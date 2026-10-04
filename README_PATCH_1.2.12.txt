RadioCharts 1.2.12

EMAUS / Zetta2GO — poprawka gapu na pelnej godzinie:
- Zetta2GO zeruje gap na HH:00, bo kazda godzine laduje jako osobny log.
- RadioCharts odtwarza rzeczywisty carry miedzy godzinami.
- Priorytet: koncowy RESET poprzedniej godziny (zwykle 59:59) i jego natywny gap z Zetty.
- Korekta do granicy HH:00 uwzglednia roznice czasu, np. RESET 59:59 +00:14 => HH:00 +00:13.
- Gdy w poprzedniej godzinie nie ma koncowego RESET-u (typowe dla dziennych godzin z HARD), fallback liczy ogon po ostatnim Hard/Soft z AirTime + DurationMilliseconds elementow Zetty.
- Jesli Zetta zacznie zwracac natywny niezerowy gap na pelnej godzinie, RadioCharts go nie nadpisuje.
- Dla 00:00 pobierany jest dodatkowo blok 23:00 poprzedniego dnia, aby policzyc carry przez polnoc.
- Podsumowanie ETM pokazuje, ile pelnych godzin zostalo skorygowanych z RESET-u i ile z ogona logu.

Testy: 215 passed.
