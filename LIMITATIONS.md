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
  `/proc/stat` and `/proc/<pid>/stat` were read by the Axle parsers, on files taken from that machine, and
  read what the files hold.

What stays unrun on Linux is every `extern "C"` call itself, and so the errno handling, the `inotify`
descriptor and the walk of `/proc/<pid>/fd`.

What stands in for the compiler on the rest is the test program in `tests/` (Axle, like the library), and each claim below says which suite backs it. `axle check` and `axle fmt --check` hold the grammar, the names and the layout.

| Claim | Backed by | How far |
|---|---|---|
| The vocabulary does what it says: errors, privileges, support, plans, keys, spans, UTF-16, the errno tables, text scanning (`Scan`), lists, and `Host` on the real machine | `tests/src/core_vocab.axle`, `units.axle` | `core`, `sys/errno`, `raw` |
| Network as data: addresses (parse, print, kinds, subnets), sockets and their narrowing, interfaces, routes with longest-prefix lookup, traffic rates, and the parsers of `/proc/net/{tcp,tcp6,udp,udp6,route,ipv6_route,dev}` on real lines | `tests/src/net.axle`, `net_parse.axle` | `core/netaddr`, `core/netinfo`, `core/netparse`, `core/addrtext`, `net` |
| Processor load (between readings, counters that go back, unreadable lines), the `/proc/stat` line, battery words and `PowerInfo` | `tests/src/system.axle` | `core/sysinfo`, `system` |
| Files as data: path joining, the kind a mode says, mode text, mount-table parsing and volume kinds, which volume holds a path, space, entry lists, the change queue; and `Fs` (stat, list, tree size, links, watcher) on a scratch folder of the real disk | `tests/src/fs.axle` | `core/fsinfo`, `core/fsparse`, `core/fswatch`, `fs` |
| DNS and the trace as data: the reverse-zone names, a DNS message read as bytes (PTR, TXT, compressed names, a name that points at itself, a refused or cut answer), Team Cymru's names and answers, the resolver's cache inverted, the payloads of Kernel-Network and DNS-Client events and the running counts | `tests/src/dns.axle`, `trace.axle` | `core/dnswire`, `core/dnsinfo`, `core/asinfo`, `core/trace`, `net/dnsreader`, `net/nettrace` |
| Processes as data: the id index, the tree (orphans, reused ids, loops of parents), the parsing of `/proc/<pid>/stat` and `btime`, the priority and signal numbers, and the process list of the real machine | `tests/src/proc.axle` | `core/process`, `core/procstat`, `core/index`, `proc` |
| The desk and the join: the reveal refusals, image paths and their cache, and the join of sockets, processes and names on the real machine | `tests/src/desk.axle`, `machine.axle` | `desk`, `proc/imagepaths`, `machine` |

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
- **DNS.** The cache reader (`DnsGetCacheDataTable`, `DnsQuery_W` with `DNS_QUERY_NO_WIRE_QUERY`) and the record
  offsets it uses are netaudit's, which reads them in production; the same records are walked here for PTR
  and TXT, whose data offsets (a PTR's target at 32, a TXT's count at 32 and strings from 40) are from the
  header and were not run. On Linux `res_query` is called through `libresolv` (in libc since glibc 2.34; the
  symbol exists there, and `h_errno` was read with a throwaway call), and the answer is read by
  `core/dnswire`, which is tested on messages built by hand but not on a real server's.
- **The live trace has never run.** `EVENT_TRACE_PROPERTIES`, `EVENT_TRACE_LOGFILEW` (offsets 8, 28, 416, 432),
  `EVENT_RECORD` (12, 40, 86, 96, 104), the two provider GUIDs, the event ids and the payload layouts of
  Microsoft-Windows-Kernel-Network and DNS-Client are written from the headers and the manifests as the
  author knows them. One assumption is named in the source: that a *receive* event names this machine as its
  destination, so that local and remote are the other way round from a send. If a real trace says
  otherwise, `KernelNet::destinationIsLocal` is the one place to change. The ring between the callback's
  thread and the reader has no barrier, which is sound on the x86-64 targets and nowhere else. The
  callback is passed as a function pointer (`Raw::callback`, a cast), and the session's reader is a
  spawned task whose result is awaited on `stop`; neither has met the compiler on a library.
