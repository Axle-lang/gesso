"""The portable parts of gesso, run through the translated source: no operating system behind them."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from axpy.run import load  # noqa: E402
from axpy import rt  # noqa: E402

g = load()
fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + str(extra) if extra and not cond else ""))
    if not cond:
        fails.append(name)


def raises(kind, fn):
    try:
        fn()
    except kind as e:
        return e
    except Exception as e:  # a different failure is not the one asked for
        return None
    return None


def thrown(fn):
    """The exception `fn` raises, or None."""
    try:
        fn()
    except Exception as e:
        return e
    return None


# --- Privilege and access ---------------------------------------------------------------------
U, E, S = g.Privilege.User, g.Privilege.Elevated, g.Privilege.System
check("an elevated session covers a user's operation", E.covers(U) and S.covers(E) and not U.covers(E))
check("an admin operation needs an elevated session", g.Access.Admin.needs() == E and g.Access.Read.needs() == U and g.Access.Change.needs() == U)
check("labels read as words", g.Access.Admin.label() == "admin" and "administrator" in E.label())

# --- Errors ----------------------------------------------------------------------------------
d = g.Denied("net.addRoute", "10.0.0.0/8", E, 5)
check("Denied names the operation, the object and the privilege", "net.addRoute" in d.message and "10.0.0.0/8" in d.message and "administrator" in d.message, d.message)
check("Denied is a SysError is an IOException", isinstance(d, g.SysError) and isinstance(d, rt.IOException))
check("Denied keeps what a caller acts on", d.needs == E and d.code == 5 and d.what == "10.0.0.0/8" and d.op == "net.addRoute")
check("Unsupported says where", "linux" in g.Unsupported("fs.acl", "linux", "ACLs").message)
check("Gone and Busy say what", "4120" in g.Gone("proc.read", "process 4120").message and "in use" in g.Busy("fs.lock", "a.txt").message)
check("Expired says how long", "250" in g.Expired("net.ping", 250).message)
check("OsFailure carries the code and the name", "4" in g.OsFailure("x", 4, "EINTR").message and "EINTR" in g.OsFailure("x", 4, "EINTR").message)

# --- Errno -----------------------------------------------------------------------------------
check("Windows access denied is Denied needing an administrator", isinstance(thrown(lambda: g.Errno.win32("proc.open", "pid 4", 5)), g.Denied))
check("a missing privilege is Denied too", isinstance(thrown(lambda: g.Errno.win32("proc.open", "pid 4", 1314)), g.Denied))
check("file not found is Gone", isinstance(thrown(lambda: g.Errno.win32("fs.open", "a", 2)), g.Gone))
check("a sharing violation is Busy", isinstance(thrown(lambda: g.Errno.win32("fs.open", "a", 32)), g.Busy))
check("an invalid parameter is Invalid", isinstance(thrown(lambda: g.Errno.win32("proc.open", "pid", 87)), g.Invalid))
check("a timeout is Expired", isinstance(thrown(lambda: g.Errno.win32("net.dns", "x", 1460)), g.Expired))
check("an unknown Windows code is OsFailure with its name", isinstance(thrown(lambda: g.Errno.win32("x", "y", 997)), g.OsFailure) and "ERROR_IO_PENDING" in thrown(lambda: g.Errno.win32("x", "y", 997)).message)
check("EPERM is Denied, ESRCH is Gone, EBUSY is Busy", isinstance(thrown(lambda: g.Errno.posix("a", "b", 1)), g.Denied) and isinstance(thrown(lambda: g.Errno.posix("a", "b", 3)), g.Gone) and isinstance(thrown(lambda: g.Errno.posix("a", "b", 16)), g.Busy))
check("ENOSYS is Unsupported on linux", "linux" in thrown(lambda: g.Errno.posix("a", "b", 38)).message)
check("ECONNREFUSED keeps its name", "ECONNREFUSED" in thrown(lambda: g.Errno.posix("a", "b", 111)).message)

# --- Guard -----------------------------------------------------------------------------------
check("a guard lets an enough privilege through", raises(g.Denied, lambda: g.Guard.require(E, E, "x", "y")) is None)
e = raises(g.Denied, lambda: g.Guard.require(U, E, "proc.setAffinity", "process 4120"))
check("a guard refuses an ordinary user, naming what was needed", e is not None and e.needs == E and "process 4120" in e.message)

# --- Support ---------------------------------------------------------------------------------
check("yes is usable by anyone", g.Support.yes().usableBy(U))
w = g.Support.withPrivilege(E, "changes the routing table")
check("a privileged operation is usable only with it", not w.usableBy(U) and w.usableBy(E) and w.usableBy(S))
check("unsupported is never usable", not g.Support.unsupported("no such thing").usableBy(S))
check("unknown says try it", g.Support.unknown("depends on the process").usableBy(U))
check("explain gives the reason", "routing table" in w.explain() and w.explain().startswith("needs "))
cap = g.Capability("net", "addRoute", g.Access.Admin) if False else rt._rt_lit(g.Capability, None, module="net", name="addRoute", access=g.Access.Admin)
check("a capability is spelled module.name", cap.label() == "net.addRoute")

# --- Plan ------------------------------------------------------------------------------------
plan = g.Plan("proc.setPriority")
plan.add(g.PlanStep("set the priority of process 4120 to below normal", g.Access.Change, "set it back to normal"))
plan.note(g.Access.Admin, "raise the priority class of process 4 to real time")
check("a plan counts its steps", plan.count() == 2)
check("a plan's weight is its heaviest step", plan.highest() == g.Access.Admin and plan.needs() == E)
check("a plan with a step that cannot be undone is not reversible", not plan.reversible())
text = plan.describe()
check("a plan describes itself, one numbered line a step", text.startswith("proc.setPriority:") and "1. [change]" in text and "2. [admin]" in text and "undo: set it back" in text, text)
big = g.Plan("many")
for i in range(40):
    big.note(g.Access.Read, "step %d" % i)
check("a plan grows past its first room", big.count() == 40 and big.whatAt(39) == "step 39")
check("a read-only plan is reversible and needs nothing", big.reversible() and big.needs() == U)

# --- Keys ------------------------------------------------------------------------------------
check("a key is never negative", g.Key.ofText("chrome.exe") >= 0 and g.Key.pair(1, 2) >= 0)
check("the same text is the same key, another text another", g.Key.ofText("a") == g.Key.ofText("a") and g.Key.ofText("a") != g.Key.ofText("b"))
check("scoping separates kinds", g.Key.scoped("pid", 4) != g.Key.scoped("port", 4))
check("order matters in a pair", g.Key.pair(1, 2) != g.Key.pair(2, 1))
check("a process id and its start time make a key", g.Key.named(4120, "chrome.exe") != g.Key.named(4121, "chrome.exe"))

# --- Clock and span --------------------------------------------------------------------------
check("the monotonic clock only goes forward", g.Clock.mono() <= g.Clock.mono())
check("spans convert", g.Span.seconds(2) == 2000000000 and g.Span.millis(5) == 5000000 and g.Span.toMillis(g.Span.minutes(1)) == 60000)
for ns, want in [(g.Span.millis(850), "850 ms"), (g.Span.seconds(8), "8 s"), (g.Span.minutes(3), "3 min"), (g.Span.minutes(120), "2 h"), (g.Span.minutes(60 * 24 * 5), "5 d")]:
    check("%r reads %r" % (ns, want), g.Span.human(ns) == want, g.Span.human(ns))
check("an age is never negative", g.Span.age(5, 9) == 0 and g.Span.age(9, 5) == 4)

# --- Units -----------------------------------------------------------------------------------
for n, want in [(0, "0 B"), (1023, "1023 B"), (1024, "1.0 KiB"), (1536, "1.5 KiB"), (3 * 1024 * 1024 + 209715, "3.2 MiB"), (16 * 1024 ** 3, "16.0 GiB"), (1024 * 1024 - 1, "1.0 MiB"), (1024 * 1024 * 1024 - 1, "1.0 GiB")]:
    check("%d bytes read %r" % (n, want), g.Bytes.human(n) == want, g.Bytes.human(n))
check("a rate says per second", g.Bytes.rate(2048) == "2.0 KiB/s")
check("a share of a whole", g.Percent.text(1, 3) == "33.3 %" and g.Percent.text(0, 0) == "0.0 %" and g.Percent.tenths(1, 1) == 1000)

# --- Text ------------------------------------------------------------------------------------
for s in ["", "svchost.exe", "naïve café", "日本語", "emoji \U0001F600 here", "aé\U0001F680z"]:
    units = g.Utf16.encode(s)
    n = g.Utf16.length(s)
    check("UTF-16 round-trips %r" % s, g.Utf16.decode(units, n) == s and n == len(s.encode("utf-16-le")) // 2, (n, g.Utf16.decode(units, n)))
check("a lone surrogate decodes to U+FFFD", g.Utf16.decode([0xD800, 65], 2) == "�A")
check("codepoints are counted, not bytes", g.Utf8.count("aé\U0001F600") == 3)

# --- Host, over a fixed fake host ----------------------------------------------------------------
g.sysinfo.hostname = lambda: "fixture"
g.sysinfo.username = lambda: "ada"
g.sysinfo.cpuCount = lambda: 8
info = g.Host.info()
check("the host reports what the seam and std say", info.os == "testos" and info.hostName == "fixture" and info.user == "ada" and info.cpus == 8 and info.privilege == U)
check("it knows its own process id", info.pid > 0)
mem = g.Host.memory()
check("memory is total less available", mem.total == 16000000000 and mem.used() == 12000000000 and mem.loadTenths() == 750)
check("uptime comes through", g.Host.uptimeMillis() == 90061000)

check("Host::require refuses an ordinary user for an admin operation", raises(g.Denied, lambda: g.Host.require(E, "proc.kill", "process 4")) is not None)
check("and lets an ordinary operation through", raises(g.Denied, lambda: g.Host.require(U, "proc.list", "all")) is None)

# --- List and Scan ----------------------------------------------------------------------------------
vals = g.Values()
for i in range(40):
    vals.add(i * 2)
check("a sequence of numbers grows and keeps its order", vals.size() == 40 and vals.at(0) == 0 and vals.at(39) == 78 and list(vals.toArray()) == [i * 2 for i in range(40)])
lst = g.List()
for i in range(40):
    lst.add(g.PlanStep("step %d" % i, g.Access.Read, ""))
lst.set(3, g.PlanStep("changed", g.Access.Read, ""))
copies = lst.toArray()
check("a list of rows grows by copying, keeps its order and sets in place", lst.size() == 40 and lst.at(0).what == "step 0" and lst.at(39).what == "step 39" and lst.at(3).what == "changed")
check("its array holds copies, not the rows themselves", len(copies) == 40 and copies[5] is not lst.at(5) and copies[5].what == "step 5")
TXT = "cpu  1 2 3\nbtime 99\n  spaced\tfields  7  \n"
check("eol finds the end of a line, or of the text", g.Scan.eol(TXT, 0) == 10 and g.Scan.eol("abc", 0) == 3 and g.Scan.eol("abc\n", 4) == 4)
row = g.Line.at(TXT, 0)
check("a line knows where it ends and where the next starts", row.end == 10 and row.next() == 11)
check("fields are blank-separated and counted from 0", row.field(1).text() == "1" and row.field(0).text() == "cpu" and not row.field(9).present() and row.field(9).text() == "")
check("a field reads as a number, or as nothing", row.field(2).dec() == 2 and row.field(0).dec() == -1 and row.field(9).dec() == -1 and g.Line.at("ff 10", 0).field(0).hex() == 255)
check("tabs and runs of blanks separate fields too", g.Line.at(TXT, 20).field(1).text() == "fields" and g.Line.at(TXT, 20).field(2).dec() == 7)
check("a field can be asked what it is", row.field(0).equals("cpu") and not row.field(0).equals("cp") and row.field(0).size() == 3 and row.field(3).lastByte() == 51)
check("dec reads digits, allows one leading minus, and refuses the rest", g.Scan.dec("-42", 0, 3) == -42 and g.Scan.dec("4x", 0, 2) == -1 and g.Scan.dec("-", 0, 1) == -1 and g.Scan.dec("", 0, 0) == -1)
check("hex reads up to sixteen digits", g.Scan.hex("0100007F", 0, 8) == 0x0100007F and g.Scan.hex("zz", 0, 2) == -1 and g.Scan.hex("00000000000000001", 0, 17) == -1)
check("number reads a short file", g.Scan.number("1500\n") == 1500 and g.Scan.number("-1\n") == -1 and g.Scan.number("up\n") == -1)
check("lineWith finds a line by its start, not by a tail", g.Scan.lineWith(TXT, "btime ") == 11 and g.Scan.lineWith("xbtime 5\n", "btime ") == -1 and g.Scan.lineWith(TXT, "nope") == -1)
check("a keyed line is read through its fields", g.Line.at(TXT, g.Scan.lineWith(TXT, "btime ")).field(1).dec() == 99)
check("startsAt and has", g.Scan.startsAt("socket:[1]", 0, "socket:") and not g.Scan.startsAt("so", 0, "socket") and g.Scan.has("a/virtual/b", "/virtual/") and g.Scan.has("abc", "") and not g.Scan.has("ab", "abc"))
check("digits", g.Scan.digit(ord("7")) == 7 and g.Scan.digit(ord("f")) == 15 and g.Scan.digit(ord("F")) == 15 and g.Scan.digit(ord("g")) == -1)

print("all ok" if not fails else "FAILED: %s" % fails)
sys.exit(1 if fails else 0)
