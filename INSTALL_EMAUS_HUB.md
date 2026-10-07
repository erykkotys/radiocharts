# Instalacja Emaus Hub na TrueNAS SCALE

Instrukcja migruje trwałe dane ze starej aplikacji `sprawdzacz-audycji`, ale pozostawia stary dataset jako kopię awaryjną.

## 1. Poczekaj na obraz 0.10.1

Po pushu zaczekaj, aż GitHub Actions `Server and Android update` zakończy się na zielono. Obraz pozostaje pod dotychczasowym adresem:

```text
ghcr.io/erykkotys/sprawdzacz-audycji:latest
```

## 2. Zatrzymaj starą aplikację i skopiuj dane

W TrueNAS przejdź do `Apps`, zatrzymaj `sprawdzacz-audycji`, a następnie w interfejsie datasetów utwórz:

```text
NVME/apps/emaus-hub
```

Stara aplikacja musi być zatrzymana przed kopiowaniem SQLite. Następnie w Shell wykonaj:

```bash
rsync -a /mnt/NVME/apps/sprawdzacz-audycji/ /mnt/NVME/apps/emaus-hub/
chown -R 568:1000 /mnt/NVME/apps/emaus-hub
install -d -o root -g root -m 700 /mnt/NVME/apps/emaus-hub/tailscale
```

Nie usuwaj jeszcze `/mnt/NVME/apps/sprawdzacz-audycji`. Jest to rollback, dopóki Emaus Hub nie zostanie sprawdzony.

Skopiuj certyfikat głównego CA EMAUS do trwałego datasetu jako:

```text
/mnt/NVME/apps/emaus-hub/emaus-root-ca.crt
```

Plik musi być w formacie PEM. Nadaj aplikacji prawo odczytu:

```bash
chown 568:1000 /mnt/NVME/apps/emaus-hub/emaus-root-ca.crt
chmod 640 /mnt/NVME/apps/emaus-hub/emaus-root-ca.crt
openssl x509 -in /mnt/NVME/apps/emaus-hub/emaus-root-ca.crt -noout -subject -issuer
```

## 3. Utwórz oddzielne urządzenie Tailscale

W panelu administratora Tailscale wygeneruj nowy, jednorazowy, nieephemeralny Auth key specjalnie dla `emaus-hub`. Nie używaj klucza ani plików stanu RadioCharts i nie zapisuj prawdziwego klucza w Git.

## 4. Dodaj Custom App

W TrueNAS wybierz `Apps` → `Discover Apps` → `Custom App` → instalacja z YAML. Nazwij aplikację `emaus-hub` i wklej poniższy YAML, zastępując tylko wartość `TS_AUTHKEY` nowym kluczem:

```yaml
services:
  tailscale:
    image: tailscale/tailscale:latest
    environment:
      TS_AUTHKEY: "WSTAW_TUTAJ_NOWY_JEDNORAZOWY_KLUCZ_TAILSCALE"
      TS_AUTH_ONCE: "true"
      TS_ACCEPT_DNS: "false"
      TS_HOSTNAME: emaus-hub
      TS_STATE_DIR: /var/lib/tailscale
      TS_TAILNET_TARGET_IP: 100.70.188.50
      TS_USERSPACE: "false"
    cap_add:
      - NET_ADMIN
      - NET_RAW
    devices:
      - /dev/net/tun:/dev/net/tun
    networks:
      default:
        aliases:
          - emaus-zetta-srv.swdm.local
    pull_policy: always
    restart: unless-stopped
    volumes:
      - /mnt/NVME/apps/emaus-hub/tailscale:/var/lib/tailscale

  emaus-hub:
    depends_on:
      - tailscale
    environment:
      ARCHIVE_ROOT: /media/archiwum
      COOKIE_SECURE: "false"
      DATABASE_PATH: /data/sprawdzacz.db
      DELIVERY_CONFIG_FILE: /data/delivery_config.json
      EMAUS_CONTACT_ROOT: /media/emaus-kontakt
      EMAUS_ROOT: /media/emaus
      FTP_CREDENTIALS_FILE: /data/forum_ftp_credentials
      MEDIA_ROOT: /media/audycje
      SPY_ROOT: /media/szpieg
      SETTINGS_PASSWORD: "RaEm^567!#"
      TZ: Europe/Warsaw
      ZETTA_CA_CERT_FILE: /data/emaus-root-ca.crt
    image: ghcr.io/erykkotys/sprawdzacz-audycji:latest
    ports:
      - "9510:8080"
    pull_policy: always
    restart: unless-stopped
    volumes:
      - /mnt/NVME/apps/emaus-hub:/data
      - /mnt/vdevB/.remote/dyna/dynamix/AUDYCJE:/media/audycje:rw
      - /mnt/vdevA/archiwum/ArchiwumEmausSWDM/AUDYCJE:/media/archiwum:rw
      - /mnt/vdevB/.remote/production/nasserver/Emaus:/media/emaus:rw
      - "/mnt/vdevB/.remote/production/nasserver/Emaus Kontakt:/media/emaus-kontakt:rw"
      - /mnt/vdevB/szpieg:/media/szpieg:ro
```

