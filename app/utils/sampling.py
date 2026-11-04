"""Picking a few items to measure instead of all of them (the import's estimates)."""

from __future__ import annotations

from typing import List, Tuple, TypeVar

Item = TypeVar("Item")
# A spread sample holds at least the first item and the last.
_FIRST_AND_LAST = 2


def spread_sample(items: List[Item], count: int) -> List[Item]:
    """count of items spread evenly from the first to the last (all of them when there are no
    more than count): an estimate's sample from items sorted by size."""
    if count < _FIRST_AND_LAST:
        raise ValueError("a spread sample needs at least two items: the first and the last")
    if len(items) <= count:
        return list(items)
    last = len(items) - 1
    return [items[index * last // (count - 1)] for index in range(count)]


def scaled_total(sample: List[Tuple[int, int]], total: int) -> int:
    """total scaled as the sample's (before, after) sizes scale: about what total comes to."""
    before = sum(size_before for size_before, _size_after in sample)
    if before == 0:
        return total
    return round(total * sum(size_after for _size_before, size_after in sample) / before)
