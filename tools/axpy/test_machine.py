"""The readings joined, over the fake machine and the fake network."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from axpy.run import load  # noqa: E402

g = load()
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


A = g.Addr.parse

# The fake network's sockets belong to pids 4, 4120 and none; the fake machine has processes 1, 20, 21, 22, 30.
# Give the network owners that exist, so a join can be tested.
def sockets():
    t = g.SocketTable()
    ep = g.Endpoint
    t.add(g.SocketInfo(g.Proto.Tcp, ep(A("0.0.0.0"), 443), ep.none(), g.TcpState.Listen, 21))
    t.add(g.SocketInfo(g.Proto.Tcp, ep(A("192.168.1.20"), 51000), ep(A("93.184.216.34"), 443), g.TcpState.Established, 21))
    t.add(g.SocketInfo(g.Proto.Tcp, ep(A("192.168.1.20"), 51001), ep(A("52.1.2.3"), 443), g.TcpState.Established, 22))
    t.add(g.SocketInfo(g.Proto.Tcp, ep(A("192.168.1.20"), 51002), ep(A("8.8.8.8"), 53), g.TcpState.Established, 9999))
    t.add(g.SocketInfo(g.Proto.Udp, ep(A("0.0.0.0"), 5353), ep.none(), g.TcpState.Open, -1))
    return t


g.NetSys.sockets = staticmethod(sockets)
m = g.Machine()
check("nothing is read before refresh", not m.hasRead() and m.sockets().size() == 0 and m.processes().size() == 0 and not m.readings()[0].isOn())
m.refresh()
check("refresh reads processes and sockets", m.hasRead() and m.processes().size() == 5 and m.sockets().size() == 5)
check("a socket's process", m.processOf(m.sockets().at(1)).name == "editor" and m.process(22).name == "Editor")
check("an owner that is not in the reading is Absent", isinstance(thrown(lambda: m.processOf(m.sockets().at(3))), g.Absent) and isinstance(thrown(lambda: m.processOf(m.sockets().at(4))), g.Absent) and isinstance(thrown(lambda: m.process(12345)), g.Absent))
check("the owner's name, or why there is none", m.ownerName(m.sockets().at(1)) == "editor" and m.ownerName(m.sockets().at(3)) == "(exited)" and m.ownerName(m.sockets().at(4)) == "(owner not visible)")
check("a process's sockets", m.socketsOf(m.process(21)).size() == 2 and m.socketsOf(m.process(30)).size() == 0)

# the programs: found once, and the unreadable ones with their reason
calls = []
real = g.ProcSys.imagePath
g.ProcSys.imagePath = staticmethod(lambda pid: (calls.append(pid), real(pid))[1])
check("the program of a process", m.programOf(m.process(21)) == "/usr/bin/editor" and m.programOfSocket(m.sockets().at(2)) == "/usr/bin/éditor")
m.programOf(m.process(21))
m.programOfSocket(m.sockets().at(1))
check("each program is looked up once, however often it is asked for", sorted(calls) == [21, 22])
check("a program that cannot be read says why, and a socket with no known owner has none", m.programOf(m.process(30)) == "" and "elevated" in m.whyNoProgram(m.process(30)) and m.programOfSocket(m.sockets().at(4)) == "" and m.programOfSocket(m.sockets().at(3)) == "")
g.ProcSys.imagePath = real
m.refresh()
check("what is remembered survives a refresh", m.programOf(m.process(21)) == "/usr/bin/editor" and len(calls) == 3, calls)

# names: the resolver's cache, through the reader
check("the cache was swept by the refresh", m.readings()[1].isOn() and m.nameOf(A("93.184.216.34")) == "cdn.example.net" and m.nameOf(A("8.8.8.8")) == "")
check("an endpoint with a name", m.endpointText(g.Endpoint(A("52.1.2.3"), 443)) == "api.stripe.com:443" and m.endpointText(g.Endpoint(A("8.8.8.8"), 53)) == "8.8.8.8:53" and m.endpointText(g.Endpoint(A("52.1.2.3"), 0)) == "api.stripe.com")
check("a socket in one line", m.describe(m.sockets().at(1)) == "tcp 192.168.1.20:51000 → cdn.example.net:443 established — editor [21]", m.describe(m.sockets().at(1)))
check("a listener, a socket whose owner went, a socket nobody can see", m.describe(m.sockets().at(0)) == "tcp 0.0.0.0:443 listening — editor [21]" and m.describe(m.sockets().at(3)).endswith("— (exited) [9999]") and m.describe(m.sockets().at(4)) == "udp 0.0.0.0:5353 open — (owner not visible)", [m.describe(m.sockets().at(i)) for i in (0, 3, 4)])
check("the sources and their states", [r.name for r in m.readings()] == ["connection tables", "dns cache"] and all(r.isOn() for r in m.readings()))

# a machine on which the resolver's cache cannot be read still joins everything else
def unsupported():
    raise g.Unsupported("net.dnsCache", "linux", "no cache")


g.DnsSys.cache = staticmethod(unsupported)
m2 = g.Machine()
m2.refresh()
check("no resolver cache: names stay addresses, and the reading says why", m2.describe(m2.sockets().at(1)) == "tcp 192.168.1.20:51000 → 93.184.216.34:443 established — editor [21]" and not m2.readings()[1].capable and m2.readings()[0].isOn())

print("all ok" if not fails else "FAILED: %s" % fails)
sys.exit(1 if fails else 0)
