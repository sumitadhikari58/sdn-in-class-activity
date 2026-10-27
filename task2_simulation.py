"""Offline simulation of the Task 2 logic (no Ryu / Mininet needed) to produce demo output."""
import time

BCAST = "ff:ff:ff:ff:ff:ff"
STORM_LIMIT = 5
table, seen, flows = {}, {}, []


def packet_in(dpid, in_port, src, dst, etype=0x0806):
    print(f"PacketIn dpid={dpid} in={in_port} type=0x{etype:04x} {src} -> {dst}")
    t = table.setdefault(dpid, {})
    if src not in t or t[src] != in_port:
        t[src] = in_port
        print(f"  LEARN  {src} -> port {in_port}")
    if dst == BCAST:
        k = (dpid, src, in_port)
        seen[k] = seen.get(k, 0) + 1
        if seen[k] > STORM_LIMIT:
            if ("DROP", in_port, src, dst) not in flows:
                flows.append(("DROP", in_port, src, dst))
            print(f"  STORM! {seen[k]} broadcasts -> FlowMod DROP (in={in_port}, src={src}, dst=bcast)")
            return
    if dst in t:
        flows.append(("FWD", in_port, src, dst, t[dst]))
        print(f"  KNOWN  {dst} on port {t[dst]} -> FlowMod + PacketOut(port {t[dst]})")
    else:
        print("  UNKNOWN dst -> FLOOD")


A, B = "00:00:00:00:00:01", "00:00:00:00:00:02"
packet_in(1, 1, A, B)               # unknown -> flood
packet_in(1, 2, B, A)               # A known -> install flow
packet_in(1, 1, A, B)               # B known now
print("--- loop: same broadcast keeps returning ---")
for _ in range(8):
    packet_in(1, 3, A, BCAST)
print("\nInstalled flows:")
for f in flows:
    print(" ", f)
