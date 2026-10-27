"""Task 2 - Ryu (OpenFlow 1.3) app: MAC learning + broadcast-storm protection.

Run:  ryu-manager task2_mac_learning_storm.py
Test: sudo mn --topo single,3 --controller remote --switch ovsk,protocols=OpenFlow13
"""
import time
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet

BCAST = "ff:ff:ff:ff:ff:ff"
STORM_WINDOW = 1.0      # seconds
STORM_LIMIT = 5         # same (dpid, src, in_port) broadcast > N times/window => loop


class StormGuard(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.mac_to_port = {}      # dpid -> {mac: port}
        self.bcast_seen = {}       # (dpid, src, in_port) -> [count, window_start]

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def features_handler(self, ev):
        dp = ev.msg.datapath
        p = dp.ofproto_parser
        # table-miss: send to controller
        self.add_flow(dp, 0, p.OFPMatch(),
                      [p.OFPActionOutput(dp.ofproto.OFPP_CONTROLLER,
                                         dp.ofproto.OFPCML_NO_BUFFER)])

    def add_flow(self, dp, prio, match, actions, idle=0, hard=0):
        ofp, p = dp.ofproto, dp.ofproto_parser
        inst = [p.OFPInstructionActions(ofp.OFPIT_APPLY_ACTIONS, actions)]  # [] => drop
        dp.send_msg(p.OFPFlowMod(datapath=dp, priority=prio, match=match,
                                 instructions=inst, idle_timeout=idle,
                                 hard_timeout=hard))

    def is_storm(self, dpid, src, in_port):
        key, now = (dpid, src, in_port), time.time()
        cnt, start = self.bcast_seen.get(key, [0, now])
        if now - start > STORM_WINDOW:
            cnt, start = 0, now
        cnt += 1
        self.bcast_seen[key] = [cnt, start]
        return cnt > STORM_LIMIT

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in(self, ev):
        msg = ev.msg
        dp, ofp, p = msg.datapath, msg.datapath.ofproto, msg.datapath.ofproto_parser
        in_port, dpid = msg.match["in_port"], dp.id

        eth = packet.Packet(msg.data).get_protocols(ethernet.ethernet)[0]
        eth_type, src, dst = eth.ethertype, eth.src, eth.dst
        self.logger.info("PacketIn dpid=%s in=%s type=0x%04x %s -> %s",
                         dpid, in_port, eth_type, src, dst)

        table = self.mac_to_port.setdefault(dpid, {})
        table[src] = in_port                                   # 1. learn source

        if dst == BCAST and self.is_storm(dpid, src, in_port):  # 2. storm detected
            self.logger.warning("Storm from %s on port %s -> install DROP", src, in_port)
            self.add_flow(dp, 100, p.OFPMatch(in_port=in_port, eth_src=src, eth_dst=BCAST),
                          [], hard=30)
            return

        out_port = table.get(dst, ofp.OFPP_FLOOD)              # 3. lookup
        actions = [p.OFPActionOutput(out_port)]
        if out_port != ofp.OFPP_FLOOD:                         # known: reactive flow
            self.add_flow(dp, 10, p.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src),
                          actions, idle=30)
        data = msg.data if msg.buffer_id == ofp.OFP_NO_BUFFER else None
        dp.send_msg(p.OFPPacketOut(datapath=dp, buffer_id=msg.buffer_id,
                                   in_port=in_port, actions=actions, data=data))
