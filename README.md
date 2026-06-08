# Baicell 5G gNB Collector / Logger / Visualizer

Stack para recoger, almacenar y visualizar telemetría de una antena/gNB Baicell 5G.

Estado actual:
- **Ingesta activa:** `scraper` por SSH ejecutando `mibcli` en el gNB.
- **Ingesta futura:** vía API del equipo (pendiente, no implementada en este repo).

## Qué hace hoy

- Se conecta al gNB por SSH (`paramiko`), consulta métricas con `mibcli` y parsea respuestas `KEY:=VALUE`.
- Escribe puntos en InfluxDB 2.x (`gnb_metrics`) cada `SCRAPE_INTERVAL` segundos (`COLLECT_INTERVAL` sigue como fallback legacy).
- Visualiza en Grafana con dashboard provisionado automáticamente.
- Expone una API FastAPI de lectura sobre Influx (`/status`, `/cell`, `/gnb`, historiales, etc.).

## Arquitectura

```text
Baicell gNB (SSH + mibcli)
          |
          v
   scraper (Python)
          |
          v
    InfluxDB 2.7
      |       |
      v       v
 Grafana     FastAPI
 (dash)      (query API)
```

Servicios en `collector/docker-compose.yml`:
- `influxdb` → `8086`
- `grafana` → `3000`
- `api` → `8000`
- `scraper` (sin puerto público; writer a Influx)

## Estructura del proyecto

```text
collector/
  docker-compose.yml
  .env.example
  scraper/
    collector.py
    Dockerfile
  api/
    main.py
    Dockerfile
  grafana/
    provisioning/
      datasources/influxdb.yml
      dashboards/dashboard.yml
      dashboards/baicell.json
```

## Flujo de scraping (actual)

Implementado en `collector/scraper/collector.py`.

1. Lee targets de antenas y credenciales por host:
   - recomendado: `BAICELL_TARGETS_JSON` (array JSON de objetos `host/user/password/port` y `target_name` opcional)
   - alternativa: `BAICELL_TARGETS` (`ip|user|pass` CSV, puerto opcional `|port`)
   - fallback legado: `BAICELL_IP` + `SSH_USER`/`SSH_PASS` (`SSH_PORT` opcional)
   y conecta por SSH a cada gNB.
2. Lee tags estáticos al arranque (`arfcn`, `pci`, `tac`, `band`, `plmn`, `sst/sd`, etc.).
3. Guarda esos parámetros también en la medición `gnb_config`.
4. En cada ciclo consulta:
   - `cell_status`
   - `core_connectivity`
   - `gnb_status`
   - `uplink_noise`
5. Calcula throughput DL/UL en `fm1-mac3` leyendo `/proc/net/dev` y guarda en `throughput`:
   - `dl_bps`, `ul_bps`, `dl_mbps`, `ul_mbps`
6. Si hay error SSH, reintenta reconexión en el siguiente ciclo.

## Mediciones y campos (Influx)

- `cell_status`:
  - Ej: `NR_OP_STATE`, `NR_ADMIN_STATE`, `NR_NUM_OF_ACTIVE_UE`, `NR_CELL_BARRED`, etc.
- `core_connectivity`:
  - Ej: `NR_F1AP_STATUS`, `NR_NGAP_SCTP_STATUS`, `NR_F1AP_SCTP_STATUS`, `AMF_STATUS`
- `gnb_status`:
  - Ej: `HMS_CONNECTED_STATE`, `GPS_SYNC_STATE`, `NR_UE_NUMBER`
- `uplink_noise`:
  - Ej: `NR_UPLINK_NOISE`, `NR_CELL_RU_NOISE_GAIN`
- `throughput`:
  - `dl_bps`, `ul_bps`, `dl_mbps`, `ul_mbps`
- `gnb_config`:
  - snapshot de parámetros de configuración del gNB

Tags típicos: `gnb_host`, `plmn`, `sst`, `sd`, `arfcn`, `pci`, `band`, etc.

## API disponible (FastAPI)

Implementada en `collector/api/main.py` sobre datos de Influx.

- `GET /status` → resumen + última muestra de cada medición
- `GET /params` → parámetros extraídos recientes
- `GET /cell` → último `cell_status`
- `GET /connectivity` → último `core_connectivity`
- `GET /gnb` → último `gnb_status`
- `GET /noise` → último `uplink_noise`
- `GET /{measurement}/history?from=-1h&to=now()&step=1m`
  - `measurement` válido: `cell_status`, `core_connectivity`, `gnb_status`, `uplink_noise`

Swagger UI: `http://localhost:8000/docs`

## Dashboard Grafana

Provisionado automáticamente desde:
- datasource: `collector/grafana/provisioning/datasources/influxdb.yml`
- dashboard: `collector/grafana/provisioning/dashboards/baicell.json`

Incluye, entre otros:
- Estado general (`Cell OP`, `GPS Sync`, `AMF`, `NGAP`, `F1AP`)
- UEs activos (`NR_NUM_OF_ACTIVE_UE`, `NR_UE_NUMBER`)
- Series de conectividad
- Tabla de `gnb_config`
- Throughput DL/UL (Mbps)

## Arranque rápido

1) Configura variables:

```bash
cd collector
cp .env.example .env
```

2) Edita `collector/.env` con credenciales reales del gNB e Influx.

3) Levanta stack:

```bash
docker compose up -d --build
```

4) Accesos:
- Grafana: `http://localhost:3000` (user `admin`, pass `GRAFANA_PASSWORD`)
- API: `http://localhost:8000/docs`
- InfluxDB UI: `http://localhost:8086`

Logs útiles:

```bash
docker compose logs -f scraper
docker compose logs -f api
```

## Variables de entorno relevantes

Definidas en `collector/.env.example`:

- gNB SSH (recomendado): `BAICELL_TARGETS_JSON` (JSON `[{"host":"...","user":"...","password":"...","port":27149,"target_name":"site_01"}]`)
- gNB SSH (alternativa): `BAICELL_TARGETS` (CSV `ip|user|pass[|port]`)
- gNB SSH (fallback legado): `BAICELL_IP` (CSV), `SSH_PORT`, `SSH_USER`, `SSH_PASS`
- Tags útiles en Influx: `gnb_host` y, si se define, `target_name` (ideal para filtros/variables en Grafana)
- Scraper: `SCRAPE_INTERVAL` (segundos, recomendado), `COLLECT_INTERVAL` (fallback legacy)
- Influx: `INFLUX_ORG`, `INFLUX_BUCKET`, `INFLUX_ADMIN_USER`, `INFLUX_ADMIN_PASSWORD`, `INFLUX_TOKEN`
- Grafana: `GRAFANA_PASSWORD`

## Limitaciones actuales

- La ingesta depende de acceso SSH y comandos `mibcli` del equipo.
- Throughput fijo a interfaz `fm1-mac3` (hardcoded en scraper).
- API actual es de consulta de Influx; no habla directamente con la antena.

## Roadmap inmediato sugerido

1. Añadir un `collector` de API nativa del gNB (en paralelo al scraper SSH).
2. Unificar esquema de campos/tags para backend dual (SSH/API) sin romper dashboards.
3. Añadir health endpoint y métricas internas del scraper (errores, latencia, reconnects).
4. Tests de parsing de `mibcli` con fixtures reales.

