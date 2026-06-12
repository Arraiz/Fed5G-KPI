#!/usr/bin/env python3
import json
import os
import re
import time
import logging
from datetime import datetime, timezone
from typing import Optional

import paramiko
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)

SSH_PORT    = int(os.environ.get('SSH_PORT', 27149))
SSH_USER    = os.environ.get('SSH_USER')
SSH_PASS    = os.environ.get('SSH_PASS')
INFLUX_URL  = os.environ.get('INFLUX_URL', 'http://influxdb:8086')
INFLUX_TOKEN  = os.environ['INFLUX_TOKEN']
INFLUX_ORG    = os.environ.get('INFLUX_ORG', 'baicell')
INFLUX_BUCKET = os.environ.get('INFLUX_BUCKET', 'gnb_metrics')


def parse_scan_interval() -> int:
    raw = os.environ.get('SCRAPE_INTERVAL', os.environ.get('COLLECT_INTERVAL', '20'))
    try:
        interval = int(raw)
    except (TypeError, ValueError) as e:
        raise RuntimeError(
            f'Invalid scan interval "{raw}". Use SCRAPE_INTERVAL (preferred) or COLLECT_INTERVAL as integer seconds'
        ) from e

    if interval <= 0:
        raise RuntimeError(f'Scan interval must be > 0 seconds, got "{interval}"')
    return interval


INTERVAL = parse_scan_interval()


def parse_baicell_targets() -> list:
    """
    Preferred format:
      BAICELL_TARGETS_JSON=[{"host":"192.168.22.200","user":"u","password":"p","port":27149,"target_name":"site-a"}, ...]
    Alternative format:
      BAICELL_TARGETS=ip|user|pass,ip|user|pass|port
    Legacy fallback:
      BAICELL_IP=ip1,ip2 + SSH_USER/SSH_PASS (+ SSH_PORT optional)
    """
    raw_targets_json = os.environ.get('BAICELL_TARGETS_JSON', '').strip()
    raw_targets = os.environ.get('BAICELL_TARGETS', '').strip()
    targets = []
    seen = set()

    if raw_targets_json:
        try:
            parsed = json.loads(raw_targets_json)
        except json.JSONDecodeError as e:
            raise RuntimeError(f'Invalid BAICELL_TARGETS_JSON: {e}') from e

        if not isinstance(parsed, list):
            raise RuntimeError('Invalid BAICELL_TARGETS_JSON: expected a JSON array')

        for i, item in enumerate(parsed):
            if not isinstance(item, dict):
                raise RuntimeError(f'Invalid BAICELL_TARGETS_JSON item at index {i}: expected object')

            host = str(item.get('host', '')).strip()
            user = str(item.get('user', '')).strip()
            password = str(item.get('password', '')).strip()
            target_name = str(item.get('target_name', item.get('name', ''))).strip()
            port_raw = item.get('port', SSH_PORT)
            try:
                port = int(port_raw)
            except (TypeError, ValueError) as e:
                raise RuntimeError(
                    f'Invalid BAICELL_TARGETS_JSON item at index {i}: invalid "port" value "{port_raw}"'
                ) from e

            if not host or not user or not password:
                raise RuntimeError(
                    f'Invalid BAICELL_TARGETS_JSON item at index {i}: host/user/password required'
                )

            key = (host, user, port)
            if key in seen:
                continue
            seen.add(key)
            targets.append({
                'host': host,
                'user': user,
                'password': password,
                'port': port,
                'target_name': target_name,
            })
    elif raw_targets:
        for entry in raw_targets.split(','):
            entry = entry.strip()
            if not entry:
                continue

            parts = [p.strip() for p in entry.split('|')]
            if len(parts) not in (3, 4):
                raise RuntimeError(
                    f'Invalid BAICELL_TARGETS entry "{entry}". Expected "ip|user|pass" or "ip|user|pass|port"'
                )

            host, user, password = parts[0], parts[1], parts[2]
            port = SSH_PORT if len(parts) == 3 else int(parts[3])
            if not host or not user or not password:
                raise RuntimeError(f'Invalid BAICELL_TARGETS entry "{entry}" (host/user/pass required)')

            key = (host, user, port)
            if key in seen:
                continue
            seen.add(key)
            targets.append({'host': host, 'user': user, 'password': password, 'port': port, 'target_name': ''})
    else:
        raw_hosts = os.environ.get('BAICELL_IP', '').strip()
        if not raw_hosts:
            raise RuntimeError(
                'Set BAICELL_TARGETS_JSON (recommended), BAICELL_TARGETS, or BAICELL_IP with SSH_USER/SSH_PASS'
            )
        if not SSH_USER or not SSH_PASS:
            raise RuntimeError('SSH_USER and SSH_PASS are required when using BAICELL_IP fallback')

        for host in raw_hosts.split(','):
            host = host.strip()
            if not host:
                continue
            key = (host, SSH_USER, SSH_PORT)
            if key in seen:
                continue
            seen.add(key)
            targets.append({'host': host, 'user': SSH_USER, 'password': SSH_PASS, 'port': SSH_PORT, 'target_name': ''})

    if not targets:
        raise RuntimeError('No valid Baicell targets configured')
    return targets


