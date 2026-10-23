"""Addresses, sockets and interfaces as data, run through the translated source."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from axpy.run import load  # noqa: E402
from axpy.rt import _rt_lit  # noqa: E402

g = load()


def link(**fields):
    return _rt_lit(g.LinkInfo, None, **fields)

fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + str(extra) if extra and not cond else ""))
    if not cond:
        fails.append(name)


def thrown(fn):
    try:
        fn()
    except Exception as e:
        return e
    return None


A = g.Addr
K = g.AddrKind

# --- Addr text ------------------------------------------------------------------------------
for t, want in [
    ("192.168.1.20", "192.168.1.20"), ("0.0.0.0", "0.0.0.0"), ("255.255.255.255", "255.255.255.255"),
    ("::", "::"), ("::1", "::1"), ("2001:db8::1", "2001:db8::1"), ("2001:0db8:0000:0000:0000:0000:0000:0001", "2001:db8::1"),
    ("fe80::1ff:fe23:4567:890a", "fe80::1ff:fe23:4567:890a"), ("1:0:0:2:0:0:0:3", "1:0:0:2::3"),
    ("1:2:3:4:5:6:7:8", "1:2:3:4:5:6:7:8"), ("1:0:3:4:5:6:7:8", "1:0:3:4:5:6:7:8"), ("::ffff:10.0.0.1", "::ffff:10.0.0.1"),
    ("ABCD::EF", "abcd::ef"), ("2001:db8:0:0:1::", "2001:db8:0:0:1::"),
]:
    got = g.Addr.parse(t).text()
    check("parse/print %s" % t, got == want, got)

for bad in ["", "1.2.3", "1.2.3.4.5", "256.1.1.1", "1..2.3", "a.b.c.d", "1:2:3", "1::2::3", ":1", "1:", "12345::", "g::1", "::1.2.3", "1:2:3:4:5:6:7:8:9", "1.2.3.4:80"]:
    check("refuses %r" % bad, isinstance(thrown(lambda: g.Addr.parse(bad)), g.Invalid))

# --- kinds, equality, subnets -----------------------------------------------------------------
kinds = {
    "0.0.0.0": K.Unspecified, "127.0.0.1": K.Loopback, "10.1.2.3": K.Private, "172.16.0.1": K.Private, "172.32.0.1": K.Public,
    "192.168.5.5": K.Private, "169.254.1.1": K.LinkLocal, "224.0.0.251": K.Multicast, "8.8.8.8": K.Public, "100.64.0.1": K.Private,
    "::": K.Unspecified, "::1": K.Loopback, "fe80::1": K.LinkLocal, "fd00::1": K.Private, "ff02::1": K.Multicast, "2606:4700::1111": K.Public,
    "::ffff:127.0.0.1": K.Loopback, "::ffff:8.8.8.8": K.Public,
}
for t, k in kinds.items():
    check("kind of %s" % t, g.Addr.parse(t).kind() == k, g.Addr.parse(t).kind().label())
check("a mapped address equals its IPv4 form", g.Addr.parse("::ffff:1.2.3.4").equals(g.Addr.parse("1.2.3.4")) and not g.Addr.parse("1.2.3.4").equals(g.Addr.parse("1.2.3.5")))
check("keys follow equality", g.Addr.parse("::ffff:1.2.3.4").key() == g.Addr.parse("1.2.3.4").key() and g.Addr.parse("1.2.3.4").key() != g.Addr.parse("1.2.3.5").key())
net = g.Addr.parse("192.168.0.0")
check("subnet membership", g.Addr.parse("192.168.77.1").inSubnet(net, 16) and not g.Addr.parse("192.169.0.1").inSubnet(net, 16) and g.Addr.parse("192.168.0.1").inSubnet(net, 24))
check("a prefix that is not a byte multiple", g.Addr.parse("10.130.0.1").inSubnet(g.Addr.parse("10.128.0.0"), 9) and not g.Addr.parse("10.127.0.1").inSubnet(g.Addr.parse("10.128.0.0"), 9))
check("/0 holds everything of its family and no other", g.Addr.parse("1.2.3.4").inSubnet(g.Addr.none(), 0) and not g.Addr.parse("::1").inSubnet(g.Addr.none(), 0))
check("v6 subnet", g.Addr.parse("2001:db8:1::5").inSubnet(g.Addr.parse("2001:db8::"), 32) and not g.Addr.parse("2001:db9::5").inSubnet(g.Addr.parse("2001:db8::"), 32))
check("bytes in network order", [g.Addr.parse("1.2.3.4").byteAt(i) for i in range(4)] == [1, 2, 3, 4] and g.Addr.parse("102:304::").byteAt(1) == 2)

# --- Endpoint ------------------------------------------------------------------------------
E = g.Endpoint
check("endpoint text", E(A.parse("10.0.0.2"), 443).text() == "10.0.0.2:443" and E(A.parse("::1"), 80).text() == "[::1]:80" and E(A.parse("1.2.3.4"), 0).text() == "1.2.3.4")
check("a mapped endpoint prints as IPv4", E(A.parse("::ffff:1.2.3.4"), 80).text() == "1.2.3.4:80")
check("empty endpoint", E.none().isEmpty() and not E(A.none(), 80).isEmpty())

# --- /proc/net/tcp and friends, as Linux writes them ---------------------------------------------
TCP = """  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 0100007F:0035 00000000:0000 0A 00000000:00000000 00:00000000 00000000   101        0 12345 1 0000000000000000 100 0 0 10 0
   1: 0F02000A:C7E8 142AC15B:01BB 01 00000000:00000000 02:000A7214 00000000  1000        0 67890 2 0000000000000000 20 4 30 10 -1
   2: 0F02000A:C7EA 142AC15B:01BB 06 00000000:00000000 03:00001700 00000000     0        0 0 3 0000000000000000