- `ShellExecuteW` with `explorer.exe /select,"…"`, and `xdg-open` through `ProcessBuilder`, have not run.
- `CreateSymbolicLinkW` answers a `BOOLEAN`, of which only the low byte is read.
- `GetSystemPowerStatus` (offsets 0, 1, 2, 4), on a machine with a battery: the one it was run on has none.
- Everything under `src/raw/` and `src/sys/<port>/` by the tests: Axle has no way to put a fake behind a seam, so
  the checks of the portable logic feed it rows built by hand, and the rest run on the machine that runs them. A test passing says what the portable code does with
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
- **Network, reading only.** IPv6 routes are not listed on Windows (`GetIpForwardTable2` hands back a table that must be freed with a call this slice does not make). The owner of a Linux socket is visible for the caller's own processes, and for all of them from an elevated session; the rest read `pid` -1 but keep the `uid` of their user, which `/proc/net/tcp` gives for every socket, and stay in the table: `withoutOwner()` takes them, `unowned()` counts them, and `Net::socketsStatus` reports the table as *partial* with the reason. A display must show them, with their user, and not drop them for want of a process. A Linux route has no interface number (`ifIndex` 0), only a name. DNS cache, statistics and ping are not in this slice.
- **Files.** The watcher sees the entries of one folder, not those below it. The standard library's own file calls are not wrapped: use `Path` for reading, writing, renaming and deleting. There is no ACL or ownership reading yet, and Windows has no permission bits (`setMode` raises `Unsupported`; `setReadOnly` works on both). A Linux volume's label is not read (empty), nor whether it is removable.
- **DNS and the trace.** The resolver's cache is not readable on Linux (`Unsupported`, naming why): a plain
  glibc system keeps none, and `systemd-resolved` keeps one behind D-Bus. A reverse or TXT lookup goes to the
  network and can take seconds. The trace is Windows only (`Unsupported` on Linux, where per-process byte
  counts need eBPF), needs an elevated session, and keeps up to 1,000 bytes of each event, so a DNS answer
  longer than that is read as no event. Of an event's two ends the library trusts the provider's naming
  (above); of UDP it knows only what the provider reports.
- **Revealing a file.** Windows selects the file in Explorer. Linux asks the file manager to select it over D-Bus
  (`org.freedesktop.FileManager1.ShowItems`, through `dbus-send`), and where nothing answers opens the folder
  with `xdg-open`; it says `Unsupported` only where neither exists. A path with a quote in it,
  or longer than 1,000 UTF-16 units, is refused rather than passed on cut.
- **No async.** Watchers block for up to a time they are given (`Watch::wait`); a program that wants
  them off its main thread runs them on its own.

## 3. What the language costs

- **A `catch` by a subclass inside a function that holds owned objects can corrupt the heap** (§531 of the Axle roadmap). In Axle 0.20, a function with a
  live owned local (an `EntryList`, say) that calls something throwing a subclass and catches that subclass leaves
  with exit code 0xC0000374. Moving the `try`/`catch` into a function of its own, with nothing owned alive, is
  safe: `Attrs::linkFlags` and the test helper `fsIsNotALink` are written that way for this reason.
- **Struct field order is not C's.** The compiler may permute the fields of a `struct` and has no
  `repr(C)`, so an operating-system record is never an Axle aggregate: it is read as `base + offset`
  through `Raw` or `Buf`, with the offsets written down beside the code that knows the record.
- **`unsafe` is per-function** (E0707), which is what makes confining it to `src/raw/` something
  compiler can hold.
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
- **A `Values<string>` grown in place is unsafe.** `Values.add` doubles the array by moving each string into a
  bigger one; the old array then releases the strings it appears to still own, and the heap is corrupted (the
  Linux `/proc` listing crashed on the first real run because of it). The library pre-sizes every string-valued
  `Values` — a folder's names, image paths and their reasons — and grows only the numeric ones. Fixing this at
  the language level is the real answer; until then a caller appending strings must size the sequence up front.
- **The compiler does not build a library by itself** and does not check a name against its imports.
