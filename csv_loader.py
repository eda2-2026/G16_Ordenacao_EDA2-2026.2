from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import TypeAlias


CellValue: TypeAlias = int | float | str | None
SUPPORTED_ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
SUPPORTED_DELIMITERS = ",;\t"


class CsvFormatError(ValueError):
    """Raised when a CSV file cannot be interpreted as a table."""


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    kind: str
    integer: bool = False

    @property
    def display_type(self) -> str:
        if self.kind == "text":
            return "Texto"
        return "Número inteiro" if self.integer else "Número decimal"


@dataclass(frozen=True)
class CsvDataset:
    path: Path
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    columns: tuple[ColumnInfo, ...]
    delimiter: str
    encoding: str

    def values_for(self, column_index: int) -> list[CellValue]:
        if not 0 <= column_index < len(self.columns):
            raise IndexError(f"Índice de coluna inválido: {column_index}")

        column = self.columns[column_index]
        values: list[CellValue] = []
        for row in self.rows:
            raw_value = row[column_index].strip()
            if not raw_value:
                values.append(None)
            elif column.kind == "numeric":
                number = _parse_number(raw_value)
                if number is None:
                    raise CsvFormatError(
                        f"O valor {raw_value!r} na coluna {column.name!r} "
                        "não corresponde ao tipo detectado."
                    )
                values.append(number)
            else:
                values.append(raw_value)
        return values


def _parse_number(value: str) -> int | float | None:
    try:
        return int(value)
    except ValueError:
        try:
            number = float(value.replace(",", "."))
        except ValueError:
            return None
        return number if math.isfinite(number) else None


def _detect_delimiter(stream) -> str:
    sample = stream.read(8192)
    stream.seek(0)
    if not sample:
        raise CsvFormatError("O arquivo CSV está vazio.")
    try:
        return csv.Sniffer().sniff(sample, delimiters=SUPPORTED_DELIMITERS).delimiter
    except csv.Error:
        return ","


def _build_dataset(path: Path, stream, encoding: str) -> CsvDataset:
    delimiter = _detect_delimiter(stream)
    reader = csv.reader(stream, delimiter=delimiter)
    try:
        raw_headers = next(reader)
    except StopIteration as exc:
        raise CsvFormatError("O arquivo CSV não contém cabeçalho.") from exc
    except csv.Error as exc:
        raise CsvFormatError(f"Não foi possível ler o cabeçalho: {exc}") from exc

    if not raw_headers:
        raise CsvFormatError("O arquivo CSV não contém nomes de coluna.")
    headers = tuple(
        cell.strip() or f"Coluna {index + 1}"
        for index, cell in enumerate(raw_headers)
    )
    rows: list[tuple[str, ...]] = []
    try:
        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            if len(row) > len(headers):
                raise CsvFormatError(
                    f"A linha {reader.line_num} contém mais valores "
                    f"({len(row)}) do que colunas ({len(headers)})."
                )
            rows.append(tuple(row + [""] * (len(headers) - len(row))))
    except csv.Error as exc:
        raise CsvFormatError(f"Erro de formato na linha {reader.line_num}: {exc}") from exc

    columns: list[ColumnInfo] = []
    for index, name in enumerate(headers):
        nonempty_values = [
            row[index].strip() for row in rows if row[index].strip()
        ]
        parsed = [_parse_number(value) for value in nonempty_values]
        is_numeric = bool(nonempty_values) and all(value is not None for value in parsed)
        is_integer = is_numeric and all(isinstance(value, int) for value in parsed)
        columns.append(
            ColumnInfo(
                name=name,
                kind="numeric" if is_numeric else "text",
                integer=is_integer,
            )
        )

    return CsvDataset(
        path=path,
        headers=headers,
        rows=tuple(rows),
        columns=tuple(columns),
        delimiter=delimiter,
        encoding=encoding,
    )


def load_csv(file_path: str | Path) -> CsvDataset:
    path = Path(file_path)
    if not path.is_file():
        raise CsvFormatError(f"O arquivo não existe: {path}")

    decode_errors: list[str] = []
    for encoding in SUPPORTED_ENCODINGS:
        try:
            with path.open("r", encoding=encoding, newline="") as stream:
                return _build_dataset(path, stream, encoding)
        except UnicodeDecodeError as exc:
            decode_errors.append(f"{encoding}: {exc}")
        except csv.Error as exc:
            raise CsvFormatError(f"Erro ao ler o CSV: {exc}") from exc

    details = "; ".join(decode_errors)
    raise CsvFormatError(f"Não foi possível decodificar o arquivo. {details}")