BAICELL_TARGETS = parse_baicell_targets()

# Metrics collected every cycle
METRICS = [
    ('cell_status',
     'mibcli get FAP.0.NR_CELL.0:NR_OP_STATE:+NR_ADMIN_STATE'
     ':+NR_NUM_OF_ACTIVE_UE:+NR_CELL_BARRED:+NR_RFTX_ENABLE:+NR_MEAS_MODE'),

    ('core_connectivity',
     'mibcli get FAP.0.FAP_NRCU.0:NR_F1AP_STATUS'
     ':+NR_NGAP_SCTP_STATUS:+NR_F1AP_SCTP_STATUS:+NR_AMFS_STATUS'),

    ('gnb_status',
     'mibcli get FAP.0:HMS_CONNECTED_STATE:+GPS_SYNC_STATE:+NR_UE_NUMBER'),

    ('uplink_noise',
     'mibcli get FAP.0.NR_CELL.0:NR_UPLINK_NOISE:+NR_CELL_RU_NOISE_GAIN'),
]

# Queried once at startup, used as tags on every point
STATIC_QUERIES = [
    ('arfcn',         'mibcli get FAP.0.NR_CELL.0.NR_RAN_CELL_COMMON_PARAMS.0:NR_ARFCNDL'),
    ('arfcn_ul',      'mibcli get FAP.0.NR_CELL.0.NR_RAN_CELL_COMMON_PARAMS.0:NR_ARFCNUL'),
    ('pci',           'mibcli get FAP.0.NR_CELL.0.NR_RAN_CELL_COMMON_PARAMS.0:NR_PCI'),
    ('tac',           'mibcli get FAP.0.NR_CELL.0.NR_PLMN_IDENTITYINFO_LIST.0:NR_TAC'),
    ('band',          'mibcli get FAP.0.NR_CELL.0.NR_RAN_CELL_COMMON_PARAMS.0:NR_FREQ_BAND_INDICATOR'),
    ('bw_dl',         'mibcli get FAP.0.NR_CELL.0.NR_DL_BWP.0:NR_BWP_BANDWIDTH'),
    ('bw_ul',         'mibcli get FAP.0.NR_CELL.0.NR_UL_BWP.0:NR_BWP_BANDWIDTH'),
    ('mcs_table',     'mibcli get FAP.0.NR_CELL.0.NR_DL_BWP.0.NR_PDSCH_CONFIG.0:NR_MCS_TABLE'),
    ('mcs_dl',        'mibcli get FAP.0.NR_CELL.0.NR_DL_BWP.0:NR_BWP_INIT_DL_MCS'),
    ('mcs_ul',        'mibcli get FAP.0.NR_CELL.0.NR_UL_BWP.0:NR_BWP_INIT_UL_MCS'),
    ('cell_identity', 'mibcli get FAP.0.NR_CELL.0.NR_PLMN_IDENTITYINFO_LIST.0:NR_CELL_IDENTITY:+NR_LOCAL_CELL_ID:+NR_RANAC'),
    ('plmn',          'mibcli getobject FAP.0.NR_CELL.0.NR_PLMN_IDENTITYINFO_LIST.0.NR_PLMN_LIST'),
    ('sst',           'mibcli getobject FAP.0.NR_CELL.0.NR_PLMN_IDENTITYINFO_LIST.0.NR_PLMN_LIST.0.NR_SLICE_LIST'),
]


