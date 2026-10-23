"""Processes as data: the index and the tree, run through the translated source."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from axpy.run import load  # noqa: E402
from axpy.rt import _rt_lit  # noqa: E402

g = load()
fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + str(extra) if extra and not cond else ""))
    if not cond:
        fails.append(name)


def proc(pid, parent, name, started=0):
    return g.ProcInfo(pid, parent, name, 1, started, 1000)


# --- PidIndex --------------------------------------------------------------------------------
ix = g.PidIndex(200)
for n in range(200):
    ix.put(n * 7919, n)
check("every id put is found again, at its capacity", all(ix.get(n * 7919) == n for n in range(200)))
check("an id never put answers -1", ix.get(5) == -1 and ix.get(123456789) == -1)
ix.put(7919, 999)
check("a second put replaces the first", ix.get(7919) == 999)
check("id 0 is a valid key", g.PidIndex(1).get(0) == -1)
z = g.PidIndex(1)
z.put(0, 3)
check("and is found once put", z.get(0) == 3)

# --- ProcInfo --------------------------------------------------------------------------------
a, b = proc(10, 1, "x", 100), proc(10, 1, "x", 200)
check("a reused id is another key", a.key != b.key and a.key == proc(10, 1, "x", 100).key)

# --- ProcTree --------------------------------------------------------------------------------
t = g.ProcTree([
    proc(1, 0, "init", 10),
    proc(2, 1, "a", 20),
    proc(3, 2, "a1", 30),
    proc(4, 1, "b", 40),
    proc(5, 2, "a2", 50),
    proc(6, 999, "orphan", 60),
    proc(7, 7, "self", 70),
])
order = [t.infoAt(r).pid for r in range(t.size())]
depth = [t.depthAt(r) for r in range(t.size())]
check("outline is depth first, children in list order", order == [1, 2, 3, 5, 4, 6, 7], order)
check("depths follow the shape", depth == [0, 1, 2, 2, 1, 0, 0], depth)
check("a missing parent and a self-parent make roots", t.rootCount() == 3 and t.parentPid(6) == -1 and t.parentPid(7) == -1)
check("parent and children", t.parentPid(3) == 2 and list(t.childrenOf(1)) == [2, 4] and list(t.childrenOf(3)) == [])
check("descendants in outline order", list(t.descendantsOf(1)) == [2, 3, 5, 4] and list(t.descendantsOf(2)) == [3, 5])
check("a leaf has no descendants, an unknown pid neither", list(t.descendantsOf(3)) == [] and list(t.descendantsOf(404)) == [])
check("ancestors, nearest first", list(t.ancestorsOf(5)) == [2, 1], list(t.ancestorsOf(5)))
check("rowOf", t.rowOf(4) == 4 and t.rowOf(404) == -1)

# A reused id: the "parent" 20 now belongs to a process younger than its supposed child.
r = g.ProcTree([proc(20, 1, "young", 900), proc(21, 20, "child", 100)])
check("a parent younger than its child is not its parent", r.parentPid(21) == -1 and r.rootCount() == 2)

# Cycles can only come from reused ids; the start times break them, and so must not hang.
c = g.ProcTree([proc(1, 2, "p", 0), proc(2, 1, "q", 0)])
check("a cycle with no start times still lays out every process", [c.infoAt(r).pid for r in range(2)] == [1, 2] and c.rootCount() == 1, [c.infoAt(r).pid for r in range(c.size())])

e = g.ProcTree([])
check("an empty list is an empty tree", e.size() == 0 and e.rootCount() == 0)

# --- ProcStat: lines as Linux writes them ------------------------------------------------------
BOOT, TICK, PAGE = 1700000000000, 10, 4096
CLOCK = _rt_lit(g.ProcClock, None, bootMillis=BOOT, tickMillis=TICK, pageBytes=PAGE)
line = "4120 (chrome) S 1 4120 4120 0 -1 4194560 100 0 5 0 30 12 0 0 20 0 11 0 1830442 2000000 25641 18446744073709551615"
p = g.ProcStat.parse(line, CLOCK)
check("pid, name, parent, threads", (p.pid, p.name, p.parent, p.threads) == (4120, "chrome", 1, 11), (p.pid, p.name, p.parent, p.threads))
check("start is boot plus ticks", p.started == BOOT + 1830442 * TICK and p.memory == 25641 * PAGE)
tricky = "77 (a) b (c d)) R 5 77 77 0 -1 0 0 0 0 0 0 0 0 0 20 0 3 0 99 0 10"
q = g.ProcStat.parse(tricky, CLOCK)
check("the name ends at the last parenthesis, spaces and parentheses inside", q.name == "a) b (c d)" and q.parent == 5 and q.threads == 3, (q.name, q.parent, q.threads))
u = g.ProcStat.parse("9 (café) S 1 9 9 0 -1 0 0 0 0 0 0 0 0 0 20 0 1 0 5 0 2", CLOCK)
check("a name with non-ASCII text survives", u.name == "café")
for bad, why in [("", "empty"), ("12 chrome S 1", "no parentheses"), ("(x) S 1", "no pid"), ("5 (x) S 1 2 3", "cut short"), ("5 (x) S a 2", "not numbers")]:
    try:
        g.ProcStat.parse(bad, CLOCK)
        check("a bad line is refused: " + why, False)
    except g.Invalid:
        check("a bad line is refused: " + why, True)

# --- Priority and Signal numbers -------------------------------------------------------------
P = g.Priority
check("nice values round-trip through the levels", all(P.fromNice(l.nice()) == l for l in [P.Idle, P.BelowNormal, P.Normal, P.AboveNormal, P.High]))
check("nice edges", P.fromNice(19) == P.Idle and P.fromNice(0) == P.Normal and P.fromNice(-20) == P.High and P.fromNice(-5) == P.AboveNormal and P.fromNice(4) == P.Normal and P.fromNice(5) == P.BelowNormal)
check("Windows classes round-trip", all(P.fromWinClass(l.winClass()) == l for l in [P.Idle, P.BelowNormal, P.Normal, P.AboveNormal, P.High, P.Realtime]))
check("an unknown class is normal", P.fromWinClass(0) == P.Normal)
check("the scale is the order", [P.at(n) for n in range(-1, 7)] == [P.Idle, P.Idle, P.BelowNormal, P.Normal, P.AboveNormal, P.High, P.Realtime, P.Realtime])
S = g.Signal
check("signal numbers are POSIX's", (S.Interrupt.posix(), S.Terminate.posix(), S.Kill.posix(), S.Hangup.posix(), S.Stop.posix(), S.Resume.posix()) == (2, 15, 9, 1, 19, 18))
stat = "cpu  1 2 3\ncpu0 1 2 3\nbtime 1700000123\nprocesses 99\n"
check("btime is found at the start of a line", g.ProcStat.bootSeconds(stat) == 1700000123)
check("a line that merely ends in btime is not it", g.ProcStat.bootSeconds("xbtime 5\n") == -1 and g.ProcStat.bootSeconds("") == -1)
check("btime at the very end of the text", g.ProcStat.bootSeconds("btime 42") == 42)

# --- Procs, over the fake machine ------------------------------------------------------------
def thrown(fn):
    try:
        fn()
    except Exception as e:
        return e
    return None


names = [i.name for i in g.Procs.list()]
check("the list is the seam's", names == ["init", "Shell", "editor", "Editor", "orphan"], names)
tree = g.Procs.tree()
check("the tree has the shape of the list", tree.rootCount() == 2 and list(tree.descendantsOf(1)) == [20, 21, 22])
check("get finds one", g.Procs.get(21).name == "editor" and isinstance(thrown(lambda: g.Procs.get(99)), g.Absent))
check("find ignores case and returns every match", [i.pid for i in g.Procs.find("EDITOR")] == [21, 22] and len(g.Procs.find("nothing")) == 0)
check("a gone process is Gone, not a silent default", isinstance(thrown(lambda: g.Procs.imagePath(99)), g.Gone) and g.Procs.imagePath(21) == "/usr/bin/editor")
check("priority reads through", g.Procs.priority(21) == P.High)

# What can be said before trying depends on the platform; the fake host is "testos", which is neither.
check("real time needs an elevated session off Linux", g.Procs.canSetPriority(P.Realtime).state == g.SupportState.NeedsPrivilege and g.Procs.canSetPriority(P.Realtime).needs == g.Privilege.Elevated)
check("an ordinary level is unknown until tried", g.Procs.canSetPriority(P.Idle).state == g.SupportState.Unknown)
check("any signal is unknown here, not promised", g.Procs.canSignal(S.Kill).state == g.SupportState.Unknown)

plan = g.Procs.planSetPriority(21, P.Idle)
check("a plan says what it would do and how to put it back", plan.count() == 1 and "idle" in plan.whatAt(0) and plan.undoAt(0) == "set it back to high" and plan.reversible(), plan.describe())
check("a plan for a process that is gone promises no way back", not g.Procs.planSetPriority(99, P.Idle).reversible())
check("real time is an admin step", g.Procs.planSetPriority(21, P.Realtime).highest() == g.Access.Admin and g.Procs.planSetPriority(21, P.Realtime).needs() == g.Privilege.Elevated)
check("kill cannot be undone, stop can", not g.Procs.planSignal(21, S.Kill).reversible() and g.Procs.planSignal(21, S.Stop).reversible())
check("acting on a gone process raises Gone", isinstance(thrown(lambda: g.Procs.signal(99, S.Kill)), g.Gone) and isinstance(thrown(lambda: g.Procs.setPriority(99, P.Idle)), g.Gone))
check("acting on a live one succeeds", thrown(lambda: g.Procs.signal(21, S.Stop)) is None and thrown(lambda: g.Procs.setPriority(21, P.Idle)) is None)
check("same-folded text", g.Utf8.sameFolded("Chrome.EXE", "chrome.exe") and not g.Utf8.sameFolded("a", "ab") and not g.Utf8.sameFolded("a", "b"))

print("all ok" if not fails else "FAILED: %s" % fails)
sys.exit(1 if fails else 0)
