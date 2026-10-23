"""Files and volumes as data, run through the translated source."""
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


# --- Mode ------------------------------------------------------------------------------------
check("modes read as rwx", g.Mode.text(0o755) == "rwxr-xr-x" and g.Mode.text(0o644) == "rw-r--r--" and g.Mode.text(0) == "---------" and g.Mode.text(0o777) == "rwxrwxrwx")
check("owner write", g.Mode.ownerWrites(0o644) and not g.Mode.ownerWrites(0o444))
check("withWrite sets and clears every write bit", g.Mode.withWrite(0o755, False) == 0o555 and g.Mode.withWrite(0o444, True) == 0o644 and g.Mode.withWrite(0o644, True) == 0o644)

# --- Mounts ------------------------------------------------------------------------------------
MOUNTS = """sysfs /sys sysfs rw,nosuid,nodev,noexec,relatime 0 0
proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0
/dev/nvme0n1p2 / ext4 rw,relatime 0 0
tmpfs /run tmpfs rw,nosuid,nodev,size=1618048k,mode=755 0 0
/dev/sda1 /media/user/My\\040Stick vfat rw,nosuid,nodev,relatime 0 0
server:/export /mnt/nas nfs4 rw,relatime 0 0
//host/share /mnt/win cifs rw 0 0
/dev/sr0 /media/cdrom iso9660 ro 0 0
/dev/loop3 /snap/core/1 squashfs ro 0 0
"""
vt = g.VolumeTable()
g.MountText.parse(MOUNTS, False, vt)
roots = [vt.at(i).root for i in range(vt.size())]
check("virtual mounts are left out by default", roots == ["/", "/run", "/media/user/My Stick", "/mnt/nas", "/mnt/win", "/media/cdrom"], roots)
kinds = [vt.at(i).kind for i in range(vt.size())]
K = g.VolumeKind
check("kinds", kinds == [K.Fixed, K.Ram, K.Fixed, K.Network, K.Network, K.Optical])
check("escapes in a mount point", vt.at(2).device == "/dev/sda1" and vt.at(2).fsType == "vfat")
every = g.VolumeTable()
g.MountText.parse(MOUNTS, True, every)
check("all=true keeps them", every.size() == 9)
check("title falls back to the root", vt.at(0).title() == "/")
check("unescape", g.MountText.unescape("a\\040b\\134c") == "a b\\c" and g.MountText.unescape("plain") == "plain" and g.MountText.unescape("end\\04") == "end\\04")
check("hidden names", g.MountText.isHidden(".bashrc") and not g.MountText.isHidden("a.txt") and not g.MountText.isHidden(".") and not g.MountText.isHidden(".."))

# --- Which volume holds a path -----------------------------------------------------------------
check("the longest root that holds it", vt.at(vt.holding("/media/user/My Stick/photos/a.jpg")).root == "/media/user/My Stick" and vt.at(vt.holding("/home/me")).root == "/")
check("a root is a folder boundary, not a prefix of text", vt.at(vt.holding("/runner/x")).root == "/" and vt.at(vt.holding("/run")).root == "/run" and vt.at(vt.holding("/run/user/1")).root == "/run")
wv = g.VolumeTable()
wv.add(g.VolumeInfo("C:\\", "", "System", "NTFS", K.Fixed))
wv.add(g.VolumeInfo("D:\\", "", "", "exFAT", K.Removable))
check("Windows drive letters ignore case", wv.holding("c:\\Users\\me") == 0 and wv.holding("D:\\x") == 1 and wv.holding("E:\\x") == -1)
check("title is the label when there is one", wv.at(0).title() == "System" and wv.at(1).title() == "D:\\")

# --- Space ---------------------------------------------------------------------------------------
sp = g.SpaceInfo(1000, 400, 350)
check("space", sp.used() == 600 and sp.fullTenths() == 631, sp.fullTenths())
check("a volume of nothing is not full", g.SpaceInfo(0, 0, 0).fullTenths() == 0)

# --- Entries -------------------------------------------------------------------------------------
E = g.EntryKind
el = g.EntryList()
for i in range(40):
    el.add(g.DirEntry("f%d" % i, g.FileStat("/d/f%d" % i, E.File, 10, 0, 0o644, False)))
el.add(g.DirEntry("sub", g.FileStat("/d/sub", E.Dir, 4096, 0, 0o755, False)))
el.add(g.DirEntry("ln", g.FileStat("/d/ln", E.Link, 7, 0, 0o777, False)))
check("a list grows and finds", el.size() == 42 and el.find("f39") == 39 and el.find("sub") == 40 and el.find("zz") == -1)
check("counts", el.folders() == 1 and el.bytes() == 400)
st = g.FileStat("/d/x", E.File, 5, 1000, 0o444, True)
check("read-only comes from the mode", st.readOnly and st.hidden and not st.isDir() and not st.isLink())
check("keys follow the path", g.FileStat("/d/x", E.File, 99, 5, 0o644, False).key == st.key and g.FileStat("/d/y", E.File, 5, 1000, 0o444, True).key != st.key)

