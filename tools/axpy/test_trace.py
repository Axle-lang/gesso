"""A live trace, as data: the providers' payloads decoded, and the counts kept over them."""
import os
import socket
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from axpy.run import load  # noqa: E402

g = load()
fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + str(extra) if extra and not cond else ""))
    if not cond:
        fails.append(name)


A = g.Addr.parse
K = g.TraceKind


def v4(pid, size, dest, src, dport, sport, tail=b"\x00" * 16):
    return list(struct.pack("<II", pid, size) + socket.inet_aton(dest) + socket.inet_aton(src) + struct.pack(">HH", dport, sport) + tail)


def v6(pid, size, dest, src, dport, sport, tail=b"\x00" * 16):
    return list(struct.pack("<II", pid, size) + socket.inet_pton(socket.AF_INET6, dest) + socket.inet_pton(socket.AF_INET6, src) + struct.pack(">HH", dport, sport) + tail)


def decode(id, data):
    return g.KernelNet.decode(id, data, len(data))


# --- Kernel-Network ----------------------------------------------------------------------------------
e = decode(10, v4(4120, 1448, "93.184.216.34", "192.168.1.20", 443, 51000))
check("a TCP send: this end is the source, the peer the destination", (e.kind, e.pid, e.bytes, e.proto) == (K.Send, 4120, 1448, g.Proto.Tcp) and e.local.text() == "192.168.1.20:51000" and e.remote.text() == "93.184.216.34:443", e.describe())
e = decode(11, v4(4120, 900, "192.168.1.20", "93.184.216.34", 51000, 443))
check("a TCP receive: the destination is this end", (e.kind, e.bytes) == (K.Receive, 900) and e.local.text() == "192.168.1.20:51000" and e.remote.text() == "93.184.216.34:443", e.describe())
e = decode(12, v4(77, 0, "10.1.1.1", "10.0.0.2", 22, 40000))
check("a connect is a connection event with no bytes", (e.kind, e.bytes, e.pid) == (K.Connect, 0, 77) and e.remote.text() == "10.1.1.1:22")
check("an accept reads like a receive, a disconnect like a send", decode(15, v4(1, 0, "10.0.0.2", "10.9.9.9", 80, 5000)).remote.text() == "10.9.9.9:5000" and decode(13, v4(1, 0, "10.9.9.9", "10.0.0.2", 80, 5000)).remote.text() == "10.9.9.9:80")
e = decode(26, v6(9, 100, "2606:4700::1111", "2001:db8::2", 443, 50000))
check("IPv6 send", e.kind == K.Send and e.local.text() == "[2001:db8::2]:50000" and e.remote.text() == "[2606:4700::1111]:443" and e.bytes == 100, e.describe())
e = decode(42, v4(5, 64, "8.8.8.8", "10.0.0.2", 53, 40000))
check("UDP send and receive", e.proto == g.Proto.Udp and e.kind == K.Send and decode(43, v4(5, 64, "10.0.0.2", "8.8.8.8", 40000, 53)).proto == g.Proto.Udp and decode(59, v6(5, 8, "::1", "::1", 1, 2)).proto == g.Proto.Udp)
check("ids that are not transfers or connections are Other", not decode(14, v4(1, 1, "1.1.1.1", "2.2.2.2", 1, 2)).isKnown() and not decode(17, v4(1, 1, "1.1.1.1", "2.2.2.2", 1, 2)).isKnown() and not decode(999, v4(1, 1, "1.1.1.1", "2.2.2.2", 1, 2)).isKnown())
check("a payload cut short is Other, not a guess", not decode(10, v4(1, 1, "1.1.1.1", "2.2.2.2", 1, 2)[:19]).isKnown() and not decode(26, v6(1, 1, "::1", "::1", 1, 2)[:43]).isKnown() and not g.KernelNet.decode(10, [], 0).isKnown())
check("a big byte count is read as unsigned", decode(10, v4(1, 0xFFFFFFFF, "1.1.1.1", "2.2.2.2", 1, 2)).bytes == 0xFFFFFFFF)
check("the ports are big-endian", decode(10, v4(1, 1, "1.1.1.1", "2.2.2.2", 0x01BB, 0xC738)).remote.port == 443)

# --- DNS-Client -------------------------------------------------------------------------------------
def wide(s):
    return list((s + "\0").encode("utf-16-le"))


def dns_event(name, status, results):
    return wide(name) + list(struct.pack("<IQI", 1, 0, status)) + wide(results)


d = dns_event("api.stripe.com", 0, "52.1.2.3;2001:db8::7;")
e = g.DnsClient.decode(3008, 4120, d, len(d))
check("a resolution: the process, the name and what it got", (e.kind, e.pid, e.name) == (K.Resolved, 4120, "api.stripe.com") and e.answers == "52.1.2.3;2001:db8::7;" and e.describe() == "pid 4120 resolved api.stripe.com")
check("its addresses", [a.text() for a in e.addresses()] == ["52.1.2.3", "2001:db8::7"])
d = dns_event("alias.example", 0, "type: 5 target.example;93.184.216.34;")
e = g.DnsClient.decode(3008, 1, d, len(d))
check("answers that are not addresses are skipped", [a.text() for a in e.addresses()] == ["93.184.216.34"])
d = dns_event("nope.example", 9003, "")
e = g.DnsClient.decode(3008, 1, d, len(d))
check("a failed query is still a resolution, with no addresses", e.kind == K.Resolved and e.name == "nope.example" and e.answers == "" and len(e.addresses()) == 0)
check("another id, or a cut payload, is Other", not g.DnsClient.decode(3006, 1, d, len(d)).isKnown() and not g.DnsClient.decode(3008, 1, d[:5], 5).isKnown() and not g.DnsClient.decode(3008, 1, [], 0).isKnown())
unterminated = list("abc".encode("utf-16-le"))
check("a name with no terminator is not read past the end", not g.DnsClient.decode(3008, 1, unterminated, len(unterminated)).isKnown())