"""
scan = g.SocketScan()
g.NetText.sockets(TCP, g.Proto.Tcp, scan)
t, ino = scan.table, scan.inodes
check("three rows, header skipped", t.size() == 3, t.size())
check("inodes ride along", [ino.at(i) for i in range(ino.size())] == [12345, 67890, 0])
r0, r1, r2 = t.at(0), t.at(1), t.at(2)
check("a listening socket on loopback", r0.local.text() == "127.0.0.1:53" and r0.isListening() and r0.remote.isEmpty(), r0.describe())
check("an established connection", r1.local.text() == "10.0.2.15:51176" and r1.remote.text() == "91.193.42.20:443" and r1.state == g.TcpState.Established, r1.describe())
check("time wait", r2.state == g.TcpState.TimeWait)
check("the owner is not known yet", r0.pid == -1 and r0.describe() == "tcp 127.0.0.1:53 listening")
check("an external peer is told from an internal one", r1.isExternal() and not r0.isExternal())

TCP6 = """  sl  local_address                         remote_address                        st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000000000000000000001000000:0016 00000000000000000000000000000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 4242 1 0000000000000000 100 0 0 10 0
   1: 0000000000000000FFFF00000F02000A:1F90 0000000000000000FFFF00000100000A:C350 01 00000000:00000000 00:00000000 00000000  1000        0 4343 1 0000000000000000 100 0 0 10 0
"""
scan6 = g.SocketScan()
g.NetText.sockets(TCP6, g.Proto.Tcp, scan6)
t6 = scan6.table
check("an IPv6 loopback listener", t6.at(0).local.text() == "[::1]:22", t6.at(0).local.text())
check("a mapped IPv4 connection prints as IPv4", t6.at(1).local.text() == "10.0.2.15:8080" and t6.at(1).remote.text() == "10.0.0.1:50000", (t6.at(1).local.text(), t6.at(1).remote.text()))

UDP = """   sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode ref pointer drops
  100: 00000000:0044 00000000:0000 07 00000000:00000000 00:00000000 00000000     0        0 555 2 0000000000000000 0
