RadioCharts Research 0.3.10

- Emisje: jawne pokrycie bloków 2h. Pełna doba to 12 bloków na każdą stację.
- Ranking ostrzega, gdy zakres ma niepełne pokrycie; nie udaje wtedy pełnej doby.
- „Uzupełnij ostatnie 24h” sprawdza 12 ostatnich zakończonych bloków 2h i pobiera tylko brakujące.
- Scheduler co 2h wykonuje ten sam 24-godzinny catch-up, więc restart/deploy nie zostawia łatwo dziur.
- Backfill nadal pobiera wszystkie 12 bloków historycznej doby, ale nie odpytuje bieżących/przyszłych bloków.
- Naprawa starych przedwcześnie zapisanych okien: rekord jest uznawany za kompletny tylko, jeśli został pobrany po końcu danego bloku 2h.
