"""DNS as data: the wire reader, the zone names, the cache, the AS origin, and reading status."""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from axpy.run import load  # noqa: E402

g = load()
fails = []


def check(name, cond, extra=""):
    print(("ok   " if cond else "FAIL ") + name + (" " + str(extra) if extra and not cond else ""))
    if not cond:
        fails.append(name)


A = g.Addr.parse

# --- the reverse zone names ----------------------------------------------------------------------
check("IPv4 reverse name", g.Arpa.name(A("93.184.216.34")) == "34.216.184.93.in-addr.arpa")
check("IPv6 reverse name is 32 nibbles, reversed", g.Arpa.name(A("2001:db8::1")) == "1.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.0.8.b.d.0.1.0.0.2.ip6.arpa")
check("a mapped address is asked for as IPv4", g.Arpa.name(A("::ffff:1.2.3.4")) == "4.3.2.1.in-addr.arpa")


# --- DNS messages as bytes -----------------------------------------------------------------------
def name_bytes(name):
    out = b""
    for label in name.split("."):
        out += bytes([len(label)]) + label.encode()
    return out + b"\x00"


def message(qname, qtype, answers, rcode=0, ancount=None):
    """A response: header, one question, answers given as (owner-bytes, type, rdata)."""
    head = struct.pack(">HHHHHH", 0x1234, 0x8180 | rcode, 1, len(answers) if ancount is None else ancount, 0, 0)
    body = name_bytes(qname) + struct.pack(">HH", qtype, 1)
    for owner, rtype, rdata in answers:
        body += owner + struct.pack(">HHIH", rtype, 1, 60, len(rdata)) + rdata
    return list(head + body)


def run_name(msg):
    return g.Dns.firstName(msg, len(msg))


def run_text(msg):
    return g.Dns.firstText(msg, len(msg))


PTR_OWNER = b"\xc0\x0c"   # a pointer to the question's name at offset 12
ptr = message("34.216.184.93.in-addr.arpa", 12, [(PTR_OWNER, 12, name_bytes("example.com"))])
check("the first PTR record's target", run_name(ptr) == "example.com", run_name(ptr))

# a target that itself ends in a pointer back into the question
target = b"\x03www" + b"\xc0\x0c"
p2 = message("example.com", 12, [(PTR_OWNER, 12, target)])
check("a name that ends in a pointer is followed", run_name(p2) == "www.example.com", run_name(p2))

TXT = b"15133 | 93.184.216.0/24 | US | arin | 2008-06-02"
txt = message("x.origin.asn.cymru.com", 16, [(PTR_OWNER, 16, bytes([len(TXT)]) + TXT)])
check("a TXT record's text", run_text(txt) == TXT.decode(), run_text(txt))
split = message("x.example", 16, [(PTR_OWNER, 16, b"\x05hello\x06 world")])
check("a TXT record's strings read as one text", run_text(split) == "hello world", run_text(split))

mixed = message("a.example", 16, [(PTR_OWNER, 5, name_bytes("alias.example")), (PTR_OWNER, 16, b"\x02ok")])
check("records of another type are skipped", run_text(mixed) == "ok" and run_name(mixed) == "")

nx = message("nope.example", 12, [], rcode=3)
check("a refused or empty answer is the empty string", run_name(nx) == "" and run_text(nx) == "" and run_name(message("a.b", 12, [])) == "")
check("a message with a non-zero response code says nothing even if records follow", run_name(message("a.b", 12, [(PTR_OWNER, 12, name_bytes("x.y"))], rcode=2)) == "")

check("a message shorter than its header", run_name([0] * 5) == "" and run_text([]) == "")
cut = ptr[:-4]
check("a message cut inside a record", run_name(cut) == "")
claims = message("a.b", 12, [(PTR_OWNER, 12, name_bytes("x.y"))], ancount=7)
check("an answer count larger than the data does not run off the end", run_name(claims) == "x.y")

loop = list(struct.pack(">HHHHHH", 1, 0x8180, 1, 1, 0, 0)) + [0xC0, 12] + [0, 12, 0, 1] + [0xC0, 0x0C] + [0, 12, 0, 1, 0, 0, 0, 60, 0, 2, 0xC0, 12 + 4 + 2 + 2]
check("a name that points at itself ends", isinstance(run_name(loop), str))
bad_label = message("a.b", 12, [(PTR_OWNER, 12, bytes([0x40]) + b"x" * 5)])
check("a label with reserved high bits is refused", run_name(bad_label) == "")
nonascii = message("a.b", 16, [(PTR_OWNER, 16, b"\x03a\xffb")])
check("bytes outside printable ASCII become ?", run_text(nonascii) == "a?b")

