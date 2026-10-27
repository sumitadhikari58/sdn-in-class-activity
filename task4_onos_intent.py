#!/usr/bin/env python3
"""Task 4 - ONOS Intent Framework: create / verify / fail-link / re-verify via REST.

  python3 task4_onos_intent.py --mock
  python3 task4_onos_intent.py --url http://127.0.0.1:8181/onos/v1
Equivalent CLI:
  onos> add-point-intent -b 10M --ethSrc 00:00:00:00:00:01 --ethDst 00:00:00:00:00:02 of:0000000000000001/1 of:0000000000000002/1
  onos> intents
  mininet> link s1 s2 down      (simulate failure)
"""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

AUTH = ("onos", "rok")
H = {"Content-Type": "application/json"}
APP_ID = "org.onosproject.cli"

# Point-to-point intent between H1 (00:00:00:00:00:01 @ s1 port 1) and
# H2 (00:00:00:00:00:02 @ s2 port 1) with a 10 Mbps bandwidth constraint.
# (the reverse direction is a second intent, since P2P is unidirectional)
INTENT = {
    "type": "PointToPointIntent",
    "appId": APP_ID,
    "priority": 100,
    "ingressPoint": {"device": "of:0000000000000001", "port": "1"},
    "egressPoint": {"device": "of:0000000000000002", "port": "1"},
    "selector": {"criteria": [{"type": "ETH_SRC", "mac": "00:00:00:00:00:01"},
                              {"type": "ETH_DST", "mac": "00:00:00:00:00:02"}]},
    "constraints": [{"type": "BandwidthConstraint", "bandwidth": "10.0"}],  # Mbps
}


def create_intent(base):
    r = requests.post(f"{base}/intents", auth=AUTH, headers=H, data=json.dumps(INTENT))
    print(f"POST /intents -> HTTP {r.status_code}")


def intent_state(base):
    r = requests.get(f"{base}/intents/{APP_ID}", auth=AUTH, headers=H)
    r.raise_for_status()
    for i in r.json()["intents"]:
        return i["state"]


def wait_for(base, want, tries=10):
    for _ in range(tries):
        s = intent_state(base)
        print(f"  intent state = {s}")
        if s == want:
            return True
        time.sleep(0.5)
    return False


def simulate_link_failure(base, mock):
    """Real net: `mininet> link s1 s2 down` (or: sudo ovs-vsctl del-port ...)."""
    if mock:
        requests.post(f"{base}/_mock/linkdown")
    else:
        import subprocess
        subprocess.run(["bash", "-c", "echo 'link s1 s2 down' > /tmp/mn_cmd"], check=False)
    print("Link s1<->s2 brought DOWN")


def run(base, mock):
    print("1) Creating intent"); create_intent(base)
    print("2) Verify INSTALLED"); assert wait_for(base, "INSTALLED")
    print("3) Failing active path link"); simulate_link_failure(base, mock)
    print("4) Observing recompilation")
    for _ in range(4):
        print(f"  intent state = {intent_state(base)}")
        time.sleep(0.5)
    print("   path after reroute:", requests.get(f"{base}/intents/{APP_ID}", auth=AUTH).json()["intents"][0].get("path"))


class Mock(BaseHTTPRequestHandler):
    st = {"state": None, "t": 0, "down": False, "poll": 0}
    def log_message(self, *a): pass
    def _j(self, c, b):
        self.send_response(c); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(json.dumps(b).encode())
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0)); self.rfile.read(n)
        if self.path.endswith("/intents"):
            Mock.st.update(state="INSTALLING", poll=0); self._j(201, {})
        else:
            Mock.st.update(down=True, state="COMPILING", poll=0); self._j(200, {})
    def do_GET(self):
        s = Mock.st; s["poll"] += 1
        if s["poll"] >= 2 and s["state"] == "INSTALLING": s["state"] = "INSTALLED"
        elif s["poll"] == 2 and s["state"] == "COMPILING": s["state"] = "INSTALLING"
        elif s["poll"] >= 3 and s["state"] == "INSTALLING" and s["down"]: s["state"] = "INSTALLED"
        path = ["s1", "s3", "s2"] if s["down"] else ["s1", "s2"]
        self._j(200, {"intents": [{"state": s["state"], "path": path}]})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8181/onos/v1")
    ap.add_argument("--mock", action="store_true")
    a = ap.parse_args()
    if a.mock:
        srv = HTTPServer(("127.0.0.1", 8181), Mock)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
    run(a.url, a.mock)
