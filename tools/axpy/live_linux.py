"""Live Linux smoke: the library's own parsers, run on this machine's real kernel files.

    python3 tools/axpy/live_linux.py

The seams that call libc cannot run here (they are Axle, and the translator leaves `sys/linux` out), but
everything they read is text, and the parsers of that text are portable code that the translator does run.
This feeds them what `/proc` and `/sys` actually hold on the machine it runs on — not a sample written by
hand — and checks that what comes out is sane: counts are not zero where they cannot be, every process has
a name, every socket has an address, the uptime agrees with the boot time. It is a smoke test, not a proof:
it shows the layout rules hold on a real kernel, not that the calls that fetch the text work.

It exits 0 when everything is sane, 1 with the first thing that is not, and 77 when it is not on Linux.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if not sys.platform.startswith("linux"):
    print("not Linux: nothing to read")
    sys.exit(77)

from axpy.run import load  # noqa: E402
from axpy.rt import _rt_lit  # noqa: E402

g = load()
fails = []


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" — " + str(extra) if extra else ""))
    if not cond:
        fails.append(name)


# --- sockets --------------------------------------------------------------------------------------------
total = 0
users = set()
for path, proto in [("/proc/net/tcp", g.Proto.Tcp), ("/proc/net/tcp6", g.Proto.Tcp), ("/proc/net/udp", g.Proto.Udp), ("/proc/net/udp6", g.Proto.Udp)]:
    text = read(path)
    if text is None:
        print("skip %s (not present)" % path)
        continue
    scan = g.SocketScan()
    g.NetText.sockets(text, proto, scan)
    rows = [l for l in text.splitlines()[1:] if l.strip()]
    check("%s: every row was read" % path, scan.table.size() == len(rows), (scan.table.size(), len(rows)))
    check("%s: an inode for each" % path, scan.inodes.size() == scan.table.size())
    for i in range(scan.table.size()):
        s = scan.table.at(i)
        users.add(s.uid)
        if s.local.text() == "" or s.uid < 0:
            check("%s: row %d has an address and a user" % (path, i), False, s.describe())
            break
    total += scan.table.size()
check("some sockets exist on a running machine", total > 0, total)
check("the user of each socket was read", len(users) > 0 and min(users) >= 0, sorted(users)[:5])

# --- routes ---------------------------------------------------------------------------------------------
rt = g.RouteTable()
r4 = read("/proc/net/route")
if r4 is not None:
    g.NetText.routes4(r4, rt)
r6 = read("/proc/net/ipv6_route")
if r6 is not None:
    g.NetText.routes6(r6, rt)
print("     %d routes" % rt.size())
check("every route has an interface name and a prefix inside its family's width", all(rt.at(i).ifName != "" and 0 <= rt.at(i).prefix <= (32 if rt.at(i).dest.family == 4 else 128) for i in range(rt.size())))

# --- interfaces' counters -----------------------------------------------------------------------------
dev = read("/proc/net/dev")
rows = g.NetText.devRows(dev) if dev else None
if rows is not None:
    names = [rows.at(i).name for i in range(rows.size())]
    check("the interfaces in /proc/net/dev are all named", len(names) > 0 and all(names), names)
    check("their counters are not negative", all(rows.at(i).rx >= 0 and rows.at(i).tx >= 0 for i in range(rows.size())))
    sysnames = set(os.listdir("/sys/class/net")) if os.path.isdir("/sys/class/net") else set()
    check("they are the interfaces /sys/class/net lists", set(names) == sysnames, (sorted(names), sorted(sysnames)))

# --- mounts ---------------------------------------------------------------------------------------------
vt = g.VolumeTable()
g.MountText.parse(read("/proc/mounts") or "", False, vt)
allv = g.VolumeTable()
g.MountText.parse(read("/proc/mounts") or "", True, allv)
print("     %d volumes (%d with the virtual ones)" % (vt.size(), allv.size()))
check("the root is among them, and only storage is listed by default", any(vt.at(i).root == "/" for i in range(vt.size())) and vt.size() <= allv.size())
check("every path belongs to some volume", vt.holding("/") >= 0 and vt.holding("/usr/bin") >= 0)

# --- processor and memory --------------------------------------------------------------------------------
cpu = g.CpuTimes.parse(read("/proc/stat") or "")
check("the processor counters were read, and idle is not more than all", cpu.total > 0 and 0 <= cpu.idle <= cpu.total, (cpu.idle, cpu.total))
mem = g.MemText.parse(read("/proc/meminfo") or "")
check("memory: total and available, available not more than total", mem[0] > 0 and 0 < mem[1] <= mem[0], mem)

# --- processes ------------------------------------------------------------------------------------------
boot = g.ProcStat.bootSeconds(read("/proc/stat") or "")
check("the boot time is in the past, and agrees with the uptime", 0 < boot < time.time() and abs((time.time() - boot) - float(read("/proc/uptime").split()[0])) < 5, boot)
clock = _rt_lit(g.ProcClock, None, bootMillis=boot * 1000, tickMillis=1000 // os.sysconf("SC_CLK_TCK"), pageBytes=os.sysconf("SC_PAGE_SIZE"))
seen = 0
bad = []
names_ok = True
mine = None
for entry in os.listdir("/proc"):
    if not entry.isdigit():
        continue
    line = read("/proc/%s/stat" % entry)
    if not line:
        continue
    try:
        p = g.ProcStat.parse(line, clock)
    except g.Invalid as e:
        bad.append((entry, str(e)))
        continue
    seen += 1
    if p.pid != int(entry) or not p.name or p.threads < 1 or p.started <= 0 or p.parent < 0:
        bad.append((entry, p.pid, p.name, p.threads, p.started, p.parent))
    if p.pid == os.getpid():
        mine = p
check("every process's stat line was read with a name, threads, a start time and a parent", seen > 0 and not bad, bad[:3])
check("this process is among them, started a moment ago, and holds some memory", mine is not None and abs(time.time() * 1000 - mine.started) < 600000 and mine.memory > 0, mine and (mine.started, mine.memory))
tree = g.ProcTree([g.ProcStat.parse(read("/proc/%s/stat" % e), clock) for e in os.listdir("/proc") if e.isdigit() and read("/proc/%s/stat" % e)])
check("the tree lays out every process once", tree.size() >= seen - 5 and tree.rootCount() >= 1, (tree.size(), seen, tree.rootCount()))

# --- socket inodes ------------------------------------------------------------------------------------
links = 0
for entry in os.listdir("/proc/self/fd"):
    try:
        target = os.readlink("/proc/self/fd/" + entry)
    except OSError:
        continue
    if target.startswith("socket:["):
        links += 1
        check("a socket link names its inode", g.NetText.socketInode(target) == int(target[8:-1]))
        break
print("     %d processes, %d sockets" % (seen, total))
print("all sane" if not fails else "NOT SANE: %s" % fails)
sys.exit(1 if fails else 0)
