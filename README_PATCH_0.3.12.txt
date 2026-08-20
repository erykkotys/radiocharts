RadioCharts Research 0.3.12

- „Otwórz” w tabelach jest prawdziwym linkiem: zwykły klik otwiera kartę utworu w tej samej karcie, Ctrl/Cmd-click, środkowy przycisk i menu przeglądarki pozwalają otworzyć nową kartę/okno. Link prowadzi do kotwicy u góry karty utworu.
- Dodany Radio Presence 7d: odsetek raportujących aktywnych stacji odSluchane.eu, które zagrały utwór w ostatnich 7 dniach. Wskaźnik jest osobny od Familiarity/Momentum i jest pokazany w Dashboardzie oraz na karcie Utwór.
- Format Fit przestał być „bieżącą pozycją pod inną nazwą”. Teraz jest historycznym proxy dopasowania: per źródło 55% peak + 25% długość obecności + 20% tygodnie w Top 10, z wagami RMF 40 / ZET 35 / OLiA 15 / OLiS 5 / ESKA 5. Brak recency decay zapobiega spadkom typu 80% -> 3% tylko po zejściu z listy.
- Emisje: „Śr./dzień” przemianowane na „Emisje/dzień łącznie”; dodano „Śr./grającą stację/dzień” oraz „Zasięg stacji”. UI dokładnie wyjaśnia, że np. 17/dzień oznacza 17 emisji łącznie ze wszystkich wybranych stacji, a nie 17 na każdej.
- Emisje: nowy expander pokrycia per stacja pokazuje bloki OK / oczekiwane / brakujące, puste bloki i liczbę emisji, więc widać co rzeczywiście zostało pobrane.
- Emisje: diagnostyka stacji bez danych. Stacja może zostać wyłączona dopiero po bezpiecznym kryterium: pełna historyczna doba (12/12 bloków) i 0 emisji. Wyłączenie nie kasuje danych, a stację można ręcznie włączyć ponownie. Odświeżenie katalogu nie włącza automatycznie ręcznie wyłączonych stacji.
- Dane: expander „Co jest już zapisane w bazie notowań” pokazuje liczbę notowań, najstarszą/najnowszą datę, liczbę pozycji i utworów per źródło.
- Wydajność: Emisje / Dane / Import / Metodologia nie ładują już pełnej ramki compute_scores. Emisje pobierają lekką tabelę najnowszych pozycji; dodano indeksy station_id+played_at i station_id+play_date.
- Metodologia rozszerzona o dokładne znaczenie Familiarity, Momentum, Format Fit, Radio Presence oraz surowych statystyk Emisji.
- Testy: 50/50.
