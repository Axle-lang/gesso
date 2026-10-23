# Limitations

What Gesso does not do, what it has not been shown to do, and what is only claimed. Three sections,
because the three have different answers.

---

## 1. What is verified, and how far

**Windows.** `axle build examples/probe` compiles the library and the probe runs: host, memory, uptime,
processor load, power, the process table and its tree, the sockets with their owners, the interfaces with
their counters, the routes, the drives and their room, a folder and its tree. The folder watcher was run by
hand (a file created while it waited arrived as `created`). That is a run on one machine, once; it shows the
record offsets read there are right, not that every field of every record is.

**Linux.** `axle check --target x86_64-unknown-linux-gnu examples/probe` passes and the program compiles to an
object file. It could not be linked or run: the standard library that ships with the compiler is the Windows
one. In its place:

- every constant and record offset in `src/sys/linux/libc.axle` (`struct statx`, `statvfs`, `sysinfo`,
  `dirent`, `ifaddrs`, `sockaddr_in`, `inotify_event`, `pollfd`, the flags) was compared with a C program
  built against the real headers on Ubuntu (WSL), and all of them agree;
- the parsers of `/proc/net/{tcp,tcp6,udp,udp6,route,ipv6_route,dev}`, `/proc/mounts`, `/proc/meminfo`,
  `/proc/stat` and `/proc/<pid>/stat` were run, translated to Python, on files taken from that machine, and
  read what the files hold.

What stays unrun on Linux is every `extern "C"` call itself, and so the errno handling, the `inotify`
descriptor and the walk of `/proc/<pid>/fd`.

What stands in for the compiler on the rest is in `tools/`, and each claim below says which of them backs it.

| Claim | Backed by | How far |
|---|---|---|
| Every file parses with the grammar of the language's documentation | `tools/axparse.py` (`check.py`) | the whole tree |
| Names resolve; imports are written (the compiler resolves a name from anywhere in the package, so only this notices a missing `use`); `let` bindings written to are `mut`; constructors, members and arities exist; matches are exhaustive; non-void functions return | `tools/axcheck.py` (`check.py`) | the whole tree. It is not a type checker: types and ownership are `axle check`'s |
| No layer imports upward, and the API modules do not import one another | `tools/check.py` | the whole tree |
| `extern "C"` appears only under `src/sys/<port>/`, `unsafe` only under `src/raw/` | `tools/check.py` | the whole tree |
| Every port answers each seam with the same public classes, functions and signatures | `tools/check.py` | every seam that has more than one port |
| The portable logic does what it says: errors, privileges, support, plans, keys, spans, units, UTF-16, the errno tables, text scanning (`Scan`), lists, `Host` over a fixed fake host | `tools/axpy/test_core.py` — the sources translated to Python and run | `core`, `sys/errno`, `system` |
| Network as data: addresses (parse, print, kinds, subnets), sockets and their narrowing, interfaces, routes with longest-prefix lookup, traffic rates, and the parsers of `/proc/net/{tcp,tcp6,udp,udp6,route,ipv6_route,dev}` on real lines | `tools/axpy/test_net.py` | `core/netaddr`, `core/netinfo`, `core/netparse`, `net` |
| Processor load (between readings, counters that go back, unreadable lines), the `/proc/stat` line, battery words and `PowerInfo` | `tools/axpy/test_system.py` | `core/sysinfo`, `system/cpu` |
| Files as data: path joining, the kind a mode says, mode text, mount-table parsing and volume kinds, which volume holds a path, space, entry lists, the change queue, and `Fs` (stat, list, tree size, links, watcher) over a fixed fake disk | `tools/axpy/test_fs.py` | `core/fsinfo`, `core/fsparse`, `core/fswatch`, `fs` |
| Processes as data: the id index, the tree (orphans, reused ids, loops of parents), the parsing of `/proc/<pid>/stat` and `btime`, the priority and signal numbers, and `Procs` over a fixed fake machine | `tools/axpy/test_proc.py` | `core/process`, `core/procstat`, `core/index`, `proc` |
| The checker rejects what it should | `tools/check.py --selftest` plants each fault | 25 faults |

**Not established:**

- That any Linux operating-system call works. The signatures were written from the documentation of each
  call, and the offsets checked against the headers; nothing was run. `statx` needs glibc 2.28 or later.
  `open` is variadic in C and is called with two arguments through the foreign interface, which is safe
  for a read-only open on x86-64 System V.
