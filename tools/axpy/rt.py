"""rt.py — the runtime the translated Axle runs against: its numbers, its strings, and the part of
smalt that zaffre uses.

Semantics kept faithful where the library depends on them:
  * integer `/` and `%` truncate toward zero and trap on a zero divisor;
  * `as` between numeric types truncates and saturates (float → int) or wraps (int → narrower int);
  * a `struct` is a value (copied on assignment); a class is a reference;
  * `string` is UTF-8: `byteLength` and `byteAt` speak bytes;
  * smalt's `Mem` is a flat byte heap addressed by integers, so `Frame` pixels, font bytes and the
    glyph cache are addressed exactly as they are in the real library.

Not kept: integer overflow wrapping (the library does not rely on it), threads, the OS.
"""
import math
import struct as _struct
import sys

import numpy as np

# ─── Numbers ──────────────────────────────────────────────────────────────────────────

INT_RANGE = {
    "i8": (-(1 << 7), (1 << 7) - 1, 8, True), "i16": (-(1 << 15), (1 << 15) - 1, 16, True),
    "i32": (-(1 << 31), (1 << 31) - 1, 32, True), "i64": (-(1 << 63), (1 << 63) - 1, 64, True),
    "u8": (0, (1 << 8) - 1, 8, False), "u16": (0, (1 << 16) - 1, 16, False),
    "u32": (0, (1 << 32) - 1, 32, False), "u64": (0, (1 << 64) - 1, 64, False),
}


class Trap(Exception):
    """A division by zero, an out-of-bounds index: the process abort the language specifies."""


def wrap(x, t):
    lo, hi, bits, signed = INT_RANGE[t]
    x &= (1 << bits) - 1
    if signed and x >= (1 << (bits - 1)):
        x -= 1 << bits
    return x


def cast(x, t):
    if t in INT_RANGE:
        if isinstance(x, EnumBase):
            x = x.value
        if isinstance(x, bool):
            return int(x)
        if isinstance(x, float):
            if x != x:
                return 0
            lo, hi, _, _ = INT_RANGE[t]
            if x >= hi:
                return hi
            if x <= lo:
                return lo
            return int(x)
        return wrap(x, t)
    if t in ("f64", "f32"):
        return float(x)
    if t == "char":
        return int(x)
    return x


def div(a, b):
    if isinstance(a, int) and isinstance(b, int) and not isinstance(a, bool):
        if b == 0:
            raise Trap("division by zero")
        q = abs(a) // abs(b)
        return q if (a >= 0) == (b >= 0) else -q
    if b == 0:
        raise Trap("division by zero")
    return a / b


def rem(a, b):
    if isinstance(a, int) and isinstance(b, int):
        if b == 0:
            raise Trap("division by zero")
        return a - b * div(a, b)
    if b == 0:
        raise Trap("division by zero")
    return math.fmod(a, b)


def ushr(x, n):
    if -(1 << 31) <= x < (1 << 31):
        return (x & 0xFFFFFFFF) >> n
    return (x & 0xFFFFFFFFFFFFFFFF) >> n


def floor_i(x):
    return int(math.floor(x))


def ceil_i(x):
    return int(math.ceil(x))


def trunc_i(x):
    return int(x)


def round_i(x):
    if x >= 0:
        return int(math.floor(x + 0.5))
    return -int(math.floor(-x + 0.5))


# ─── Values ───────────────────────────────────────────────────────────────────────────

class Struct:
    __slots__ = ()
    _fields = ()

    @classmethod
    def _zero(cls):
        c = object.__new__(cls)
        for f in cls._fields:
            setattr(c, f, cls._zero_of[f]())
        return c

    def copy(self):
        c = object.__new__(type(self))
        for f in self._fields:
            setattr(c, f, cp(getattr(self, f)))
        return c

    def __eq__(self, o):
        return type(self) is type(o) and all(getattr(self, f) == getattr(o, f) for f in self._fields)

    def __hash__(self):
        return hash(tuple(getattr(self, f) for f in self._fields))

    def __repr__(self):
        return "%s(%s)" % (type(self).__name__, ", ".join("%s=%r" % (f, getattr(self, f)) for f in self._fields))


def cp(v):
    if isinstance(v, Struct):
        return v.copy()
    if isinstance(v, EnumBase):
        return v
    return v


class EnumBase:
    """Every enum value is an instance of its enum's class: (name, integer value, payload)."""

    def __init__(self, name, value, payload=()):
        self.name = name
        self.value = value
        self.payload = payload

    def __eq__(self, o):
        return isinstance(o, EnumBase) and type(self) is type(o) and self.name == o.name and self.payload == o.payload

    def __hash__(self):
        return hash((type(self).__name__, self.name, self.payload))

    def __repr__(self):
        return "%s::%s%s" % (type(self).__name__, self.name, "(%s)" % ", ".join(map(repr, self.payload)) if self.payload else "")


class AxleError(Exception):
    def __init__(self, message=""):
        Exception.__init__(self, message)
        self.message = message


class IOException(AxleError):
    pass


