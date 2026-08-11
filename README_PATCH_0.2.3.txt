RadioCharts 0.2.3
- Billboard: prefer per-song DOM rows; guard against responsive WEEKS/PEAK pseudo-songs.
- UK: guard against metadata pseudo-song rows in historical layouts.
- DB: defense-in-depth filter for WEEKS/PEAK pseudo-rows; Billboard metadata reset v2.
- Archive: default 20 rows, selectable 20/40/100.
- Navigation tabs explicitly open in the same window; song detail links remain LinkColumn links (new tab/window behavior).
- Current data fetch + result moved into a collapsible sidebar expander.
- Missing source position now displays ASCII '-' so ascending text sort places it after #001..#100.
