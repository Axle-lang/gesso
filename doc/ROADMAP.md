# Roadmap

The order is the order of what has been proved. A slice is done when a real program uses it, not when it
is written.

| # | Slice | Needs | Proved by |
|---|---|---|---|
| 0 | **Foundations**: errors, privileges, support, plans, keys, time, units, UTF-16, `raw`, the checker and the translated tests | — | `test_core.py`, `check.py --selftest` |
| 1 | **`system` and `proc`**: host, memory, uptime; the process list and tree, image paths, priority, signals — *written, awaiting a compiler*; affinity, threads, environment — not yet | 0 | a program that lists processes on both |
| 2 | **`net`, reading**: interfaces, addresses, routes, the TCP/UDP tables with their owning process, traffic rates, the resolver's cache inverted, PTR and TXT, the network that announces an address, a live trace — *written; the polled tables run on Windows, the rest awaiting a machine*; statistics, ping — not yet | 1 (the owning process is an id, not a `proc` type) | **netaudit** drops its `src/sys/` and uses Gesso |
| 3 | **`net`, changing**: routes, interface configuration, behind `can…` and `plan…`; Wi-Fi and the firewall last | 2 | a program that shows the plan and applies it |
| 4 | **`fs`**: watchers (`ReadDirectoryChangesW`, inotify), volumes and free space, links, read-only and modes — *written, awaiting a compiler*; ACLs, ownership, subtree watching — not yet | 0 | a program that watches a folder |
| 5 | **`desk`**: revealing a file — *written*; notifications, clipboard, global hotkeys, other applications' windows, the session — not yet | 0 | a tray program |
| 6 | **`diag`**: the event log and the journal, performance counters, crash reports; the ETW reading netaudit declares and does not have | 1, 2 | netaudit's third badge lights |
| 6b | **`machine`**: the readings joined — a socket's process, a process's program, an address's name — *written* | 1, 2, 5 | **netaudit** loses its three joins |
| 7 | **macOS and Android** | 0–6 stable | a machine to run them on |

Why this order: slice 1 is what netaudit already does by hand and is the smallest that exercises both
ports. Slice 2 is the larger half of netaudit's `sys/`, and replacing it is the test that the Portable tier
is enough and the Advanced tier is reachable. Slices 4 and 5 are independent of the network and can be
taken whenever there is a program that needs them.