# --- the counters ------------------------------------------------------------------------------------
c = g.TraceCounters(3)
for ev in [
    decode(10, v4(100, 1000, "1.1.1.1", "10.0.0.2", 443, 50000)),
    decode(10, v4(100, 500, "1.1.1.1", "10.0.0.2", 443, 50000)),
    decode(11, v4(100, 4000, "10.0.0.2", "1.1.1.1", 50000, 443)),
    decode(10, v4(200, 70, "2.2.2.2", "10.0.0.2", 80, 50001)),
    decode(14, v4(200, 70, "2.2.2.2", "10.0.0.2", 80, 50001)),
]:
    c.add(ev)
check("bytes per process", (c.bytesSent(100), c.bytesReceived(100), c.bytesSent(200), c.bytesReceived(200)) == (1500, 4000, 70, 0) and c.pidCount() == 2 and c.pidAt(0) == 100)
check("totals, and an unknown process is 0", c.totalSent() == 1570 and c.totalReceived() == 4000 and c.bytesSent(999) == 0)
check("events of a kind not read are not counted", c.eventsSeen() == 4)
for i in range(5):
    c.add(decode(12, v4(300 + i, 0, "9.9.9.%d" % i, "10.0.0.2", 80, 40000 + i)))
c.add(decode(13, v4(300, 0, "9.9.9.0", "10.0.0.2", 80, 40000)))
check("connections opened are counted, and a close is not an opening", c.connectionsOf(300) == 1 and c.connectionsOf(304) == 1 and c.connectionsOf(100) == 0)
check("only the last few connection events are kept, oldest first", c.recentCount() == 3 and [c.recentAt(i).pid for i in range(3)] == [303, 304, 300] and c.recentAt(2).kind == K.Disconnect, [c.recentAt(i).pid for i in range(3)])
many = g.TraceCounters(10)
for p in range(1000):
    many.add(decode(10, v4(p + 1, 10, "1.1.1.1", "10.0.0.2", 443, 50000)))
check("the table of processes grows and keeps every count", many.pidCount() == 1000 and many.bytesSent(777) == 10 and many.totalSent() == 10000)

r = g.TraceCounters(4)
for ev in [g.DnsClient.decode(3008, 10, dns_event("api.stripe.com", 0, "52.1.2.3;"), len(dns_event("api.stripe.com", 0, "52.1.2.3;"))),
           g.DnsClient.decode(3008, 10, dns_event("api.stripe.com", 0, "52.1.2.3;"), len(dns_event("api.stripe.com", 0, "52.1.2.3;"))),
           g.DnsClient.decode(3008, 11, dns_event("cdn.example", 0, "52.1.2.3;"), len(dns_event("cdn.example", 0, "52.1.2.3;")))]:
    r.add(ev)
check("a name is kept once for each process and address, the latest answers", r.resolvedCount() == 2 and r.nameFor(A("52.1.2.3")) == "cdn.example" and r.nameFor(A("9.9.9.9")) == "" and r.resolvedAt(0).pid == 10)
check("a resolution is not a process that moved bytes", r.pidCount() == 0)

# --- NetTrace over the fake trace ------------------------------------------------------------------------
def thrown(fn):
    try:
        fn()
    except Exception as ex:
        return ex
    return None


t = g.NetTrace.start()
check("a started trace is on", t.status().isOn() and "resolved names" in t.status().note)
check("the first poll reads what had happened", t.poll() == 6 and t.counters().bytesSent(4120) == 1500 and t.counters().bytesReceived(4120) == 4000 and t.counters().connectionsOf(4120) == 1)
check("an event nobody decodes is read and not counted", t.counters().eventsSeen() == 5)
check("a name resolved is kept with its process", t.counters().nameFor(A("93.184.216.34")) == "example.com" and t.counters().resolvedAt(0).pid == 4120)
check("the next poll finds nothing new", t.poll() == 0 and t.counters().bytesSent(4120) == 1500)
t.stop()
check("a stopped trace says so and keeps its counts", not t.status().isOn() and t.status().state == g.ReadingState.Off and "frozen" in t.status().note and t.counters().bytesSent(4120) == 1500 and t.poll() == 0)
t.stop()
check("stopping twice is harmless", not t.status().isOn())

lossy = g.NetTrace.start()
real_dropped = g.TraceSession.dropped
g.TraceSession.dropped = lambda self: 12
check("dropped events are Lost, and the status says how many", lossy.status().state == g.ReadingState.Lost and "12 events" in lossy.status().note)
g.TraceSession.dropped = real_dropped

check("can it start: an admin right, here as on any non-Linux port", g.NetTrace.canStart().state in (g.SupportState.NeedsPrivilege, g.SupportState.Unsupported))
check("the statuses a failed start leaves", g.NetTrace.unavailable(g.Unsupported("net.trace", "linux", "no eBPF")).capable is False and g.NetTrace.refused(g.Denied("net.trace", "the session", g.Privilege.Elevated, 5)).capable is True and g.NetTrace.refused(g.Denied("net.trace", "the session", g.Privilege.Elevated, 5)).state == g.ReadingState.Off)

print("all ok" if not fails else "FAILED: %s" % fails)
sys.exit(1 if fails else 0)
