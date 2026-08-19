RadioCharts 0.3.6

- Dashboard compact source cells no longer render raw HTML; compact format is now #7 · 5w.
- Dashboard/Notowania internal Details and Spotify actions use safe value formatters + click handlers.
- Song live search hard-navigates in the same browser tab; browser Back/Forward forces a Streamlit reload when needed.
- One shared 30-second preview player is fixed to the bottom of the whole browser viewport and can be closed.
- Song detail page gets a preview button and styling closer to Dashboard/Notowania.
- Adds working Emisje view backed by odSluchane.eu public playlist pages.
- Discovers all stations listed in the odSluchane radio directory, stores exact 2-hour-window plays in SQLite, aggregates any selected stations/date range.
- Emisje table includes spins, station reach, max spins from one station, top station, status/heard, preview, Spotify and song details where matched.
- Automatic airplay collector runs every 2 hours at :12 and fetches the previous completed two-hour block for all discovered stations.
- Exact, resumable/idempotent airplay backfill with 100,000-window safety cap per process.
