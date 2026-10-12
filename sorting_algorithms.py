from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Callable, TypeAlias


SortValue: TypeAlias = int | float | str | None
ProgressCallback: TypeAlias = Callable[
    ["SortMetrics", list[SortValue] | None, tuple[int, ...], str], None
]


class SortCancelled(Exception):
    """Raised when a race or visualization is stopped by the user."""


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
        step_event: threading.Event | None = None,
        progress_callback: ProgressCallback | None = None,
        delay_getter: Callable[[], float] | None = None,
    ) -> None:
        if pause_event is None:
            pause_event = threading.Event()
            pause_event.set()
        self.pause_event = pause_event
        self.stop_event = stop_event or threading.Event()
        self.step_event = step_event or threading.Event()
        self.progress_callback = progress_callback
        self.delay_getter = delay_getter
        self.comparisons = 0
        self.swaps = 0
        self.shifts = 0
        self.paused_seconds = 0.0
        self._operations = 0
        self._last_report = time.perf_counter()
        self.tracked_values: list[SortValue] | None = None
        self.active_indices: tuple[int, ...] = ()
        self.last_action: str = "Iniciando..."

    @property
    def metrics(self) -> SortMetrics:
        return SortMetrics(self.comparisons, self.swaps, self.shifts)

    def bind(self, values: list[SortValue]) -> None:
        self.tracked_values = values

    def checkpoint(
        self,
        force: bool = False,
        active: tuple[int, ...] = (),
        action: str = "",
    ) -> None:
        self._operations += 1
        if active:
            self.active_indices = active
        if action:
            self.last_action = action

        delay = self.delay_getter() if self.delay_getter else 0.0
        is_stepping = not self.pause_event.is_set()

        if force or delay > 0 or is_stepping or self._operations % 256 == 0:
            if self.stop_event.is_set():
                raise SortCancelled
            if not self.pause_event.is_set():
                # Se estiver pausado no modo passo a passo, envia o frame atual antes de aguardar
                if self.progress_callback and self.tracked_values is not None:
                    self.progress_callback(
                        self.metrics,
                        list(self.tracked_values),
                        self.active_indices,
                        self.last_action,
                    )
                paused_at = time.perf_counter()
                while not self.pause_event.is_set():
                    if self.stop_event.is_set():
                        raise SortCancelled
                    if self.step_event.is_set():
                        self.step_event.clear()
                        break
                    time.sleep(0.03)
                self.paused_seconds += time.perf_counter() - paused_at
                if self.stop_event.is_set():
                    raise SortCancelled

        now = time.perf_counter()
        if self.progress_callback and (
            force
            or delay > 0
            or self._operations % 4096 == 0
            or now - self._last_report >= 0.04
        ):
            snapshot = (
                list(self.tracked_values)
                if self.tracked_values is not None
                else None
            )
            self.progress_callback(
                self.metrics, snapshot, self.active_indices, self.last_action
            )
            self._last_report = now

        if delay > 0 and not force and self.pause_event.is_set():
            sleep_start = time.perf_counter()
            time.sleep(delay)
            self.paused_seconds += time.perf_counter() - sleep_start

    def compare(
        self,
        left: SortValue,
        right: SortValue,
        active: tuple[int, ...] = (),
    ) -> int:
        self.comparisons += 1
        desc = f"Comparando {left!r} e {right!r}" if active else ""
        self.checkpoint(active=active, action=desc)
        if left is None:
            return 0 if right is None else 1
        if right is None:
            return -1
        return (left > right) - (left < right)

    def swap(self, values: list[SortValue], left: int, right: int) -> None:
        if left == right:
            return
        v_left, v_right = values[left], values[right]
        values[left], values[right] = v_right, v_left
        self.swaps += 1
        self.checkpoint(
            active=(left, right),
            action=f"Trocando pos [{left}] ({v_left!r}) ↔ pos [{right}] ({v_right!r})",
        )

    def shift(self, active: tuple[int, ...] = (), action: str = "") -> None:
        self.shifts += 1
        self.checkpoint(
            active=active,
            action=action or (f"Deslocando elemento na pos {active}" if active else ""),
        )


def insertion_sort(values: list[SortValue], control: SortControl) -> None:
    control.bind(values)
    for index in range(1, len(values)):
        item = values[index]
        cursor = index - 1
        while (
            cursor >= 0
            and control.compare(values[cursor], item, (cursor, cursor + 1)) > 0
        ):
            values[cursor + 1] = values[cursor]
            control.shift(
                (cursor, cursor + 1),
                f"Deslocando {values[cursor]!r} para a direita (pos {cursor + 1})",
            )
            cursor -= 1
        values[cursor + 1] = item
        control.checkpoint(
            active=(cursor + 1,),
            action=f"Inserindo {item!r} na posição {cursor + 1}",
        )