def parse_mib(output: str) -> dict:
    """Parse 'KEY:=VALUE' pairs from mibcli output."""
    result = {}
    for m in re.finditer(r'(\w+):=(-?"?[^"\s]*"?)', output):
        k, v = m.group(1), m.group(2).strip('"')
        try:
            result[k] = int(v)
        except ValueError:
            try:
                result[k] = float(v)
            except ValueError:
                result[k] = v
    return result


def ssh_run(client: paramiko.SSHClient, cmd: str) -> str:
    _, stdout, _ = client.exec_command(cmd)
    return stdout.read().decode()


def connect_ssh(host: str, user: str, password: str, port: int) -> paramiko.SSHClient:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(host, port=port, username=user, password=password, timeout=15)
    return c


def get_static_tags(client: paramiko.SSHClient, host: str, target_name: str = '') -> dict:
    tags = {'gnb_host': host}
    if target_name:
        tags['target_name'] = target_name
    for tag_name, cmd in STATIC_QUERIES:
        try:
            raw = ssh_run(client, cmd)
            parsed = parse_mib(raw)
            if not parsed:
                continue
            if tag_name == 'plmn':
                # NR_CELL_PLMNID is zero-padded ("00102") — preserve with regex
                m = re.search(r'NR_CELL_PLMNID:="(\d+)"', raw)
                if m:
                    tags['plmn'] = m.group(1)
            elif tag_name == 'sst':
                snssai = parsed.get('NR_SNSSAI', list(parsed.values())[0])
                # SNSSAI is 32-bit: SST[8b]|SD[24b]
                tags['sst'] = str((int(snssai) >> 24) & 0xFF)
                tags['sd']  = str(int(snssai) & 0xFFFFFF)
            elif tag_name == 'cell_identity':
                tags['cell_identity'] = str(parsed.get('NR_CELL_IDENTITY', ''))
                tags['local_cell_id'] = str(parsed.get('NR_LOCAL_CELL_ID', ''))
                tags['ranac']         = str(parsed.get('NR_RANAC', ''))
            else:
                tags[tag_name] = str(list(parsed.values())[0])
        except Exception as e:
            log.warning(f'Static tag {tag_name}: {e}')
    return tags


def collect(client: paramiko.SSHClient, static_tags: dict) -> list:
    points = []
    now = datetime.now(timezone.utc)

    for measurement, cmd in METRICS:
        try:
            data = parse_mib(ssh_run(client, cmd))
        except Exception as e:
            log.warning(f'{measurement}: {e}')
            continue

        p = Point(measurement).time(now, WritePrecision.S)
        for k, v in static_tags.items():
            p = p.tag(k, v)

        wrote_field = False
        for k, v in data.items():
            if isinstance(v, (int, float)):
                p = p.field(k, v)
                wrote_field = True
            elif isinstance(v, str) and v:
                # NR_AMFS_STATUS: "192.168.22.100=1" → extract int status
                if k == 'NR_AMFS_STATUS':
                    try:
                        status = int(v.split('=')[-1])
                        p = p.field('AMF_STATUS', status)
                        p = p.tag('amf_ip', v.split('=')[0])
                        wrote_field = True
                    except ValueError:
                        pass
                else:
                    p = p.tag(k, v)

        if wrote_field:
            points.append(p)
        else:
            log.warning(f'{measurement}: no numeric fields — gNB returned empty values, skipping point')

    return points


THROUGHPUT_IFACE = 'fm1-mac3'

def read_iface_bytes(client: paramiko.SSHClient, iface: str) -> Optional[tuple]:
    """Returns (rx_bytes, tx_bytes) for the given interface, or None on error."""
    _, out, _ = client.exec_command('cat /proc/net/dev')
    for line in out.read().decode().splitlines():
        if line.strip().startswith(iface + ':'):
            parts = line.split(':')[1].split()
            return int(parts[0]), int(parts[8])
    return None


