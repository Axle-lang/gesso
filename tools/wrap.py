#!/usr/bin/env python3
"""wrap.py — what `axle fmt` leaves long: doc comments, line comments and `use` lists wider than 110 columns.

    axle fmt src examples tools/axpy/fakes
    python3 tools/wrap.py

`axle fmt` lays out code but joins an import list on one line and does not wrap comments. This breaks the
`use crate::a::{x, y, …};` lists and the comments into lines of at most 110 columns, the width that
`tools/check.py` holds every line to. Run it after the formatter, never before: the formatter would join
the lists again.
"""
import glob, re, sys, textwrap

LIMIT = 110


def wrap_use(line):
    m = re.match(r'^(use [\w:]+::)\{(.*)\};$', line)
    if not m or len(line) <= LIMIT:
        return [line]
    names = [n.strip() for n in m.group(2).split(',')]
    out = [m.group(1) + '{']
    cur = '   '
    for n in names:
        piece = ' ' + n + ','
        if len(cur) + len(piece) > LIMIT - 2:
            out.append(cur)
            cur = '   '
        cur += piece
    out.append(cur)
    out.append('};')
    return out


def wrap_doc(line):
    m = re.match(r'^(\s*)/\*\* (.*) \*/$', line)
    if not m or len(line) <= LIMIT:
        return [line]
    indent, text = m.group(1), m.group(2)
    width = LIMIT - len(indent) - 3
    parts = textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)
    out = [indent + '/**']
    out += [indent + ' * ' + p for p in parts]
    out.append(indent + ' */')
    return out


def wrap_line_comment(line):
    m = re.match(r'^(\s*)// (.*)$', line)
    if not m or len(line) <= LIMIT:
        return [line]
    indent, text = m.group(1), m.group(2)
    width = LIMIT - len(indent) - 3
    parts = textwrap.wrap(text, width=width, break_long_words=False, break_on_hyphens=False)
    return [indent + '// ' + p for p in parts]


changed = 0
for path in glob.glob('src/**/*.axle', recursive=True) + glob.glob('examples/**/*.axle', recursive=True) + glob.glob('tools/axpy/fakes/*.axle'):
    raw = open(path, encoding='utf-8', newline='').read()
    nl = '\r\n' if '\r\n' in raw else '\n'
    lines = raw.replace('\r\n', '\n').split('\n')
    out = []
    for line in lines:
        if line.startswith('use '):
            out += wrap_use(line)
        elif line.lstrip().startswith('/** '):
            out += wrap_doc(line)
        elif line.lstrip().startswith('// ') and '───' not in line and not line.lstrip().startswith('//  '):
            out += wrap_line_comment(line)
        else:
            out.append(line)
    new = '\n'.join(out)
    if new != '\n'.join(lines):
        open(path, 'w', encoding='utf-8', newline='').write(new.replace('\n', nl))
        changed += 1
print('wrapped', changed, 'files')
