import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from influxdb_client import InfluxDBClient

INFLUX_URL    = os.environ.get('INFLUX_URL', 'http://influxdb:8086')
INFLUX_TOKEN  = os.environ['INFLUX_TOKEN']
INFLUX_ORG    = os.environ.get('INFLUX_ORG', 'baicell')
INFLUX_BUCKET = os.environ.get('INFLUX_BUCKET', 'gnb_metrics')

MEASUREMENTS = ['cell_status', 'core_connectivity', 'gnb_status', 'uplink_noise']

app = FastAPI(title='gNB Metrics API', version='1.0')
influx = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
query_api = influx.query_api()


def _last(measurement: str) -> dict:
    flux = f'''
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -5m)
  |> filter(fn: (r) => r._measurement == "{measurement}")
  |> last()
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
'''
    tables = query_api.query(flux)
    if not tables or not tables[0].records:
        return {}
    r = tables[0].records[0]
    row = {k: v for k, v in r.values.items()
           if not k.startswith('_') and k not in ('result', 'table')}
    row['ts'] = r.get_time().isoformat()
    return row


def _history(measurement: str, start: str, stop: str, step: str) -> list:
    flux = f'''
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: {start}, stop: {stop})
  |> filter(fn: (r) => r._measurement == "{measurement}")
  |> aggregateWindow(every: {step}, fn: last, createEmpty: false)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
'''
    tables = query_api.query(flux)
    rows = []
    for table in tables:
        for r in table.records:
            row = {k: v for k, v in r.values.items()
                   if not k.startswith('_') and k not in ('result', 'table')}
            row['ts'] = r.get_time().isoformat()
            rows.append(row)
    return rows


def _params() -> dict:
    flux = f'''
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: -5m)
  |> filter(fn: (r) => r._measurement == "cell_status")
  |> last()
'''
    tables = query_api.query(flux)
    if not tables or not tables[0].records:
        return {}
    r = tables[0].records[0]
    param_keys = {'arfcn', 'arfcn_ul', 'pci', 'tac', 'band', 'bw_dl', 'bw_ul',
                  'mcs_table', 'mcs_dl', 'mcs_ul', 'plmn', 'sst', 'sd', 'gnb_host'}
    return {k: v for k, v in r.values.items() if k in param_keys}


@app.get('/status')
def status():
    result = {'ts': datetime.now(timezone.utc).isoformat(), 'params': _params()}
    for m in MEASUREMENTS:
        key = m.replace('_status', '').replace('_connectivity', '').replace('uplink_', '')
        result[key] = _last(m)
    return result


@app.get('/params')
def params():
    p = _params()
    if not p:
        raise HTTPException(504, 'No recent data from gNB')
    return p


@app.get('/cell')
def cell():
    d = _last('cell_status')
    if not d:
        raise HTTPException(504, 'No recent data')
    return d


@app.get('/connectivity')
def connectivity():
    d = _last('core_connectivity')
    if not d:
        raise HTTPException(504, 'No recent data')
    return d


@app.get('/gnb')
def gnb():
    d = _last('gnb_status')
    if not d:
        raise HTTPException(504, 'No recent data')
    return d


@app.get('/noise')
def noise():
    d = _last('uplink_noise')
    if not d:
        raise HTTPException(504, 'No recent data')
    return d


@app.get('/{measurement}/history')
def history(
    measurement: str,
    start: str = Query('-1h', alias='from'),
    stop: str = Query('now()', alias='to'),
    step: str = Query('1m'),
):
    if measurement not in MEASUREMENTS:
        raise HTTPException(404, f'Unknown measurement. Valid: {MEASUREMENTS}')
    rows = _history(measurement, start, stop, step)
    return {'measurement': measurement, 'count': len(rows), 'data': rows}