check("PathText::join adds a separator only when it is missing", g.PathText.join("/a", "b", "/") == "/a/b" and g.PathText.join("/a/", "b", "/") == "/a/b" and g.PathText.join("C:\\", "x", "\\") == "C:\\x" and g.PathText.join("C:\\d", "x", "\\") == "C:\\d\\x")
check("PathText::leaf takes either separator", g.PathText.leaf("/a/b/c.txt") == "c.txt" and g.PathText.leaf("C:\\a\\b") == "b" and g.PathText.leaf("name") == "name")
check("the kind comes from the type bits of a mode", g.EntryKind.fromMode(0o100644) == E.File and g.EntryKind.fromMode(0o040755) == E.Dir and g.EntryKind.fromMode(0o120777) == E.Link and g.EntryKind.fromMode(0o010644) == E.Other)

# --- Fs, over the fake disk ---------------------------------------------------------------------
F = g.Fs
check("stat describes, and a link is a link", F.stat("/data/lnk").isLink() and F.stat("/data/a.txt").size == 100 and F.stat("/data/b.bin").readOnly)
check("a missing path is Gone", isinstance(thrown(lambda: F.stat("/nope")), g.Gone))
check("exists", F.exists("/data/a.txt") and not F.exists("/nope"))
items = F.list("/data")
check("a folder lists with kinds", items.size() == 5 and items.folders() == 1 and items.bytes() == 1105 and items.at(items.find("lnk")).stat.isLink())
check("hidden entries are marked", items.at(items.find(".hidden")).stat.hidden and not items.at(items.find("a.txt")).stat.hidden)
ts = F.treeSize("/data")
check("tree size counts files, folders and bytes, links excluded", (ts.bytes, ts.files, ts.folders, ts.skipped) == (1125, 4, 1, 0), (ts.bytes, ts.files, ts.folders, ts.skipped))
check("tree size of a path that is not there raises", isinstance(thrown(lambda: F.treeSize("/nope")), g.Gone))
check("volumes and the one holding a path", F.volumes().size() == 2 and F.volumeOf("/data/sub").root == "/data" and F.volumeOf("/etc").root == "/")
check("space", F.space("/data").used() == 600000)
check("reading a link", F.readLink("/data/lnk") == "a.txt" and isinstance(thrown(lambda: F.readLink("/data/a.txt")), g.Invalid))
check("can make a link: unknown here, decided by the folder", F.canMakeLink().state == g.SupportState.Unknown and F.canSetMode().state == g.SupportState.Unknown)
pl = F.planMakeLink("a.txt", "/data/l2")
check("plans say what and how to undo", pl.count() == 1 and "symbolic link" in pl.whatAt(0) and pl.reversible() and F.planSetReadOnly("/data/a.txt", True).reversible())

# --- the watcher: a queue of changes, in order --------------------------------------------------
w = F.watch("/data")
check("the watcher is open and has something", w.isOpen() and w.wait(0) == g.WatchState.Ready and w.pending() == 3)
got = []
while w.pending() > 0:
    got.append(w.next().describe())
check("changes come out in the order they went in", got == ["created new.txt", "modified a.txt", "deleted old.txt"], got)
check("then it is idle", w.wait(0) == g.WatchState.Idle)
w.close()
check("closing is final, and harmless twice", not w.isOpen() and w.wait(0) == g.WatchState.Closed and thrown(lambda: w.close()) is None)

q = g.ChangeQueue()
for i in range(100):
    q.push(g.ChangeKind.Created, "n%d" % i)
check("the queue grows past its room and keeps order", q.count() == 100 and q.pop().name == "n0" and q.pop().name == "n1")
for i in range(40):
    q.push(g.ChangeKind.Deleted, "m%d" % i)
order = []
while not q.isEmpty():
    order.append(q.pop().name)
check("and wraps without losing any", len(order) == 138 and order[0] == "n2" and order[97] == "n99" and order[98] == "m0" and order[-1] == "m39")
check("every kind survives the queue", all((lambda k: (lambda qq: (qq.push(k, "x"), qq.pop().kind == k)[1])(g.ChangeQueue()))(k) for k in [g.ChangeKind.Created, g.ChangeKind.Deleted, g.ChangeKind.Modified, g.ChangeKind.RenamedFrom, g.ChangeKind.RenamedTo]))
check("an empty pop is harmless", g.ChangeQueue().pop().name == "")

print("all ok" if not fails else "FAILED: %s" % fails)
sys.exit(1 if fails else 0)
