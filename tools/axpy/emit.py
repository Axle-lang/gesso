"""emit.py — Axle's tree, as Python source.

Translates the subset this repository is written in so that the *real* source can be run: the
numeric kernels against FreeType and HarfBuzz, the layout against expected boxes, the gallery to a
picture. It is a translator, not a second implementation — nothing here knows what a button is.

Where Axle and Python differ, and what is done about it:
  struct values    copied on assignment, `let`, return and array store (`cp`), as a struct is a value
  integer `/` `%`  `div` / `rem`: truncate toward zero, trap on zero
  `as`             `cast`: float → int truncates and saturates, int → narrower int wraps
  locals           renamed uniquely per function, so an inner `let x` does not clobber an outer one
  `match`          an `if` chain; as an expression, a nested function closing over the locals
  constructors     overloaded by arity and then by the argument types; field initialisers run after
                   `super(…)`, as the language specifies
  traits           Python classes holding the default methods; a class lists them as extra bases
  enums            one class per enum; every variant a value (name, number, payload)
  strings          Python `str`; `byteLength` / `byteAt` look at the UTF-8 encoding
"""
import keyword
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from axparse import Node  # noqa: E402

PY_RESERVED = set(keyword.kwlist) | {
    "print", "len", "list", "int", "float", "str", "min", "max", "abs", "range", "type", "id", "object", "set",
    "dict", "tuple", "map", "filter", "sum", "all", "any", "iter", "next", "input", "open", "round", "format",
    "hash", "vars", "dir", "zip", "callable", "isinstance", "super", "bool", "enumerate", "reversed", "sorted",
    "cast", "div", "rem", "ushr", "cp", "malloc", "prim", "call", "Struct", "EnumBase", "Trap", "wrap",
}
RUNTIME_NAMES = {
    "Mem", "SlotIndex", "AssetFile", "Rect", "Frame", "Surface", "StringBuilder", "println", "IOException",
    "FileNotFoundException", "ParseException", "IndexOutOfBoundsException", "IllegalStateException",
    "IllegalArgumentException", "ArithmeticException", "PlatformError", "AxleError", "nanoTime", "now", "pid", "parentPid", "panicMsg", "sysinfo", "UnsupportedOperationException",
}
PRIM_METHODS = {"min", "max", "abs", "sqrt", "sin", "cos", "pow", "floorToInt", "ceilToInt", "truncToInt", "round",
                "toString", "isEmpty", "equals", "substring", "charAt", "byteAt"}
INT_TYPES = {"i8", "i16", "i32", "i64", "u8", "u16", "u32", "u64", "char"}
FLOAT_TYPES = {"f32", "f64"}


def mangle(name):
    return name + "_" if name in PY_RESERVED else name


def attr(name):
    return name + "_" if keyword.iskeyword(name) or name in ("None", "True", "False") else name


class EmitError(Exception):
    pass


