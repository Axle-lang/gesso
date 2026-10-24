"""The desktop and the programs' paths, run through the translated source."""
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


def units(s):
    b = s.encode("utf-16-le")
    return [b[i] | (b[i + 1] << 8) for i in range(0, len(b), 2)]


# --- Desk::reveal ------------------------------------------------------------------------------
asked = []
g.DeskSys.reveal = staticmethod(lambda path: asked.append(list(path)))
D = g.Desk
check("a path is passed on as UTF-16 units", thrown(lambda: D.reveal("C:\\Program Files\\App\\app.exe")) is None and asked[-1] == units("C:\\Program Files\\App\\app.exe"))
check("a non-ASCII path survives", thrown(lambda: D.reveal("/home/zoé/日本語.txt")) is None and asked[-1] == units("/home/zoé/日本語.txt"))
check("units go through as they are, even an unpaired surrogate", thrown(lambda: D.revealUnits([0x43, 0x3A, 0x5C, 0xD800, 0x61])) is None and asked[-1] == [0x43, 0x3A, 0x5C, 0xD800, 0x61])
before = len(asked)
for bad, why in [("", "empty"), ('C:\\a"b', "a quote"), ("x" * 1001, "too long")]:
    e = thrown(lambda: D.reveal(bad))
    check("refused before the system is asked: " + why, isinstance(e, g.Invalid))
check("none of them reached the desktop", len(asked) == before)
check("a path of exactly the limit is passed on", thrown(lambda: D.reveal("y" * 1000)) is None)
check("a NUL in a path is refused", isinstance(thrown(lambda: D.revealUnits([65, 0, 66])), g.Invalid))


def gone(path):
    raise g.Gone("desk.reveal", "the path")


g.DeskSys.reveal = staticmethod(gone)
check("a path that is not there is Gone, from the system", isinstance(thrown(lambda: D.reveal("C:\\nope")), g.Gone))
check("revealing opens a window and changes nothing", D.revealAccess() == g.Access.Read and D.canReveal().state != g.SupportState.Unsupported)

# --- imagePaths: a batch, each with its own outcome ------------------------------------------------
P = g.Procs
res = P.imagePaths([1, 21, 30, 99, 22])
check("a batch keeps going past a refusal", res.size() == 5 and res.resolved() == 3, res.resolved())
check("each id has its path or its reason", res.pathOf(21) == "/usr/bin/editor" and res.pathOf(22) == "/usr/bin/éditor" and res.pathOf(30) == "" and "needs an elevated administrator" in res.whyAt(res.indexOf(30)) and "no longer exists" in res.whyAt(res.indexOf(99)))
check("order is the order asked", [res.pidAt(i) for i in range(5)] == [1, 21, 30, 99, 22])
check("an id never asked for is empty", res.pathOf(7) == "" and res.indexOf(7) == -1)
check("UTF-16 units of a path", list(P.imagePathUnits(22)) == units("/usr/bin/éditor") and list(P.imagePathUnits(21)) == units("/usr/bin/editor"))

# --- the cache ---------------------------------------------------------------------------------------
procs = P.list()
cache = g.ImagePathCache()
check("empty at first", cache.size() == 0 and not cache.knows(procs[2]))
calls = []
real = g.ProcSys.imagePath
g.ProcSys.imagePath = staticmethod(lambda pid: (calls.append(pid), real(pid))[1])
cache.resolveAll(procs)
check("every process was asked once", sorted(calls) == [1, 20, 21, 22, 30] and cache.size() == 5)
check("paths and reasons are remembered", cache.pathOf(procs[2]) == "/usr/bin/editor" and cache.why(procs[2]) == "" and cache.pathOf(procs[4]) == "" and "elevated" in cache.why(procs[4]))
cache.resolveAll(procs)
cache.pathOf(procs[0])
check("asking again asks the system nothing", len(calls) == 5)
reused = g.ProcInfo(21, 20, "editor", 8, 99999, 5)
check("a reused id with another start time is a miss", not cache.knows(reused) and cache.pathOf(reused) == "/usr/bin/editor" and len(calls) == 6 and cache.size() == 6)
many = g.ImagePathCache()
for i in range(1000):
    many.resolve(g.ProcInfo(i + 100, 1, "p", 1, i, 0))
check("it grows past its first room and still finds them", many.size() == 1000 and many.knows(g.ProcInfo(600, 1, "p", 1, 500, 0)) and not many.knows(g.ProcInfo(600, 1, "p", 1, 501, 0)))
cache.clear()
check("clearing makes it ask again", cache.size() == 0 and not cache.knows(procs[2]) and cache.pathOf(procs[2]) == "/usr/bin/editor")
g.ProcSys.imagePath = real

# --- file URIs, for the Linux file manager ---------------------------------------------------------------
U = g.FileUri
check("a plain path", U.encode("/home/me/a.txt") == "file:///home/me/a.txt")
check("spaces and punctuation are encoded", U.encode("/home/me/a b#c%d.txt") == "file:///home/me/a%20b%23c%25d.txt")
check("UTF-8 bytes are encoded one by one", U.encode("/home/zoé/日.txt") == "file:///home/zo%C3%A9/%E6%97%A5.txt", U.encode("/home/zoé/日.txt"))
check("the safe marks stay", U.encode("/a-b_c.d~e/f") == "file:///a-b_c.d~e/f")

print("all ok" if not fails else "FAILED: %s" % fails)
sys.exit(1 if fails else 0)
