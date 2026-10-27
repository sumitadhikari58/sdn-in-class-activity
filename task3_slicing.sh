#!/bin/bash
# Task 3 - Two isolated slices on one OVS switch using QoS queues + DSCP/VLAN flows.
# Slice A (streaming): Queue 1, min 50 Mbps, max 100 Mbps, DSCP 34 (AF41) / VLAN 10
# Slice B (control):   Queue 2, min  1 Mbps, max   5 Mbps, DSCP 46 (EF)   / VLAN 20
# Usage: sudo ./task3_slicing.sh
set -e
BR=br0
EGRESS=eth1          # shared uplink (egress port)
OUT_OFPORT=2         # OpenFlow port number of $EGRESS

ovs-vsctl --may-exist add-br $BR
ovs-vsctl set bridge $BR protocols=OpenFlow13
ovs-vsctl --may-exist add-port $BR $EGRESS

# --- QoS + Queue tables (HTB, link = 100 Mbps) ---
ovs-vsctl -- set port $EGRESS qos=@newqos \
  -- --id=@newqos create qos type=linux-htb other-config:max-rate=100000000 queues:1=@q1 queues:2=@q2 \
  -- --id=@q1 create queue other-config:min-rate=50000000 other-config:max-rate=100000000 \
  -- --id=@q2 create queue other-config:min-rate=1000000  other-config:max-rate=5000000

# --- Flow rules ---
ovs-ofctl -O OpenFlow13 del-flows $BR
# Slice A: DSCP 34 (tos = 34<<2 = 136) OR VLAN 10 -> queue 1
ovs-ofctl -O OpenFlow13 add-flow $BR "priority=200,ip,nw_tos=136,actions=set_queue:1,output:$OUT_OFPORT"
ovs-ofctl -O OpenFlow13 add-flow $BR "priority=200,dl_vlan=10,actions=set_queue:1,output:$OUT_OFPORT"
# Slice B: DSCP 46 (tos = 46<<2 = 184) OR VLAN 20 -> queue 2
ovs-ofctl -O OpenFlow13 add-flow $BR "priority=200,ip,nw_tos=184,actions=set_queue:2,output:$OUT_OFPORT"
ovs-ofctl -O OpenFlow13 add-flow $BR "priority=200,dl_vlan=20,actions=set_queue:2,output:$OUT_OFPORT"
# Default
ovs-ofctl -O OpenFlow13 add-flow $BR "priority=0,actions=NORMAL"

# --- Verify ---
echo "== QoS ==";    ovs-vsctl list qos
echo "== Queues =="; ovs-vsctl list queue
echo "== Flows ==";  ovs-ofctl -O OpenFlow13 dump-flows $BR
echo "== Queue stats =="; ovs-ofctl -O OpenFlow13 queue-stats $BR
# Test (iperf with DSCP):  iperf3 -c <srv> -S 0x88  (Slice A)   |  iperf3 -c <srv> -S 0xB8 (Slice B)
