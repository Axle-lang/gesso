"""run.py — translate gesso's sources to Python and load them as one module.

    python3 tools/axpy/run.py --dump out.py     write the translation
    from axpy.run import load; g = load()       the module, for the tests

What is translated is what can be run without an operating system: `core`, the portable seams'
pure parts (`sys/errno`) and the API modules. The directories that touch the machine — `raw`, and
the ports under `sys` — are left out, and each seam a module needs is answered instead by a fake
in `tools/axpy/fakes/` with the same public shape, which `tools/check.py` holds the ports to.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.dirname(HERE)
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)

from axparse import parse  # noqa: E402
from axpy.emit import Emitter  # noqa: E402

LEFT_OUT = ("raw", "win32", "linux")


def sources():
    out = []
    base = os.path.join(ROOT, "src")
    for dp, _, names in os.walk(base):
        parts = os.path.relpath(dp, base).split(os.sep)
        if any(p in LEFT_OUT for p in parts):
            continue
        for n in sorted(names):
            if n.endswith(".axle") and n != "lib.axle":
                out.append(os.path.join(dp, n))
    for n in sorted(os.listdir(os.path.join(HERE, "fakes"))):
        if n.endswith(".axle"):
            out.append(os.path.join(HERE, "fakes", n))
    return sorted(out)


def translate():
    em = Emitter()
    for p in sources():
        em.add_file(parse(open(p, encoding="utf-8").read()))
    return em.emit()


def load():
    import types
    mod = types.ModuleType("gesso")
    exec(compile(translate(), "<gesso>", "exec"), mod.__dict__)
    return mod


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--dump":
        open(sys.argv[2], "w").write(translate())
    else:
        load()
        print("loaded")