"""
scanu = g.SocketScan()
g.NetText.sockets(UDP, g.Proto.Udp, scanu)
tu = scanu.table
check("a UDP socket has no state", tu.size() == 1 and tu.at(0).state == g.TcpState.Open and tu.at(0).local.text() == "0.0.0.0:68" and tu.at(0).describe() == "udp 0.0.0.0:68 open")

junk = g.SocketScan()
g.NetText.sockets("zzz\n1: nothex:zz 0:0 xx 0 0 0 0 0 5\n\n", g.Proto.Tcp, junk)
check("garbage lines are skipped, not trusted", junk.table.size() == 0)

# --- tables narrow -----------------------------------------------------------------------------
full = g.SocketTable()
for row, pid in [(t.at(0), 100), (t.at(1), 4120), (t.at(2), 4120), (tu.at(0), -1)]:
    c = row.copy()
    c.pid = pid
    full.add(c)
check("narrowing by owner", full.ofPid(4120).size() == 2 and full.ofPid(7).size() == 0)
check("narrowing by state", full.listening().size() == 1 and full.inState(g.TcpState.TimeWait).size() == 1)
check("narrowing by transport and port", full.ofProto(g.Proto.Udp).size() == 1 and full.onPort(53).size() == 1)
check("narrowing chains", full.ofPid(4120).inState(g.TcpState.Established).size() == 1 and full.external().size() == 2)
check("the peer", full.peerIs(g.Addr.parse("91.193.42.20")).size() == 2)
check("unowned count and distinct owners", full.unowned() == 1 and list(full.owners()) == [100, 4120])
check("narrowing copies rows", full.listening().at(0) is not full.at(0))
check("the table grows past its first room", (lambda tb: [tb.add(t.at(0)) for _ in range(300)] and tb.size() == 300)(g.SocketTable()))

# --- routes ---------------------------------------------------------------------------------
ROUTE = """Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT
eth0\t00000000\t0102000A\t0003\t0\t0\t100\t00000000\t0\t0\t0
eth0\t0002000A\t00000000\t0001\t0\t0\t100\t00FFFFFF\t0\t0\t0
docker0\t000011AC\t00000000\t0001\t0\t0\t0\t0000FFFF\t0\t0\t0
eth1\t0000FEA9\t00000000\t0000\t0\t0\t1000\t0000FFFF\t0\t0\t0
"""
rt = g.RouteTable()
g.NetText.routes4(ROUTE, rt)
check("down routes are left out", rt.size() == 3, rt.size())
check("route fields", rt.at(0).isDefault() and rt.at(0).gateway.text() == "10.0.2.1" and rt.at(0).ifName == "eth0" and rt.at(0).metric == 100, rt.at(0).describe())
check("masks become prefixes", rt.at(1).dest.text() == "10.0.2.0" and rt.at(1).prefix == 24 and rt.at(1).onLink() and rt.at(2).prefix == 16, [rt.at(i).describe() for i in range(3)])
check("describe", rt.at(0).describe() == "default via 10.0.2.1 dev eth0 metric 100" and rt.at(1).describe() == "10.0.2.0/24 dev eth0 metric 100")
check("the longest prefix wins", rt.at(rt.indexFor(g.Addr.parse("10.0.2.77"))).prefix == 24 and rt.at(rt.indexFor(g.Addr.parse("8.8.8.8"))).isDefault())
check("172.17 goes to docker", rt.at(rt.indexFor(g.Addr.parse("172.17.0.5"))).ifName == "docker0")
check("no route for the other family", rt.indexFor(g.Addr.parse("::1")) == -1 and not rt.reaches(g.Addr.parse("2001:db8::1")))
check("default gateway", rt.defaultGateway(4).text() == "10.0.2.1" and rt.defaultGateway(6).isUnspecified())
check("prefix of a mask", g.NetText.prefixOf(g.Addr.parse("255.255.240.0")) == 20 and g.NetText.prefixOf(g.Addr.parse("0.0.0.0")) == 0 and g.NetText.prefixOf(g.Addr.parse("255.255.255.255")) == 32)

R6 = """00000000000000000000000000000000 00 00000000000000000000000000000000 00 fe800000000000000000000000000001 00000400 00000001 00000000 00000003 eth0
fe800000000000000000000000000000 40 00000000000000000000000000000000 00 00000000000000000000000000000000 00000100 00000001 00000000 00000001 eth0
00000000000000000000000000000001 80 00000000000000000000000000000000 00 00000000000000000000000000000000 00000000 00000003 00000000 80200001 lo
"""
r6 = g.RouteTable()
g.NetText.routes6(R6, r6)
check("IPv6 routes", r6.size() == 3 and r6.at(0).isDefault() and r6.at(0).gateway.text() == "fe80::1" and r6.at(0).metric == 1024 and r6.at(1).prefix == 64, [r6.at(i).describe() for i in range(r6.size())])
check("an IPv6 address follows its route", r6.at(r6.indexFor(g.Addr.parse("fe80::5"))).prefix == 64 and r6.defaultGateway(6).text() == "fe80::1")

# --- /proc/net/dev ----------------------------------------------------------------------------
DEV = """Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo:  123456     100    0    0    0     0          0         0   123456     100    0    0    0     0       0          0
  eth0: 9876543210  70000    0    0    0     0          0         5  1234567890   50000    0    0    0     0       0          0
