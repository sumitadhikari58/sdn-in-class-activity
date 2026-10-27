#!/usr/bin/env python3
"""Task 1 - Automated network policy engine using an SDN controller's
Northbound REST API (ONOS-style endpoints).

  python3 task1_policy_engine.py --mock      # runs against a built-in fake controller
  python3 task1_policy_engine.py --url http://<controller>:8181/onos/v1
"""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

AUTH = ("onos", "rok")
HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}
THRESHOLD_BPS = 50_000_000          # 50 Mbps
POLL_INTERVAL = 2                   # seconds
HOST_A, HOST_B = "10.0.0.1", "10.0.0.2"   # pair to block when threshold exceeded


def get_devices(base):
    """GET all connected switch device IDs."""
    r = requests.get(f"{base}/devices", auth=AUTH, headers=HEADERS, timeout=5)
    r.raise_for_status()
    return [d["id"] for d in r.json()["devices"] if d.get("available")]


def get_port_stats(base, device_id):
    """GET and parse port statistics -> {port: bytes_received+sent}."""
    r = requests.get(f"{base}/statistics/ports/{device_id}", auth=AUTH,
                     headers=HEADERS, timeout=5)
    r.raise_for_status()
    out = {}
    for dev in r.json()["statistics"]:
        for p in dev["ports"]:
            out[p["port"]] = p["bytesReceived"] + p["bytesSent"]
    return out


def icmp_block_flow(device_id, src_ip, dst_ip):
    """Flow rule payload: match ICMP src->dst, empty treatment = DROP."""
    return {
        "priority": 40000,
        "timeout": 0,
        "isPermanent": True,
        "deviceId": device_id,
        "treatment": {"instructions": []},
        "selector": {"criteria": [
            {"type": "ETH_TYPE", "ethType": "0x0800"},
            {"type": "IP_PROTO", "protocol": 1},
            {"type": "IPV4_SRC", "ip": f"{src_ip}/32"},
            {"type": "IPV4_DST", "ip": f"{dst_ip}/32"},
        ]},
    }


def push_flow(base, device_id, flow):
    """POST the flow rule to the controller."""
    r = requests.post(f"{base}/flows/{device_id}?appId=org.policy.engine",
                      auth=AUTH, headers=HEADERS, data=json.dumps(flow), timeout=5)
    r.raise_for_status()
    return r.status_code


def run(base, cycles):
    last, blocked = {}, set()
    for _ in range(cycles):
        for dev in get_devices(base):
            stats = get_port_stats(base, dev)
            for port, total in stats.items():
                prev = last.get((dev, port))
                last[(dev, port)] = total
                if prev is None:
                    continue
                bps = (total - prev) * 8 / POLL_INTERVAL
                print(f"[{dev}] port {port}: {bps/1e6:8.2f} Mbps")
                if bps > THRESHOLD_BPS and dev not in blocked:
                    print(f"  !! threshold {THRESHOLD_BPS/1e6:.0f} Mbps exceeded "
                          f"-> blocking ICMP {HOST_A} <-> {HOST_B} on {dev}")
                    for s, d in ((HOST_A, HOST_B), (HOST_B, HOST_A)):
                        code = push_flow(base, dev, icmp_block_flow(dev, s, d))
                        print(f"  POST flow {s}->{d}: HTTP {code}")
                    blocked.add(dev)
        time.sleep(POLL_INTERVAL)


# ---------------- built-in fake controller for offline demo ----------------
class MockController(BaseHTTPRequestHandler):
    counter = {}

    def log_message(self, *a):
        pass

    def _send(self, code, body):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def do_GET(self):
        if self.path.endswith("/devices"):
            self._send(200, {"devices": [
                {"id": "of:0000000000000001", "available": True},
                {"id": "of:0000000000000002", "available": True}]})
        elif "/statistics/ports/" in self.path:
            dev = self.path.split("/")[-1]
            c = MockController.counter.setdefault(dev, {"n": 0, "bytes": 0})
            c["n"] += 1
            # device 1 becomes a heavy hitter after 3 polls (~100 Mbps at 0.2s poll)
            c["bytes"] += 2_500_000 if (dev.endswith("1") and c["n"] > 3) else 50_000
            self._send(200, {"statistics": [{"device": dev, "ports": [
                {"port": 1, "bytesReceived": c["bytes"], "bytesSent": c["bytes"] // 2},
                {"port": 2, "bytesReceived": 500 * c["n"], "bytesSent": 400 * c["n"]}]}]})

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self._send(201, {})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8181/onos/v1")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--cycles", type=int, default=6)
    a = ap.parse_args()
    if a.mock:
        srv = HTTPServer(("127.0.0.1", 8181), MockController)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        POLL_INTERVAL = 0.2
        a.cycles = 8
    run(a.url, a.cycles)