def selection_sort(values: list[SortValue], control: SortControl) -> None:
    control.bind(values)
    for start in range(len(values) - 1):
        minimum = start
        for index in range(start + 1, len(values)):
            if (
                control.compare(
                    values[index], values[minimum], (index, minimum)
                )
                < 0
            ):
                minimum = index
        control.swap(values, start, minimum)


def bubble_sort(values: list[SortValue], control: SortControl) -> None:
    control.bind(values)
    for end in range(len(values) - 1, 0, -1):
        changed = False
        for index in range(end):
            if (
                control.compare(
                    values[index], values[index + 1], (index, index + 1)
                )
                > 0
            ):
                control.swap(values, index, index + 1)
                changed = True
        if not changed:
            break


def merge_sort(values: list[SortValue], control: SortControl) -> None:
    control.bind(values)
    scratch = values.copy()

    def merge(start: int, middle: int, end: int) -> None:
        left, right, target = start, middle, start
        while left < middle and right < end:
            if (
                control.compare(values[left], values[right], (left, right))
                <= 0
            ):
                scratch[target] = values[left]
                left += 1
            else:
                scratch[target] = values[right]
                right += 1
            values[target] = scratch[target]
            control.shift(
                (target,),
                f"Intercalando valor {scratch[target]!r} na posição {target}",
            )
            target += 1
        while left < middle:
            scratch[target] = values[left]
            values[target] = scratch[target]
            left += 1
            control.shift(
                (target,),
                f"Copiando restante esquerdo {scratch[target]!r} para pos {target}",
            )
            target += 1
        while right < end:
            scratch[target] = values[right]
            values[target] = scratch[target]
            right += 1
            control.shift(
                (target,),
                f"Copiando restante direito {scratch[target]!r} para pos {target}",
            )
            target += 1

    width = 1
    while width < len(values):
        for start in range(0, len(values), width * 2):
            middle = min(start + width, len(values))
            end = min(start + width * 2, len(values))
            if middle < end:
                merge(start, middle, end)
        width *= 2


def quick_sort(values: list[SortValue], control: SortControl) -> None:
    control.bind(values)
    if len(values) < 2:
        return
    pending = [(0, len(values) - 1)]
    while pending:
        low, high = pending.pop()
        if low >= high:
            continue
        pivot_idx = (low + high) // 2
        pivot = values[pivot_idx]
        lower, cursor, upper = low, low, high
        while cursor <= upper:
            relation = control.compare(
                values[cursor], pivot, (cursor, pivot_idx)
            )
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
    control.bind(values)
    size = len(values)

    def sift_down(root: int, end: int) -> None:
        while root * 2 + 1 <= end:
            child = root * 2 + 1
            larger = root
            if (
                control.compare(values[larger], values[child], (larger, child))
                < 0
            ):
                larger = child
            if (
                child + 1 <= end
                and control.compare(
                    values[larger], values[child + 1], (larger, child + 1)
                )
                < 0
            ):
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
    control.bind(values)
    gap = len(values) // 2
    while gap > 0:
        for index in range(gap, len(values)):
            item = values[index]
            cursor = index
            while (
                cursor >= gap
                and control.compare(
                    values[cursor - gap], item, (cursor - gap, cursor)
                )
                > 0
            ):
                values[cursor] = values[cursor - gap]
                control.shift(
                    (cursor - gap, cursor),
                    f"Gap={gap}: movendo {values[cursor]!r} da pos {cursor - gap} para {cursor}",
                )
                cursor -= gap
            values[cursor] = item
            control.checkpoint(
                active=(cursor,),
                action=f"Gap={gap}: posicionando {item!r} no índice {cursor}",
            )
        gap //= 2


def _integer_values(
    values: list[SortValue], algorithm: str, control: SortControl
) -> tuple[list[int], int]:
    present: list[int] = []
    for idx, value in enumerate(values):
        control.checkpoint(active=(idx,), action=f"Lendo elemento na posição {idx}")
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            raise TypeError(f"{algorithm} aceita somente valores inteiros.")
        present.append(value)
    return present, len(present)


def counting_sort(values: list[SortValue], control: SortControl) -> None:
    control.bind(values)
    present, count = _integer_values(values, "Counting Sort", control)
    if not count:
        return
    minimum = maximum = present[0]
    for idx, value in enumerate(present[1:], start=1):
        if control.compare(value, minimum, (idx,)) < 0:
            minimum = value
        if control.compare(value, maximum, (idx,)) > 0:
            maximum = value
    span = maximum - minimum + 1
    if span > 1_000_000:
        raise ValueError(
            "O intervalo dos inteiros é grande demais para o Counting Sort "
            f"({span} posições; limite de 1.000.000)."
        )
    counts = [0] * span
    for idx, value in enumerate(present):
        counts[value - minimum] += 1
        control.checkpoint(
            active=(idx,), action=f"Contando frequência do valor {value}"
        )
    output_index = 0
    for offset, frequency in enumerate(counts):
        for _ in range(frequency):
            val = offset + minimum
            values[output_index] = val
            control.shift(
                (output_index,),
                f"Escrevendo valor {val} na posição {output_index}",
            )
            output_index += 1
    for idx in range(output_index, len(values)):
        values[idx] = None
        control.checkpoint(active=(idx,))


