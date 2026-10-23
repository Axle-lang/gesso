#!/usr/bin/env python3
"""axparse.py — a parser for the subset of Axle this tree is written in.

The Axle compiler is not on every machine that edits this repository, so a slip of grammar — an
`if … then`, a missing semicolon, a brace left open — would otherwise travel to the first person who
runs `axle check`. This parses every file the way the language's own documentation says it reads,
and `check.py` builds its name, mutability and shape checks on the tree it returns.

It is calibrated, not trusted: `python3 tools/axparse.py --corpus DIR…` parses every `.axle` file
under the directories (vendor/smalt is 35 000 lines the real compiler accepts), and a file that fails
there is a bug in *this* parser. It parses what the language documentation shows too, when it is
given a directory of `.md` pages with ```axle blocks.

Not covered, and refused loudly rather than half-parsed: macros, `async` blocks, generics bounds
beyond `A + B`, and anything the documentation lists under "Limits / Uncabled" as not parsing.

The tree is made of `Node`s (a kind, a line, and named children) so a checker can walk it without
a class per construct.
"""
import os
import re
import sys


class ParseError(Exception):
    def __init__(self, msg, line):
        Exception.__init__(self, "line %d: %s" % (line, msg))
        self.line = line
        self.msg = msg


class Node:
    __slots__ = ("kind", "line", "f")

    def __init__(self, kind, line, **f):
        self.kind = kind
        self.line = line
        self.f = f

    def __getattr__(self, name):
        try:
            return self.f[name]
        except KeyError:
            raise AttributeError(name)

    def get(self, name, default=None):
        return self.f.get(name, default)

    def __repr__(self):
        return "Node(%s %s)" % (self.kind, {k: v for k, v in self.f.items() if k != "body"})


# ─── Tokens ──────────────────────────────────────────────────────────────────────────

OPS = [
    ">>>=", "<<=", ">>=", ">>>", "===", "..=", "&&=", "||=", "??=", "...",
    "?.", "??", "==", "!=", "<=", ">=", "&&", "||", "<<", ">>", "+=", "-=", "*=", "/=", "%=", "&=", "|=",
    "^=", "=>", "->", "::", "..", "++", "--",
]
OPS3 = [o for o in OPS if len(o) >= 3]
OPS2 = [o for o in OPS if len(o) == 2]


class Tok:
    __slots__ = ("t", "v", "line", "pos")

    def __init__(self, t, v, line, pos):
        self.t, self.v, self.line, self.pos = t, v, line, pos

    def __repr__(self):
        return "%s:%r@%d" % (self.t, self.v, self.line)


NUM = re.compile(r"0[xX][0-9A-Fa-f_]+|0[bB][01_]+|0[oO][0-7_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?")
IDENT = re.compile(r"[A-Za-z_]\w*")


