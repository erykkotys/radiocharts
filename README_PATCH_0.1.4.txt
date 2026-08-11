RadioCharts 0.1.4

Podmień zawartość repo plikami z tej paczki, następnie:
  git add -A
  git commit -m "RadioCharts 0.1.4 - collectors, backfill and UI fixes"
  git push

Po zielonym GitHub Action możesz nadal używać w TrueNAS:
  image: ghcr.io/erykkotys/radiocharts:latest
  pull_policy: always

Po redeployu sprawdź w sidebarze: Build: 0.1.4 · <SHA>
Następnie kliknij "Pobierz dane teraz". Jeśli OLiA/OLiS/ESKA nie zadziałają,
skopiuj wynik z "Diagnostyka źródeł" dla każdego problematycznego źródła.
