"""RFC 8785 canonicalization.

Getting this wrong means accusing a correctly signed card of carrying a broken
signature. Given the pilot found one signed card in twenty-five, a single false verdict
here would be a large fraction of the positive class, so the edge cases get real tests.
"""

import pytest

from agentidprobe.jcs import AmbiguousNumberError, JcsError, canonicalize


def test_object_keys_are_sorted_and_whitespace_removed():
    assert canonicalize({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_nested_structures():
    assert canonicalize({"z": [1, {"b": True, "a": None}]}) == b'{"z":[1,{"a":null,"b":true}]}'


def test_array_order_is_preserved():
    assert canonicalize([3, 1, 2]) == b"[3,1,2]"


def test_keys_sort_by_utf16_code_unit_not_code_point():
    """RFC 8785 sorts by UTF-16 code units. A supplementary-plane character encodes as a
    surrogate pair starting at 0xD800, which sorts *below* BMP characters above 0xE000 —
    the opposite of code-point order. A naive sorted() would get this backwards."""
    emoji = "\U0001f600"      # code point U+1F600, UTF-16 starts 0xD83D
    private = ""        # code point U+E000, sorts after the surrogate
    out = canonicalize({private: 1, emoji: 2}).decode()
    assert out.index(emoji) < out.index(private)


def test_control_characters_use_lowercase_short_escapes():
    assert canonicalize({"a": "\n\t"}) == b'{"a":"\\n\\t\\u0001"}'


def test_quote_and_backslash_escaped():
    assert canonicalize('a"b\\c') == b'"a\\"b\\\\c"'


def test_non_ascii_is_not_escaped():
    assert canonicalize("ü") == '"ü"'.encode()


def test_integral_floats_lose_the_decimal_point():
    assert canonicalize(1.0) == b"1"


def test_negative_zero_normalises():
    assert canonicalize(-0.0) == b"0"


def test_booleans_are_not_treated_as_numbers():
    assert canonicalize({"a": True, "b": 1}) == b'{"a":true,"b":1}'


def test_nan_and_infinity_rejected():
    with pytest.raises(JcsError):
        canonicalize(float("nan"))
    with pytest.raises(JcsError):
        canonicalize(float("inf"))


def test_large_magnitude_is_ambiguous_rather_than_guessed():
    """Decision rule R6: where ES6 and Python may disagree we refuse, and the caller
    reports UNSPECIFIED instead of manufacturing a signature failure."""
    with pytest.raises(AmbiguousNumberError):
        canonicalize(1e21)
    with pytest.raises(AmbiguousNumberError):
        canonicalize(1e-7)
    with pytest.raises(AmbiguousNumberError):
        canonicalize(2**53)


def test_ordinary_magnitudes_are_not_ambiguous():
    assert canonicalize(1e20) == b"100000000000000000000"
    assert canonicalize(0.5) == b"0.5"


def test_non_string_keys_rejected():
    with pytest.raises(JcsError):
        canonicalize({1: "a"})