Emaus Hub publikuje port `9510` we wspólnej sieci aplikacji. Alias `emaus-zetta-srv.swdm.local` wskazuje na sidecar Tailscale, który przez `TS_TAILNET_TARGET_IP` przekazuje ruch do `100.70.188.50`. Dzięki temu HTTPS nadal używa prawidłowej nazwy hosta, bez łączenia niezgodnych opcji `network_mode` i `extra_hosts`.

## 5. Sprawdź Tailscale i backend

Po uruchomieniu wykonaj:

```bash
TAILSCALE_CONTAINER=$(docker ps --format '{{.Names}}' | grep 'emaus-hub.*tailscale' | head -n 1)
docker exec "$TAILSCALE_CONTAINER" tailscale status
docker exec "$TAILSCALE_CONTAINER" tailscale ping 100.70.188.50
```

Następnie sprawdź Emaus Hub:

```bash
curl -s http://127.0.0.1:9510/api/health
HUB_CONTAINER=$(docker ps --format '{{.Names}}' | grep 'emaus-hub.*emaus-hub' | head -n 1)
docker exec "$HUB_CONTAINER" python -c "import socket; print(socket.gethostbyname('emaus-zetta-srv.swdm.local'))"
docker exec "$HUB_CONTAINER" python -c "import os, requests; p=os.environ['ZETTA_CA_CERT_FILE']; print(requests.get('https://emaus-zetta-srv.swdm.local/Zetta2GO/Zetta/Go', verify=p, timeout=15).status_code)"
```

Po potwierdzeniu działania możesz usunąć wiersz `TS_AUTHKEY` z prywatnego YAML i unieważnić jednorazowy klucz. `TS_AUTH_ONCE=true` oraz `/mnt/NVME/apps/emaus-hub/tailscale` zachowują logowanie przy restartach i redeployu.

## 6. Przełącz Caddy

Na czas aktualizacji Androida zachowaj oba hosty skierowane na nowy backend:

```caddy
hub.emaus {
    tls internal
    reverse_proxy 192.168.1.79:9510
}

sprawdzacz.emaus {
    tls internal
    reverse_proxy 192.168.1.79:9510
}
```

Po przeładowaniu Caddy sprawdź `https://hub.emaus/api/health`. Stary hostname warto zostawić przez co najmniej jedną wersję, aby zainstalowane APK 0.9.x mogło pobrać aktualizację. APK 0.10.1 sam zmieni zapisany dokładny adres `https://sprawdzacz.emaus` na `https://hub.emaus`.

## 7. Skonfiguruj Played

W `https://hub.emaus` otwórz koło zębate, odblokuj Ustawienia i w sekcji `Zetta2GO — Played` wpisz:

- URL: `https://emaus-zetta-srv.swdm.local/Zetta2GO/Zetta/Go`
- Station ID: `3658ac9a-335e-4839-ac18-2159ba1e4a16`
- login i hasło Zetta2GO

Zapisz ustawienia i użyj `Test połączenia`. Hasło jest przechowywane w SQLite po stronie backendu i nie wraca w odpowiedzi do przeglądarki.

## 8. Sprawdź aktualizację Androida

Nowe APK jest dostępne pod:

```text
https://hub.emaus/api/android/apk
```

Package ID i klucz podpisu pozostają bez zmian, więc wersja 0.10.1 aktualizuje obecną aplikację. Po pełnym sprawdzeniu Emaus Hub możesz usunąć starą aplikację z TrueNAS, ale dataset awaryjny usuń dopiero wtedy, gdy masz pewną kopię bazy i konfiguracji.