def tokenize(src):
    toks = []
    i, n, line = 0, len(src), 1
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1
            i += 1
        elif c in " \t\r":
            i += 1
        elif src.startswith("//", i):
            j = src.find("\n", i)
            i = n if j < 0 else j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0:
                raise ParseError("unterminated block comment", line)
            line += src.count("\n", i, j)
            i = j + 2
        elif c == '"' or c == "`":
            j = i + 1
            pieces = []      # ("s", text) and ("e", source, line), in order
            cur = []
            while j < n and src[j] != c:
                if src[j] == "\\":
                    esc = src[j + 1] if j + 1 < n else ""
                    table = {"n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\", '"': '"', "`": "`", "$": "$", "'": "'"}
                    if esc == "u" and j + 2 < n and src[j + 2] == "{":
                        k = src.index("}", j)
                        cur.append(chr(int(src[j + 3:k], 16)))
                        j = k + 1
                        continue
                    cur.append(table.get(esc, esc))
                    j += 2
                    continue
                if src[j] == "$" and j + 1 < n and src[j + 1] == "{":
                    depth, k = 1, j + 2
                    while k < n and depth:
                        if src[k] == "{":
                            depth += 1
                        elif src[k] == "}":
                            depth -= 1
                        k += 1
                    if cur:
                        pieces.append(("s", "".join(cur)))
                        cur = []
                    pieces.append(("e", src[j + 2:k - 1], line))
                    j = k
                    continue
                if src[j] == "\n":
                    if c == '"':
                        raise ParseError("newline in string literal", line)
                    line += 1
                cur.append(src[j])
                j += 1
            if j >= n:
                raise ParseError("unterminated string", line)
            if cur or not pieces:
                pieces.append(("s", "".join(cur)))
            toks.append(Tok("str", pieces, line, i))
            i = j + 1
        elif c == "'":
            # a char literal: 'a' or '\n'
            m = re.match(r"'(?:\\.|[^'\\])'", src[i:])
            if not m:
                raise ParseError("bad character literal", line)
            toks.append(Tok("int", 0, line, i))
            i += len(m.group(0))
        elif c.isdigit():
            m = NUM.match(src, i)
            text = m.group(0)
            toks.append(Tok("float" if ("." in text and not text.lower().startswith("0x")) or
                            (re.search(r"[eE]", text) and not text.lower().startswith("0x")) else "int", text, line, i))
            i = m.end()
        elif c.isalpha() or c == "_":
            m = IDENT.match(src, i)
            toks.append(Tok("id", m.group(0), line, i))
            i = m.end()
        elif c == "@":
            toks.append(Tok("op", "@", line, i))
            i += 1
        else:
            for o in OPS3:
                if src.startswith(o, i):
                    toks.append(Tok("op", o, line, i))
                    i += len(o)
                    break
            else:
                two = src[i:i + 2]
                if two in OPS2:
                    toks.append(Tok("op", two, line, i))
                    i += 2
                elif c in "{}()[]<>;:,.+-*/%&|^~!?=#$":
                    toks.append(Tok("op", c, line, i))
                    i += 1
                else:
                    raise ParseError("unexpected character %r" % c, line)
    toks.append(Tok("eof", None, line, n))
    return toks


# ─── Parser ──────────────────────────────────────────────────────────────────────────

VIS = {"pub"}
MODIFIERS = {"static", "readonly", "abstract", "final", "native"}
ASSIGN_OPS = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>=", ">>>=", "&&=", "||=", "??="}
BIN_PREC = [
    ("??",),
    ("||",),
    ("&&",),
    ("|",),
    ("^",),
    ("&",),
    ("==", "!=", "==="),
    ("<", "<=", ">", ">=", "is", "!is"),
    ("<<", ">>", ">>>"),
    ("..", "..="),
    ("+", "-"),
    ("*", "/", "%"),
]


class Parser:
    def __init__(self, src):
        self.toks = tokenize(src)
        self.p = 0
        self.no_struct = False
        self.no_lambda1 = False

    # -- token helpers --
    @property
    def tok(self):
        return self.toks[self.p]

    def peek(self, k=1):
        return self.toks[min(self.p + k, len(self.toks) - 1)]

    def next(self):
        t = self.toks[self.p]
        self.p += 1
        return t

    def at(self, v):
        t = self.tok
        return t.t in ("op", "id") and t.v == v

    def at_id(self):
        return self.tok.t == "id"

    def accept(self, v):
        if self.at(v):
            return self.next()
        return None

    def expect(self, v):
        if not self.at(v):
            raise ParseError("expected %r, found %r" % (v, self.tok.v), self.tok.line)
        return self.next()

    RESERVED = ("own", "let", "fn", "pub", "class", "struct", "enum", "trait", "static", "const", "match",
                "if", "else", "for", "while", "return", "new", "shared", "super", "as", "use", "try", "catch", "throw")

    def ident(self):
        if self.tok.t != "id":
            raise ParseError("expected an identifier, found %r" % (self.tok.v,), self.tok.line)
        if self.tok.v in self.RESERVED:
            raise ParseError("expected an identifier, found the keyword `%s`" % (self.tok.v,), self.tok.line)
        return self.next().v

    def fail(self, msg):
        raise ParseError(msg, self.tok.line)

    # -- file --
    def parse_file(self):
        items = []
        while self.tok.t != "eof":
            items.append(self.item())
        return items

    def annotations(self):
        out = []
        while self.at("@"):
            line = self.next().line
            name = self.ident()
            args = None
            if self.at("("):
                args = self.skip_balanced("(", ")")
            out.append(Node("annotation", line, name=name))
        return out

    def skip_balanced(self, open_, close):
        depth, start = 0, self.p
        while True:
            t = self.next()
            if t.t == "eof":
                raise ParseError("unbalanced %s" % open_, t.line)
            if t.t == "op" and t.v == open_:
                depth += 1
            elif t.t == "op" and t.v == close:
                depth -= 1
                if depth == 0:
                    return self.toks[start:self.p]

    def visibility(self):
        if self.at("pub"):
            self.next()
            if self.at("(") and self.peek().t == "id" and self.peek(2).v == ")":
                self.next()
                v = self.ident()
                self.expect(")")
                return "pub(%s)" % v
            return "pub"
        return None

    def item(self):
        anns = self.annotations()
        line = self.tok.line
        vis = self.visibility()
        mods = set()
        while self.tok.t == "id" and self.tok.v in MODIFIERS and self.peek().v not in ("(", ":", "=", ";", ","):
            mods.add(self.next().v)
        t = self.tok
        if t.t != "id":
            self.fail("expected a declaration, found %r" % (t.v,))
        k = t.v
        if k == "use":
            return self.use_decl()
        if k == "const":
            return self.const_decl(vis)
        if k == "extern":
            return self.extern_decl(vis, anns)
        if k == "async" and self.peek().v == "fn":
            self.next()
            return self.fn_decl(vis, mods, anns, is_async=True)
        if k == "fn":
            return self.fn_decl(vis, mods, anns)
        if k in ("class", "struct", "trait", "exception"):
            return self.type_decl(k, vis, anns)
        if k == "enum":
            return self.enum_decl(vis, anns)
        if k == "static":
            self.fail("`static` outside a class")
        self.fail("unexpected %r at file scope" % k)

    def use_decl(self):
        line = self.next().line
        path = [self.ident()]
        names = None
        alias = None
        while self.accept("::"):
            if self.at("{"):
                self.next()
                names = []
                while not self.at("}"):
                    n = self.ident()
                    a = None
                    if self.accept("as"):
                        a = self.ident()
                    names.append((n, a))
                    if not self.accept(","):
                        break
                self.expect("}")
                break
            path.append(self.ident())
        if self.accept("as"):
            alias = self.ident()
        self.expect(";")
        return Node("use", line, path=path, names=names, alias=alias)

    def const_decl(self, vis):
        line = self.next().line
        name = self.ident()
        ty = None
        if self.accept(":"):
            ty = self.type_()
        self.expect("=")
        val = self.expr()
        self.expect(";")
        return Node("const", line, name=name, type=ty, value=val, vis=vis)

    def extern_decl(self, vis, anns):
        line = self.next().line
        abi = None
        if self.tok.t == "str":
            self.next()
            abi = "C"
        if self.at("from"):
            self.next()
            lib = self.next()
            self.expect("{")
            fns = []
            while not self.at("}"):
                a2 = self.annotations()
                fns.append(self.fn_decl(None, set(), a2, extern=True))
            self.expect("}")
            return Node("extern_block", line, fns=fns)
        if self.at("fn"):
            return self.fn_decl(vis, set(), anns, extern=True)
        if self.at("struct"):
            return self.type_decl("struct", vis, anns)
        self.fail("bad extern declaration")

    def generics(self):
        params = []
        if self.accept("<"):
            while True:
                name = self.ident()
                bounds = []
                if self.accept(":"):
                    bounds.append(self.type_())
                    while self.accept("+"):
                        bounds.append(self.type_())
                params.append((name, bounds))
                if not self.accept(","):
                    break
            self.expect(">")
        return params

    def params(self):
        self.expect("(")
        out = []
        while not self.at(")"):
            own = mut = False
            while self.tok.t == "id" and self.tok.v in ("own", "mut") and self.peek().t == "id":
                if self.next().v == "own":
                    own = True
                else:
                    mut = True
            if self.tok.t == "id" and self.tok.v in ("self",):
                name = self.next().v
                out.append(Node("param", self.tok.line, name=name, type=None, own=own, mut=mut))
            else:
                line = self.tok.line
                name = self.ident()
                ty = None
                if self.accept(":"):
                    ty = self.type_()
                default = None
                out.append(Node("param", line, name=name, type=ty, own=own, mut=mut))
            if not self.accept(","):
                break
        self.expect(")")
        return out

    def ret(self):
        rt, errs = None, []
        if self.accept(":"):
            if self.at("!"):
                pass
            rt = self.type_()
            if self.accept("!"):
                errs.append(self.type_())
                while self.accept(","):
                    errs.append(self.type_())
        return rt, errs

    def fn_decl(self, vis, mods, anns, is_async=False, extern=False):
        line = self.expect("fn").line
        name = self.ident()
        gen = self.generics()
        params = self.params()
        rt, errs = self.ret()
        body = None
        if self.at("{"):
            body = self.block()
        else:
            self.expect(";")
        return Node("fn", line, name=name, params=params, ret=rt, errs=errs, body=body, vis=vis,
                    static="static" in mods, generics=gen, anns=anns, is_async=is_async, extern=extern)

    def supertypes(self):
        out = []
        if self.accept(":"):
            out.append(self.type_())
            while self.accept(","):
                out.append(self.type_())
        return out

    def type_decl(self, kind, vis, anns):
        line = self.next().line
        name = self.ident()
        gen = self.generics()
        supers = self.supertypes()
        self.expect("{")
        members = self.members(kind)
        self.expect("}")
        return Node(kind, line, name=name, generics=gen, supers=supers, members=members, vis=vis, anns=anns)

    def members(self, kind):
        out = []
        while not self.at("}"):
            if self.tok.t == "eof":
                self.fail("unterminated %s body" % kind)
            out.append(self.member(kind))
        return out

    def member(self, kind):
        anns = self.annotations()
        line = self.tok.line
        if self.at("when"):
            self.next()
            tname = self.ident()
            self.expect(":")
            bound = self.type_()
            self.expect("{")
            inner = self.members(kind)
            self.expect("}")
            return Node("when", line, tparam=tname, members=inner)
        if self.at("impl") and self.peek().v == "Self":
            self.next()
            self.next()
            self.expect("{")
            arms = []
            while not self.at("}"):
                ty = self.type_()
                self.expect("=>")
                if self.at("{"):
                    body = self.block()
                else:
                    body = self.expr()
                arms.append((ty, body))
                self.accept(",")
            self.expect("}")
            return Node("impl_self", line, arms=arms)
        vis = self.visibility()
        mods = set()
        while self.tok.t == "id" and self.tok.v in MODIFIERS and self.peek().v not in ("(", ":", "=", ";", ","):
            mods.add(self.next().v)
        if self.at("constructor"):
            self.next()
            params = self.params()
            errs = []
            if self.accept("!"):
                errs.append(self.type_())
                while self.accept(","):
                    errs.append(self.type_())
            body = self.block()
            return Node("constructor", line, params=params, errs=errs, body=body, vis=vis)
        if self.at("drop") and self.peek().v == "(":
            self.next()
            self.expect("(")
            self.expect(")")
            return Node("drop", line, body=self.block())
        if self.at("fn") or (self.at("async") and self.peek().v == "fn"):
            is_async = bool(self.accept("async"))
            return self.fn_decl(vis, mods, anns, is_async=is_async)
        name = self.ident()
        if kind == "enum":
            raise ParseError("enum variant handled by enum_decl", line)
        ty = None
        if self.accept(":"):
            ty = self.type_()
        default = None
        if self.accept("="):
            default = self.expr()
        if not (self.accept(";") or self.accept(",")):
            if not self.at("}"):
                self.fail("expected ';' or ',' after field %s" % name)
        return Node("field", line, name=name, type=ty, default=default, vis=vis, static="static" in mods,
                    readonly="readonly" in mods)

    def enum_decl(self, vis, anns):
        line = self.next().line
        name = self.ident()
        gen = self.generics()
        supers = self.supertypes()
        self.expect("{")
        variants, methods = [], []
        while not self.at("}"):
            if self.tok.t == "eof":
                self.fail("unterminated enum body")
            save = self.p
            self.annotations()
            if self.at("pub") or self.at("fn") or self.at("static"):
                methods.append(self.member("class"))
                continue
            vline = self.tok.line
            vname = self.ident()
            payload = []
            value = None
            if self.accept("("):
                while not self.at(")"):
                    payload.append(self.type_())
                    if not self.accept(","):
                        break
                self.expect(")")
            if self.accept("="):
                value = self.expr()
            variants.append(Node("variant", vline, name=vname, payload=payload, value=value))
            if not self.accept(","):
                if not self.at("}") and not (self.at("pub") or self.at("fn") or self.at("static")):
                    self.fail("expected ',' after variant %s" % vname)
        self.expect("}")
        return Node("enum", line, name=name, generics=gen, supers=supers, variants=variants,
                    members=methods, vis=vis, anns=anns)

    # -- types --
    def type_(self):
        line = self.tok.line
        if self.at("extern"):
            self.next()
            if self.tok.t == "str":
                self.next()
            self.expect("(")
            ps = []
            while not self.at(")"):
                ps.append(self.type_())
                if not self.accept(","):
                    break
            self.expect(")")
            self.expect("=>")
            return Node("ftype", line, params=ps, ret=self.type_())
        if self.at("("):
            # tuple type, parenthesised type, or function type
            self.next()
            elems = []
            while not self.at(")"):
                label = None
                if self.tok.t == "id" and self.peek().v == ":" and self.peek(2).v != ":":
                    label = self.next().v
                    self.next()
                elems.append((label, self.type_()))
                if not self.accept(","):
                    break
            self.expect(")")
            if self.accept("=>"):
                rt = self.type_()
                base = Node("ftype", line, params=[t for _, t in elems], ret=rt)
            else:
                base = Node("tuple_type", line, elems=elems)
        else:
            if self.at("dyn"):
                self.next()
            if self.at("typeof"):
                self.fail("typeof")
            name = self.ident()
            while self.accept("::"):
                name += "::" + self.ident()
            args = []
            if self.at("<"):
                self.next()
                while True:
                    args.append(self.type_())
                    if not self.accept(","):
                        break
                self.expect_gt()
            base = Node("type", line, name=name, args=args)
        while True:
            if self.at("[") :
                self.next()
                size = None
                if not self.at("]"):
                    size = self.expr()
                self.expect("]")
                base = Node("array_type", line, elem=base, size=size)
            elif self.at("|") and self.peek().v == "null":
                self.next()
                self.next()
                base = Node("nullable", line, inner=base)
            else:
                break
        return base

    def expect_gt(self):
        # `>>` closes two generic lists
        t = self.tok
        if t.t == "op" and t.v == ">":
            self.next()
        elif t.t == "op" and t.v == ">>":
            t.v = ">"
        elif t.t == "op" and t.v == ">>>":
            t.v = ">>"
        elif t.t == "op" and t.v == ">=":
            t.v = "="
        else:
            self.fail("expected '>'")

    # -- statements --
    def block(self):
        line = self.expect("{").line
        stmts = []
        while not self.at("}"):
            if self.tok.t == "eof":
                raise ParseError("unterminated block", line)
            stmts.append(self.stmt())
        self.expect("}")
        return Node("block", line, stmts=stmts)

    def pattern_names(self):
        # let (a, b) / let mut (a, b)
        self.expect("(")
        names = []
        while not self.at(")"):
            names.append(self.ident())
            if not self.accept(","):
                break
        self.expect(")")
        return names

    def stmt(self):
        t = self.tok
        line = t.line
        if t.t == "op" and t.v == "{":
            return self.block()
        if t.t == "op" and t.v == ";":
            self.next()
            return Node("empty", line)
        if t.t == "op" and t.v == "@":
            self.annotations()
            return self.stmt()
        if t.t == "id":
            k = t.v
            if k == "let":
                self.next()
                mut = bool(self.accept("mut"))
                if self.at("("):
                    names = self.pattern_names()
                    ty = None
                    if self.accept(":"):
                        ty = self.type_()
                    self.expect("=")
                    val = self.expr()
                    self.expect(";")
                    return Node("let_tuple", line, names=names, mut=mut, value=val)
                name = self.ident()
                ty = None
                if self.accept(":"):
                    ty = self.type_()
                val = None
                if self.accept("="):
                    val = self.expr()
                self.expect(";")
                return Node("let", line, name=name, mut=mut, type=ty, value=val)
            if k == "const" and self.peek().t == "id":
                self.next()
                name = self.ident()
                ty = None
                if self.accept(":"):
                    ty = self.type_()
                self.expect("=")
                val = self.expr()
                self.expect(";")
                return Node("let", line, name=name, mut=False, type=ty, value=val, legacy_const=True)
            if k == "if":
                return self.if_stmt()
            if k == "while":
                self.next()
                cond = self.head_expr()
                body = self.block()
                return Node("while", line, cond=cond, body=body)
            if k == "do":
                self.next()
                body = self.block()
                self.expect("while")
                cond = self.head_expr()
                self.expect(";")
                return Node("dowhile", line, cond=cond, body=body)
            if k == "for":
                return self.for_stmt()
            if k == "return":
                self.next()
                val = None
                if not self.at(";"):
                    val = self.expr()
                self.expect(";")
                return Node("return", line, value=val)
            if k == "break" or k == "continue":
                self.next()
                self.expect(";")
                return Node(k, line)
            if k == "throw":
                self.next()
                val = self.expr()
                self.expect(";")
                return Node("throw", line, value=val)
            if k == "defer":
                self.next()
                if self.at("{"):
                    body = self.block()
                else:
                    body = self.expr()
                    self.expect(";")
                return Node("defer", line, body=body)
            if k == "try":
                return self.try_stmt()
            if k == "unsafe" and self.peek().v == "{":
                self.next()
                return Node("unsafe", line, body=self.block())
            if k == "match" and self.peek().v != "(" or k == "match":
                e = self.expr()
                self.accept(";")
                return Node("expr", line, value=e)
            if k == "synchronized":
                self.next()
                self.expect("(")
                lock = self.expr()
                self.expect(")")
                return Node("sync", line, lock=lock, body=self.block())
        e = self.expr()
        if self.tok.t == "op" and self.tok.v in ASSIGN_OPS:
            op = self.next().v
            val = self.expr()
            self.expect(";")
            return Node("assign", line, target=e, op=op, value=val)
        if self.at("++") or self.at("--"):
            op = self.next().v
            self.expect(";")
            return Node("incdec", line, target=e, op=op)
        # an expression statement; a trailing `;` is optional after a match / block-bodied construct
        if not self.accept(";"):
            if e.kind in ("match", "if_expr") or self.at("}"):
                pass
            else:
                self.fail("expected ';' after expression, found %r" % (self.tok.v,))
        return Node("expr", line, value=e)

    def head_expr(self):
        old = self.no_struct
        self.no_struct = True
        e = self.expr()
        self.no_struct = old
        return e

    def if_stmt(self):
        line = self.expect("if").line
        cond = self.head_expr()
        then = self.block()
        els = None
        if self.accept("else"):
            if self.at("if"):
                els = self.if_stmt()
            else:
                els = self.block()
        return Node("if", line, cond=cond, then=then, els=els)

    def for_stmt(self):
        line = self.expect("for").line
        paren = bool(self.accept("("))
        if self.at("["):
            self.next()
            names = []
            while not self.at("]"):
                names.append(self.ident())
                if not self.accept(","):
                    break
            self.expect("]")
            var = names
        else:
            var = [self.ident()]
        self.expect("of")
        if paren:
            it = self.expr()
            self.expect(")")
        else:
            it = self.head_expr()
        body = self.block()
        return Node("for", line, vars=var, iter=it, body=body)

    def try_stmt(self):
        line = self.expect("try").line
        resources = []
        if self.at("("):
            self.next()
            while not self.at(")"):
                name = self.ident()
                ty = None
                if self.accept(":"):
                    ty = self.type_()
                self.expect("=")
                resources.append((name, ty, self.expr()))
                if not self.accept(";"):
                    break
            self.expect(")")
        body = self.block()
        catches = []
        fin = None
        while self.at("catch"):
            cl = self.next().line
            var = self.ident()
            types = []
            if self.accept(":"):
                types.append(self.type_())
                while self.accept("|"):
                    types.append(self.type_())
            catches.append(Node("catch", cl, var=var, types=types, body=self.block()))
        if self.accept("finally"):
            fin = self.block()
        return Node("try", line, resources=resources, body=body, catches=catches, fin=fin)

    # -- expressions --
    def expr(self):
        return self.ternary()

    def ternary(self):
        c = self.binary(0)
        if self.at("?"):
            line = self.next().line
            a = self.expr()
            self.expect(":")
            b = self.expr()
            return Node("ternary", line, cond=c, then=a, els=b)
        return c

    def binary(self, level):
        if level >= len(BIN_PREC):
            return self.unary()
        ops = BIN_PREC[level]
        left = self.binary(level + 1)
        while True:
            t = self.tok
            v = t.v
            if t.t == "op" and v in ops:
                # a `<` that begins a generic argument list is not a comparison — handled in primary
                self.next()
                if v in ("..", "..="):
                    # an open-ended range `a..` is not used in this tree; require a right side
                    right = self.binary(level + 1)
                else:
                    right = self.binary(level + 1)
                left = Node("binary", t.line, op=v, left=left, right=right)
            elif t.t == "id" and v == "is" and "is" in ops:
                self.next()
                neg = False
                ty = self.type_()
                left = Node("is", t.line, value=left, type=ty, neg=neg)
            elif t.t == "op" and v == "!" and self.peek().v == "is" and "is" in ops:
                self.next()
                self.next()
                ty = self.type_()
                left = Node("is", t.line, value=left, type=ty, neg=True)
            else:
                return left

    def unary(self):
        t = self.tok
        if t.t == "op" and t.v in ("-", "!", "~", "++", "--", "&"):
            self.next()
            operand = self.unary()
            return Node("unary", t.line, op=t.v, value=operand)
        if t.t == "op" and t.v == "*":
            self.next()
            return Node("deref", t.line, value=self.unary())
        if t.t == "id" and t.v == "await":
            self.next()
            return Node("await", t.line, value=self.unary())
        if t.t == "id" and t.v == "spawn":
            self.next()
            return Node("spawn", t.line, value=self.unary())
        return self.cast()

    def cast(self):
        e = self.postfix()
        while self.at("as"):
            line = self.next().line
            ty = self.type_no_union()
            e = Node("cast", line, value=e, type=ty)
        return e

    def type_no_union(self):
        # `x as i32 | y` must not read `| y` as a nullable suffix: only `| null` is a type suffix
        return self.type_()

    def args(self):
        self.expect("(")
        out = []
        old = self.no_struct
        self.no_struct = False
        while not self.at(")"):
            label = None
            if self.tok.t == "id" and self.peek().v == ":" and self.peek(2).v != ":":
                label = self.next().v
                self.next()
            out.append(Node("arg", self.tok.line, label=label, value=self.expr()))
            if not self.accept(","):
                break
        self.expect(")")
        self.no_struct = old
        return out

    def postfix(self):
        e = self.primary()
        while True:
            t = self.tok
            if t.t == "op" and t.v == "(":
                e = Node("call", t.line, callee=e, args=self.args())
            elif t.t == "op" and t.v == ".":
                self.next()
                if self.tok.t == "int":
                    e = Node("tuple_index", t.line, value=e, index=self.next().v)
                else:
                    name = self.ident()
                    if self.at("<") and self.generic_call_ahead():
                        self.next()
                        targs = []
                        while True:
                            targs.append(self.type_())
                            if not self.accept(","):
                                break
                        self.expect_gt()
                    e = Node("field", t.line, value=e, name=name)
            elif t.t == "op" and t.v == "?.":
                self.next()
                name = self.ident()
                e = Node("field", t.line, value=e, name=name, safe=True)
            elif t.t == "op" and t.v == "::":
                self.next()
                name = self.ident()
                e = Node("path", t.line, value=e, name=name)
            elif t.t == "op" and t.v == "[":
                self.next()
                old = self.no_struct
                self.no_struct = False
                idx = self.expr()
                self.no_struct = old
                self.expect("]")
                e = Node("index", t.line, value=e, index=idx)
            elif t.t == "id" and t.v == "catch":
                self.next()
                var = self.ident()
                body = self.block()
                e = Node("catch_expr", t.line, value=e, var=var, body=body)
            elif t.t == "op" and t.v in ("++", "--") and False:
                break
            else:
                return e

    def generic_call_ahead(self):
        # at '<': is this `name<T, U>(` ?
        depth, i = 0, self.p
        while i < len(self.toks):
            t = self.toks[i]
            if t.t == "op" and t.v == "<":
                depth += 1
            elif t.t == "op" and t.v == ">":
                depth -= 1
                if depth == 0:
                    n = self.toks[i + 1]
                    return n.t == "op" and n.v == "("
            elif t.t == "op" and t.v == ">>":
                depth -= 2
                if depth <= 0:
                    n = self.toks[i + 1]
                    return depth == 0 and n.t == "op" and n.v == "("
            elif t.t == "op" and t.v in (";", "{", "}", "&&", "||", "==", "!=", "=", "(", ")"):
                return False
            elif t.t not in ("id", "op", "int"):
                return False
            i += 1
        return False

    def is_lambda(self):
        # at '(' : find the matching ')' and look for '=>'
        depth, i = 0, self.p
        while i < len(self.toks):
            t = self.toks[i]
            if t.t == "op" and t.v == "(":
                depth += 1
            elif t.t == "op" and t.v == ")":
                depth -= 1
                if depth == 0:
                    n = self.toks[i + 1]
                    return n.t == "op" and n.v == "=>"
            elif t.t == "eof":
                return False
            i += 1
        return False

    def primary(self):
        t = self.tok
        line = t.line
        if t.t == "int":
            self.next()
            return Node("int", line, value=t.v)
        if t.t == "float":
            self.next()
            return Node("float", line, value=t.v)
        if t.t == "str":
            self.next()
            parts = []
            for piece in t.v:
                if piece[0] == "s":
                    parts.append(piece[1])
                else:
                    sub = Parser(piece[1])
                    for tk in sub.toks:
                        tk.line = piece[2]
                    parts.append(sub.expr())
            return Node("str", line, parts=parts)
        if t.t == "op":
            if t.v == "(":
                if self.is_lambda():
                    return self.lambda_()
                self.next()
                old = self.no_struct
                self.no_struct = False
                first = self.expr()
                if self.at(","):
                    elems = [first]
                    while self.accept(","):
                        if self.at(")"):
                            break
                        elems.append(self.expr())
                    self.expect(")")
                    self.no_struct = old
                    return Node("tuple", line, elems=elems)
                self.expect(")")
                self.no_struct = old
                return Node("paren", line, value=first)
            if t.v == "[":
                self.next()
                elems = []
                old = self.no_struct
                self.no_struct = False
                while not self.at("]"):
                    elems.append(self.expr())
                    if not self.accept(","):
                        break
                self.expect("]")
                self.no_struct = old
                return Node("array", line, elems=elems)
            if t.v == "{":
                self.fail("a block where an expression was expected")
            self.fail("unexpected %r in expression" % t.v)
        if t.t == "id":
            v = t.v
            if v in ("true", "false", "null"):
                self.next()
                return Node("lit", line, value=v)
            if v == "new":
                return self.new_expr()
            if v == "match":
                return self.match_expr()
            if v == "if":
                self.fail("`if` is a statement, not an expression (use `?:`)")
            if v == "unsupported" and self.peek().t == "str":
                self.next()
                self.next()
                return Node("unsupported", line)
            if v == "self" or v == "super":
                self.next()
                return Node("name", line, name=v)
            if self.peek().v == "=>" and self.peek().t == "op" and not self.no_lambda1:
                # x => expr
                return self.lambda_()
            self.next()
            name = v
            targs = []
            if self.at("<") and self.generic_call_ahead():
                self.next()
                while True:
                    targs.append(self.type_())
                    if not self.accept(","):
                        break
                self.expect_gt()
            if self.at("{") and not self.no_struct and self.struct_literal_ahead(name):
                return self.struct_lit(name, line)
            return Node("name", line, name=name, targs=targs)
        self.fail("unexpected %r" % (t.v,))

    def struct_literal_ahead(self, name):
        # `Name {` where the next tokens look like fields: `}` | ident `:` | ident `,` | ident `}` | `..`
        a, b = self.peek(1), self.peek(2)
        if a.t == "op" and a.v == "}":
            return name[:1].isupper()
        if a.t == "op" and a.v == "..":
            return True
        if a.t == "id" and b.t == "op" and b.v in (":", ",", "}") and name[:1].isupper():
            return True
        return False

    def struct_lit(self, name, line):
        self.expect("{")
        fields, base = [], None
        old = self.no_struct
        self.no_struct = False
        while not self.at("}"):
            if self.accept(".."):
                base = self.expr()
            else:
                fl = self.tok.line
                fname = self.ident()
                if self.accept(":"):
                    fields.append((fname, self.expr(), fl))
                else:
                    fields.append((fname, Node("name", fl, name=fname), fl))
            if not self.accept(","):
                break
        self.no_struct = old
        self.expect("}")
        return Node("struct_lit", line, name=name, fields=fields, base=base)

    def lambda_(self):
        line = self.tok.line
        params = []
        if self.at("("):
            self.next()
            while not self.at(")"):
                pl = self.tok.line
                pname = self.ident()
                ty = None
                if self.accept(":"):
                    ty = self.type_()
                params.append(Node("param", pl, name=pname, type=ty, own=False, mut=False))
                if not self.accept(","):
                    break
            self.expect(")")
        else:
            params.append(Node("param", line, name=self.ident(), type=None, own=False, mut=False))
        self.expect("=>")
        if self.at("{"):
            body = self.block()
        else:
            body = self.expr()
        return Node("lambda", line, params=params, body=body)

    def new_expr(self):
        line = self.next().line
        shared = bool(self.accept("shared"))
        name = self.ident()
        while self.accept("::"):
            name += "::" + self.ident()
        targs = []
        if self.at("<"):
            self.next()
            while True:
                targs.append(self.type_())
                if not self.accept(","):
                    break
            self.expect_gt()
        args = self.args()
        return Node("new", line, name=name, targs=targs, args=args, shared=shared)

    def match_expr(self):
        line = self.expect("match").line
        if self.at("type"):
            self.next()
            self.type_()
            subject = None
        else:
            old = self.no_struct
            self.no_struct = True
            subject = self.expr()
            self.no_struct = old
        self.expect("{")
        arms = []
        while not self.at("}"):
            al = self.tok.line
            pats = [self.pattern()]
            while self.accept("|"):
                pats.append(self.pattern())
            guard = None
            if self.accept("if"):
                old1 = self.no_lambda1
                self.no_lambda1 = True
                guard = self.expr()
                self.no_lambda1 = old1
            self.expect("=>")
            if self.at("{"):
                body = self.block()
            else:
                body = self.expr()
            arms.append(Node("arm", al, pats=pats, guard=guard, body=body))
            if not self.accept(","):
                if not self.at("}") and body.kind != "block":
                    self.fail("expected ',' after match arm")
        self.expect("}")
        return Node("match", line, subject=subject, arms=arms)

    def pat_bound(self):
        """A range bound: an optionally negated integer, a character, or a name."""
        line = self.tok.line
        neg = False
        if self.at("-"):
            self.next()
            neg = True
        t = self.next()
        if t.t == "int":
            v = int(str(t.v).replace("_", ""), 0) if not str(t.v).lower().startswith(("0b", "0o", "0x")) else int(str(t.v).replace("_", ""), 0)
            return Node("int", line, value=-v if neg else v)
        if t.t == "id":
            return Node("name", line, name=t.v)
        raise ParseError("bad range bound", line)

    def pattern(self):
        t = self.tok
        line = t.line
        if t.t == "op" and t.v in ("..", "..="):
            incl = self.next().v == "..="
            hi = self.pat_bound()
            return Node("pat_range", line, lo=None, hi=hi, incl=incl)
        if t.t == "op" and t.v == "-":
            lo = self.pat_bound()
            return self.range_tail(lo, line)
        if t.t == "int":
            lo = self.pat_bound()
            return self.range_tail(lo, line)
        if t.t == "float":
            self.next()
            return Node("pat_lit", line, lit="float", value=float(str(t.v).replace("_", "")))
        if t.t == "str":
            self.next()
            return Node("pat_lit", line, lit="str", value=t.v)
        if t.t == "op" and t.v == "(":
            self.next()
            elems = []
            while not self.at(")"):
                elems.append(self.pattern())
                if not self.accept(","):
                    break
            self.expect(")")
            return Node("pat_tuple", line, elems=elems)
        if t.t == "id":
            if t.v in ("true", "false", "null"):
                self.next()
                return Node("pat_lit", line, lit="kw", value=t.v)
            if t.v == "_":
                self.next()
                return Node("pat_wild", line)
            name = self.next().v
            while self.accept("::"):
                name += "::" + self.ident()
            if (self.at("..=") or self.at("..")) and "::" not in name:
                return self.range_tail(Node("name", line, name=name), line)
            if self.at("("):
                self.next()
                subs = []
                while not self.at(")"):
                    subs.append(self.pattern())
                    if not self.accept(","):
                        break
                self.expect(")")
                return Node("pat_variant", line, name=name, subs=subs)
            if self.at("{") and name[:1].isupper():
                self.next()
                fields = []
                while not self.at("}"):
                    fields.append(self.ident())
                    if self.accept(":"):
                        self.pattern()
                    if not self.accept(","):
                        break
                self.expect("}")
                return Node("pat_struct", line, name=name, fields=fields)
            return Node("pat_name", line, name=name)
        self.fail("bad pattern")

    def range_tail(self, lo, line):
        if self.at("..") or self.at("..="):
            incl = self.next().v == "..="
            hi = self.pat_bound()
            return Node("pat_range", line, lo=lo, hi=hi, incl=incl)
        return Node("pat_lit", line, lit="int", value=lo.value) if lo.kind == "int" else Node("pat_name", line, name=lo.name)


def parse(src):
    return Parser(src).parse_file()


# ─── Calibration ─────────────────────────────────────────────────────────────────────

def corpus(paths):
    bad = total = 0
    for base in paths:
        if os.path.isfile(base):
            files = [base]
        else:
            files = []
            for dp, _, names in os.walk(base):
                for n in sorted(names):
                    if n.endswith(".axle"):
                        files.append(os.path.join(dp, n))
        for f in files:
            total += 1
            try:
                parse(open(f, encoding="utf-8").read())
            except ParseError as e:
                bad += 1
                print("%s: %s" % (f, e))
            except RecursionError:
                bad += 1
                print("%s: recursion limit" % f)
    print("parsed %d files, %d failed" % (total - bad, bad))
    return bad


def docs(paths):
    bad = total = 0
    for base in paths:
        for dp, _, names in os.walk(base):
            for n in sorted(names):
                if not n.endswith(".md"):
                    continue
                text = open(os.path.join(dp, n), encoding="utf-8").read()
                for m in re.finditer(r"```axle\n(.*?)```", text, re.S):
                    total += 1
                    try:
                        try:
                            parse(m.group(1))
                        except ParseError:
                            # a fragment: statements that were never a whole file
                            parse("fn fragment() : void {\n" + m.group(1) + "\n}")
                    except ParseError as e:
                        bad += 1
                        line0 = text[:m.start()].count("\n") + 2
                        print("%s:%d: %s" % (os.path.join(dp, n), line0, e))
    print("doc blocks: %d, %d failed" % (total, bad))
    return bad


if __name__ == "__main__":
    sys.setrecursionlimit(10000)
    args = sys.argv[1:]
    if args and args[0] == "--corpus":
        sys.exit(1 if corpus(args[1:]) else 0)
    if args and args[0] == "--docs":
        sys.exit(1 if docs(args[1:]) else 0)
    sys.exit(1 if corpus(args or ["src"]) else 0)