class FileNotFoundException(IOException):
    pass


class ParseException(AxleError):
    pass


class IndexOutOfBoundsException(AxleError):
    pass


class IllegalStateException(AxleError):
    pass


class IllegalArgumentException(AxleError):
    pass


class ArithmeticException(AxleError):
    pass


class PlatformError(AxleError):
    pass


def malloc(n, zero):
    return [zero() for _ in range(int(n))]


def length(a):
    return len(a)


# ─── Strings ──────────────────────────────────────────────────────────────────────────

_enc_cache = {}


def enc(s):
    b = _enc_cache.get(s)
    if b is None:
        b = s.encode("utf-8")
        if len(_enc_cache) > 4096:
            _enc_cache.clear()
        _enc_cache[s] = b
    return b


def byte_length(s):
    return len(enc(s))


def byte_at(s, i):
    return enc(s)[i]


def to_string(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        r = repr(v)
        return r
    return str(v)


class StringBuilder:
    def __init__(self):
        self.parts = []

    def append(self, s):
        self.parts.append(s)

    def appendChar(self, c):
        self.parts.append(chr(c))

    def appendI32(self, n):
        self.parts.append(str(n))

    def toString(self):
        return "".join(self.parts)

    def byteLength(self):
        return byte_length("".join(self.parts))


def prim(recv, name, args):
    """A method on a primitive: min, floorToInt, toString, …"""
    if name == "min":
        return min(recv, args[0])
    if name == "max":
        return max(recv, args[0])
    if name == "abs":
        return abs(recv)
    if name == "sqrt":
        return math.sqrt(recv)
    if name == "sin":
        return math.sin(recv)
    if name == "cos":
        return math.cos(recv)
    if name == "pow":
        return math.pow(recv, args[0])
    if name == "floorToInt":
        return floor_i(recv)
    if name == "ceilToInt":
        return ceil_i(recv)
    if name == "truncToInt":
        return trunc_i(recv)
    if name == "round":
        return round_i(recv)
    if name == "toString":
        return to_string(recv)
    if name == "isEmpty":
        return len(recv) == 0
    if name == "equals":
        return recv == args[0]
    if name == "substring":
        return recv[args[0]:args[1]]
    if name == "charAt":
        return ord(recv[args[0]]) if 0 <= args[0] < len(recv) else -1
    if name == "byteAt":
        return byte_at(recv, args[0])
    raise AttributeError("no primitive method %s on %r" % (name, recv))


PRIM_METHODS = {"min", "max", "abs", "sqrt", "sin", "cos", "pow", "floorToInt", "ceilToInt", "truncToInt", "round",
                "toString", "isEmpty", "equals", "substring", "charAt", "byteAt"}


def call(recv, name, args):
    if isinstance(recv, (int, float, str, bool)):
        return prim(recv, name, args)
    return getattr(recv, name)(*args)


# ─── Memory: smalt's `Mem` over one flat heap ─────────────────────────────────────────

HEAP_BYTES = 192 * 1024 * 1024
_heap = np.zeros(HEAP_BYTES, dtype=np.uint8)
_h32 = _heap.view(np.int32)
_h64 = _heap.view(np.int64)
_hf64 = _heap.view(np.float64)
_hf32 = _heap.view(np.float32)
_top = [64]


class Mem:
    @staticmethod
    def take(n):
        n = int(n)
        if n <= 0:
            return 0
        a = (_top[0] + 15) & ~15
        if a + n > HEAP_BYTES:
            raise Trap("out of memory")
        _top[0] = a + n
        return a

    @staticmethod
    def takeZeroed(n):
        a = Mem.take(n)
        return a

    @staticmethod
    def release(a):
        pass

    @staticmethod
    def isNil(a):
        return a == 0

    @staticmethod
    def clear(a, n):
        _heap[a:a + n] = 0

    @staticmethod
    def copy(dst, src, n):
        _heap[dst:dst + n] = _heap[src:src + n].copy()

    @staticmethod
    def byteAt(base, off):
        return int(_heap[base + off])

    @staticmethod
    def putByte(base, off, v):
        _heap[base + off] = v & 255

    @staticmethod
    def wordAt(base, off):
        a = base + off
        return int(_heap[a]) | (int(_heap[a + 1]) << 8)

    @staticmethod
    def dwordAt(base, off):
        a = base + off
        return int(np.frombuffer(_heap[a:a + 4].tobytes(), dtype=np.int32)[0])

    @staticmethod
    def putDword(base, off, v):
        a = base + off
        _heap[a:a + 4] = np.frombuffer(np.int32(wrap(v, "i32")).tobytes(), dtype=np.uint8)

    @staticmethod
    def wordOf(base, index):
        return int(_h32[(base >> 2) + index])

    @staticmethod
    def putWordOf(base, index, v):
        _h32[(base >> 2) + index] = wrap(v, "i32") if not (-(1 << 31) <= v < (1 << 31)) else v

    @staticmethod
    def qwordOf(base, index):
        return int(_h64[(base >> 3) + index])

    @staticmethod
    def putQwordOf(base, index, v):
        _h64[(base >> 3) + index] = v

    @staticmethod
    def realOf(base, index):
        return float(_hf64[(base >> 3) + index])

    @staticmethod
    def putRealOf(base, index, v):
        _hf64[(base >> 3) + index] = v


class SlotIndex:
    def __init__(self, capacity):
        self.map = {}
        self.cap = capacity

    def get(self, key):
        return self.map.get(key, -1)

    def has(self, key):
        return key in self.map

    def put(self, key, slot):
        self.map[key] = slot
        return True

    def clear(self):
        self.map = {}

    def close(self):
        pass

    def size(self):
        return len(self.map)

    def capacity(self):
        return self.cap


class AssetFile:
    @staticmethod
    def readInto(path, base, nbytes):
        try:
            data = open(path, "rb").read(int(nbytes))
        except OSError:
            return 0
        _heap[base:base + len(data)] = np.frombuffer(data, dtype=np.uint8)
        return len(data)


# ─── smalt's 2-D surface ──────────────────────────────────────────────────────────────

class Rect(Struct):
    __slots__ = ("x", "y", "w", "h")
    _fields = ("x", "y", "w", "h")

    def __init__(self, x=0, y=0, w=0, h=0):
        self.x, self.y, self.w, self.h = x, y, w, h

    @staticmethod
    def make(x, y, w, h):
        return Rect(x, y, w, h)

    def contains(self, px, py):
        return self.x <= px < self.x + self.w and self.y <= py < self.y + self.h

    def isEmpty(self):
        return self.w <= 0 or self.h <= 0


class Frame(Struct):
    __slots__ = ("px", "w", "h", "cx0", "cy0", "cx1", "cy1")
    _fields = ("px", "w", "h", "cx0", "cy0", "cx1", "cy1")

    def __init__(self, px, w, h):
        self.px, self.w, self.h = px, w, h
        self.cx0, self.cy0, self.cx1, self.cy1 = 0, 0, w, h

    def base(self):
        return self.px

    def clipRect(self):
        return Rect(self.cx0, self.cy0, self.cx1 - self.cx0, self.cy1 - self.cy0)


class Surface:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.block = Mem.take(w * h * 4)

    def frame(self):
        return Frame(self.block, self.w, self.h)

    def resize(self, w, h):
        self.w, self.h = w, h
        self.block = Mem.take(w * h * 4)

    def close(self):
        pass

    def present(self, win):
        pass

    def width(self):
        return self.w

    def height(self):
        return self.h

    def pixels_rgb(self):
        """The surface as an (h, w, 3) uint8 array — what a snapshot shows."""
        words = _h32[(self.block >> 2):(self.block >> 2) + self.w * self.h].astype(np.int64) & 0xFFFFFF
        r = (words >> 16) & 255
        g = (words >> 8) & 255
        b = words & 255
        return np.stack([r, g, b], axis=-1).astype(np.uint8).reshape(self.h, self.w, 3)


def pixels_rgb(base, w, h):
    words = _h32[(base >> 2):(base >> 2) + w * h].astype(np.int64) & 0xFFFFFF
    return np.stack([(words >> 16) & 255, (words >> 8) & 255, words & 255], axis=-1).astype(np.uint8).reshape(h, w, 3)


class UnsupportedOperationException(AxleError):
    pass


class _Namespace:
    """A std module as the translation sees it: a bag of functions the tests may replace."""

    def __init__(self, **fns):
        self.__dict__.update(fns)


sysinfo = _Namespace(
    cpuCount=lambda: 4,
    pageSize=lambda: 4096,
    hostname=lambda: "host",
    username=lambda: "user",
)


def nanoTime():
    import time
    return time.monotonic_ns()


def now():
    import time
    return int(time.time() * 1000)


def pid():
    import os
    return os.getpid()


def parentPid():
    import os
    return os.getppid()


def panicMsg(message):
    """An abort: nothing catches it, so the translation turns it into an error no `catch` names."""
    raise SystemError("panic: " + message)


def println(*a):
    print(*[x if isinstance(x, str) else to_string(x) for x in a])


# ─── Struct literals and constructor selection ───────────────────────────────────────

def _rt_lit(cls, base=None, **kw):
    """`Name { a: 1, ..base }`: explicit fields, then the copied base, then declared defaults, then zero."""
    c = object.__new__(cls)
    for f in cls._fields:
        if f in kw:
            setattr(c, f, cp(kw[f]))
        elif base is not None:
            setattr(c, f, cp(getattr(base, f)))
        elif f in cls._defaults:
            setattr(c, f, cls._defaults[f]())
        else:
            setattr(c, f, cls._zero_of[f]())
    return c


def _rt_dispatch(cls, self, args):
    """Pick the constructor by arity, then by the first one whose parameter types suit the arguments."""
    for arity, checks, name in cls._ctors:
        if arity == len(args) and all(ck(a) for ck, a in zip(checks, args)):
            getattr(cls, name)(self, *args)
            return
    raise TypeError("%s: no constructor for %d args: %r" % (cls.__name__, len(args), args))