# --- Team Cymru ------------------------------------------------------------------------------------
C = g.Cymru
check("origin names", C.originName(A("10.104.79.160")) == "160.79.104.10.origin.asn.cymru.com" and C.originName(A("2001:db8::1")).endswith(".origin6.asn.cymru.com") and C.originName(A("2001:db8::1")).startswith("1.0.0.0."))
check("AS names", C.asName(399358) == "AS399358.asn.cymru.com")
o = C.parseOrigin("399358 | 160.79.104.0/23 | US | arin | 2023-09-14")
check("an origin answer", (o.asn, o.prefix, o.country, o.registry) == (399358, "160.79.104.0/23", "US", "arin") and o.isKnown() and o.title() == "AS399358", (o.asn, o.prefix))
n = C.named(o, "399358 | US | arin | 2023-09-20 | ANTHROPIC - Anthropic, PBC, US")
check("the name from the AS answer", n.name == "ANTHROPIC - Anthropic, PBC, US" and n.title() == "AS399358 ANTHROPIC - Anthropic, PBC, US" and n.asn == 399358)
check("several networks: the first", C.parseOrigin("7018 3356 | 4.0.0.0/9 | US | arin | 2000-01-01").asn == 7018)
check("an answer nobody can read", not C.parseOrigin("").isKnown() and not C.parseOrigin("garbage").isKnown() and C.parseOrigin("12345678901 | x").asn == 0)
check("fields are trimmed", C.parseOrigin("  15133  |  93.184.216.0/24  |US|arin|").country == "US" and C.parseOrigin("  15133  |  93.184.216.0/24  |US|arin|").prefix == "93.184.216.0/24")