"""
rows = g.NetText.devRows(DEV)
by_name = {rows.at(k).name: rows.at(k) for k in range(rows.size())}
check("interface names, in order", [rows.at(k).name for k in range(rows.size())] == ["lo", "eth0"])
check("counters", (by_name["eth0"].rx, by_name["eth0"].tx) == (9876543210, 1234567890) and "wlan0" not in by_name)
check("a name that is a prefix of another is its own row", "eth" not in by_name)
check("short files", g.Scan.number("1500\n") == 1500 and g.Scan.number("-1\n") == -1 and g.Scan.number("up\n") == -1 and g.Scan.line("aa:bb\n") == "aa:bb")
check("kinds", g.NetText.kindOf(772, False, False) == g.IfaceKind.Loopback and g.NetText.kindOf(1, True, False) == g.IfaceKind.Wifi and g.NetText.kindOf(1, False, True) == g.IfaceKind.Virtual and g.NetText.kindOf(1, False, False) == g.IfaceKind.Ethernet and g.NetText.kindOf(65534, False, False) == g.IfaceKind.Other)

# --- interfaces ----------------------------------------------------------------------------------
ifc = g.IfaceInfo(2, "eth0", "Ethernet")
ifc.link(link(mac="aa:bb:cc:dd:ee:ff", kind=g.IfaceKind.Ethernet, up=True, mtu=1500, speedBps=1000000000))
for i in range(6):
    ifc.addAddress(g.Addr.parse("fe80::%d" % (i + 1)), 64)
ifc.addAddress(g.Addr.parse("10.0.2.15"), 24)
check("addresses grow and keep their order", ifc.addressCount() == 7 and ifc.addrAt(0).text() == "fe80::1" and ifc.prefixAt(6) == 24)
check("first IPv4", ifc.firstV4().text() == "10.0.2.15" and g.IfaceInfo(1, "x", "x").firstV4().isUnspecified())
check("holds and reaches", ifc.holds(g.Addr.parse("10.0.2.15")) and not ifc.holds(g.Addr.parse("10.0.2.16")) and ifc.reaches(g.Addr.parse("10.0.2.99")) and not ifc.reaches(g.Addr.parse("10.0.3.1")))
tab = g.IfaceTable()
tab.add(g.IfaceInfo(1, "lo", "lo"))
tab.at(0).link(link(kind=g.IfaceKind.Loopback, up=True, mtu=65536))
tab.add(ifc)
check("lookup by name, label, index, address", tab.find("ETH0") == 1 and tab.find("ethernet") == 1 and tab.find("zz") == -1 and tab.byIndex(2) == 1 and tab.holding(g.Addr.parse("10.0.2.15")) == 1)
check("loopback is not counted as a way out", tab.upCount() == 1)
check("an interface keeps its key", g.IfaceInfo(9, "eth0", "x").key == ifc.key)

check("has", g.Scan.has("../../devices/virtual/net/lo", "/virtual/") and not g.Scan.has("../../devices/pci0000:00/net/eth0", "/virtual/") and g.Scan.has("abc", "") and not g.Scan.has("ab", "abc"))
check("socket inodes", g.NetText.socketInode("socket:[12345]") == 12345 and g.NetText.socketInode("pipe:[12345]") == -1 and g.NetText.socketInode("/dev/null") == -1 and g.NetText.socketInode("socket:[]") == -1 and g.NetText.socketInode("socket:[12a]") == -1)
# --- Net, over the fake network ----------------------------------------------------------------
N = g.Net
check("sockets come through, owners and all", N.sockets().size() == 4 and N.socketsOf(4120).size() == 2 and N.socketsOf(4120).external().size() == 1)
check("who listens", N.sockets().listening().at(0).local.text() == "0.0.0.0:443")
check("an unowned socket is counted, not hidden", N.sockets().unowned() == 1)
check("the route to the internet is the default one", N.routeTo(A.parse("8.8.8.8")).isDefault() and N.routeTo(A.parse("192.168.1.77")).prefix == 24)
check("no route to the other family is Absent, not a made-up answer", isinstance(thrown(lambda: N.routeTo(A.parse("2001:db8::1"))), g.Absent))
check("gateway", N.gateway().text() == "192.168.1.1")
check("the primary interface is the one the default route leaves by", N.primary().name == "eth0")
check("the local address", N.localAddress().text() == "192.168.1.20")
check("online", N.isOnline())
check("totals leave the loopback out", tuple(N.totals()) == (1000077, 250088), tuple(N.totals()))

# --- TrafficMeter ------------------------------------------------------------------------------
m = g.TrafficMeter()
def reading(rx, tx):
    t = g.IfaceTable()
    e = g.IfaceInfo(2, "eth0", "Ethernet")
    e.traffic(rx, tx)
    t.add(e)
    return t
m.sample(reading(1000, 500), 10000)
check("the first reading has nothing to compare", m.rxPerSecond("eth0") == 0 and m.rxTotal() == 0)
m.sample(reading(1000 + 2_000_000, 500 + 500_000), 12000)
check("rates are bytes per second over the interval", m.rxPerSecond("eth0") == 1_000_000 and m.txPerSecond("eth0") == 250_000 and m.rxTotal() == 1_000_000)
m.sample(reading(100, 100), 13000)
check("a counter that went back is no measurement", m.rxPerSecond("eth0") == 0 and m.txPerSecond("eth0") == 0)
m.sample(reading(100, 100), 13000)
check("no time passed, no rate", m.rxPerSecond("eth0") == 0)
check("an unknown interface is 0", m.rxPerSecond("wlan9") == 0)

print("all ok" if not fails else "FAILED: %s" % fails)
sys.exit(1 if fails else 0)
