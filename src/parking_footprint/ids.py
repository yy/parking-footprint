from __future__ import annotations

import re
from collections.abc import Iterable

# Deliberately stricter than ``int``, which accepts underscore separators and
# surrounding whitespace. A feature ID such as "1_0" is a distinct label, not
# the number ten.
_INTEGER_ID = re.compile(r"^-?[0-9]+$")


def id_sort_key(value: str) -> tuple[int, int, str]:
    """Order feature IDs numerically when they are integers.

    Municipal services issue integer object IDs, national sources issue opaque
    strings, and a plain lexicographic sort puts "100" before "9". Integer IDs
    therefore sort numerically and ahead of non-integer IDs, so a mixed layer
    still has one deterministic order.
    """
    if _INTEGER_ID.fullmatch(value):
        return (0, int(value), value)
    return (1, 0, value)


def sorted_ids(values: Iterable[str]) -> list[str]:
    return sorted(values, key=id_sort_key)
