"""JSON Canonicalization Scheme (RFC 8785).

A2A requires the Agent Card to be canonicalized with JCS before signing, so verifying a
signature means reproducing the exact bytes the signer hashed. Getting this wrong
produces false accusations of a broken signature, which would be the worst kind of
error this study could make.

Two parts of RFC 8785 are worth calling out:

* **Key ordering is by UTF-16 code unit**, not by Unicode code point. The two agree for
  the Basic Multilingual Plane and disagree above it, so a card with an astral-plane key
  (emoji, rare scripts) sorts differently under the naive rule.
* **Numbers use the ECMAScript `Number::toString` algorithm**, which is shortest
  round-trip formatting. Python's `repr` agrees with it for ordinary values but the two
  diverge for large magnitudes, where ES6 switches to exponential notation at different
  thresholds. Rather than reimplement V8's Grisu, `canonicalize` raises
  `AmbiguousNumberError` for values in the divergent range, and decision rule R6 routes
  those endpoints to UNSPECIFIED instead of guessing.
"""

from __future__ import annotations

import math
from typing import Any

__all__ = ["canonicalize", "AmbiguousNumberError", "JcsError"]


class JcsError(ValueError):
    """The value cannot be canonicalized at all (NaN, Infinity, non-JSON type)."""


class AmbiguousNumberError(JcsError):
    """A number whose ES6 and Python string forms may disagree.

    Per decision rule R6 the caller must report UNSPECIFIED rather than pick a side.
    """


# ES6 prints integers plainly below 1e21 and switches to exponential at or above it.
# Below 1e-6 it also switches. Inside this band Python's repr matches ES6 for all
# doubles; outside it we refuse rather than approximate.
_ES6_UPPER = 1e21
_ES6_LOWER = 1e-6


def _format_number(value: int | float) -> str:
    if isinstance(value, bool):  # bool is a subclass of int; JSON keeps them separate
        raise JcsError("bool routed to number formatter")

    if isinstance(value, int):
        if abs(value) >= 2**53:
            # Outside the exactly representable double range the JSON producer and the
            # signer may already disagree about the value itself.
            raise AmbiguousNumberError(f"integer {value} exceeds 2^53")
        return str(value)

    if math.isnan(value) or math.isinf(value):
        raise JcsError("NaN and Infinity are not valid JSON numbers")

    if value == 0:
        return "0"  # JCS normalises -0 to 0

    magnitude = abs(value)
    if magnitude >= _ES6_UPPER or magnitude < _ES6_LOWER:
        raise AmbiguousNumberError(f"number {value!r} falls in the ES6/Python divergent range")

    if value.is_integer():
        return str(int(value))

    return repr(value)


def _escape_string(value: str) -> str:
    out = ['"']
    for ch in value:
        code = ord(ch)
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\f":
            out.append("\\f")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif code < 0x20:
            out.append(f"\\u{code:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _utf16_sort_key(key: str) -> tuple[int, ...]:
    """RFC 8785 sorts member names by their UTF-16 code units."""
    return tuple(key.encode("utf-16-be"))


def _serialize(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return _format_number(value)
    if isinstance(value, str):
        return _escape_string(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_serialize(item) for item in value) + "]"
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise JcsError(f"non-string object key: {key!r}")
        members = sorted(value.items(), key=lambda kv: _utf16_sort_key(kv[0]))
        return "{" + ",".join(f"{_escape_string(k)}:{_serialize(v)}" for k, v in members) + "}"
    raise JcsError(f"unsupported type for JSON canonicalization: {type(value).__name__}")


def canonicalize(value: Any) -> bytes:
    """Return the RFC 8785 canonical UTF-8 encoding of a JSON value."""
    return _serialize(value).encode("utf-8")
