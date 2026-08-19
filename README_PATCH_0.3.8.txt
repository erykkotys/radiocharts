RadioCharts 0.3.8

- Naprawiono „Otwórz” w Dashboardzie/Notowaniach: kliknięcie Szczegóły wraca z AG Grid do Pythona i dopiero wtedy zmienia widok Streamlit, zamiast próbować nawigować z sandboxowanego iframe.
- Widok Utwór nie używa już iframe do wyszukiwarki. Zastępuje go natywny, przeszukiwalny selectbox Streamlit, więc nie powstaje „ramka w ramce”.
- Emisje przebudowane na osobny moduł analityczny: ranking najczęściej granych utworów + osobna zakładka do sprawdzania konkretnego utworu.
- Dla wybranego utworu Emisje pokazują łączną liczbę spinów, liczbę stacji, rozbicie „gdzie i jak często”, wykres dzień po dniu oraz dokładną historię emisji.
- Filtry Emisji: wszystkie/wybrane stacje i zakres dat; sekcja pobierania/backfillu została schowana do technicznego expandera.
- Emisje są twardo odseparowane od Dashboardu/Notowań: nowe rekordy nie dostają song_id, istniejące linki airplay→songs są jednorazowo zerowane, a agregacja nie odczytuje statusów ani danych chartowych.
- Dane emisji nie wpływają na Familiarity, Momentum, Format Fit ani rekomendacje.