class Emitter:
    def __init__(self):
        self.decls = {}          # name -> node (class/struct/enum/trait/exception)
        self.fns = {}            # name -> node
        self.consts = {}
        self.out = []
        self.uid = 0

    # ─── Collection ─────────────────────────────────────────────────────────────────

    def add_file(self, items):
        for it in items:
            if it.kind in ("class", "struct", "enum", "trait", "exception"):
                self.decls[it.name] = it
            elif it.kind == "fn":
                self.fns[it.name] = it
            elif it.kind == "const":
                self.consts[it.name] = it
            elif it.kind == "extern_block":
                pass

    def kind_of(self, name):
        d = self.decls.get(name)
        return d.kind if d is not None else None

    # ─── Module ─────────────────────────────────────────────────────────────────────

    def emit(self):
        w = self.w = []
        w.append("from axpy.rt import *")
        w.append("from axpy.rt import _rt_dispatch, _rt_lit")
        w.append("from axpy import rt as _rt")
        w.append("")
        for n, c in self.consts.items():
            self.fn_ctx = None
            w.append("%s = %s" % (mangle(n), self.expr_top(c.value)))
        for d in self.order():
            self.emit_decl(d)
        for n, f in self.fns.items():
            self.emit_fn(f, 0, None)
        return "\n".join(w) + "\n"

    def order(self):
        done, out = set(), []

        def visit(name):
            if name in done or name not in self.decls:
                return
            done.add(name)
            d = self.decls[name]
            for s in d.supers:
                if s.kind == "type":
                    visit(s.name.split("::")[-1])
            out.append(d)
        for n in self.decls:
            visit(n)
        return out

    # ─── Declarations ───────────────────────────────────────────────────────────────

    def bases_of(self, d, default):
        bases = []
        traits = []
        for s in d.supers:
            if s.kind != "type":
                continue
            n = s.name.split("::")[-1]
            k = self.kind_of(n)
            if k in ("class", "exception") and not bases:
                bases.append(mangle(n))
            elif k == "trait":
                traits.append(mangle(n))
            elif n in RUNTIME_NAMES:
                bases.append(n)
        if not bases and default and (default != "object" or not traits):
            bases = [default]
        return bases + traits

    def emit_decl(self, d):
        k = d.kind
        if k == "struct":
            self.emit_struct(d)
        elif k == "enum":
            self.emit_enum(d)
        elif k == "trait":
            self.emit_trait(d)
        else:
            self.emit_class(d)

    def zero_of(self, ty):
        """Python source for the zero value of an Axle type."""
        if ty is None:
            return "None"
        if ty.kind == "type":
            n = ty.name.split("::")[-1]
            if n in INT_TYPES:
                return "0"
            if n in FLOAT_TYPES:
                return "0.0"
            if n == "bool":
                return "False"
            if n == "string":
                return "''"
            k = self.kind_of(n)
            if k == "struct":
                return "%s._zero()" % mangle(n)
            if k == "enum":
                d = self.decls[n]
                return "%s.%s" % (mangle(n), attr(d.variants[0].name))
            return "None"
        if ty.kind == "tuple_type":
            return "(" + ", ".join(self.zero_of(t) for _, t in ty.elems) + ("," if len(ty.elems) == 1 else "") + ")"
        return "None"

    def emit_members_common(self, d, indent, cname, is_struct=False, is_enum=False):
        w = self.w
        pad = "    " * indent
        fields = [m for m in d.members if m.kind == "field" and not m.static]
        statics = [m for m in d.members if m.kind == "field" and m.static]
        methods = [m for m in d.members if m.kind == "fn"]
        for m in d.members:
            if m.kind == "when":
                fields += [x for x in m.members if x.kind == "field" and not x.static]
                methods += [x for x in m.members if x.kind == "fn"]
        for st in statics:
            self.fn_ctx = None
            w.append("%s    %s = %s" % (pad, attr(st.name), self.expr_top(st.default) if st.default is not None else self.zero_of(st.type)))
        for fn in methods:
            self.emit_fn(fn, indent + 1, d)
        return fields

    def emit_struct(self, d):
        w = self.w
        cname = mangle(d.name)
        bases = ["Struct"] + [b for b in self.bases_of(d, None)]
        w.append("class %s(%s):" % (cname, ", ".join(bases)))
        fields = self.emit_members_common(d, 0, cname, is_struct=True)
        names = [attr(f.name) for f in fields]
        w.append("    _fields = (%s)" % "".join("'%s', " % n for n in names))
        defaults = []
        for f in fields:
            if f.default is not None:
                self.fn_ctx = None
                defaults.append("'%s': lambda: %s" % (attr(f.name), self.expr_top(f.default)))
        w.append("    _defaults = {%s}" % ", ".join(defaults))
        w.append("    _zero_of = {%s}" % ", ".join("'%s': lambda: %s" % (attr(f.name), self.zero_of(f.type)) for f in fields))
        w.append("")

    def emit_trait(self, d):
        w = self.w
        cname = mangle(d.name)
        supers = [mangle(s.name.split("::")[-1]) for s in d.supers if s.kind == "type" and self.kind_of(s.name.split("::")[-1]) == "trait"]
        w.append("class %s(%s):" % (cname, ", ".join(supers) if supers else "object"))
        w.append("    pass")
        for m in d.members:
            if m.kind == "fn" and m.body is not None:
                self.emit_fn(m, 1, d)
        w.append("")

    def emit_enum(self, d):
        w = self.w
        cname = mangle(d.name)
        bases = ["EnumBase"] + self.bases_of(d, None)
        w.append("class %s(%s):" % (cname, ", ".join(bases)))
        self.emit_members_common(d, 0, cname, is_enum=True)
        w.append("    pass")
        # variants after the class exists
        value = 0
        for v in d.variants:
            if v.value is not None:
                self.fn_ctx = None
                value_src = self.expr_top(v.value)
                try:
                    value = int(eval(value_src))
                except Exception:
                    pass
            if v.payload:
                w.append("%s.%s = staticmethod(lambda *a: %s(%r, %d, tuple(a)))" % (cname, attr(v.name), cname, v.name, value))
                w.append("%s._tag_%s = %s(%r, %d, ())" % (cname, attr(v.name), cname, v.name, value))
            else:
                w.append("%s.%s = %s(%r, %d, ())" % (cname, attr(v.name), cname, v.name, value))
            value += 1
        w.append("")

    def class_ctors(self, d):
        ctors = [m for m in d.members if m.kind == "constructor"]
        return ctors

    def emit_class(self, d):
        w = self.w
        cname = mangle(d.name)
        default = "AxleError" if d.kind == "exception" else "object"
        bases = self.bases_of(d, default)
        w.append("class %s(%s):" % (cname, ", ".join(bases)))
        w.append("    _cname = %r" % d.name)
        fields = self.emit_members_common(d, 0, cname)
        base_name = None
        for s in d.supers:
            if s.kind == "type":
                n = s.name.split("::")[-1]
                if self.kind_of(n) in ("class", "exception") or n in RUNTIME_NAMES:
                    base_name = n
                    break
        # field initialisers of this class
        w.append("    def _fi_%s(self):" % cname)
        any_field = False
        for f in fields:
            any_field = True
            self.fn_ctx = FnCtx(self)
            self.fn_ctx.declare("self", "self")
            self.fn_ctx.owner = d
            if f.default is not None:
                w.append("        self.%s = %s" % (attr(f.name), self.fn_expr(f.default)))
            else:
                w.append("        self.%s = %s" % (attr(f.name), self.zero_of(f.type)))
        if not any_field:
            w.append("        pass")
        # An object is allocated zeroed; initialisers run only in a constructor, and a base's only when the
        # derived constructor reaches it with `super(...)`. `_zero_*` is the zeroed state a class starts from.
        w.append("    def _zero_%s(self):" % cname)
        w.append("        pass")
        base_decl0 = self.decls.get(base_name) if base_name else None
        if base_decl0 is not None and self.class_has_ctor_dispatch(base_decl0):
            w.append("        %s._zero_%s(self)" % (mangle(base_name), mangle(base_name)))
        for f in fields:
            self.fn_ctx = FnCtx(self)
            w.append("        self.%s = %s" % (attr(f.name), self.zero_of(f.type)))
        # constructors
        ctors = self.class_ctors(d)
        base_decl = self.decls.get(base_name) if base_name else None
        cinfo = []
        if not ctors:
            w.append("    def _c0(self):")
            if base_name in RUNTIME_NAMES:
                w.append("        %s.__init__(self)" % base_name)
            elif base_decl is not None and self.class_has_ctor_dispatch(base_decl):
                w.append("        %s._zero_%s(self)" % (mangle(base_name), mangle(base_name)))
            # `new C()` on a class with no constructor runs the field initialisers (the implicit one)
            w.append("        self._fi_%s()" % cname)
            cinfo.append((0, []))
        for i, c in enumerate(ctors):
            self.emit_ctor(d, c, i, cname, base_name)
            cinfo.append((len(c.params), [self.checker(p.type) for p in c.params]))
        w.append("    _ctors = [%s]" % ", ".join("(%d, [%s], '_c%d')" % (a, ", ".join(chk), i) for i, (a, chk) in enumerate(cinfo)))
        w.append("    def __init__(self, *args):")
        w.append("        _rt_dispatch(%s, self, args)" % cname)
        w.append("    @classmethod")
        w.append("    def _dispatch(cls, self, args):")
        w.append("        _rt_dispatch(cls, self, args)")
        w.append("")

    def class_has_ctor_dispatch(self, d):
        return d.kind in ("class", "exception")

    def checker(self, ty):
        """A predicate (source) that says whether a runtime value suits a declared type."""
        if ty is None:
            return "lambda v: True"
        if ty.kind == "nullable":
            return "lambda v: v is None or (%s)(v)" % self.checker(ty.inner)
        if ty.kind == "array_type":
            return "lambda v: isinstance(v, list)"
        if ty.kind == "ftype":
            return "lambda v: callable(v)"
        if ty.kind == "tuple_type":
            return "lambda v: isinstance(v, tuple)"
        n = ty.name.split("::")[-1]
        if n in INT_TYPES:
            return "lambda v: isinstance(v, int) and not isinstance(v, bool)"
        if n in FLOAT_TYPES:
            return "lambda v: isinstance(v, (int, float)) and not isinstance(v, bool)"
        if n == "bool":
            return "lambda v: isinstance(v, bool)"
        if n == "string":
            return "lambda v: isinstance(v, str)"
        if n in ("Shared", "Weak") and ty.args:
            return self.checker(ty.args[0])
        k = self.kind_of(n)
        if k in ("class", "struct", "enum", "trait", "exception"):
            return "lambda v: isinstance(v, %s)" % mangle(n)
        return "lambda v: True"

    def emit_ctor(self, d, c, i, cname, base_name):
        w = self.w
        ctx = FnCtx(self)
        ctx.owner = d
        self.fn_ctx = ctx
        ctx.declare("self", "self")
        params = []
        for p in c.params:
            params.append(ctx.declare(p.name))
        w.append("    def _c%d(self%s):" % (i, "".join(", " + p for p in params)))
        stmts = list(c.body.stmts)
        lines = []
        first = stmts[0] if stmts else None
        has_super = (first is not None and first.kind == "expr" and first.value.kind == "call"
                     and first.value.callee.kind == "name" and first.value.callee.name == "super")
        base_decl = self.decls.get(base_name) if base_name else None
        if has_super:
            args = [self.fn_expr(a.value) for a in first.value.args]
            lines.extend(ctx.take_pre())
            if base_name in RUNTIME_NAMES:
                lines.append("%s.__init__(self%s)" % (base_name, "".join(", " + a for a in args)))
            else:
                lines.append("%s._dispatch(self, (%s))" % (mangle(base_name), "".join(a + ", " for a in args)))
            stmts = stmts[1:]
        elif base_decl is not None and self.class_has_ctor_dispatch(base_decl):
            # no `super()`: the base's fields stay zeroed, as the compiler leaves them
            lines.append("%s._zero_%s(self)" % (mangle(base_name), mangle(base_name)))
        lines.append("self._fi_%s()" % cname)
        body = ctx.block_lines(stmts)
        lines.extend(body)
        if not body and not lines:
            lines.append("pass")
        for ln in lines:
            w.append("        " + ln)

    # ─── Functions ──────────────────────────────────────────────────────────────────

    def emit_fn(self, fn, indent, owner):
        w = self.w
        pad = "    " * indent
        if fn.body is None:
            return
        ctx = FnCtx(self)
        ctx.owner = owner
        self.fn_ctx = ctx
        has_self = any(p.name == "self" for p in fn.params)
        params = []
        if has_self:
            ctx.declare("self", "self")
        for p in fn.params:
            if p.name != "self":
                params.append(ctx.declare(p.name))
        static = owner is not None and not has_self
        if static:
            w.append("%s@staticmethod" % pad)
        sig = ", ".join((["self"] if has_self else []) + params)
        w.append("%sdef %s(%s):" % (pad, attr(fn.name) if owner is not None else mangle(fn.name), sig))
        body = ctx.function_lines(fn.body)
        if not body:
            body = ["pass"]
        for ln in body:
            w.append(pad + "    " + ln)

    # ─── Expressions at the top level (constants, defaults) ─────────────────────────

    def expr_top(self, e):
        ctx = FnCtx(self)
        self.fn_ctx = ctx
        src = ctx.expr(e)
        if ctx.pre:
            raise EmitError("a constant needs a statement")
        return src

    def fn_expr(self, e):
        return self.fn_ctx.expr(e)


