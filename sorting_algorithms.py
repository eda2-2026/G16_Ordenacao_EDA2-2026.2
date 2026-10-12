from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Callable, TypeAlias


SortValue: TypeAlias = int | float | str | None
ProgressCallback: TypeAlias = Callable[["SortMetrics"], None]


class SortCancelled(Exception):
    """Raised when a race is stopped by the user."""


@dataclass(frozen=True)
class SortMetrics:
    comparisons: int = 0
    swaps: int = 0
    shifts: int = 0


class SortControl:
    def __init__(
        self,
        pause_event: threading.Event | None = None,
        stop_event: threading.Event | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        if pause_event is None:
            pause_event = threading.Event()
            pause_event.set()
        self.pause_event = pause_event
        self.stop_event = stop_event or threading.Event()
        self.progress_callback = progress_callback
        self.comparisons = 0
        self.swaps = 0
        self.shifts = 0
        self.paused_seconds = 0.0
        self._operations = 0
        self._last_report = time.perf_counter()

    @property
    def metrics(self) -> SortMetrics:
        return SortMetrics(self.comparisons, self.swaps, self.shifts)

    def checkpoint(self, force: bool = False) -> None:
        self._operations += 1
        now = time.perf_counter()
        if force or self._operations % 256 == 0:
            if self.stop_event.is_set():
                raise SortCancelled
            if not self.pause_event.is_set():
                paused_at = time.perf_counter()
                while not self.pause_event.wait(0.1):
                    if self.stop_event.is_set():
                        raise SortCancelled
                self.paused_seconds += time.perf_counter() - paused_at
                if self.stop_event.is_set():
                    raise SortCancelled
        if self.progress_callback and (
            force or self._operations % 8192 == 0 or now - self._last_report >= 0.2
        ):
            self.progress_callback(self.metrics)
            self._last_report = now

    def compare(self, left: SortValue, right: SortValue) -> int:
        self.comparisons += 1
        self.checkpoint()
        if left is None:
            return 0 if right is None else 1
        if right is None:
            return -1
        return (left > right) - (left < right)

    def swap(self, values: list[SortValue], left: int, right: int) -> None:
        if left == right:
            return
        values[left], values[right] = values[right], values[left]
        self.swaps += 1
        self.checkpoint()

    def shift(self) -> None:
        self.shifts += 1
        self.checkpoint()


def insertion_sort(values: list[SortValue], control: SortControl) -> None:
    for index in range(1, len(values)):
        item = values[index]
        cursor = index - 1
        while cursor >= 0 and control.compare(values[cursor], item) > 0:
            values[cursor + 1] = values[cursor]
            control.shift()
            cursor -= 1
        values[cursor + 1] = item
        control.checkpoint()


def selection_sort(values: list[SortValue], control: SortControl) -> None:
    for start in range(len(values) - 1):
        minimum = start
        for index in range(start + 1, len(values)):
            if control.compare(values[index], values[minimum]) < 0:
                minimum = index
        control.swap(values, start, minimum)


def bubble_sort(values: list[SortValue], control: SortControl) -> None:
    for end in range(len(values) - 1, 0, -1):
        changed = False
        for index in range(end):
            if control.compare(values[index], values[index + 1]) > 0:
                control.swap(values, index, index + 1)
                changed = True
        if not changed:
            break


def merge_sort(values: list[SortValue], control: SortControl) -> None:
    scratch = values.copy()

    def merge(start: int, middle: int, end: int) -> None:
        left, right, target = start, middle, start
        while left < middle and right < end:
            if control.compare(values[left], values[right]) <= 0:
                scratch[target] = values[left]
                left += 1
            else:
                scratch[target] = values[right]
                right += 1
            target += 1
            control.checkpoint()
        while left < middle:
            scratch[target] = values[left]
            left += 1
            target += 1
            control.checkpoint()
        while right < end:
            scratch[target] = values[right]
            right += 1
            target += 1
            control.checkpoint()
        values[start:end] = scratch[start:end]

    width = 1
    while width < len(values):
        for start in range(0, len(values), width * 2):
            middle = min(start + width, len(values))
            end = min(start + width * 2, len(values))
            if middle < end:
                merge(start, middle, end)
        width *= 2


def quick_sort(values: list[SortValue], control: SortControl) -> None:
    if len(values) < 2:
        return
    pending = [(0, len(values) - 1)]
    while pending:
        low, high = pending.pop()
        if low >= high:
            continue
        pivot = values[(low + high) // 2]
        lower, cursor, upper = low, low, high
        while cursor <= upper:
            relation = control.compare(values[cursor], pivot)
            if relation < 0:
                control.swap(values, lower, cursor)
                lower += 1
                cursor += 1
            elif relation > 0:
                control.swap(values, cursor, upper)
                upper -= 1
            else:
                cursor += 1
        if lower - low > high - upper:
            pending.append((low, lower - 1))
            pending.append((upper + 1, high))
        else:
            pending.append((upper + 1, high))
            pending.append((low, lower - 1))


def heap_sort(values: list[SortValue], control: SortControl) -> None:
    size = len(values)

    def sift_down(root: int, end: int) -> None:
        while root * 2 + 1 <= end:
            child = root * 2 + 1
            larger = root
            if control.compare(values[larger], values[child]) < 0:
                larger = child
            if child + 1 <= end and control.compare(
                values[larger], values[child + 1]
            ) < 0:
                larger = child + 1
            if larger == root:
                return
            control.swap(values, root, larger)
            root = larger

    for root in range(size // 2 - 1, -1, -1):
        sift_down(root, size - 1)
    for end in range(size - 1, 0, -1):
        control.swap(values, 0, end)
        sift_down(0, end - 1)


def shell_sort(values: list[SortValue], control: SortControl) -> None:
    gap = len(values) // 2
    while gap > 0:
        for index in range(gap, len(values)):
            item = values[index]
            cursor = index
            while cursor >= gap and control.compare(values[cursor - gap], item) > 0:
                values[cursor] = values[cursor - gap]
                control.shift()
                cursor -= gap
            values[cursor] = item
            control.checkpoint()
        gap //= 2


def _integer_values(
    values: list[SortValue], algorithm: str, control: SortControl
) -> tuple[list[int], int]:
    present: list[int] = []
    for value in values:
        control.checkpoint()
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{algorithm} aceita somente valores inteiros.")
        present.append(value)
    return present, len(present)


def counting_sort(values: list[SortValue], control: SortControl) -> None:
    present, count = _integer_values(values, "Counting Sort", control)
    if not count:
        return
    minimum = maximum = present[0]
    for value in present[1:]:
        if control.compare(value, minimum) < 0:
            minimum = value
        if control.compare(value, maximum) > 0:
            maximum = value
    span = maximum - minimum + 1
    if span > 1_000_000:
        raise ValueError(
            "O intervalo dos inteiros é grande demais para o Counting Sort "
            f"({span} posições; limite de 1.000.000)."
        )
    counts = [0] * span
    for value in present:
        counts[value - minimum] += 1
        control.checkpoint()
    output_index = 0
    for offset, frequency in enumerate(counts):
        for _ in range(frequency):
            values[output_index] = offset + minimum
            output_index += 1
            control.checkpoint()
    values[output_index:] = [None] * (len(values) - output_index)


def bucket_sort(values: list[SortValue], control: SortControl) -> None:
    present: list[int | float] = []
    for value in values:
        control.checkpoint()
        if value is not None:
            if not isinstance(value, (int, float)):
                raise TypeError("Bucket Sort aceita somente números.")
            present.append(value)
    if not present:
        return
    minimum = maximum = present[0]
    for value in present[1:]:
        if control.compare(value, minimum) < 0:
            minimum = value
        if control.compare(value, maximum) > 0:
            maximum = value
    buckets: list[list[SortValue]] = [[] for _ in range(max(1, math.isqrt(len(present))))]
    if minimum == maximum:
        values[: len(present)] = present
        values[len(present) :] = [None] * (len(values) - len(present))
        return

    for value in present:
        if isinstance(value, int) and isinstance(minimum, int) and isinstance(maximum, int):
            span = maximum - minimum
            bucket_index = (value - minimum) * len(buckets) // span
        else:
            scaled_minimum = minimum / 2
            scaled_span = maximum / 2 - scaled_minimum
            if scaled_span == 0:
                bucket_index = 0 if value == minimum else len(buckets) - 1
            else:
                bucket_index = int(
                    (value / 2 - scaled_minimum) / scaled_span * len(buckets)
                )
        bucket_index = min(bucket_index, len(buckets) - 1)
        buckets[bucket_index].append(value)
        control.checkpoint()

    output_index = 0
    for bucket in buckets:
        for index in range(1, len(bucket)):
            item = bucket[index]
            cursor = index - 1
            while cursor >= 0 and control.compare(bucket[cursor], item) > 0:
                bucket[cursor + 1] = bucket[cursor]
                control.shift()
                cursor -= 1
            bucket[cursor + 1] = item
        for value in bucket:
            values[output_index] = value
            output_index += 1
            control.checkpoint()
    values[output_index:] = [None] * (len(values) - output_index)


def _radix_key_bounds(
    present: list[int], control: SortControl
) -> tuple[int, int]:
    minimum = maximum = present[0]
    for value in present[1:]:
        if control.compare(value, minimum) < 0:
            minimum = value
        if control.compare(value, maximum) > 0:
            maximum = value
    return minimum, maximum


def radix_sort_lsd(values: list[SortValue], control: SortControl) -> None:
    present, count = _integer_values(values, "Radix Sort LSD", control)
    if not count:
        return
    minimum, maximum = _radix_key_bounds(present, control)
    offset = -minimum if minimum < 0 else 0
    keys = [value + offset for value in present]
    maximum_key = maximum + offset
    shift = 0
    while (maximum_key >> shift) > 0:
        frequencies = [0] * 256
        for key in keys:
            frequencies[(key >> shift) & 0xFF] += 1
            control.checkpoint()
        for index in range(1, 256):
            frequencies[index] += frequencies[index - 1]
        output_values: list[int | None] = [None] * count
        output_keys = [0] * count
        for index in range(count - 1, -1, -1):
            digit = (keys[index] >> shift) & 0xFF
            frequencies[digit] -= 1
            position = frequencies[digit]
            output_values[position] = present[index]
            output_keys[position] = keys[index]
            control.checkpoint()
        present = [value for value in output_values if value is not None]
        keys = output_keys
        shift += 8
    values[:count] = present
    values[count:] = [None] * (len(values) - count)


def radix_sort_msd(values: list[SortValue], control: SortControl) -> None:
    present, count = _integer_values(values, "Radix Sort MSD", control)
    if not count:
        return
    minimum, maximum = _radix_key_bounds(present, control)
    offset = -minimum if minimum < 0 else 0
    keys = [value + offset for value in present]
    digits = max(1, ((maximum + offset).bit_length() + 7) // 8)
    pending = [(0, count, digits - 1)]
    while pending:
        start, end, digit_index = pending.pop()
        if end - start < 2 or digit_index < 0:
            continue
        shift = digit_index * 8
        buckets: list[list[tuple[int, int]]] = [[] for _ in range(256)]
        for index in range(start, end):
            buckets[(keys[index] >> shift) & 0xFF].append((present[index], keys[index]))
            control.checkpoint()
        cursor = start
        for bucket in buckets:
            bucket_start = cursor
            for value, key in bucket:
                present[cursor] = value
                keys[cursor] = key
                cursor += 1
                control.checkpoint()
            if len(bucket) > 1:
                pending.append((bucket_start, cursor, digit_index - 1))
    values[:count] = present
    values[count:] = [None] * (len(values) - count)


ALGORITHMS: dict[str, Callable[[list[SortValue], SortControl], None]] = {
    "Insertion Sort": insertion_sort,
    "Selection Sort": selection_sort,
    "Bubble Sort": bubble_sort,
    "Merge Sort": merge_sort,
    "Quick Sort": quick_sort,
    "Heap Sort": heap_sort,
    "Shell Sort": shell_sort,
    "Counting Sort": counting_sort,
    "Bucket Sort": bucket_sort,
    "Radix Sort LSD": radix_sort_lsd,
    "Radix Sort MSD": radix_sort_msd,
}

ALGORITHM_THEORY: dict[str, dict[str, str]] = {
    "Insertion Sort": {
        "best": "O(n)", "average": "O(n²)", "worst": "O(n²)",
        "stable": "Sim", "memory": "In-place",
    },
    "Selection Sort": {
        "best": "O(n²)", "average": "O(n²)", "worst": "O(n²)",
        "stable": "Não", "memory": "In-place",
    },
    "Bubble Sort": {
        "best": "O(n)", "average": "O(n²)", "worst": "O(n²)",
        "stable": "Sim", "memory": "In-place",
    },
    "Merge Sort": {
        "best": "O(n log n)", "average": "O(n log n)", "worst": "O(n log n)",
        "stable": "Sim", "memory": "O(n) extra",
    },
    "Quick Sort": {
        "best": "O(n log n)", "average": "O(n log n)", "worst": "O(n²)",
        "stable": "Não", "memory": "In-place (pilha O(log n) média)",
    },
    "Heap Sort": {
        "best": "O(n log n)", "average": "O(n log n)", "worst": "O(n log n)",
        "stable": "Não", "memory": "In-place",
    },
    "Shell Sort": {
        "best": "O(n log n)", "average": "Depende dos intervalos", "worst": "O(n²)",
        "stable": "Não", "memory": "In-place",
    },
    "Counting Sort": {
        "best": "O(n + k)", "average": "O(n + k)", "worst": "O(n + k)",
        "stable": "Sim", "memory": "O(k) extra",
    },
    "Bucket Sort": {
        "best": "O(n + k)", "average": "O(n + k)", "worst": "O(n²)",
        "stable": "Sim", "memory": "O(n + k) extra",
    },
    "Radix Sort LSD": {
        "best": "O(d(n + b))", "average": "O(d(n + b))", "worst": "O(d(n + b))",
        "stable": "Sim", "memory": "O(n + b) extra",
    },
    "Radix Sort MSD": {
        "best": "O(d(n + b))", "average": "O(d(n + b))", "worst": "O(d(n + b))",
        "stable": "Sim", "memory": "O(n + b) extra",
    },
}
