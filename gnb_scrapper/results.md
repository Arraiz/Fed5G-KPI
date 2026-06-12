# Baicell gNB — Results

**Host:** 192.168.22.200  
**Date:** 2026-06-05

---

## Acceso

| Método | Detalle |
|--------|---------|
| SSH | `ssh new_user@192.168.22.200 -p 27149` |
| Web | `https://192.168.22.200/cgi-bin/luci` |

- Usuario confirmado: `new_user` (uid=1002, gid=1002)
- Sin directorio home (`/home/new_user` no existe)

---

## Sistema

| Campo | Valor |
|-------|-------|
| Kernel | Linux 4.19.90 |
| Arch | aarch64 |
| Build | Feb 23 2024 |
| Firmware | Gargoyle / Baicells LMT (OpenWrt-based) |
| Web root | `/userdata-A/OAM/www-nui/` |

---

## Interfaz web

- **CGI engine:** haserl
- **Scripts CGI:** `/userdata-A/OAM/www-nui/cgi-bin/` — ~70 ficheros `.htm`
- **Scripts de datos:** `/userdata-A/OAM/www-nui/utility/` — ~40 scripts `.sh`
- **Frontend:** Vue.js + Element UI + jQuery + axios

---

## API / Consulta de datos

No hay REST API. El sistema usa **`mibcli`** como interfaz de datos.

**Sintaxis:**
```
mibcli get <objeto>.<indice>:<PARAMETRO>
mibcli get FAP.0:LMT_CURRENT_CELL
mibcli get FAP.0:NR_UE_NUMBER:+HMS_CONNECTED_STATE:+GPS_SYNC_STATE
mibcli get FAP.0.NR_CELL.<cell_no>:NR_OP_STATE:+NR_UPLINK_NOISE
mibcli getobject FAP.0.ETHERNET_INTERFACE
```

**Objetos MIB identificados:**
- `FAP.0` — parámetros globales del nodo
- `FAP.0.FAP_NRCU.0` — NR CU (NR_AMFS_STATUS, NR_F1AP_STATUS)
- `FAP.0.NR_CELL.<n>` — celda NR (estado operativo, ruido uplink, modo medida)
- `FAP.0.IPSEC.<n>` — túneles IPSec
- `FAP.0.ETHERNET_INTERFACE` — interfaces de red
- `FAP.0.FAP_NRCU.0.X_COM_HSS.0` — HaloB / licencias

**Autenticación web:** cookie `hash` + `exp` validada por `lmt_session_validator`

---

## Módulos funcionales detectados (por ficheros CGI/JS)

NR, LTE, Cell, RU, EU, BWP, SIB, SRS, PDSCH, PDCCH, PUCCH, PUSCH, CSI, PCI, ANR, SAS, QOS, IPSec, IPTables, PLMN, XN, Alarm, Log, TR-069, License, User, Network, Diagnose, Backup/Restore, Update/Upgrade


## Parámetros de celda NR

| Parámetro | Objeto MIB | Valor |
|-----------|-----------|-------|
| **ARFCN DL** | `NR_CELL.0.NR_RAN_CELL_COMMON_PARAMS.0:NR_ARFCNDL` | 629334 (~3.55 GHz, n78) |
| **ARFCN UL** | `NR_CELL.0.NR_RAN_CELL_COMMON_PARAMS.0:NR_ARFCNUL` | 629334 (TDD, igual que DL) |
| **BW DL** | `NR_CELL.0.NR_DL_BWP.0:NR_BWP_BANDWIDTH` | 40 MHz |
| **BW UL** | `NR_CELL.0.NR_UL_BWP.0:NR_BWP_BANDWIDTH` | 40 MHz |
| **Modulación (MCS table)** | `NR_CELL.0.NR_DL_BWP.0.NR_PDSCH_CONFIG.0:NR_MCS_TABLE` | 1 (256QAM) |
| **MCS init DL** | `NR_CELL.0.NR_DL_BWP.0:NR_BWP_INIT_DL_MCS` | 5 |
| **MCS init UL** | `NR_CELL.0.NR_UL_BWP.0:NR_BWP_INIT_UL_MCS` | 5 |
| **TAC** | `NR_CELL.0.NR_PLMN_IDENTITYINFO_LIST.0:NR_TAC` | 2 |
| **Banda** | `NR_CELL.0.NR_RAN_CELL_COMMON_PARAMS.0:NR_FREQ_BAND_INDICATOR` | n78 |
| **PCI** | `NR_CELL.0.NR_RAN_CELL_COMMON_PARAMS.0:NR_PCI` | 21 |

---

## Network Slicing

**PLMN:** `00102` (MCC=001, MNC=02) — PLMN primaria  
**Capacidad:** hasta 6 slices por PLMN (`NR_MAX_SLICE_ENTRIES:=6`)

### Slices configuradas

| Índice | NR_SNSSAI (raw) | SST | SD | NGU_ID |
|--------|----------------|-----|----|--------|
| 0 | 16777216 (0x01000000) | **1** (eMBB) | — (no SD) | 1 |

- El SNSSAI se codifica en 32 bits: `SST[8b] \| SD[24b]`
- `16777216 = 0x01_000000` → SST=1, SD=0 (sin SD)
- `NR_SD_EXISTS:=0` confirma que no hay SD definido

**Objetos MIB relevantes:**
- `FAP.0.NR_CELL.0.NR_PLMN_IDENTITYINFO_LIST.0.NR_PLMN_LIST.0` — PLMN
- `FAP.0.NR_CELL.0.NR_PLMN_IDENTITYINFO_LIST.0.NR_PLMN_LIST.0.NR_SLICE_LIST.0` — Slice

