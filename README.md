<div align="center">

# gesso

### What an operating system exposes — as one library for Axle

</div>

---

A program that watches a machine ends up writing the same bindings over and over: the process list, the
connection tables, the resolver's cache, the battery, the clipboard. Each one is a page of `extern "C"`,
a record whose offsets were read off a header, and an error number that means something different on
every platform.

**Gesso is that layer, written once.** It is named for the ground coat a painter lays on the panel
before any paint: the thing between the picture and the wood.

## Three tiers

A call is at one of three levels, and the level is in its path.

| Tier | Where | What it is |
|---|---|---|
| **Portable** | `gesso::proc`, `gesso::net`, … | the operations that mean the same thing on every port |
| **Advanced** | `gesso::proc::win`, `gesso::net::linux`, … | what one platform has and the others do not, exposed rather than hidden |
| **Raw** | `gesso::raw` | the pointers, the buffers, the UTF-16 — for the call Gesso does not wrap |

An Advanced function exists only in its port, so calling it on another target is a compile error, not a
silent no-op.

## Three kinds of operation

Every public operation says what it does to the machine, and refuses precisely when the system says no.

| Access | It… | Takes |
|---|---|---|
| `Read` | only looks | nothing |
| `Change` | changes what an ordinary user may change | nothing |
| `Admin` | changes the machine | an elevated session |

A refusal is never swallowed and never reduced to `false`: it is a `Denied` that names the operation, the
object and the privilege that was missing. Before trying, a program can ask — `can…` answers "yes", "yes,
with this privilege" or "not on this platform", and why. An operation that changes things has a twin that
returns a `Plan` of what it would do, before it does it. See [doc/CONTRACT.md](doc/CONTRACT.md).

## The modules

| Module | For | Status |
|---|---|---|
| `core` | errors, privileges, support, plans, keys, time, units, text scanning, lists, addresses, readings, watchers | compiled; the portable logic run through the translated tests |
| `raw` | memory, buffers, UTF-16 | compiled; run on Windows |
| `system` | host, memory, uptime, processor load, battery | run on Windows; Linux compiled, its parsers checked on real `/proc` text |
| `proc` | the process list and tree, image path, priority, signals | run on Windows (reading); Linux compiled and checked the same way |
| `net` | sockets with their owner, interfaces, routes, traffic rates | reading run on Windows; Linux compiled and checked the same way; changing the network is held back until the reading is proved |
| `fs` | volumes, free space, folder listing, links, read-only, folder watcher | listing, sizes, volumes and the folder watcher run on Windows; links and changes not yet run; Linux compiled |
| `desk` | notifications, clipboard, hotkeys, windows, the session | planned |
| `diag` | logs, events, crash reports, traces, counters | planned |

## A short tour

```axle
let tree : ProcTree = Procs::tree();                          // processes as the tree they are
let web : SocketTable = Net::sockets().ofPid(4120).external();  // what process 4120 says to the internet
let way : RouteInfo = Net::routeTo(Addr::parse("8.8.8.8"));   // "default via 192.168.1.1 dev eth0 metric 100"
let disk : SpaceInfo = Fs::space("/home");                    // used, free, available
let cpu : CpuMeter = CpuMeter::start();  …  cpu.update();     // load since the last update
```

Readings are copies, tables narrow into new tables (`listening()`, `ofPid()`, `external()`), and every
failure is a `SysError` that says what was attempted and why it was refused. `examples/probe` runs every
reading once and prints it: build it first on a new machine.

The order, and why, is in [doc/ROADMAP.md](doc/ROADMAP.md).

## Honest status

`axle build examples/probe` compiles the whole library for Windows and the probe runs on it: the host,
the process table and tree, the sockets with their owners, the interfaces and the volumes read as they
should. For Linux, `axle check --target x86_64-unknown-linux-gnu examples/probe` passes and the program
compiles to an object file, but it cannot be linked or run from Windows (the standard library that ships
is the Windows one). What stands in for a Linux run is a check of every libc constant and record offset
against the real headers, and the parsers run on real `/proc` text. Read [LIMITATIONS.md](LIMITATIONS.md)
for what that does and does not establish.

The compiler does not build a library on its own (`axle build` at the root says it needs a `main`), so the
library is built through the program that uses it. What stands in for a compiler on the rest is in
`tools/`: a parser written from the language's documentation, a checker for names, imports, layers and
ports (the compiler is lax about imports), and a translator that runs the portable code as Python.

```
python3 tools/check.py             # parse, resolve, layers, ports, the seam rules
python3 tools/check.py --selftest  # plant 25 faults; fail if one is accepted
python3 tools/gen_lib.py --check   # src/lib.axle names every module
axle fmt src examples tools/axpy/fakes && python3 tools/wrap.py   # the layout, then the long lists and comments
python3 tools/axpy/test_core.py    # the portable logic, run
python3 tools/axpy/test_proc.py    # processes
python3 tools/axpy/test_net.py     # addresses, sockets, interfaces, routes
python3 tools/axpy/test_fs.py      # files, volumes, the folder watcher's queue
python3 tools/axpy/test_system.py  # processor load, power
```

## Reading the source

[doc/ARCHITECTURE.md](doc/ARCHITECTURE.md) has the layers, the ports, how a seam is written, and how to add an
operation. The short version: `core` is vocabulary, `raw` is the only place with `unsafe`, `sys` is the only
place with `extern "C"` and has one directory per port, and the API modules sit on top and never see an
operating system.

## Building

```bash
git clone https://github.com/Axle-lang/gesso
```

Add it as a path dependency, as the other libraries here do:

```toml
[dependencies]
gesso = { path = "vendor/gesso" }
```

Axle 0.18. No SDK, no DLL: every OS library is named by the block that imports from it.

MIT.
