RadioCharts 1.2.15

- EMAUS / ETM „Ignoruj resety”: carry bierze bezpośrednio gap RESET zwracany przez Zetta2GO. RESET bez gapu nie jest już rekonstruowany z AirTime/runtime, co usuwa fałszywe +30/+50 min na logach backtimowanych.
- Porównanie przyszłych godzin: elementy READY/WAITING są wyświetlane po prawej jako wygaszone „jeszcze nie zagrano — oczekuje w Zetta”, a metryki osobno pokazują Zagrane / w trakcie i Oczekuje.
- Porównanie historyczne GSelector Scheduled vs Zetta Played: fallback do symetrycznego artist/title zamiast GUID Zetty, więc dzień nie wygląda już jak 23 usunięte + 23 dodane tylko dlatego, że źródła mają różne przestrzenie ID.
- „Ścięty” dla utworu: próg >=10% i minimum 10 s krócej niż Scheduled. Kilkusekundowe trimy/crossfade nie są traktowane jako cięcie, nawet gdy Zetta raportuje fade.
