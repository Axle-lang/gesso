# The contract

What every public operation promises, so that a caller can rely on it without reading its body.

## 1. It says what it does

Every operation is `Read`, `Change` or `Admin` (`core::privilege::Access`):

| Access | It… | Needs |
|---|---|---|
| `Read` | only looks | `Privilege::User` |
| `Change` | changes what an ordinary user may change: their own process, their own files | `Privilege::User` |
| `Admin` | changes the machine: a route, a service, another user's process | `Privilege::Elevated` |

`Access::needs()` gives the privilege. The name of the function says the verb — `list`, `read`, `watch` for
`Read`; `set`, `start`, `open` for `Change`; and an `Admin` operation says so in its documentation and in
its `Capability`.

## 2. It never fails silently

A refusal is a `SysError` — which is an `IOException`, so a caller already declaring `! IOException` carries
it onward — and it is the most precise subclass that fits:

| Failure | Means | Carries |
|---|---|---|
| `Denied` | the system said no for want of a privilege | `what`, `needs` (a `Privilege`), `code` |
| `Unsupported` | this platform has no such thing | `platform`, `feature` |
| `Gone` | it existed and no longer does | `what` |
| `Busy` | it exists and is in use | `what` |
| `Invalid` | an argument the system cannot accept | `argument` |
| `Expired` | it took longer than it was given | `millis` |
| `OsFailure` | anything else the system reported | `code`, and its symbolic name when well known |

An operating system's number never reaches a caller bare: `sys::errno` sorts it. A function never returns
`false` for "the system said no".

## 3. It can be asked before it is tried

For every `Change` and `Admin` operation there is a `can…` function answering a `Support`:

| State | Means |
|---|---|
| `Yes` | it can be done |
| `NeedsPrivilege` | it can, once the process holds `needs`; `reason` says why it takes one |
| `Unsupported` | this platform has no such thing; `reason` says what is missing |
| `Unknown` | only trying will tell: the answer depends on the object |

`Support::usableBy(privilege)` answers for a given standing, and `explain()` gives a sentence for a tooltip.

## 4. It can say what it would do

An operation that changes anything has a `plan…` twin returning a `Plan`: each step as a sentence, its
`Access`, and how to undo it. Nothing in a plan has been done. A plan knows its heaviest step
(`highest()`), what the whole needs (`needs()`) and whether every step can be undone (`reversible()`).

## 5. It checks early, and the system still decides

`Host::require(needs, op, what)` refuses with `Denied` before any call is made. It is a courtesy: the
system has the last word, and a call that passes the guard can still be refused, which is reported the same
way.

## 6. It returns values

A reading returns data with an identity key. It holds no handle into the system and does not change after
it is returned. What changes is a `Watch`.
