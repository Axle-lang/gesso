"""Memory, processor load and power, run through the translated source."""
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


MEMINFO = "MemTotal:       16318828 kB\nMemFree:         1000000 kB\nMemAvailable:    8000000 kB\nBuffers:           10 kB\n"
mem = g.MemText.parse(MEMINFO)
check("meminfo gives bytes", mem == (16318828 * 1024, 8000000 * 1024), mem)
check("a kernel that does not say has no reading", g.MemText.parse("MemTotal: 5 kB\n") == (5 * 1024, -1) and g.MemText.parse("") == (-1, -1))

STAT = "cpu  4705 150 1120 16250 520 0 30 0 0 0\ncpu0 2000 100 500 8000 200 0 10 0 0 0\nintr 12345\n"
t = g.CpuTimes.parse(STAT)
check("the first line is the total, idle counts iowait", t.idle == 16250 + 520 and t.total == 4705 + 150 + 1120 + 16250 + 520 + 30, (t.idle, t.total))
check("a text with no cpu line has no reading", g.CpuTimes.parse("intr 5\n").total == -1 and g.CpuTimes.parse("").total == -1 and g.CpuTimes.parse("cpu a b c\n").total == -1)

m = g.CpuLoad()
check("a meter that has seen nothing is not ready", not m.ready() and m.percent() == 0)
m.feed(g.CpuTimes(1000, 2000))
check("one reading is not enough", not m.ready())
m.feed(g.CpuTimes(1500, 3000))
check("load is the busy share of the interval", m.ready() and m.tenths() == 500 and m.percent() == 50, m.tenths())
m.feed(g.CpuTimes(1500, 3100))
check("fully busy", m.tenths() == 1000 and m.percent() == 100)
m.feed(g.CpuTimes(1600, 3200))
check("fully idle", m.tenths() == 0)
m.feed(g.CpuTimes(1600, 3200))
check("no ticks between readings keeps the last answer", m.tenths() == 0)
m.feed(g.CpuTimes(10, 20))
check("counters that went back are no measurement", m.tenths() == 0)
m.feed(g.CpuTimes(-1, -1))
check("an unreadable reading is ignored", m.ready())
m2 = g.CpuLoad()
m2.feed(g.CpuTimes(0, 100))
m2.feed(g.CpuTimes(1, 1001))
check("percent rounds", m2.tenths() == 998 and m2.percent() == 100)

c = g.CpuMeter.start()
check("a started meter is not ready until updated", not c.ready())
c.update()
check("the fake counters do not move, so the first update keeps 0", c.percent() == 0)

p = g.Power.now()
check("power reads through", p.hasBattery() and p.percent == 78 and not p.pluggedIn() and p.describe() == "78% · on battery · 3 h 12 min left", p.describe())
check("a machine with no battery says so", g.PowerInfo.none(g.Mains.Online).describe() == "plugged in" and not g.PowerInfo.none(g.Mains.Online).hasBattery() and g.PowerInfo.none(g.Mains.Offline).describe() == "no battery")
B = g.BatteryState
check("Windows mains words", g.Mains.fromWindows(1) == g.Mains.Online and g.Mains.fromWindows(0) == g.Mains.Offline and g.Mains.fromWindows(255) == g.Mains.Unknown)
check("Linux status words", B.fromLinux("Charging") == B.Charging and B.fromLinux("Discharging") == B.Discharging and B.fromLinux("Not charging") == B.Full and B.fromLinux("???") == B.Unknown)

print("all ok" if not fails else "FAILED: %s" % fails)
sys.exit(1 if fails else 0)
