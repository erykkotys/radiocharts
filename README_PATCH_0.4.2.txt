RadioCharts 0.4.2 / Android 0.1.1

- Mobile API: lean period aggregation for Emisje/Baza; removed duplicate all-song airplay aggregation.
- Mobile API: period aggregations cached by airplay revision + stations + date range.
- Song detail: reporting-station denominator uses a cheap count instead of full presence aggregation; unused raw-play history is skipped on mobile.
- Base mobile metrics cached separately from live user note/status overlay.
- Android: 120-row pages + "Pokaż kolejne" instead of fetching 300 rows at once.
- Android: read timeout 60 s / call timeout 90 s and retry-on-connection-failure.
- Android: expanded sorting (period metrics, chart metrics, each main chart, artist/title/status) plus ascending/descending toggle.