# --- the cache, inverted ---------------------------------------------------------------------------
dc = g.DnsCache(True)
dc.add(g.DnsEntry("api.stripe.com", A("52.1.2.3")))
dc.add(g.DnsEntry("api.stripe.com", A("52.1.2.4")))
dc.add(g.DnsEntry("cdn.example.net", A("52.1.2.3")))
dc.add(g.DnsEntry("CDN.example.net", A("52.1.2.3")))
dc.add(g.DnsEntry("v6.example", A("2001:db8::7")))
check("an address's name is the first one cached", dc.nameOf(A("52.1.2.3")) == "api.stripe.com" and dc.nameOf(A("2001:db8::7")) == "v6.example" and dc.nameOf(A("9.9.9.9")) == "" and dc.knows(A("52.1.2.4")) and not dc.knows(A("9.9.9.9")))
check("every name for it, once each, case ignored", list(dc.namesOf(A("52.1.2.3"))) == ["api.stripe.com", "cdn.example.net"], list(dc.namesOf(A("52.1.2.3"))))
check("a name's addresses", [a.text() for a in dc.addressesOf("API.STRIPE.COM")] == ["52.1.2.3", "52.1.2.4"] and len(dc.addressesOf("nope")) == 0)
check("an IPv4-mapped address finds the IPv4 name", dc.nameOf(A("::ffff:52.1.2.4")) == "api.stripe.com")
check("a reading says whether the system answered", dc.answered() and not g.DnsCache(False).answered() and g.DnsCache(False).size() == 0)
check("the cache holds what was added and grows", dc.size() == 5 and (lambda c: ([c.add(g.DnsEntry("n%d" % i, A("10.0.%d.%d" % (i // 250, i % 250 + 1)))) for i in range(300)], c.size() == 300 and c.nameOf(A("10.0.1.1")) == "n250")[1])(g.DnsCache(True)))

# --- reading status --------------------------------------------------------------------------------
R = g.ReadingStatus
check("on / off / lost", R.on("dns cache", "x").isOn() and not R.off("dns cache", "x").isOn() and R.lost("dns cache", "x").state == g.ReadingState.Lost)
check("a platform without it is not capable; a refusal that a privilege would lift is", not R.unavailable("kernel trace", "no").capable and R.off("kernel trace", "needs admin").capable)
check("describe", R.on("dns cache", "reading it").describe() == "dns cache: on — reading it" and R.lost("dns cache", "empty").describe() == "dns cache: lost — empty")

# --- Net over the fake resolver ----------------------------------------------------------------------
def thrown(fn):
    try:
        fn()
    except Exception as e:
        return e
    return None


N = g.Net
check("the machine's cache names an address", N.dnsCache().nameOf(A("93.184.216.34")) == "cdn.example.net" and N.dnsCache().size() == 3)
check("a reverse lookup", N.reverse(A("93.184.216.34")) == "edge.example.net" and N.reverse(A("192.168.1.1")) == "router.lan")
check("no such record is Absent, not an empty name", isinstance(thrown(lambda: N.reverse(A("8.8.8.8"))), g.Absent) and "8.8.8.8" in thrown(lambda: N.reverse(A("8.8.8.8"))).message)
check("a text lookup", N.txt("AS15133.asn.cymru.com").endswith("EDGECAST, US") and isinstance(thrown(lambda: N.txt("nope.example")), g.Absent))
org = N.origin(A("93.184.216.34"))
check("origin: the network, its prefix and its name", (org.asn, org.prefix, org.country, org.name) == (15133, "93.184.216.0/24", "US", "EDGECAST, US") and org.title() == "AS15133 EDGECAST, US", (org.asn, org.name))
check("nothing announces an address: Absent", isinstance(thrown(lambda: N.origin(A("8.8.8.8"))), g.Absent))

real_txt = g.DnsSys.txt
g.DnsSys.txt = staticmethod(lambda name: real_txt(name) if name.startswith("34.") else "")
org2 = N.origin(A("93.184.216.34"))
check("when only the network's name fails, the number stands alone", org2.asn == 15133 and org2.name == "" and org2.title() == "AS15133")
g.DnsSys.txt = staticmethod(lambda name: "garbage" if name.endswith("origin.asn.cymru.com") else "")
check("an answer nobody can read is Invalid, naming it", isinstance(thrown(lambda: N.origin(A("93.184.216.34"))), g.Invalid))
g.DnsSys.txt = real_txt
check("the cache can be read here, by the fake's rules", N.canReadDnsCache().state != g.SupportState.Unsupported)

# --- the reader: status over time -------------------------------------------------------------------------
rd = g.DnsCacheReader(5000)
check("before a sweep, nothing is read and it says so", not rd.status().isOn() and rd.status().note == "not read yet" and rd.nameOf(A("52.1.2.3")) == "" and rd.due(0))
check("a sweep reads the cache", rd.sweep(1000) and rd.status().isOn() and rd.status().note == "3 cached answers read" and rd.nameOf(A("52.1.2.3")) == "api.stripe.com")
check("it is not due again until the interval has passed", not rd.due(5999) and rd.due(6000))

real_cache = g.DnsSys.cache
g.DnsSys.cache = staticmethod(lambda: g.DnsCache(False))
check("an empty or silent cache is Lost, and the last names stay", not rd.sweep(6000) and rd.status().state == g.ReadingState.Lost and rd.nameOf(A("52.1.2.3")) == "api.stripe.com")


def unsupported():
    raise g.Unsupported("net.dnsCache", "linux", "no cache")


g.DnsSys.cache = staticmethod(unsupported)
check("a platform with no cache is unavailable for good", not rd.sweep(11000) and rd.status().state == g.ReadingState.Off and not rd.status().capable and "linux" in rd.status().note)


def denied():
    raise g.Denied("net.dnsCache", "the cache", g.Privilege.Elevated, 5)


g.DnsSys.cache = staticmethod(denied)
check("a refusal is Off but could be lifted", not rd.sweep(16000) and rd.status().state == g.ReadingState.Off and rd.status().capable and "elevated" in rd.status().note)


def broken():
    raise g.OsFailure("net.dnsCache", 1117, "ERROR_IO_DEVICE")


g.DnsSys.cache = staticmethod(broken)
check("any other failure is Lost with its message", not rd.sweep(21000) and rd.status().state == g.ReadingState.Lost and "1117" in rd.status().note, rd.status().note)
g.DnsSys.cache = real_cache
check("and it recovers", rd.sweep(26000) and rd.status().isOn())

print("all ok" if not fails else "FAILED: %s" % fails)
sys.exit(1 if fails else 0)
