RadioCharts 0.3.7

- Hotfix startu SQLite po wdrożeniu modułu Emisje.
- Inicjalizacja bazy jest serializowana między kontenerami web/worker wspólnym lockiem, więc jednoczesny start nie powinien kończyć się błędem w executescript(SCHEMA).
- Dodano busy_timeout oraz retry dla krótkotrwałych SQLite locked/busy podczas migracji.
- Indeksy Emisji są tworzone dopiero po sprawdzeniu/uzupełnieniu kolumn airplay, dzięki czemu częściowy/starszy schemat nie blokuje startu aplikacji.
- Migracja airplay jest addytywna i nie usuwa istniejących danych chartowych ani emisji.
- Operacje zapisu stacji/okien Emisji nie wymagają już, aby starsza tabela miała dokładnie ten sam UNIQUE/PRIMARY KEY co nowy schemat.
