#!/usr/bin/env python3
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

import requests
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

INFLUX_URL = os.environ.get("INFLUX_URL", "http://influxdb:8086")
INFLUX_TOKEN = os.environ["INFLUX_TOKEN"]
INFLUX_ORG = os.environ.get("INFLUX_ORG", "baicell")
INFLUX_BUCKET = os.environ.get("INFLUX_BUCKET", "gnb_metrics")
INTERVAL = int(os.environ.get("VANKOM_SCRAPE_INTERVAL", "20"))


def _to_num(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    try:
        if "." in s:
            return float(s)
        return float(int(s))
    except ValueError:
        return None


def _token_from_response(resp: requests.Response, body_data: Any, token_name: str) -> Optional[str]:
    token = resp.cookies.get(token_name)
    if token:
        return token
    if isinstance(body_data, str) and body_data.strip():
        return body_data.strip()
    if isinstance(body_data, dict):
        v = body_data.get(token_name)
        if v:
            return str(v)
    return None


def _cookie_value(jar: requests.cookies.RequestsCookieJar, name: str) -> Optional[str]:
    values = [c.value for c in jar if c.name == name]
    return values[-1] if values else None


def _safe_json(resp: requests.Response) -> Dict[str, Any]:
    try:
        payload = resp.json()
        return payload if isinstance(payload, dict) else {}
    except ValueError:
        return {}


def _request_json(session: requests.Session, method: str, base_url: str, path: str, **kwargs) -> Dict[str, Any]:
    url = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    resp = session.request(method, url, timeout=15, **kwargs)
    resp.raise_for_status()
    payload = resp.json()
    if str(payload.get("Code")) != "200":
        raise RuntimeError(f"{path} failed: Code={payload.get('Code')} Message={payload.get('Message')}")
    return payload


def parse_targets() -> List[Dict[str, Any]]:
    raw = os.environ.get("VANKOM_TARGETS_JSON", "").strip()
    if not raw:
        raise RuntimeError("VANKOM_TARGETS_JSON is required")
    parsed = json.loads(raw)
    if not isinstance(parsed, list) or not parsed:
        raise RuntimeError("VANKOM_TARGETS_JSON must be a non-empty JSON array")

    targets = []
    for i, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise RuntimeError(f"Invalid VANKOM target at index {i}: expected object")
        base_url = str(item.get("base_url", "")).strip()
        username = str(item.get("username", "")).strip()
        password = str(item.get("password", "")).strip()
        captcha_code = str(item.get("captcha_code", "1111")).strip() or "1111"
        target_name = str(item.get("target_name", f"vankom_{i+1}")).strip()
        verify_tls = bool(item.get("verify_tls", False))
        status_xpath = str(item.get("status_xpath", "")).strip()
        param_xpaths = item.get("param_xpaths", [])
        network_params = item.get("network_params", {})
        if isinstance(param_xpaths, str):
            param_xpaths = [x.strip() for x in param_xpaths.split(",") if x.strip()]
        if isinstance(network_params, list):
            parsed_network_params = {}
            for obj in network_params:
                if isinstance(obj, dict) and "key" in obj and "xpath" in obj:
                    k = str(obj["key"]).strip()
                    xp = str(obj["xpath"]).strip()
                    if k and xp:
                        parsed_network_params[k] = xp
            network_params = parsed_network_params
        if not isinstance(network_params, dict):
            network_params = {}
        network_params = {str(k).strip(): str(v).strip() for k, v in network_params.items() if str(k).strip() and str(v).strip()}
        if not base_url or not username or not password:
            raise RuntimeError(f"Invalid VANKOM target at index {i}: base_url/username/password required")
        targets.append(
            {
                "base_url": base_url,
                "username": username,
                "password": password,
                "captcha_code": captcha_code,
                "target_name": target_name,
                "verify_tls": verify_tls,
                "status_xpath": status_xpath,
                "param_xpaths": param_xpaths if isinstance(param_xpaths, list) else [],
                "network_params": network_params,
            }
        )
    return targets


def auth(target: Dict[str, Any]) -> requests.Session:
    session = requests.Session()
    session.verify = target["verify_tls"]
    base_url = target["base_url"]

    captcha_1_resp = session.get(urljoin(base_url.rstrip("/") + "/", "api/captcha"), timeout=15)
    captcha_1_resp.raise_for_status()
    captcha_1 = _safe_json(captcha_1_resp)
    token_1 = _token_from_response(captcha_1_resp, captcha_1.get("Data"), "CaptchaToken")
    if token_1:
        session.cookies.set("CaptchaToken", token_1)
    if not _cookie_value(session.cookies, "CaptchaToken"):
        raise RuntimeError(f"captcha step did not return CaptchaToken for {target['target_name']}")

    captcha_2_resp = session.get(
        urljoin(base_url.rstrip("/") + "/", "api/captcha/verify"),
        params={"code": target["captcha_code"]},
        timeout=15,
    )
    captcha_2_resp.raise_for_status()
    captcha_2 = _safe_json(captcha_2_resp)
    if not captcha_2:
        raise RuntimeError(f"captcha verify returned non-JSON payload for {target['target_name']}")
    if str(captcha_2.get("Code")) != "200":
        log.warning(
            f"[{target['target_name']}] captcha verify returned Code={captcha_2.get('Code')} "
            f"Message={captcha_2.get('Message')} (continuing to login)"
        )
    token_2 = _token_from_response(captcha_2_resp, captcha_2.get("Data"), "CaptchaToken")
    if token_2:
        session.cookies.set("CaptchaToken", token_2)

    login_resp = session.post(
        urljoin(base_url.rstrip("/") + "/", "api/login"),
        json={"Name": target["username"], "Password": target["password"]},
        timeout=15,
    )
    login_resp.raise_for_status()
    login_data = _safe_json(login_resp)
    if not login_data:
        raise RuntimeError(f"login returned non-JSON payload for {target['target_name']}")
    if str(login_data.get("Code")) != "200":
        raise RuntimeError(f"login failed for {target['target_name']}: {login_data.get('Message')}")
    auth_token = _token_from_response(login_resp, login_data.get("Data"), "AuthToken")
    if auth_token:
        session.cookies.set("AuthToken", auth_token)
    if not _cookie_value(session.cookies, "CaptchaToken") or not _cookie_value(session.cookies, "AuthToken"):
        raise RuntimeError(f"auth tokens missing after login for {target['target_name']}")
    return session


def read_online_users(session: requests.Session, target: Dict[str, Any]) -> List[Dict[str, Any]]:
    payload = _request_json(session, "GET", target["base_url"], "/api/cn/online-users")
    data = payload.get("Data") or []
    return data if isinstance(data, list) else []


def read_online_user_count(session: requests.Session, target: Dict[str, Any]) -> Optional[int]:
    payload = _request_json(session, "GET", target["base_url"], "/api/cn/online-user-count")
    raw = payload.get("Data")
    n = _to_num(raw)
    return int(n) if n is not None else None


def read_pm_kpis(session: requests.Session, target: Dict[str, Any]) -> List[Dict[str, Any]]:
    payload = _request_json(session, "GET", target["base_url"], "/api/pm/kpis")
    data = payload.get("Data") or []
    return data if isinstance(data, list) else []


def read_alarms(session: requests.Session, target: Dict[str, Any], history: bool = False) -> List[Dict[str, Any]]:
    path = "/api/alarm/list-history" if history else "/api/alarm/list"
    payload = _request_json(session, "GET", target["base_url"], path)
    data = payload.get("Data") or []
    return data if isinstance(data, list) else []


def read_cell_status(session: requests.Session, target: Dict[str, Any]) -> Optional[int]:
    xpath = target.get("status_xpath")
    if not xpath:
        return None
    payload = _request_json(
        session,
        "GET",
        target["base_url"],
        "/api/param/status-info",
        params={"xpath": xpath},
    )
    data = payload.get("Data") or []
    if not isinstance(data, list) or not data:
        return None
    raw = data[0].get("Value")
    n = _to_num(raw)
    return int(n) if n is not None else None


def read_params(session: requests.Session, target: Dict[str, Any]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for xpath in target.get("param_xpaths", []):
        payload = _request_json(
            session,
            "GET",
            target["base_url"],
            "/api/param/value",
            params={"xpath": xpath},
        )
        out.append({"xpath": xpath, "value": str(payload.get("Data", ""))})
    return out


def read_network_params(session: requests.Session, target: Dict[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key, xpath in target.get("network_params", {}).items():
        payload = _request_json(
            session,
            "GET",
            target["base_url"],
            "/api/param/value",
            params={"xpath": xpath},
        )
        out[key] = str(payload.get("Data", "")).strip()
    return out


def write_points(
    write_api: Any,
    target: Dict[str, Any],
    online_users: List[Dict[str, Any]],
    online_users_count_api: Optional[int],
    pm_kpis: List[Dict[str, Any]],
    alarms_rt: List[Dict[str, Any]],
    alarms_hist: List[Dict[str, Any]],
    cell_status: Optional[int],
    params: List[Dict[str, str]],
    network_params: Dict[str, str],
) -> None:
    now = datetime.now(timezone.utc)
    tags = {
        "vendor": "vankom",
        "target_name": target["target_name"],
        "gnb_host": target["base_url"],
    }

    summary = Point("vankom_summary").time(now, WritePrecision.S)
    for k, v in tags.items():
        summary = summary.tag(k, v)
    ue_count_kpi = None
    rrc_percent_kpi = None
    dl_mbr_kpi = None
    ul_mbr_kpi = None
    for kpi in pm_kpis:
        kpi_type = str(kpi.get("Type", "")).strip().upper()
        if kpi_type == "UE_COUNT":
            n = _to_num(kpi.get("Val"))
            ue_count_kpi = int(n) if n is not None else None
        if kpi_type == "RRC_PERCENT":
            n = _to_num(kpi.get("Val"))
            rrc_percent_kpi = n
        if kpi_type in ("DLMBR", "DL_MBR", "DLMBR", "DL_RATE", "DL_THROUGHPUT"):
            n = _to_num(kpi.get("Val"))
            dl_mbr_kpi = n if n is not None else dl_mbr_kpi
        if kpi_type in ("ULMBR", "UL_MBR", "ULMBR", "UL_RATE", "UL_THROUGHPUT"):
            n = _to_num(kpi.get("Val"))
            ul_mbr_kpi = n if n is not None else ul_mbr_kpi

    online_count = ue_count_kpi if ue_count_kpi is not None else (
        online_users_count_api if online_users_count_api is not None else len(online_users)
    )
    if dl_mbr_kpi is None:
        dl_vals = [_to_num(u.get("Dlmbr")) for u in online_users]
        dl_vals = [v for v in dl_vals if v is not None]
        dl_mbr_kpi = sum(dl_vals) if dl_vals else 0.0
    if ul_mbr_kpi is None:
        ul_vals = [_to_num(u.get("Ulmbr")) for u in online_users]
        ul_vals = [v for v in ul_vals if v is not None]
        ul_mbr_kpi = sum(ul_vals) if ul_vals else 0.0

    summary = summary.field("online_users_count", online_count)
    summary = summary.field("online_users_list_count", len(online_users))
    summary = summary.field("dl_mbr_mbps", float(dl_mbr_kpi))
    summary = summary.field("ul_mbr_mbps", float(ul_mbr_kpi))
    if online_users_count_api is not None:
        summary = summary.field("online_users_count_cn", online_users_count_api)
    if ue_count_kpi is not None:
        summary = summary.field("online_users_count_kpi", ue_count_kpi)
    if rrc_percent_kpi is not None:
        summary = summary.field("rrc_percent", rrc_percent_kpi)
    summary = summary.field("alarms_realtime_count", len(alarms_rt))
    summary = summary.field("alarms_history_count", len(alarms_hist))
    if cell_status is not None:
        summary = summary.field("cell_status", cell_status)
    write_api.write(bucket=INFLUX_BUCKET, record=summary)

    user_points = []
    for u in online_users:
        imsi = str(u.get("Imsi", "")).strip()
        if not imsi:
            continue
        p = Point("vankom_online_user").time(now, WritePrecision.S)
        for k, v in tags.items():
            p = p.tag(k, v)
        p = p.tag("imsi", imsi)
        if str(u.get("Status", "")).strip():
            p = p.tag("status", str(u.get("Status")))
        if str(u.get("LinkQuality", "")).strip():
            p = p.tag("link_quality", str(u.get("LinkQuality")))

        for src, field in (
            ("Sinr", "sinr"),
            ("Rsrp", "rsrp"),
            ("Dlmbr", "dl_mbr_mbps"),
            ("Ulmbr", "ul_mbr_mbps"),
            ("TransmissionDelay", "tx_delay"),
            ("DelayChange", "jitter"),
            ("PacketLossProbability", "packet_loss"),
            ("ChannelLoadCondition", "channel_load"),
        ):
            n = _to_num(u.get(src))
            if n is not None:
                p = p.field(field, n)
        user_points.append(p)
    if user_points:
        write_api.write(bucket=INFLUX_BUCKET, record=user_points)

    if params:
        param_points = []
        for item in params:
            p = Point("vankom_param_value").time(now, WritePrecision.S)
            for k, v in tags.items():
                p = p.tag(k, v)
            p = p.tag("xpath", item["xpath"])
            val = item["value"]
            n = _to_num(val)
            p = p.field("value_num", n) if n is not None else p.field("value_str", val)
            param_points.append(p)
        write_api.write(bucket=INFLUX_BUCKET, record=param_points)

    if network_params:
        cfg = Point("vankom_config").time(now, WritePrecision.S)
        for k, v in tags.items():
            cfg = cfg.tag(k, v)
        wrote = False
        for k, v in network_params.items():
            if not v:
                continue
            n = _to_num(v)
            if n is not None:
                cfg = cfg.field(k, n)
            else:
                cfg = cfg.field(k, v)
            wrote = True
        if wrote:
            write_api.write(bucket=INFLUX_BUCKET, record=cfg)

    if pm_kpis:
        kpi_points = []
        for item in pm_kpis:
            kpi_type = str(item.get("Type", "")).strip()
            if not kpi_type:
                continue
            p = Point("vankom_kpis").time(now, WritePrecision.S)
            for k, v in tags.items():
                p = p.tag(k, v)
            p = p.tag("kpi_type", kpi_type)
            oui = str(item.get("Oui", "")).strip()
            unit = str(item.get("Unit", "")).strip()
            if oui:
                p = p.tag("oui", oui)
            if unit:
                p = p.tag("unit", unit)
            n = _to_num(item.get("Val"))
            if n is not None:
                p = p.field("value", n)
            else:
                p = p.field("value_str", str(item.get("Val", "")))
            kpi_points.append(p)
        if kpi_points:
            write_api.write(bucket=INFLUX_BUCKET, record=kpi_points)


def main() -> None:
    targets = parse_targets()
    log.info(f"Configured Vankom targets: {[t['target_name'] for t in targets]}")
    log.info(f"Vankom scan interval: {INTERVAL}s")

    influx = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    write_api = influx.write_api(write_options=SYNCHRONOUS)
    sessions: Dict[str, requests.Session] = {}

    while True:
        for target in targets:
            name = target["target_name"]
            try:
                if name not in sessions:
                    sessions[name] = auth(target)
                    log.info(f"[{name}] authenticated")

                session = sessions[name]
                online_users = read_online_users(session, target)
                online_users_count_api = read_online_user_count(session, target)
                pm_kpis = read_pm_kpis(session, target)
                alarms_rt = read_alarms(session, target, history=False)
                alarms_hist = read_alarms(session, target, history=True)
                cell_status = read_cell_status(session, target)
                params = read_params(session, target)
                network_params = read_network_params(session, target)

                write_points(
                    write_api,
                    target,
                    online_users,
                    online_users_count_api,
                    pm_kpis,
                    alarms_rt,
                    alarms_hist,
                    cell_status,
                    params,
                    network_params,
                )
                log.info(
                    f"[{name}] users_kpi={[k.get('Val') for k in pm_kpis if str(k.get('Type','')).upper()=='UE_COUNT']} "
                    f"users_api={online_users_count_api} users_list={len(online_users)} alarms_rt={len(alarms_rt)} "
                    f"alarms_hist={len(alarms_hist)} cell_status={cell_status} net_params={len(network_params)}"
                )
            except Exception as e:
                log.error(f"[{name}] read/auth error: {e}; will re-auth next cycle")
                old = sessions.pop(name, None)
                if old:
                    try:
                        old.close()
                    except Exception:
                        pass

        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