def bucket_sort(values: list[SortValue], control: SortControl) -> None:
    control.bind(values)
    present: list[int | float] = []
    for idx, value in enumerate(values):
        control.checkpoint(active=(idx,))
        if value is not None:
            if not isinstance(value, (int, float)):
                raise TypeError("Bucket Sort aceita somente números.")
            present.append(value)
    if not present:
        return
    minimum = maximum = present[0]
    for idx, value in enumerate(present[1:], start=1):
        if control.compare(value, minimum, (idx,)) < 0:
            minimum = value
        if control.compare(value, maximum, (idx,)) > 0:
            maximum = value
    buckets: list[list[SortValue]] = [
        [] for _ in range(max(1, math.isqrt(len(present))))
    ]
    if minimum == maximum:
        values[: len(present)] = present
        values[len(present) :] = [None] * (len(values) - len(present))
        return

    for idx, value in enumerate(present):
        if (
            isinstance(value, int)
            and isinstance(minimum, int)
            and isinstance(maximum, int)
        ):
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
        control.checkpoint(
            active=(idx,),
            action=f"Distribuindo {value} para o Balde #{bucket_index}",
        )

    preview_idx = 0
    for bucket in buckets:
        for val in bucket:
            values[preview_idx] = val
            preview_idx += 1
    control.checkpoint(force=True, action="Baldes distribuídos; ordenando internamente...")

    output_index = 0
    for b_idx, bucket in enumerate(buckets):
        base_idx = output_index
        for index in range(1, len(bucket)):
            item = bucket[index]
            cursor = index - 1
            while (
                cursor >= 0
                and control.compare(
                    bucket[cursor], item, (base_idx + cursor, base_idx + index)
                )
                > 0
            ):
                bucket[cursor + 1] = bucket[cursor]
                values[base_idx + cursor + 1] = bucket[cursor]
                control.shift(
                    (base_idx + cursor, base_idx + cursor + 1),
                    f"Balde #{b_idx}: deslocando {bucket[cursor]!r}",
                )
                cursor -= 1
            bucket[cursor + 1] = item
            values[base_idx + cursor + 1] = item
        for value in bucket:
            values[output_index] = value
            control.checkpoint(
                active=(output_index,),
                action=f"Consolidando Balde #{b_idx}: {value!r} na pos {output_index}",
            )
            output_index += 1
    values[output_index:] = [None] * (len(values) - output_index)


def _radix_key_bounds(
    present: list[int], control: SortControl
) -> tuple[int, int]:
    minimum = maximum = present[0]
    for idx, value in enumerate(present[1:], start=1):
        if control.compare(value, minimum, (idx,)) < 0:
            minimum = value
        if control.compare(value, maximum, (idx,)) > 0:
            maximum = value
    return minimum, maximum


def radix_sort_lsd(values: list[SortValue], control: SortControl) -> None:
    control.bind(values)
    present, count = _integer_values(values, "Radix Sort LSD", control)
    if not count:
        return
    minimum, maximum = _radix_key_bounds(present, control)
    offset = -minimum if minimum < 0 else 0
    keys = [value + offset for value in present]
    maximum_key = maximum + offset
    shift = 0
    pass_num = 1
    while (maximum_key >> shift) > 0:
        frequencies = [0] * 256
        for idx, key in enumerate(keys):
            frequencies[(key >> shift) & 0xFF] += 1
            control.checkpoint(
                active=(idx,),
                action=f"Passada LSD #{pass_num}: contando dígito de {present[idx]}",
            )
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
            values[position] = present[index]
            control.shift(
                (position, index),
                f"Passada LSD #{pass_num}: movendo {present[index]} para pos {position}",
            )
        present = [value for value in output_values if value is not None]
        keys = output_keys
        shift += 8
        pass_num += 1
    values[:count] = present
    values[count:] = [None] * (len(values) - count)


def radix_sort_msd(values: list[SortValue], control: SortControl) -> None:
    control.bind(values)
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
            buckets[(keys[index] >> shift) & 0xFF].append(
                (present[index], keys[index])
            )
            control.checkpoint(
                active=(index,),
                action=f"MSD nível {digit_index}: classificando {present[index]}",
            )
        cursor = start
        for bucket in buckets:
            bucket_start = cursor
            for value, key in bucket:
                present[cursor] = value
                keys[cursor] = key
                values[cursor] = value
                control.shift(
                    (cursor,),
                    f"MSD nível {digit_index}: posicionando {value} no índice {cursor}",
                )
                cursor += 1
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