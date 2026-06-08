# Baicell gNB Analysis Report
**Target:** 192.168.22.200  
**Date:** 2025-06-05

---

## 1. Connectivity
- **Ping:** Successful (RTT ~1.2-1.7ms, TTL=63)
- **Status:** Host is up and reachable

## 2. Open Ports & Services

| Port | State | Service | Version |
|------|-------|---------|---------|
| 111/tcp | open | rpcbind | 2-4 (RPC #100000) |
| 443/tcp | open | ssl/https | Baicells Management Utility (Gargoyle Firmware) |
| 7547/tcp | open | cwmp? | TR-069 (503 Service Unavailable) |
| 27149/tcp | open | ssh | OpenSSH 9.4 (protocol 2.0) |

## 3. SSH Access
- **Port:** 27149 (not the default 22)
- **Authentication:** password + publickey
- **Host Keys:** ECDSA (256), ED25519 (256)
- **Access:** Requires credentials (root user exists)
- **Command:** `ssh root@192.168.22.200 -p 27149`

## 4. Web Interface
- **URL:** `https://192.168.22.443/`
- **Firmware:** Gargoyle Firmware Webgui (Baicells branded)
- **SSL Cert:** Baicells, Beijing, CN (self-signed, 2017-2067)
- **Tech Stack:** Vue.js, Element UI, jQuery, SHA-512 login
- **Server header:** Redacted/obfuscated

## 5. OS Fingerprinting

| Method | Result |
|--------|--------|
| TTL Analysis | TTL=63 → Linux (1 hop away from TTL 64) |
| OpenSSH Version | 9.4 → Recent Linux distro (2023+) |
| Firmware | Gargoyle → Based on OpenWrt/Linux |
| Vendor | Baicells → Embedded Linux platform |

**Conclusion: Linux-based embedded system (OpenWrt or Yocto)**

## 6. Security Notes
- SSH on non-standard port (27149) — basic obscurity
- Web UI requires authentication (SHA-512 hashing)
- TR-069 (7547) returning 503 — possibly disabled or misconfigured
- rpcbind exposed (111) — potential RPC enumeration risk
- SSL certificate expires in 2067 (unusual, likely self-signed)

## 7. Raw Data Files
- `full_scan.nmap` — Full TCP port scan results
- `full_scan.gnmap` — Grepable scan output
- `full_scan.xml` — XML scan output
