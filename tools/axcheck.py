#!/usr/bin/env python3
"""axcheck.py — the checks a compiler makes first, over the tree `axparse` builds.

What it holds the code to, each with the compiler's own code where there is one:

  names        a bare name must be a local, a parameter, something declared in the file, something
               the file imports, or a prelude word (E0014)
  mutability   a binding that is written must be `let mut`; a field of a `let` struct value is not
               written (E0004)
  members      `x.name` and `x.name(…)` must name a field or method of x's type, found through its
               base classes and traits; `Type::name` a static member, a variant or a constant
  arity        a call's argument count must match one of the callee's overloads; a `::`-call on a
               constructor-less path likewise (E0001)
  literals     a struct literal supplies every field that has no default, names no field the struct
               does not have, and `..base` is of the same struct (E0743, E0747)
  matches      a `match` over an enum that names no `_` names every variant
  returns      a non-`void` function whose last statement is not a return, throw, or a match/if that
               returns on every path, falls off its end
  types, lightly: the type of an expression is worked out where the declarations make it certain
               (a local with a written type, a field, a call's declared return), and a mismatch
               between two certain *class* types in an assignment or `return` is reported. A type that
               cannot be worked out is never reported against.

It is not the type checker and says so: operator typing, widening, trait conformance and ownership
(E0501–E0513, E0511) all still need `axle check`. Everything reported here is a mistake, and nothing
is reported on a guess.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from axparse import parse, ParseError, Node  # noqa: E402

PRELUDE = {
    "nanoTime", "now", "sleep", "exit", "pid", "parentPid", "argc", "hasEnv", "println", "print", "malloc", "free", "sizeof", "offsetof", "self", "super", "true", "false", "null",
    "panicMsg", "argc", "argAt", "exit", "dbg", "assert", "i32", "i64", "f64", "f32", "u8", "u16", "u32", "u64",
    "i8", "i16", "bool", "string", "char", "Shared", "Weak", "Future", "Thread", "ptr",
    # exceptions of the standard library that need no import
    "Exception", "RuntimeException", "Error", "IOException", "FileNotFoundException", "ParseException",
    "IndexOutOfBoundsException", "ArithmeticException", "TimeoutException", "InterruptedException",
    "IllegalStateException", "IllegalArgumentException", "NullPointerException", "UnsupportedOperationException",
}
PRIMS = {"i8", "i16", "i32", "i64", "u8", "u16", "u32", "u64", "f32", "f64", "bool", "char", "string", "void"}
INTS = {"i8", "i16", "i32", "i64", "u8", "u16", "u32", "u64"}
FLOATS = {"f32", "f64"}


# ─── Types ───────────────────────────────────────────────────────────────────────────

def T(name, args=()):
    return ("n", name, tuple(args))


def tnode(n, generics=()):
    """A type as a tuple, from its AST node; None when it cannot be said."""
    if n is None:
        return None
    k = n.kind
    if k == "type":
        name = n.name.split("::")[-1]
        return T(name, [tnode(a) for a in n.args])
    if k == "array_type":
        return ("a", tnode(n.elem), n.size is not None)
    if k == "nullable":
        return ("null", tnode(n.inner))
    if k == "tuple_type":
        return ("t", tuple(tnode(t) for _, t in n.elems))
    if k == "ftype":
        return ("f", tuple(tnode(p) for p in n.params), tnode(n.ret))
    return None


def strip(t):
    """The type with nullability, Shared and Weak peeled: what members are looked up on."""
    while t is not None:
        if t[0] == "null":
            t = t[1]
        elif t[0] == "n" and t[1] in ("Shared", "Weak") and t[2]:
            t = t[2][0]
        else:
            return t
    return None


def show(t):
    if t is None:
        return "?"
    if t[0] == "n":
        return t[1] + ("<%s>" % ", ".join(show(a) for a in t[2]) if t[2] else "")
    if t[0] == "a":
        return show(t[1]) + "[]"
    if t[0] == "null":
        return show(t[1]) + " | null"
    if t[0] == "t":
        return "(" + ", ".join(show(x) for x in t[1]) + ")"
    return "fn"


# ─── Declarations ────────────────────────────────────────────────────────────────────

class FnInfo:
    def __init__(self, node, static, owner):
        self.node = node
        self.name = node.name
        self.static = static
        self.owner = owner
        ps = [p for p in node.params if p.name != "self"]
        self.arity = len(ps)
        self.has_self = any(p.name == "self" for p in node.params)
        self.ret = tnode(node.ret)
        self.params = ps


class ClassInfo:
    def __init__(self, node, file):
        self.node = node
        self.name = node.name
        self.kind = node.kind
        self.file = file
        self.generics = [g for g, _ in node.generics]
        self.supers = [tnode(s) for s in node.supers]
        self.fields = {}
        self.statics = {}
        self.methods = {}
        self.ctors = []
        self.variants = {}
        self.has_drop = False
        self.visit(node.members if node.kind != "enum" else node.members)
        if node.kind == "exception":
            # an exception derives `Exception` implicitly, which brings `message`
            self.fields.setdefault("message", Node("field", node.line, name="message", type=Node("type", node.line, name="string", args=[]), default=None, vis="pub", static=False, readonly=False))
        if node.kind == "enum":
            for v in node.variants:
                self.variants[v.name] = v
            self.has_enum_payload = any(v.payload for v in node.variants)
        self.stuct_fields_nodes = {m.name: m for m in node.members if m.kind == "field"} if node.kind == "struct" else {}

    def visit(self, members):
        for m in members:
            if m.kind == "field":
                if m.static:
                    self.statics[m.name] = tnode(m.type)
                else:
                    self.fields[m.name] = m
            elif m.kind == "fn":
                fi = FnInfo(m, m.static or not any(p.name == "self" for p in m.params), self)
                self.methods.setdefault(m.name, []).append(fi)
            elif m.kind == "constructor":
                self.ctors.append(m)
            elif m.kind == "drop":
                self.has_drop = True
            elif m.kind == "when":
                self.visit(m.members)


class FileInfo:
    def __init__(self, path, root_kind, items):
        self.path = path
        self.root = root_kind        # "crate" or "smalt"
        self.items = items
        self.classes = {}
        self.fns = {}
        self.consts = {}
        self.imports = {}            # local name -> (source, original name)
        self.modules = set()         # names bound to whole modules
        for it in items:
            if it.kind in ("class", "struct", "enum", "trait", "exception"):
                self.classes[it.name] = ClassInfo(it, path)
            elif it.kind == "fn":
                self.fns[it.name] = FnInfo(it, True, None)
            elif it.kind == "const":
                self.consts[it.name] = it
            elif it.kind == "extern_block":
                for f in it.fns:
                    self.fns[f.name] = FnInfo(f, True, None)
            elif it.kind == "use":
                self.use(it)

    def use(self, it):
        src = it.path[0]
        if it.names is not None:
            for n, a in it.names:
                self.imports[a or n] = (src, n)
        else:
            self.imports[it.alias or it.path[-1]] = (src, it.path[-1])
            self.modules.add(it.alias or it.path[-1])


class World:
    def __init__(self):
        self.crate_files = {}
        self.smalt_files = {}
        self.crate_classes = {}
        self.smalt_classes = {}
        self.crate_fns = {}
        self.errors = []

    def add(self, fi, smalt):
        (self.smalt_files if smalt else self.crate_files)[fi.path] = fi
        target = self.smalt_classes if smalt else self.crate_classes
        for n, c in fi.classes.items():
            target.setdefault(n, c)
        if not smalt:
            for n, f in fi.fns.items():
                self.crate_fns.setdefault(n, []).append(f)

    def cls(self, fi, name):
        """The ClassInfo a name means inside file `fi`."""
        if name in fi.classes:
            return fi.classes[name]
        imp = fi.imports.get(name)
        if imp:
            src, orig = imp
            if src in ("crate", "gesso"):
                return self.crate_classes.get(orig)
            if src == "smalt":
                return self.smalt_classes.get(orig)
            return None
        if fi.root == "smalt":
            return self.smalt_classes.get(name)
        return None


# ─── The checker ─────────────────────────────────────────────────────────────────────

class Scope:
    def __init__(self, parent=None):
        self.vars = {}
        self.parent = parent

    def declare(self, name, mut, ty, kind="local"):
        self.vars[name] = {"mut": mut, "type": ty, "kind": kind}

    def find(self, name):
        s = self
        while s:
            if name in s.vars:
                return s.vars[name]
            s = s.parent
        return None


class Checker:
    def __init__(self, world, fi, errors):
        self.w = world
        self.fi = fi
        self.errors = errors
        self.cls = None          # the ClassInfo whose body is being checked
        self.fn = None
        self.generics = set()

    def err(self, line, msg, code=None):
        self.errors.append("%s:%d: %s%s" % (self.fi.path, line, "[%s] " % code if code else "", msg))

    # -- entry --
    def run(self):
        for it in self.fi.items:
            if it.kind == "fn":
                self.check_fn(it, None)
            elif it.kind in ("class", "struct", "enum", "trait", "exception"):
                self.check_type(it)
            elif it.kind == "const":
                self.expr(it.value, Scope())
            elif it.kind == "extern_block":
                pass

    def check_type(self, node):
        ci = self.fi.classes[node.name]
        self.cls = ci
        self.generics = set(ci.generics)
        # fields' defaults
        for m in node.members:
            self.member(m, ci)
        self.cls = None
        self.generics = set()
        # shape rules
        if node.kind in ("class", "exception"):
            self.check_overrides(ci)

    def member(self, m, ci):
        if m.kind == "fn":
            self.check_fn(m, ci)
        elif m.kind == "constructor":
            sc = Scope()
            sc.declare("self", True, T(ci.name, [T(g) for g in ci.generics]))
            for p in m.params:
                sc.declare(p.name, False, tnode(p.type), "param")
            self.fn = m
            self.block(m.body, sc)
        elif m.kind == "drop":
            sc = Scope()
            sc.declare("self", True, T(ci.name))
            self.block(m.body, sc)
        elif m.kind == "field":
            if m.default is not None:
                sc = Scope()
                self.expr(m.default, sc)
        elif m.kind == "when":
            for mm in m.members:
                self.member(mm, ci)
        elif m.kind == "impl_self":
            pass

    def check_overrides(self, ci):
        # a class that lists a trait must supply every method it declares without a body
        for s in ci.supers:
            if s is None:
                continue
            tc = self.w.cls(self.fi, s[1])
            if not tc or tc.kind != "trait":
                continue
            for name, fns in tc.methods.items():
                for f in fns:
                    if f.node.body is not None:
                        continue
                    if not self.has_method(ci, name):
                        self.err(ci.node.line, "class %s lists trait %s but has no method `%s`" % (ci.name, tc.name, name), "E0026")

    def has_method(self, ci, name, seen=None):
        seen = seen or set()
        if ci.name in seen:
            return False
        seen.add(ci.name)
        if name in ci.methods:
            return True
        for s in ci.supers:
            if s is None:
                continue
            sc = self.w.cls(self.fi, s[1]) or self.w.cls(self.w.crate_files.get(ci.file) or self.fi, s[1])
            if sc and sc.kind != "trait" and self.has_method(sc, name, seen):
                return True
            if sc and sc.kind == "trait" and name in sc.methods and sc.methods[name][0].node.body is not None:
                return True
        return False

    # -- functions --
    def check_fn(self, fn, ci):
        if fn.body is None:
            return
        sc = Scope()
        g_before = self.generics
        self.generics = set(self.generics) | {g for g, _ in fn.generics}
        if ci is not None and any(p.name == "self" for p in fn.params):
            selfp = [p for p in fn.params if p.name == "self"][0]
            sc.declare("self", selfp.mut or ci.kind in ("struct", "enum") and False, T(ci.name, [T(g) for g in ci.generics]), "self")
        for p in fn.params:
            if p.name == "self":
                continue
            sc.declare(p.name, False, tnode(p.type), "param")
            sc.vars[p.name]["mutparam"] = p.mut
        self.fn = fn
        self.block(fn.body, sc)
        if fn.ret is not None and not (fn.ret.kind == "type" and fn.ret.name == "void"):
            if not self.terminates_block(fn.body):
                self.err(fn.line, "`%s` can fall off its end without returning a value" % fn.name, "E0001")
        self.generics = g_before

    def terminates_block(self, b):
        if b.kind != "block":
            return self.terminates(b)
        for s in b.stmts:
            if self.terminates(s):
                return True
        return False

    def terminates(self, s):
        k = s.kind
        if k in ("return", "throw"):
            return True
        if k == "block":
            return self.terminates_block(s)
        if k == "if":
            if s.els is None:
                return False
            return self.terminates_block(s.then) and self.terminates(s.els)
        if k == "expr":
            e = s.value
            if e.kind == "match":
                return all(self.arm_terminates(a) for a in e.arms)
            return False
        if k in ("while", "dowhile"):
            # `while (true)` with no break never falls through
            c = s.cond
            while c.kind == "paren":
                c = c.value
            return c.kind == "lit" and c.value == "true" and not self.has_break(s.body)
        if k == "try":
            if not self.terminates_block(s.body):
                return False
            return all(self.terminates_block(c.body) for c in s.catches)
        if k in ("unsafe", "sync", "defer"):
            return self.terminates_block(s.body) if s.body.kind == "block" else False
        return False

    def has_break(self, b):
        found = []

        def walk(n):
            if isinstance(n, Node):
                if n.kind == "break":
                    found.append(n)
                if n.kind in ("while", "for", "dowhile"):
                    return
                for v in n.f.values():
                    walk(v)
            elif isinstance(n, (list, tuple)):
                for x in n:
                    walk(x)
        walk(b.stmts if b.kind == "block" else b)
        return bool(found)

    def arm_terminates(self, a):
        b = a.body
        if b.kind == "block":
            return self.terminates_block(b)
        return b.kind in ("unsupported",) or b.kind == "call" and False or self.expr_returns(b)

    def expr_returns(self, e):
        # an arm whose value *is* the match's value: it does not need a return of its own
        return True

    # -- statements --
    def block(self, b, sc):
        inner = Scope(sc)
        for s in b.stmts:
            self.stmt(s, inner)

    def stmt(self, s, sc):
        k = s.kind
        if k == "block":
            self.block(s, sc)
        elif k == "let":
            ty = tnode(s.type)
            vt = None
            if s.value is not None:
                vt = self.expr(s.value, sc)
            if ty is None:
                ty = vt
            elif vt is not None:
                self.assignable(s.line, ty, vt, "let `%s`" % s.name)
            sc.declare(s.name, s.mut, ty)
            if s.get("legacy_const"):
                self.err(s.line, "a local `const` is spelled `let` now", "E0001")
        elif k == "let_tuple":
            vt = self.expr(s.value, sc)
            elems = list(vt[1]) if vt and vt[0] == "t" else [None] * len(s.names)
            if vt and vt[0] == "t" and len(elems) != len(s.names):
                self.err(s.line, "the pattern names %d values and the tuple has %d" % (len(s.names), len(elems)), "E0755")
                elems = [None] * len(s.names)
            for n, et in zip(s.names, elems):
                sc.declare(n, s.mut, et)
        elif k == "if":
            self.expr(s.cond, sc)
            self.block(s.then, sc)
            if s.els is not None:
                if s.els.kind == "if":
                    self.stmt(s.els, sc)
                else:
                    self.block(s.els, sc)
        elif k == "while" or k == "dowhile":
            self.expr(s.cond, sc)
            self.block(s.body, sc)
        elif k == "for":
            it = self.expr(s.iter, sc)
            inner = Scope(sc)
            et = None
            if s.iter.kind == "binary" and s.iter.op in ("..", "..="):
                et = self.expr(s.iter.left, sc)
            elif it and it[0] == "a":
                et = it[1]
            for v in s.vars:
                inner.declare(v, False, et, "loop")
            self.block(s.body, inner)
        elif k == "return":
            if s.value is not None:
                vt = self.expr(s.value, sc)
                fn = self.fn
                if fn is not None and getattr(fn, "ret", None) is not None and fn.kind == "fn":
                    rt = tnode(fn.ret)
                    if rt is not None and vt is not None:
                        self.assignable(s.line, rt, vt, "return")
        elif k == "throw":
            self.expr(s.value, sc)
        elif k == "defer":
            if s.body.kind == "block":
                self.block(s.body, sc)
            else:
                self.expr(s.body, sc)
        elif k == "try":
            inner = Scope(sc)
            for name, ty, init in s.resources:
                self.expr(init, sc)
                inner.declare(name, False, tnode(ty))
            self.block(s.body, inner)
            for c in s.catches:
                cs = Scope(sc)
                cs.declare(c.var, False, tnode(c.types[0]) if c.types else None)
                self.block(c.body, cs)
            if s.fin is not None:
                self.block(s.fin, sc)
        elif k in ("unsafe", "sync"):
            if k == "sync":
                self.expr(s.lock, sc)
            self.block(s.body, sc)
        elif k == "expr":
            self.expr(s.value, sc)
        elif k == "assign":
            self.assign_target(s.target, sc, s.line, s.op)
            tt = self.expr(s.target, sc, as_target=True)
            vt = self.expr(s.value, sc)
            if s.op == "=" and tt is not None and vt is not None:
                self.assignable(s.line, tt, vt, "assignment")
        elif k == "incdec":
            self.assign_target(s.target, sc, s.line, s.op)
            self.expr(s.target, sc)

    def assign_target(self, t, sc, line, op):
        # the root binding of an assignment must be mutable, unless the write goes through a reference
        # (a class instance's field, an array element, a deref)
        self._indexed = False
        root, through = self.root_of(t)
        if root is None:
            return
        v = sc.find(root.name)
        if v is None:
            return
        if v["kind"] == "self":
            return
        if not through:
            if not v["mut"]:
                self.err(line, "cannot assign to immutable `%s` (declare it `let mut`)" % root.name, "E0004")
            return
        # a write *through* a binding: fine for a class instance, a pointer, an array; an error for a
        # struct value held in a `let`
        vt = v.get("type")
        st = strip(vt)
        if st and st[0] == "n":
            c = self.w.cls(self.fi, st[1])
            if c is not None and c.kind == "struct" and not v["mut"] and not v.get("mutparam") and not self._indexed:
                self.err(line, "cannot assign to a field of the struct value `%s` (declare it `let mut`)" % root.name, "E0004")

    def root_of(self, t):
        through = False
        while True:
            if t.kind == "name":
                return t, through
            if t.kind == "field":
                through = True
                t = t.value
            elif t.kind in ("index", "tuple_index"):
                if t.kind == "index":
                    self._indexed = True
                through = True
                t = t.value
            elif t.kind == "paren":
                t = t.value
            elif t.kind == "deref":
                return None, False
            else:
                return None, False

    # -- expressions: each returns a type tuple or None --
    def expr(self, e, sc, as_target=False):
        k = e.kind
        m = getattr(self, "e_" + k, None)
        if m is None:
            return None
        return m(e, sc)

    def e_int(self, e, sc):
        return T("i32")

    def e_float(self, e, sc):
        return T("f64")

    def e_str(self, e, sc):
        for p in e.parts:
            if isinstance(p, Node):
                self.expr(p, sc)
        return T("string")

    def e_lit(self, e, sc):
        if e.value in ("true", "false"):
            return T("bool")
        return None

    def e_paren(self, e, sc):
        return self.expr(e.value, sc)

    def e_tuple(self, e, sc):
        return ("t", tuple(self.expr(x, sc) for x in e.elems))

    def e_array(self, e, sc):
        ts = [self.expr(x, sc) for x in e.elems]
        return ("a", ts[0] if ts else None, False)

    def e_unsupported(self, e, sc):
        return None

    def e_lambda(self, e, sc):
        inner = Scope(sc)
        for p in e.params:
            inner.declare(p.name, False, tnode(p.type), "param")
        if e.body.kind == "block":
            self.block(e.body, inner)
        else:
            self.expr(e.body, inner)
        return ("f", (), None)

    def e_name(self, e, sc):
        n = e.name
        v = sc.find(n)
        if v is not None:
            return v["type"]
        if self.resolvable(n):
            c = self.w.cls(self.fi, n)
            return None
        self.err(e.line, "undefined name `%s`" % n, "E0014")
        return None

    def resolvable(self, n):
        if n in PRELUDE or n in self.fi.fns or n in self.fi.consts or n in self.fi.classes or n in self.fi.imports:
            return True
        if n in self.generics:
            return True
        if self.fi.root == "smalt":
            return True
        return False

    def e_new(self, e, sc):
        for a in e.args:
            self.expr(a.value, sc)
        name = e.name.split("::")[-1]
        ci = self.w.cls(self.fi, name)
        if ci is None:
            if name not in self.fi.imports and name not in PRELUDE and name not in self.fi.classes and name not in self.generics:
                self.err(e.line, "unknown type `%s`" % name, "E0014")
            return T(name, [tnode(t) for t in e.targs])
        if ci.kind in ("trait",):
            self.err(e.line, "cannot instantiate trait `%s`" % name, "E0001")
        elif ci.kind == "struct":
            self.err(e.line, "`new` on struct `%s`: a struct is built with a literal" % name, "E0001")
        else:
            self.check_ctor(ci, e.args, e.line)
        t = T(name, [tnode(x) for x in e.targs])
        if e.shared:
            return T("Shared", [t])
        return t

    def check_ctor(self, ci, args, line):
        n = len(args)
        if not ci.ctors:
            if n != 0 and ci.kind != "exception":
                # a class with no constructor may still be built from its inherited one
                base = self.base_of(ci)
                if base is not None:
                    return self.check_ctor(base, args, line)
                self.err(line, "`%s` has no constructor taking %d argument(s)" % (ci.name, n), "E0001")
            return
        if not any(len(c.params) == n for c in ci.ctors):
            self.err(line, "`%s` has no constructor of %d argument(s) (it has %s)" % (
                ci.name, n, ", ".join(str(len(c.params)) for c in ci.ctors)), "E0001")

    def base_of(self, ci):
        for s in ci.supers:
            if s is None:
                continue
            c = self.w.cls(self.fi, s[1])
            if c is not None and c.kind in ("class", "exception"):
                return c
        return None

    def e_struct_lit(self, e, sc):
        name = e.name.split("::")[-1]
        ci = self.w.cls(self.fi, name)
        given = set()
        for fname, val, ln in e.fields:
            self.expr(val, sc)
            given.add(fname)
        bt = None
        if e.base is not None:
            bt = self.expr(e.base, sc)
        if ci is None:
            return T(name)
        if ci.kind != "struct":
            self.err(e.line, "`%s` is not a struct" % name, "E0001")
            return T(name)
        fields = ci.fields
        for fname, val, ln in e.fields:
            if fname not in fields:
                self.err(ln, "struct `%s` has no field `%s`" % (name, fname), "E0001")
        if e.base is None:
            missing = [f for f, m in fields.items() if m.default is None and f not in given]
            if missing:
                self.err(e.line, "struct literal `%s` omits field(s) %s that have no default" % (name, ", ".join(missing)), "E0743")
        elif bt is not None and bt[0] == "n" and bt[1] != name:
            self.err(e.line, "`..base` is a `%s`, the literal is a `%s`" % (bt[1], name), "E0747")
        return T(name)

    def e_catch_expr(self, e, sc):
        t = self.expr(e.value, sc)
        inner = Scope(sc)
        inner.declare(e.var, False, None)
        self.block(e.body, inner)
        return t

    def e_ternary(self, e, sc):
        self.expr(e.cond, sc)
        a = self.expr(e.then, sc)
        self.expr(e.els, sc)
        return a

    def e_cast(self, e, sc):
        self.expr(e.value, sc)
        return tnode(e.type)

    def e_is(self, e, sc):
        self.expr(e.value, sc)
        return T("bool")

    def e_await(self, e, sc):
        t = self.expr(e.value, sc)
        if t and t[0] == "n" and t[1] == "Future" and t[2]:
            return t[2][0]
        return None

    def e_spawn(self, e, sc):
        self.expr(e.value, sc)
        return None

    def e_deref(self, e, sc):
        self.expr(e.value, sc)
        return None

    def e_unary(self, e, sc):
        t = self.expr(e.value, sc)
        if e.op == "!":
            return T("bool")
        if e.op == "&":
            return None
        return t

    def e_binary(self, e, sc):
        a = self.expr(e.left, sc)
        b = self.expr(e.right, sc)
        op = e.op
        if op in ("==", "!=", "===", "<", "<=", ">", ">=", "&&", "||"):
            return T("bool")
        if op in ("..", "..="):
            return None
        if op == "??":
            return strip(a) if a else b
        # arithmetic: the type of an operand that is not a bare literal
        if a is not None and b is not None and a[0] == "n" and b[0] == "n":
            sa, sb = a[1], b[1]
            if sa in INTS | FLOATS and sb in INTS | FLOATS:
                if (sa in INTS) != (sb in INTS) and not self.is_lit(e.left) and not self.is_lit(e.right):
                    if not (sa in INTS and sb in FLOATS and sa in ("i8", "i16", "i32", "u8", "u16", "u32")):
                        pass
                if op not in ("<<", ">>", ">>>"):
                    if sa in INTS and sb in INTS and (sa[0] == "u") != (sb[0] == "u") \
                            and not self.is_lit(e.left) and not self.is_lit(e.right):
                        self.err(e.line, "`%s` mixes %s and %s: say which with a cast" % (op, sa, sb), "E0037")
                if sa in FLOATS or sb in FLOATS:
                    return T("f64") if "f64" in (sa, sb) else T("f32")
                return a if not self.is_lit(e.left) else b
        if a is not None and (self.is_lit(e.right) or b is None):
            return a
        if b is not None and self.is_lit(e.left):
            return b
        return a or b

    def is_lit(self, n):
        while n.kind in ("paren",):
            n = n.value
        if n.kind in ("int", "float"):
            return True
        if n.kind == "unary" and n.op == "-":
            return self.is_lit(n.value)
        return False

    def e_index(self, e, sc):
        t = self.expr(e.value, sc)
        self.expr(e.index, sc)
        if t and t[0] == "a":
            return t[1]
        return None

    def e_tuple_index(self, e, sc):
        t = self.expr(e.value, sc)
        if t and t[0] == "t":
            try:
                return t[1][int(e.index)]
            except (ValueError, IndexError):
                return None
        return None

    def e_match(self, e, sc):
        st = None
        if e.subject is not None:
            st = self.expr(e.subject, sc)
        enum = None
        sstrip = strip(st)
        if sstrip and sstrip[0] == "n":
            c = self.w.cls(self.fi, sstrip[1])
            if c is not None and c.kind == "enum":
                enum = c
        covered = set()
        wild = False
        result = None
        for a in e.arms:
            inner = Scope(sc)
            for p in a.pats:
                self.pattern(p, inner, enum)
                if p.kind in ("pat_wild",):
                    wild = True
                if p.kind == "pat_name" and "::" not in p.name:
                    if enum is None or p.name not in enum.variants:
                        wild = True
                    else:
                        covered.add(p.name)
                if p.kind in ("pat_variant",) :
                    covered.add(p.name.split("::")[-1])
                if p.kind == "pat_name" and "::" in p.name:
                    covered.add(p.name.split("::")[-1])
            if a.guard is not None:
                self.expr(a.guard, inner)
            if a.body.kind == "block":
                self.block(a.body, inner)
            else:
                t = self.expr(a.body, inner)
                if result is None:
                    result = t
        if enum is not None and not wild:
            guarded = {p.name.split("::")[-1] for a in e.arms if a.guard is not None for p in a.pats if hasattr(p, "name")}
            missing = [v for v in enum.variants if v not in covered]
            if missing and e.subject is not None:
                self.err(e.line, "`match` over %s does not cover %s" % (enum.name, ", ".join(missing)), "E0001")
        return result

    def pattern(self, p, sc, enum):
        k = p.kind
        if k == "pat_name":
            n = p.name
            if "::" in n:
                ename, vname = n.split("::")[-2], n.split("::")[-1]
                ec = self.w.cls(self.fi, ename)
                if ec is not None and ec.kind == "enum" and vname not in ec.variants:
                    self.err(p.line, "enum `%s` has no variant `%s`" % (ename, vname), "E0015")
                return
            if enum is not None and n in enum.variants:
                return
            if n[:1].isupper() and (n in self.fi.consts or n in self.fi.imports or n in self.fi.classes):
                return
            sc.declare(n, False, None)
        elif k == "pat_variant":
            parts = p.name.split("::")
            ec = None
            if len(parts) >= 2:
                ec = self.w.cls(self.fi, parts[-2])
                if ec is not None and ec.kind == "enum" and parts[-1] not in ec.variants:
                    self.err(p.line, "enum `%s` has no variant `%s`" % (parts[-2], parts[-1]), "E0015")
            elif enum is not None:
                ec = enum
                if parts[0] not in enum.variants:
                    self.err(p.line, "enum `%s` has no variant `%s`" % (enum.name, parts[0]), "E0015")
            vnode = ec.variants.get(parts[-1]) if ec is not None and ec.kind == "enum" else None
            if vnode is not None and len(vnode.payload) != len(p.subs):
                self.err(p.line, "variant `%s` carries %d value(s), the pattern binds %d" % (parts[-1], len(vnode.payload), len(p.subs)), "E0001")
            for i, sp in enumerate(p.subs):
                self.pattern(sp, sc, None)
        elif k == "pat_tuple":
            for sp in p.elems:
                self.pattern(sp, sc, None)
        elif k == "pat_struct":
            for f in p.fields:
                sc.declare(f, False, None)

    def e_path(self, e, sc):
        # Type::member, Module::member, Enum::Variant
        root = e.value
        if root.kind == "name":
            n = root.name
            if sc.find(n) is None:
                ci = self.w.cls(self.fi, n)
                if ci is not None:
                    return self.type_member(ci, e.name, e.line, call=False)
                if n in self.fi.modules or n in PRELUDE or n in self.generics:
                    return None
                if n in self.fi.imports or n in self.fi.classes:
                    return None
                if self.fi.root != "smalt":
                    self.err(e.line, "undefined name `%s`" % n, "E0014")
                return None
        else:
            self.expr(root, sc)
        return None

    def type_member(self, ci, name, line, call):
        if ci.kind == "enum" and name in ci.variants:
            return T(ci.name)
        if name in ci.statics:
            return ci.statics[name]
        if name in ci.methods:
            return None
        base = self.base_of(ci)
        if base is not None:
            return self.type_member(base, name, line, call)
        # constants in a trait's impl, associated consts: unknown members are errors only for crate-local types
        if ci.file in self.w.crate_files or ci.file in self.fi.path:
            self.err(line, "`%s` has no member `%s`" % (ci.name, name), "E0015")
        return None

    def e_field(self, e, sc):
        recv = self.expr(e.value, sc)
        rs = strip(recv)
        if rs is None or rs[0] != "n":
            if rs is not None and rs[0] == "t":
                return None
            return None
        name = rs[1]
        ci = self.w.cls(self.fi, name)
        if ci is None:
            return None
        if getattr(e, "safe", False):
            pass
        return self.member_type(ci, rs, e.name, e.line, False)

    def member_type(self, ci, recv_t, name, line, is_call):
        """The type of `recv.name`: a field's, or None for a method (after checking it exists)."""
        subst = dict(zip(ci.generics, recv_t[2])) if recv_t and recv_t[0] == "n" else {}
        if name in ci.fields:
            return self.subst(tnode(ci.fields[name].type), subst)
        if name in ci.methods:
            return None
        if ci.kind == "enum" or ci.kind == "struct" or ci.kind == "class" or ci.kind == "exception" or ci.kind == "trait":
            for s in ci.supers:
                if s is None:
                    continue
                sc = self.w.cls(self.fi, s[1])
                if sc is None:
                    # a super type the checker does not know (a stdlib trait): cannot say
                    return None
                r = self.member_type_opt(sc, name)
                if r is not False:
                    return r
        if ci.name in ("string",):
            return None
        if ci.file in self.w.crate_files or ci.file.startswith(os.path.dirname(self.fi.path)) or True:
            if ci.kind != "trait" or True:
                self.err(line, "`%s` has no %s `%s`" % (ci.name, "method" if is_call else "member", name), "E0015")
        return None

    def member_type_opt(self, ci, name):
        if name in ci.fields:
            return tnode(ci.fields[name].type)
        if name in ci.methods:
            return None
        for s in ci.supers:
            if s is None:
                continue
            sc = self.w.cls(self.fi, s[1])
            if sc is None:
                return None
            r = self.member_type_opt(sc, name)
            if r is not False:
                return r
        return False

    def subst(self, t, m):
        if t is None or not m:
            return t
        if t[0] == "n":
            if t[1] in m and not t[2]:
                return m[t[1]]
            return ("n", t[1], tuple(self.subst(a, m) for a in t[2]))
        if t[0] == "a":
            return ("a", self.subst(t[1], m), t[2])
        if t[0] == "null":
            return ("null", self.subst(t[1], m))
        if t[0] == "t":
            return ("t", tuple(self.subst(x, m) for x in t[1]))
        return t

    def e_call(self, e, sc):
        c = e.callee
        n = len(e.args)
        if c.kind == "name" and c.name == "offsetof":
            return T("i64")
        argts = [self.expr(a.value, sc) for a in e.args]
        if c.kind == "name":
            name = c.name
            v = sc.find(name)
            if v is not None:
                t = v["type"]
                if t and t[0] == "f":
                    return t[2]
                return None
            fns = None
            if name in self.fi.fns:
                fns = [self.fi.fns[name]]
            elif name in self.fi.classes and self.fi.classes[name].kind in ("class",):
                self.err(e.line, "`%s(...)` — a class is built with `new`" % name, "E0001")
                return None
            elif name in self.fi.imports:
                src, orig = self.fi.imports[name]
                if src in ("crate", "gesso"):
                    fns = self.w.crate_fns.get(orig)
            elif name in PRELUDE or name in self.generics:
                return None
            else:
                self.err(e.line, "undefined name `%s`" % name, "E0014")
                return None
            if fns:
                if not any(f.arity == n for f in fns):
                    self.err(e.line, "`%s` takes %s argument(s), %d given" % (name, "/".join(str(f.arity) for f in fns), n), "E0001")
                return fns[0].ret
            return None
        if c.kind == "path":
            root = c.value
            if root.kind == "name" and sc.find(root.name) is None:
                rn = root.name
                ci = self.w.cls(self.fi, rn)
                if ci is not None:
                    return self.static_call(ci, c.name, n, e.line)
                if rn in self.fi.modules or rn in PRELUDE or rn in self.generics or rn in self.fi.imports:
                    return None
                if self.fi.root != "smalt":
                    self.err(e.line, "undefined name `%s`" % rn, "E0014")
                return None
            self.expr(root, sc)
            return None
        if c.kind == "field":
            recv = self.expr(c.value, sc)
            rs = strip(recv)
            if rs is None:
                return None
            if rs[0] == "n":
                name = rs[1]
                ci = self.w.cls(self.fi, name)
                if ci is None:
                    return None
                return self.method_call(ci, rs, c.name, n, e.line)
            if rs[0] == "f":
                return None
            return None
        self.expr(c, sc)
        return None

    def static_call(self, ci, name, n, line):
        if ci.kind == "enum" and name in ci.variants:
            v = ci.variants[name]
            if len(v.payload) != n:
                self.err(line, "variant `%s::%s` carries %d value(s), %d given" % (ci.name, name, len(v.payload), n), "E0001")
            return T(ci.name)
        for cc in self.chain(ci):
            if name in cc.methods:
                fns = cc.methods[name]
                if not any(f.arity == n for f in fns):
                    self.err(line, "`%s::%s` takes %s argument(s), %d given" % (cc.name, name, "/".join(str(f.arity) for f in fns), n), "E0001")
                f = fns[0]
                if not f.static and f.has_self:
                    pass
                return f.ret
        if ci.file in self.w.crate_files:
            self.err(line, "`%s` has no function `%s`" % (ci.name, name), "E0015")
        return None

    def chain(self, ci):
        out = [ci]
        seen = {ci.name}
        i = 0
        while i < len(out):
            for s in out[i].supers:
                if s is None:
                    continue
                sc = self.w.cls(self.fi, s[1])
                if sc is not None and sc.name not in seen:
                    seen.add(sc.name)
                    out.append(sc)
            i += 1
        return out

    def method_call(self, ci, recv_t, name, n, line):
        subst = dict(zip(ci.generics, recv_t[2])) if recv_t[0] == "n" else {}
        # a function-typed field being called
        for cc in self.chain(ci):
            if name in cc.fields:
                ft = tnode(cc.fields[name].type)
                if ft and ft[0] == "f":
                    return ft[2]
        for cc in self.chain(ci):
            if name in cc.methods:
                fns = cc.methods[name]
                if not any(f.arity == n for f in fns):
                    self.err(line, "`%s.%s` takes %s argument(s), %d given" % (ci.name, name, "/".join(str(f.arity) for f in fns), n), "E0001")
                return self.subst(fns[0].ret, subst)
        # supers the checker could not resolve (stdlib traits) make the question unanswerable
        for cc in self.chain(ci):
            for s in cc.supers:
                if s is not None and self.w.cls(self.fi, s[1]) is None:
                    return None
        if ci.kind == "struct" or ci.kind == "enum" or ci.kind == "class" or ci.kind == "trait" or ci.kind == "exception":
            self.err(line, "`%s` has no method `%s`" % (ci.name, name), "E0015")
        return None

    def assignable(self, line, want, got, what):
        # only certain, class-versus-class mismatches are reported
        w, g = strip(want), strip(got)
        if w is None or g is None or w[0] != "n" or g[0] != "n":
            return
        if w[1] == g[1]:
            return
        wc = self.w.cls(self.fi, w[1])
        gc = self.w.cls(self.fi, g[1])
        if wc is None or gc is None:
            return
        if wc.kind == "class" and gc.kind == "class":
            # a subclass is assignable to its base
            if any(c.name == wc.name for c in self.chain(gc)):
                return
            self.err(line, "%s: expected `%s`, found `%s`" % (what, show(want), show(got)), "E0001")
        if wc.kind == "struct" and gc.kind == "struct":
            self.err(line, "%s: expected `%s`, found `%s`" % (what, show(want), show(got)), "E0001")