def collect_throughput(client: paramiko.SSHClient, prev: Optional[dict],
                       static_tags: dict, elapsed: float) -> tuple:
    """Returns (point_or_None, new_prev_state)."""
    now = datetime.now(timezone.utc)
    reading = read_iface_bytes(client, THROUGHPUT_IFACE)
    if reading is None:
        return None, prev

    rx, tx = reading
    new_state = {'rx': rx, 'tx': tx, 'ts': now.timestamp()}

    if prev is None:
        return None, new_state

    dt = now.timestamp() - prev['ts']
    if dt <= 0:
        return None, new_state

    dl_bps = max(0, (rx - prev['rx']) * 8 / dt)
    ul_bps = max(0, (tx - prev['tx']) * 8 / dt)

    p = Point('throughput').time(now, WritePrecision.S)
    for k, v in static_tags.items():
        p = p.tag(k, v)
    p = p.tag('iface', THROUGHPUT_IFACE)
    p = p.field('dl_bps', dl_bps)
    p = p.field('ul_bps', ul_bps)
    p = p.field('dl_mbps', round(dl_bps / 1_000_000, 3))
    p = p.field('ul_mbps', round(ul_bps / 1_000_000, 3))

    return p, new_state


def main():
    influx = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    write_api = influx.write_api(write_options=SYNCHRONOUS)

    host_state = {
        idx: {
            'target': target,
            'client': None,
            'static_tags': {},
            'tput_prev': None,
        }
        for idx, target in enumerate(BAICELL_TARGETS)
    }
    configured = [
        f"{t['target_name']}={t['host']}:{t['port']} ({t['user']})"
        if t.get('target_name') else f"{t['host']}:{t['port']} ({t['user']})"
        for t in BAICELL_TARGETS
    ]
    log.info(f'Configured Baicell targets: {configured}')
    log.info(f'Scan interval: {INTERVAL}s')

    while True:
        for _, state in host_state.items():
            target = state['target']
            host = target['host']
            user = target['user']
            password = target['password']
            port = target['port']
            target_name = target.get('target_name', '')
            target_id = target_name if target_name else host
            client = state['client']
            static_tags = state['static_tags']
            tput_prev = state['tput_prev']

            try:
                if client is None:
                    log.info(f'[{target_id}] Connecting SSH → {host}:{port} as {user}')
                    client = connect_ssh(host, user, password, port)
                    static_tags = get_static_tags(client, host, target_name)
                    log.info(f'[{target_id}] Connected. Static tags: {static_tags}')
                    # Write static params as fields so Grafana can display them
                    cfg = Point('gnb_config').time(datetime.now(timezone.utc), WritePrecision.S).tag('gnb_host', host)
                    if target_name:
                        cfg = cfg.tag('target_name', target_name)
                    for k, v in static_tags.items():
                        if k in ('gnb_host', 'target_name'):
                            # Already written as tags on gnb_config; avoid tag/field collisions in Flux pivot.
                            continue
                        try:
                            cfg = cfg.field(k, int(v))
                        except (ValueError, TypeError):
                            cfg = cfg.field(k, str(v))
                    write_api.write(bucket=INFLUX_BUCKET, record=cfg)
                    log.info(f'[{target_id}] Wrote gnb_config point')
                    tput_prev = None

                pts = collect(client, static_tags)
                if pts:
                    write_api.write(bucket=INFLUX_BUCKET, record=pts)
                    log.info(f'[{target_id}] Wrote {len(pts)} points to {INFLUX_BUCKET}')

                tput_pt, tput_prev = collect_throughput(client, tput_prev, static_tags, INTERVAL)
                if tput_pt:
                    write_api.write(bucket=INFLUX_BUCKET, record=tput_pt)
                    log.info(
                        f'[{target_id}] Throughput → DL {tput_pt._fields.get("dl_mbps",0)} Mbps  '
                        f'UL {tput_pt._fields.get("ul_mbps",0)} Mbps'
                    )

                state['client'] = client
                state['static_tags'] = static_tags
                state['tput_prev'] = tput_prev

            except (paramiko.SSHException, OSError, EOFError) as e:
                log.error(f'[{target_id}] SSH error: {e} — will reconnect next cycle')
                if client:
                    try:
                        client.close()
                    except Exception:
                        pass
                state['client'] = None
                state['tput_prev'] = None

            except Exception as e:
                log.exception(f'[{target_id}] Unexpected error: {e}')

        time.sleep(INTERVAL)


if __name__ == '__main__':
    main()
