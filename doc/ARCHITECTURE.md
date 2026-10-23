# Architecture

## Layers

```
 core   →   raw   →   sys   →   system  proc  net  fs  desk  diag
 (vocabulary) (memory) (seams, one directory per port)   (the API modules)
```

A module imports from a layer below its own, or from its own, and from nothing above. The API modules —
the last six — share the top rank and never import one another: if `net` needs to say which process owns a
socket, it says a process id (a `core` type), not a `proc` type. `tools/check.py` holds this.

| Layer | Holds | May contain |
|---|---|---|
| `core` | errors, `Access`, `Privilege`, `Support`, `Plan`, keys, time, units, UTF-8/16, `Scan` (lines, fields, numbers), `List`, the `Watch` trait | no operating system, no memory access |
| `raw` | `Raw` (pointer reads and writes), `Buf` (owned, bounds-checked), `Wide` and `Narrow` (strings across the boundary) | **`unsafe`** — and nowhere else |
| `sys` | one *seam* per concern: `os`, `procsys`, later `ifaces`, … | **`extern "C"`** — and nowhere else |
| API | what a program calls | neither |

## Ports and seams

A seam is a module whose file is picked by the build's target. `src/sys/win32/os.axle` and
`src/sys/linux/os.axle` are both `crate::sys::os`; `axle.toml` says which directory goes with which
operating system. The rest of the library imports `crate::sys::os::Os` and does not know which one it got.

A seam is written to be answered alike by every port. The checker compares the public classes, functions
and signatures of every port of a seam, and a difference is an error:

```
port parity: `Os` differs between src/sys/linux/os.axle and src/sys/win32/os.axle: static fn name():string
```

Files that exist in one port only (`src/sys/win32/kernel32.axle`, `src/sys/linux/netproc.axle`) are that
port's own helpers: the imports of one library gathered in one place, because a name can be declared once
per package, and the code that only that port needs. A helper does not go in the seam's own class, even
private: any member of a seam class that the other port lacks is a difference the compiler refuses.

### What `std` already says

The standard library's `std::sys::sysinfo` answers the host's name and processor count on both
targets, and `Host` uses it rather than asking the system a second time. The `os` seam holds only what
`std` has no word for: the platform name, the process's privilege, and the uptime; the `syssys` seam adds the
memory, which `std` does not report on Windows. A seam is written for a gap, not for a concern.

### Writing a seam

1. The portable question first, as a class of `static` functions returning plain values or small tuples:
   `Os::memory() : (total: i64, available: i64) ! SysError`. Return what a caller needs, not what the
   system happens to give.
2. Each port answers it. The call, the buffer, the record offsets (as `const`s next to the code that
   knows the record), and — on failure — `throw Errno::win32(op, what, GetLastError())` or
   `Errno::posix(...)`, which sorts the number into the reason it means.
3. A fake in `tools/axpy/fakes/` with the same shape and fixed answers, so the API module above is tested
   without a machine.
4. The API module shapes the answer into a type a program wants (`HostInfo`, `MemoryInfo`).

## The three tiers

- **Portable** is `gesso::<module>`: what has the same meaning everywhere. A function is here only if a
  caller can use it without knowing the platform.
- **Advanced** is `gesso::<module>::win`, `::linux`: what one platform has. These live in the port
  directory, so they exist only on that target. A program that uses one is written for that target and says
  so in its own `axle.toml`, as netaudit does with `targets = ["x86_64-pc-windows-msvc"]`.
- **Raw** is `gesso::raw`, and is how an Advanced function is written and how a program writes one of its
  own: `Raw` reads and writes memory unchecked, `Buf` is the same with bounds, `Wide` and `Narrow` carry
  strings.

## Conventions

- **Snapshots are values.** A reading returns data — structs of numbers and strings — with an identity
  key (`core::ident`), never a handle into the system. A process that exits after it was listed is still in
  the list; asking it for more says `Gone`.
- **Identity is never an index.** Anything a program remembers between readings is remembered by key.
- **What changes is watched, not polled.** A watcher is a `Watch` (`core::watch`): `wait(timeoutMs)`, then
  the module's own `next()`. If the system dropped events the state is `Lost`, and the caller reads
  everything again; the watcher never guesses.
- **Buffers are asked for twice.** Listings are sized by asking and then read; `Buf::fit` grows the block
  when the system says it was short (`Errno::win32TooSmall`), and a reading retries until it fits.
- **Text crosses as `string`.** UTF-16 and NUL-terminated bytes are `raw`'s business and do not leak.
- **Units are SI or bytes.** Nanoseconds for spans, bytes for sizes, milliseconds since 1970 for wall time.
  Display forms (`Bytes::human`, `Span::human`) are separate.

## Adding an operation

1. Name its `Access`. If it changes the machine it is `Admin` and takes an elevated session.
2. If it changes anything, write its `plan…` twin first: what it would do, as a `Plan`.
3. Write the `can…` answer: `Support` — yes, with a privilege, no, or unknown.
4. Write the seam question, the ports, the fake, and the API function.
5. Test the API function over the fake: the success, each failure it can name, the guard.
6. Say in LIMITATIONS.md what has and has not been run.

## Style

- **Layout is the formatter's.** `axle fmt`, then `tools/wrap.py` for the import lists and comments it leaves
  long. No line is wider than 110 columns; `tools/check.py` refuses one.
- **A decision over a value is a `match`.** A chain of `if … else if` comparing one thing is a `match`, with
  `|` for arms that agree and ranges for numbers; early `return`s stay when each one is a different guard.
- **Four arguments or more are a struct.** `LinkInfo`, `ProcClock`, `RowLayout` and `DevRow` carry what a
  call would otherwise pass as a row of positional numbers; the call site names each field.
- **Break a long expression into named lets** before breaking it across lines: `let share = …;` reads
  better than a parenthesised ternary of concatenations.
- **A reading says itself.** The types a program prints have a `describe()` returning one line, so a program
  does not rebuild the same sentence.
- **A seam class holds the seam and nothing else.** Any member one port has and another lacks — public or
  not — is a build error, so a port's helpers live in a class of their own in a file of that port.
