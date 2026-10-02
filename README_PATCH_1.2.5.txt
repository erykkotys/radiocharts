RadioCharts 1.2.5

EMAUS / comparison:
- Scheduled and Played share one vertical scroll container; mouse wheel scrolls both logs together.
- 24-hour comparison summary now loads each daily log only once and partitions rows in memory.

Performance:
- EMAUS seed/relink work is lazy and cached, so Dashboard/Emisje/Baza do not pay that startup cost.
- Airplay revision already resolved for the current rerun is reused by Dashboard presence aggregation.

Android: 1.2.5 / versionCode 29 (no EMAUS-specific Android screen in this iteration).