class FnCtx:
    """The state of translating one function body."""

    def __init__(self, em):
        self.em = em
        self.scopes = [{}]
        self.used = {}
        self.pre = []
        self.owner = None
        self.has_defer = False

    # -- names --
    def declare(self, name, py=None):
        if py is None:
            base = mangle(name)
            n = self.used.get(base, 0)
            self.used[base] = n + 1
            py = base if n == 0 else "%s_%d" % (base, n)
        else:
            self.used[py] = self.used.get(py, 0) + 1
        self.scopes[-1][name] = py
        return py

    def lookup(self, name):
        for s in reversed(self.scopes):
            if name in s:
                return s[name]
        return None

    def push(self):
        self.scopes.append({})

    def pop(self):
        self.scopes.pop()

    def temp(self, prefix="_t"):
        self.em.uid += 1
        return "%s%d" % (prefix, self.em.uid)

    def take_pre(self):
        p, self.pre = self.pre, []
        return p

    # -- function bodies --
    def function_lines(self, body):
        # defers wrap the whole body
        if self.contains_defer(body):
            self.has_defer = True
            inner = self.block_lines(body.stmts)
            out = ["_defer = []", "try:"]
            out += ["    " + l for l in (inner or ["pass"])]
            out += ["finally:", "    for _f in reversed(_defer):", "        _f()"]
            return out
        return self.block_lines(body.stmts)

    def contains_defer(self, n):
        if isinstance(n, Node):
            if n.kind == "defer":
                return True
            if n.kind in ("lambda",):
                return False
            return any(self.contains_defer(v) for v in n.f.values())
        if isinstance(n, (list, tuple)):
            return any(self.contains_defer(x) for x in n)
        return False

    def block_lines(self, stmts):
        self.push()
        out = []
        for s in stmts:
            out.extend(self.stmt(s))
        self.pop()
        return out

    def body(self, block):
        lines = self.block_lines(block.stmts) if block.kind == "block" else self.stmt(block)
        return lines or ["pass"]

    def indent(self, lines):
        return ["    " + l for l in lines]

    # -- statements --
    def stmt(self, s):
        k = s.kind
        m = getattr(self, "s_" + k, None)
        if m is None:
            raise EmitError("line %d: cannot translate statement %s" % (s.line, k))
        self.pre = []
        out = m(s)
        pre = self.take_pre()
        return pre + out

    def val(self, e):
        """An expression whose value is stored: copied when it is a struct read from somewhere."""
        src = self.expr(e)
        if e.kind in ("name", "field", "index", "tuple_index", "path") or (e.kind == "paren" and e.value.kind in ("name", "field", "index")):
            return "cp(%s)" % src
        return src

    def s_block(self, s):
        return self.block_lines(s.stmts) or ["pass"]

    def s_empty(self, s):
        return []

    def s_let(self, s):
        if s.value is None:
            py = self.declare(s.name)
            return ["%s = %s" % (py, self.em.zero_of(s.type))]
        src = self.val(s.value)
        # an integer literal flowing into a float
        if s.type is not None and s.type.kind == "type" and s.type.name in FLOAT_TYPES and s.value.kind == "int":
            src = "float(%s)" % src
        py = self.declare(s.name)
        return ["%s = %s" % (py, src)]

    def s_let_tuple(self, s):
        src = self.expr(s.value)
        names = [self.declare(n) for n in s.names]
        return ["%s = %s" % (", ".join(names) + ("," if len(names) == 1 else ""), src)]

    def s_assign(self, s):
        tgt = self.expr(s.target)
        op = s.op
        if op in ("&&=", "||=", "??="):
            v = self.expr(s.value)
            if op == "&&=":
                return ["%s = %s and %s" % (tgt, tgt, v)]
            if op == "||=":
                return ["%s = %s or %s" % (tgt, tgt, v)]
            return ["if %s is None:" % tgt, "    %s = %s" % (tgt, v)]
        v = self.val(s.value) if op == "=" else self.expr(s.value)
        if op == "/=":
            return ["%s = div(%s, %s)" % (tgt, tgt, v)]
        if op == "%=":
            return ["%s = rem(%s, %s)" % (tgt, tgt, v)]
        if op == ">>>=":
            return ["%s = ushr(%s, %s)" % (tgt, tgt, v)]
        return ["%s %s %s" % (tgt, op, v)]

    def s_incdec(self, s):
        return ["%s %s 1" % (self.expr(s.target), "+=" if s.op == "++" else "-=")]

    def s_expr(self, s):
        e = s.value
        if e.kind == "match":
            return self.match_stmt(e)
        return [self.expr(e)]

    def s_return(self, s):
        if s.value is None:
            return ["return"]
        if s.value.kind == "match":
            return [("return " + self.expr(s.value))]
        return ["return " + self.val(s.value)]

    def s_break(self, s):
        return ["break"]

    def s_continue(self, s):
        return ["continue"]

    def s_throw(self, s):
        return ["raise " + self.expr(s.value)]

    def s_unsafe(self, s):
        return self.body(s.body)

    def s_sync(self, s):
        return self.body(s.body)

    def s_defer(self, s):
        if s.body.kind == "block":
            name = self.temp("_d")
            lines = ["def %s():" % name] + self.indent(self.body(s.body))
            return lines + ["_defer.append(%s)" % name]
        return ["_defer.append(lambda: %s)" % self.expr(s.body)]

    def cond(self, e):
        return self.expr(e)

    def s_if(self, s):
        c = self.cond(s.cond)
        pre = self.take_pre()
        out = pre + ["if %s:" % c] + self.indent(self.body(s.then))
        if s.els is not None:
            out.append("else:")
            if s.els.kind == "if":
                inner = self.stmt(s.els)
                out += self.indent(inner)
            else:
                out += self.indent(self.body(s.els))
        return out

    def s_while(self, s):
        c = self.cond(s.cond)
        pre = self.take_pre()
        if pre:
            return ["while True:"] + self.indent(pre + ["if not (%s):" % c, "    break"] + self.body(s.body))
        return ["while %s:" % c] + self.indent(self.body(s.body))

    def s_dowhile(self, s):
        body = self.body(s.body)
        c = self.cond(s.cond)
        pre = self.take_pre()
        return ["while True:"] + self.indent(body + pre + ["if not (%s):" % c, "    break"])

    def s_for(self, s):
        it = s.iter
        while it.kind == "paren":
            it = it.value
        self.push()
        if it.kind == "binary" and it.op in ("..", "..="):
            lo, hi = self.expr(it.left), self.expr(it.right)
            rng = "range(%s, %s%s)" % (lo, hi, " + 1" if it.op == "..=" else "")
        else:
            rng = self.expr(it)
        pre = self.take_pre()
        if len(s.vars) == 1:
            v = self.declare(s.vars[0])
        else:
            v = "(" + ", ".join(self.declare(x) for x in s.vars) + ")"
        out = pre + ["for %s in %s:" % (v, rng)] + self.indent(self.body(s.body))
        self.pop()
        return out

    def s_try(self, s):
        out = []
        res = []
        for name, ty, init in s.resources:
            py = self.declare(name)
            out.append("%s = %s" % (py, self.expr(init)))
            res.append(py)
        out += self.take_pre()
        out.append("try:")
        out += self.indent(self.body(s.body))
        for c in s.catches:
            self.push()
            tys = [self.exc_type(t) for t in c.types] or ["Exception"]
            v = self.declare(c.var)
            out.append("except (%s) as %s:" % (", ".join(tys), v) if len(tys) > 1 else "except %s as %s:" % (tys[0], v))
            out += self.indent(self.body(c.body))
            self.pop()
        if s.fin is not None or res:
            out.append("finally:")
            fin = []
            for r in reversed(res):
                fin.append("%s.close()" % r)
            if s.fin is not None:
                fin += self.body(s.fin)
            out += self.indent(fin or ["pass"])
        return out

    def exc_type(self, t):
        n = t.name.split("::")[-1]
        return mangle(n)

    # -- match --
    def pat_cond(self, p, subj, binds):
        """(condition source, bindings) for a pattern against the python expression `subj`."""
        k = p.kind
        if k == "pat_wild":
            return "True"
        if k == "pat_lit":
            if p.lit == "kw":
                return {"true": "%s is True", "false": "%s is False", "null": "%s is None"}[p.value] % subj
            if p.lit == "str":
                text = "".join(piece[1] for piece in p.value if piece[0] == "s")
                return "%s == %r" % (subj, text)
            return "%s == %r" % (subj, p.value)
        if k == "pat_range":
            parts = []
            if p.lo is not None:
                parts.append("%s <= %s" % (self.expr(p.lo), subj))
            parts.append("%s %s %s" % (subj, "<=" if p.incl else "<", self.expr(p.hi)))
            return "(" + " and ".join(parts) + ")"
        if k == "pat_name":
            n = p.name
            if "::" in n:
                parts = n.split("::")
                return "%s == %s.%s" % (subj, mangle(parts[-2]), attr(parts[-1]))
            # a bare variant name of the scrutinee's enum, a constant, or a binding
            if n[:1].isupper() and (n in self.em.consts):
                return "%s == %s" % (subj, mangle(n))
            if n[:1].isupper() and self.bare_variant(n):
                return "(%s).name == %r" % (subj, n)
            binds.append((n, subj))
            return "True"
        if k == "pat_variant":
            parts = p.name.split("::")
            vname = parts[-1]
            conds = ["(%s).name == %r" % (subj, vname)]
            for i, sp in enumerate(p.subs):
                sub = "(%s).payload[%d]" % (subj, i)
                c = self.pat_cond(sp, sub, binds)
                if c != "True":
                    conds.append(c)
            return "(" + " and ".join(conds) + ")"
        if k == "pat_tuple":
            conds = []
            for i, sp in enumerate(p.elems):
                c = self.pat_cond(sp, "%s[%d]" % (subj, i), binds)
                if c != "True":
                    conds.append(c)
            return "(" + " and ".join(conds) + ")" if conds else "True"
        raise EmitError("line %d: pattern %s" % (p.line, k))

    def bare_variant(self, n):
        for d in self.em.decls.values():
            if d.kind == "enum" and any(v.name == n for v in d.variants):
                return True
        return False

    def match_arms(self, e, subj, as_value):
        """Lines of an if/elif chain; arms assign or return per `as_value`."""
        lines = []
        first = True
        for a in e.arms:
            self.push()
            binds = []
            conds = []
            for p in a.pats:
                b2 = []
                c = self.pat_cond(p, subj, b2)
                conds.append((c, b2))
            # bindings: only the first alternative may bind (or-patterns do not bind)
            cond = " or ".join("(%s)" % c for c, _ in conds)
            body = []
            for name, src in conds[0][1]:
                py = self.declare(name)
                body.append("%s = %s" % (py, src))
            if a.guard is not None:
                # the guard sees the bindings: bind first, test second
                g = self.expr(a.guard)
                pre = self.take_pre()
                head = ("if" if first else "elif") + " %s:" % cond
                lines.append(head)
                inner = list(body) + pre
                inner.append("if %s:" % g)
                inner2 = self.arm_body(a, as_value)
                inner += self.indent(inner2)
                inner.append("else:")
                inner.append("    raise _rt.Trap('no arm matched')" if False else "    pass")
                lines += self.indent(inner)
                # a failed guard falls through to later arms: re-express as nested conditions
                self.pop()
                first = False
                continue
            head = ("if" if first else "elif") + " %s:" % cond
            lines.append(head)
            inner = list(body) + self.arm_body(a, as_value)
            lines += self.indent(inner or ["pass"])
            self.pop()
            first = False
        return lines

    def arm_body(self, a, as_value):
        b = a.body
        if b.kind == "block":
            lines = self.block_lines(b.stmts)
            return lines
        if as_value == "stmt":
            return [self.expr(b)] + self.take_pre()
        src = self.val(b)
        pre = self.take_pre()
        if as_value == "return":
            return pre + ["return " + src]
        return pre + ["%s = %s" % (as_value, src)]

    def match_stmt(self, e):
        subj = self.expr(e.subject)
        pre = self.take_pre()
        t = self.temp("_s")
        lines = pre + ["%s = %s" % (t, subj)]
        lines += self.match_arms_ordered(e, t, "stmt")
        return lines

    def match_arms_ordered(self, e, subj, mode):
        # guards make a plain elif chain wrong (a failed guard must fall through), so emit arms as
        # sequential `if` blocks that `break` out of a one-iteration loop when they fire
        has_guard = any(a.guard is not None for a in e.arms)
        if not has_guard:
            return self.match_arms(e, subj, mode)
        lines = ["while True:"]
        inner = []
        for a in e.arms:
            self.push()
            binds_all = []
            conds = []
            for p in a.pats:
                b2 = []
                conds.append((self.pat_cond(p, subj, b2), b2))
            cond = " or ".join("(%s)" % c for c, _ in conds)
            body = []
            for name, src in conds[0][1]:
                py = self.declare(name)
                body.append("%s = %s" % (py, src))
            inner.append("if %s:" % cond)
            blk = list(body)
            if a.guard is not None:
                g = self.expr(a.guard)
                blk += self.take_pre()
                blk.append("if %s:" % g)
                arm = self.arm_body(a, mode)
                if mode == "return":
                    blk += self.indent(arm)
                else:
                    blk += self.indent(arm + ["break"])
            else:
                arm = self.arm_body(a, mode)
                blk += arm
                if mode != "return":
                    blk.append("break")
            inner += self.indent(blk or ["pass"])
            self.pop()
        inner.append("break")
        return lines + self.indent(inner)

    def e_match(self, e):
        subj = self.expr(e.subject)
        t = self.temp("_s")
        name = self.temp("_m")
        fn = ["def %s(%s):" % (name, t)]
        arms = self.match_arms_ordered(e, t, "return")
        fn += self.indent(arms or ["pass"])
        self.pre.append(fn[0])
        for l in fn[1:]:
            self.pre.append(l)
        return "%s(%s)" % (name, subj)

    # -- expressions --
    def expr(self, e):
        m = getattr(self, "e_" + e.kind, None)
        if m is None:
            raise EmitError("line %d: cannot translate expression %s" % (e.line, e.kind))
        return m(e)

    def e_int(self, e):
        v = str(e.value).replace("_", "")
        try:
            return str(int(v, 0))
        except ValueError:
            return str(int(v))

    def e_float(self, e):
        return repr(float(str(e.value).replace("_", "")))

    def e_str(self, e):
        parts = []
        for p in e.parts:
            if isinstance(p, str):
                parts.append(repr(p))
            else:
                parts.append("to_string(%s)" % self.expr(p))
        if not parts:
            return "''"
        if len(parts) == 1 and isinstance(e.parts[0], str):
            return parts[0]
        return "(" + " + ".join(parts) + ")"

    def e_lit(self, e):
        return {"true": "True", "false": "False", "null": "None"}[e.value]

    def e_paren(self, e):
        return "(" + self.expr(e.value) + ")"

    def e_tuple(self, e):
        return "(" + ", ".join(self.expr(x) for x in e.elems) + ("," if len(e.elems) == 1 else "") + ")"

    def e_array(self, e):
        return "[" + ", ".join(self.val(x) for x in e.elems) + "]"

    def e_name(self, e):
        n = e.name
        py = self.lookup(n)
        if py is not None:
            return py
        if n == "self":
            return "self"
        if n in self.em.consts:
            return mangle(n)
        if n in self.em.fns:
            return mangle(n)
        if n in self.em.decls:
            return mangle(n)
        if n in RUNTIME_NAMES:
            return n
        raise EmitError("line %d: unresolved name %s" % (e.line, n))

    def e_path(self, e):
        root = e.value
        if root.kind == "name":
            n = root.name
            if self.lookup(n) is None and (n in self.em.decls or n in RUNTIME_NAMES):
                return "%s.%s" % (mangle(n) if n in self.em.decls else n, attr(e.name))
        return "%s.%s" % (self.expr(root), attr(e.name))

    def e_field(self, e):
        recv = self.expr(e.value)
        name = e.name
        if getattr(e, "safe", False):
            t = self.temp("_q")
            return "(None if (%s := %s) is None else %s.%s)" % (t, recv, t, attr(name))
        if name == "length":
            return "length(%s)" % recv
        if name == "byteLength":
            return "byte_length(%s)" % recv
        return "%s.%s" % (recv, attr(name))

    def e_tuple_index(self, e):
        return "%s[%s]" % (self.expr(e.value), e.index)

    def e_index(self, e):
        return "%s[%s]" % (self.expr(e.value), self.expr(e.index))

    def e_unary(self, e):
        v = self.expr(e.value)
        if e.op == "!":
            return "(not %s)" % v
        if e.op == "-":
            return "(-%s)" % v
        if e.op == "~":
            return "(~%s)" % v
        if e.op == "&":
            return v
        raise EmitError("line %d: unary %s" % (e.line, e.op))

    def e_deref(self, e):
        raise EmitError("line %d: a pointer dereference cannot be translated" % e.line)

    def e_binary(self, e):
        op = e.op
        a, b = self.expr(e.left), self.expr(e.right)
        if op == "/":
            return "div(%s, %s)" % (a, b)
        if op == "%":
            return "rem(%s, %s)" % (a, b)
        if op == ">>>":
            return "ushr(%s, %s)" % (a, b)
        if op == "&&":
            return "(%s and %s)" % (a, b)
        if op == "||":
            return "(%s or %s)" % (a, b)
        if op == "===":
            return "(%s == %s)" % (a, b)
        if op == "??":
            t = self.temp("_n")
            return "(%s if (%s := %s) is not None else %s)" % (t, t, a, b)
        if op in ("..", "..="):
            return "range(%s, %s%s)" % (a, b, " + 1" if op == "..=" else "")
        return "(%s %s %s)" % (a, op, b)

    def e_ternary(self, e):
        return "(%s if %s else %s)" % (self.expr(e.then), self.expr(e.cond), self.expr(e.els))

    def e_cast(self, e):
        v = self.expr(e.value)
        t = e.type
        if t.kind == "type":
            n = t.name
            if n in INT_TYPES or n in FLOAT_TYPES:
                return "cast(%s, %r)" % (v, n)
        return v

    def e_is(self, e):
        n = e.type.name.split("::")[-1] if e.type.kind == "type" else None
        test = "isinstance(%s, %s)" % (self.expr(e.value), mangle(n))
        return "(not %s)" % test if e.neg else test

    def e_new(self, e):
        n = e.name.split("::")[-1]
        args = ", ".join(self.val(a.value) for a in e.args)
        if n in self.em.decls:
            return "%s(%s)" % (mangle(n), args)
        if n in RUNTIME_NAMES:
            return "%s(%s)" % (n, args)
        raise EmitError("line %d: unknown type %s" % (e.line, n))

    def e_struct_lit(self, e):
        n = e.name.split("::")[-1]
        if n not in self.em.decls:
            raise EmitError("line %d: unknown struct %s" % (e.line, n))
        base = "None" if e.base is None else self.expr(e.base)
        kws = ", ".join("%s=%s" % (attr(f), self.val(v)) for f, v, ln in e.fields)
        return "_rt_lit(%s, %s%s)" % (mangle(n), base, ", " + kws if kws else "")

    def e_lambda(self, e):
        self.push()
        params = [self.declare(p.name) for p in e.params]
        if e.body.kind == "block":
            name = self.temp("_l")
            saved = self.pre
            self.pre = []
            lines = self.block_lines(e.body.stmts)
            lines = self.take_pre() + lines
            self.pre = saved
            self.pre.append("def %s(%s):" % (name, ", ".join(params)))
            for l in (lines or ["pass"]):
                self.pre.append("    " + l)
            self.pop()
            return name
        saved = self.pre
        self.pre = []
        src = self.expr(e.body)
        inner_pre = self.pre
        self.pre = saved
        if inner_pre:
            name = self.temp("_l")
            self.pre.append("def %s(%s):" % (name, ", ".join(params)))
            for l in inner_pre:
                self.pre.append("    " + l)
            self.pre.append("    return " + src)
            self.pop()
            return name
        self.pop()
        return "(lambda %s: %s)" % (", ".join(params), src)

    def e_catch_expr(self, e):
        raise EmitError("line %d: `catch` expressions are not translated" % e.line)

    def e_await(self, e):
        raise EmitError("line %d: await" % e.line)

    def e_spawn(self, e):
        raise EmitError("line %d: spawn" % e.line)

    def e_unsupported(self, e):
        return "_rt.Trap('unsupported')"

    def e_call(self, e):
        c = e.callee
        args = [a.value for a in e.args]
        if c.kind == "name":
            n = c.name
            if n == "malloc":
                if not getattr(c, "targs", None):
                    raise EmitError("line %d: malloc without a type" % e.line)
                return "malloc(%s, lambda: %s)" % (self.val(args[0]), self.em.zero_of(c.targs[0]))
            if n == "sizeof" or n == "offsetof":
                return "0"
            py = self.lookup(n)
            if py is not None:
                return "%s(%s)" % (py, ", ".join(self.expr(a) for a in args))
            if n in self.em.fns:
                return "%s(%s)" % (mangle(n), ", ".join(self.val(a) for a in args))
            if n in self.em.decls:
                # an exception thrown without `new`, or an enum-like constructor call
                return "%s(%s)" % (mangle(n), ", ".join(self.val(a) for a in args))
            if n in RUNTIME_NAMES:
                return "%s(%s)" % (n, ", ".join(self.val(a) for a in args))
            raise EmitError("line %d: call to unresolved %s" % (e.line, n))
        if c.kind == "path":
            return "%s(%s)" % (self.e_path(c), ", ".join(self.val(a) for a in args))
        if c.kind == "field":
            name = c.name
            recv = self.expr(c.value)
            if name in PRIM_METHODS:
                return "call(%s, %r, [%s])" % (recv, name, ", ".join(self.expr(a) for a in args))
            return "%s.%s(%s)" % (recv, attr(name), ", ".join(self.val(a) for a in args))
        return "%s(%s)" % (self.expr(c), ", ".join(self.val(a) for a in args))


def emit_module(parsed_files):
    em = Emitter()
    for items in parsed_files:
        em.add_file(items)
    return em.emit()