# ─── Driving ─────────────────────────────────────────────────────────────────────────

def load(root, smalt_root=None):
    w = World()
    errors = []
    parsed = []
    for kind, base in (("crate", os.path.join(root, "src")), ("smalt", smalt_root)):
        if not base or not os.path.isdir(base):
            continue
        for dp, _, names in os.walk(base):
            for n in sorted(names):
                if not n.endswith(".axle"):
                    continue
                path = os.path.join(dp, n)
                try:
                    items = parse(open(path, encoding="utf-8").read())
                except ParseError as ex:
                    if kind == "crate":
                        errors.append("%s:%d: [parse] %s" % (os.path.relpath(path, root), ex.line, ex.msg))
                    continue
                fi = FileInfo(os.path.relpath(path, root) if kind == "crate" else path, kind, items)
                w.add(fi, kind == "smalt")
                if kind == "crate":
                    parsed.append(fi)
    return w, parsed, errors


def examples_load(root, w):
    out = []
    errors = []
    base = os.path.join(root, "examples")
    if not os.path.isdir(base):
        return out, errors
    for dp, _, names in os.walk(base):
        for n in sorted(names):
            if n.endswith(".axle"):
                path = os.path.join(dp, n)
                try:
                    items = parse(open(path, encoding="utf-8").read())
                except ParseError as ex:
                    errors.append("%s:%d: [parse] %s" % (os.path.relpath(path, root), ex.line, ex.msg))
                    continue
                fi = FileInfo(os.path.relpath(path, root), "crate", items)
                out.append(fi)
    return out, errors


def check_tree(root, smalt_root=None):
    w, files, errors = load(root, smalt_root)
    ex, e2 = examples_load(root, w)
    errors += e2
    for fi in files + ex:
        Checker(w, fi, errors).run()
    return errors


if __name__ == "__main__":
    root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    errs = check_tree(root, os.path.join(root, "vendor", "smalt", "src"))
    for e in errs:
        print(e)
    print("axcheck: %d problem(s)" % len(errs))
    sys.exit(1 if errs else 0)