- That every Windows record field is right. The ones the probe prints are; the rest are not shown. Of
  `SYSTEM_PROCESS_INFORMATION` the id, the parent id, the thread count, the creation time, the name and the
  working set are exercised; of `IP_ADAPTER_ADDRESSES` the name, friendly name, MAC, addresses, type and
  status; of `MIB_IF_ROW2` the counters. The adapter speed and MTU, `WIN32_FILE_ATTRIBUTE_DATA` times,
  the reparse buffer (`FSCTL_GET_REPARSE_POINT`), `FILE_NOTIFY_INFORMATION` and `OVERLAPPED` are from the
  header's layout and were not run (links and `readLink`, the read-only flag, and the watcher's lost-events
  path). A wrong offset reads the wrong bytes without any error.
- `CreateSymbolicLinkW` answers a `BOOLEAN`, of which only the low byte is read.
- `GetSystemPowerStatus` (offsets 0, 1, 2, 4), on a machine with a battery: the one it was run on has none.
- Everything under `src/raw/` and `src/sys/<port>/` by the translated tests: they leave those out and
  answer each seam with a fake (`tools/axpy/fakes/`). A test passing says what the portable code does with
  an answer, not that a machine gives that answer.

## 2. The library's own scope

- **Two targets.** Windows (x86-64) and Linux (x86-64, glibc). macOS and Android are not served:
  there is nothing to test them on. A port is a directory of files answering the seams; adding one
  does not touch anything else.
- **Linux has no "system account".** `Privilege::System` is never answered there. A process holding
  some of root's capabilities without being root reads as an ordinary user, which understates it.
- **A privilege check is a courtesy.** `Host::require` and `Guard` refuse early from what the process
  knows about itself; the system still decides. A call that passes can be refused, and is reported as
  `Denied` the same way.
- **Windows privilege is read from the token.** An administrator who has not elevated reads as an
  ordinary user, which is the truth about what the process may do.
- **Linux process changes.** `Priority::Realtime` cannot be *set* on Linux (it is a scheduling policy,
  `SCHED_FIFO`, not a nice value) and is raised as `Unsupported`; it can be *read*. Process affinity and
  per-thread listing are not in this slice.
- **Network, reading only.** IPv6 routes are not listed on Windows (`GetIpForwardTable2` hands back a table that must be freed with a call this slice does not make). The owner of a Linux socket is visible for the caller's own processes, and for all of them from an elevated session; the rest read `pid` -1 and are counted by `SocketTable::unowned()`. A Linux route has no interface number (`ifIndex` 0), only a name. DNS cache, statistics and ping are not in this slice.
- **Files.** The watcher sees the entries of one folder, not those below it. The standard library's own file calls are not wrapped: use `Path` for reading, writing, renaming and deleting. There is no ACL or ownership reading yet, and Windows has no permission bits (`setMode` raises `Unsupported`; `setReadOnly` works on both). A Linux volume's label is not read (empty), nor whether it is removable.
- **No async.** Watchers block for up to a time they are given (`Watch::wait`); a program that wants
  them off its main thread runs them on its own.

## 3. What the language costs

- **Struct field order is not C's.** The compiler may permute the fields of a `struct` and has no
  `repr(C)`, so an operating-system record is never an Axle aggregate: it is read as `base + offset`
  through `Raw` or `Buf`, with the offsets written down beside the code that knows the record.
- **`unsafe` is per-function** (E0707), which is what makes confining it to `src/raw/` something the
  checker can hold.
- **A name is declared once per package.** A seam imported by two files cannot be re-declared in each,
  so the library's kernel32 imports are in one file (`src/sys/win32/kernel32.axle`) and its libc
  imports in another (`src/sys/linux/libc.axle`).
- **An array of objects cannot be grown by aliasing its elements.** Moving the rows into a bigger array
  leaves two arrays owning the same objects, and the program dies when the old one is released. The
  standard library's own collections refuse a class for an element (E0604) for this reason. `core/list`
  grows by calling `copy()` on each row, which is what its `Copy` bound asks of them; numbers and strings
  need nothing and go in a `Values`.
- **A lambda cannot capture an object** (E0731), only numbers and the like; the filters of `SocketTable`
  capture the number behind an enum, and `peerIs` is a loop for that reason.
- **The compiler does not build a library by itself** and does not check a name against its imports.
