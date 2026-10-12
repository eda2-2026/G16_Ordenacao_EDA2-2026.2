from __future__ import annotations

import csv
import math
import queue
import random
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from csv_loader import CellValue, CsvDataset, CsvFormatError, load_csv
from sorting_algorithms import (
    ALGORITHMS,
    ALGORITHM_THEORY,
    SortCancelled,
    SortControl,
    SortMetrics,
)

DEFAULT_CSV_PATH = Path(__file__).resolve().parent / "dados_padrao.csv"


@dataclass(frozen=True)
class AlgorithmResult:
    name: str
    seconds: float
    metrics: SortMetrics


class BarCanvas(tk.Canvas):
    """Canvas de alta performance para desenhar barras e destacar trocas/comparações."""

    def __init__(
        self,
        master: tk.Misc,
        values: list[CellValue],
        height: int = 120,
        max_bars: int = 120,
        show_labels: bool = False,
    ) -> None:
        super().__init__(
            master,
            height=height,
            bg="#16181d",
            highlightthickness=1,
            highlightbackground="#2b2f38",
        )
        self.max_bars = max_bars
        self.show_labels = show_labels
        self._rank_map = self._build_rank_map(values)
        self._last_values: list[CellValue] = list(values)
        self._last_active: tuple[int, ...] = ()
        self._status = "waiting"
        self.bind("<Configure>", lambda _e: self._redraw())

    def set_dataset(self, values: list[CellValue]) -> None:
        self._rank_map = self._build_rank_map(values)
        self._last_values = list(values)
        self._last_active = ()
        self._status = "waiting"
        self._redraw()

    @staticmethod
    def _build_rank_map(values: list[CellValue]) -> dict[CellValue, float]:
        non_none = [v for v in values if v is not None]
        if not non_none:
            return {None: 0.08}
        if all(isinstance(v, (int, float)) for v in non_none):
            low = float(min(non_none))  # type: ignore[type-var]
            high = float(max(non_none))  # type: ignore[type-var]
            span = high - low
            mapping: dict[CellValue, float] = {None: 0.06}
            for v in set(non_none):
                norm = 0.5 if span == 0 else (float(v) - low) / span  # type: ignore[arg-type]
                mapping[v] = 0.12 + 0.80 * norm
            return mapping
        unique_sorted = sorted(set(str(v) for v in non_none))
        total = max(1, len(unique_sorted) - 1)
        mapping = {None: 0.06}
        for idx, text in enumerate(unique_sorted):
            mapping[text] = 0.12 + 0.80 * (idx / total)
        return mapping

    def update_bars(
        self,
        values: list[CellValue] | None = None,
        active: tuple[int, ...] = (),
        status: str | None = None,
    ) -> None:
        if values is not None:
            self._last_values = values
        self._last_active = active
        if status is not None:
            self._status = status
        self._redraw()

    def _redraw(self) -> None:
        self.delete("all")
        values = self._last_values
        n = len(values)
        if n == 0:
            return
        width = max(self.winfo_width(), 200)
        height = max(self.winfo_height(), 60)
        pad_x = 10
        pad_top = 24 if (self.show_labels and n <= 35) else 8
        pad_bottom = 8
        usable_w = width - 2 * pad_x
        usable_h = height - pad_top - pad_bottom

        step = max(1, math.ceil(n / self.max_bars)) if n > self.max_bars else 1
        sampled_indices = list(range(0, n, step))
        num_bars = len(sampled_indices)
        bar_w = usable_w / max(1, num_bars)
        gap = 2 if bar_w > 6 else (1 if bar_w > 3 else 0)

        active_set = set(self._last_active)

        for bar_i, data_idx in enumerate(sampled_indices):
            val = values[data_idx]
            norm_h = self._rank_map.get(
                val if isinstance(val, (int, float)) or val is None else str(val),
                0.1,
            )
            bar_h = max(4.0, norm_h * usable_h)
            x0 = pad_x + bar_i * bar_w
            x1 = x0 + max(1.0, bar_w - gap)
            y0 = height - pad_bottom - bar_h
            y1 = height - pad_bottom

            is_active = any(
                idx in active_set for idx in range(data_idx, min(n, data_idx + step))
            )

            if self._status == "done":
                color = "#2ecc71"
            elif self._status == "failed":
                color = "#e67e22"
            elif is_active:
                color = "#ff4757"
            elif val is None:
                color = "#555555"
            else:
                color = "#3b8ed0"

            self.create_rectangle(x0, y0, x1, y1, fill=color, outline="")

            if self.show_labels and n <= 35 and val is not None:
                label_str = str(val)
                if len(label_str) > 6:
                    label_str = label_str[:5] + "…"
                cx = (x0 + x1) / 2
                self.create_text(
                    cx,
                    y0 - 9,
                    text=label_str,
                    fill="#ffffff" if is_active else "#b0b8c4",
                    font=("Segoe UI", 8, "bold" if is_active else "normal"),
                )


class SortingRaceApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("Sorting Race - Corrida & Visualizador de Algoritmos")
        self.geometry("1240x840")
        self.minsize(980, 680)

        self.dataset: CsvDataset | None = None
        self._column_choice = ctk.IntVar(value=0)
        self._algorithm_choices: dict[str, ctk.BooleanVar] = {}
        self._algorithm_checks: dict[str, ctk.CTkCheckBox] = {}
        self._race_rows: dict[str, tuple[ctk.CTkLabel, BarCanvas, ctk.CTkLabel]] = {}
        self._results: list[AlgorithmResult] = []
        self._failures: list[tuple[str, str]] = []
        self._race_events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._stop_event = threading.Event()
        self._step_event = threading.Event()
        self._paused = False
        self._race_active = False
        self._parallel_race = ctk.BooleanVar(value=True)
        self._race_delay_ms = ctk.DoubleVar(value=12.0)

        # Estado da Tela Dedicada do Visualizador Passo a Passo
        self._vis_algo_var = ctk.StringVar(value="Bubble Sort")
        self._vis_size_var = ctk.StringVar(value="25")
        self._vis_delay_ms = ctk.DoubleVar(value=65.0)
        self._vis_values: list[CellValue] = []
        self._vis_canvas: BarCanvas | None = None
        self._vis_running = False

        self._poll_queue()
        self._load_default_csv(go_to_config=True)

    def _load_default_csv(self, go_to_config: bool = False) -> None:
        if DEFAULT_CSV_PATH.is_file():
            try:
                self.dataset = load_csv(DEFAULT_CSV_PATH)
                self._column_choice.set(2 if len(self.dataset.columns) > 2 else 0)
                if go_to_config:
                    self.show_configuration()
                    return
            except (CsvFormatError, OSError):
                pass
        self.show_menu()

    def _clear_screen(self) -> None:
        # Interrompe qualquer worker anterior que ainda esteja rodando
        self._stop_event.set()
        self._pause_event.set()
        while not self._race_events.empty():
            try:
                self._race_events.get_nowait()
            except queue.Empty:
                break
        for widget in self.winfo_children():
            if widget is not self:
                widget.destroy()
        self._race_rows.clear()
        self._vis_canvas = None

    def _page(self, title: str, subtitle: str = "") -> ctk.CTkFrame:
        self._clear_screen()
        shell = ctk.CTkFrame(self, fg_color="transparent")
        shell.pack(fill="both", expand=True, padx=28, pady=20)
        header = ctk.CTkFrame(shell, fg_color="transparent")
        header.pack(fill="x")
        ctk.CTkLabel(
            header,
            text=title,
            font=ctk.CTkFont(size=28, weight="bold"),
            anchor="w",
        ).pack(fill="x", pady=(0, 4))
        if subtitle:
            ctk.CTkLabel(
                header,
                text=subtitle,
                text_color=("gray40", "gray70"),
                anchor="w",
                wraplength=1140,
                justify="left",
            ).pack(fill="x", pady=(0, 14))
        content = ctk.CTkFrame(shell, fg_color="transparent")
        content.pack(fill="both", expand=True)
        return content

    def show_menu(self) -> None:
        page = self._page(
            "Sorting Race",
            "Corrida de Benchmarking e Laboratório Visual Passo a Passo de Algoritmos",
        )
        center = ctk.CTkFrame(page, fg_color="transparent")
        center.pack(expand=True)
        ctk.CTkLabel(
            center,
            text="Sorting Race - EDA 2",
            font=ctk.CTkFont(size=32, weight="bold"),
        ).pack(pady=(0, 28))

        if DEFAULT_CSV_PATH.is_file():
            ctk.CTkButton(
                center,
                text="🏁 Configurar Corrida (CSV Padrão)",
                width=290,
                height=48,
                font=ctk.CTkFont(weight="bold"),
                command=lambda: self._load_default_csv(go_to_config=True),
            ).pack(pady=8)

        ctk.CTkButton(
            center,
            text="🔬 Visualizador Passo a Passo (Laboratório)",
            width=290,
            height=48,
            fg_color="#1f6aa5",
            hover_color="#144870",
            font=ctk.CTkFont(weight="bold"),
            command=self.show_visualizer,
        ).pack(pady=8)

        ctk.CTkButton(
            center,
            text="📂 Carregar CSV Próprio...",
            width=290,
            height=46,
            fg_color="transparent",
            border_width=1,
            command=self._choose_csv,
        ).pack(pady=8)

        ctk.CTkButton(
            center,
            text="Sobre",
            width=290,
            height=42,
            fg_color="transparent",
            border_width=1,
            command=self._show_about,
        ).pack(pady=8)

        ctk.CTkButton(
            center,
            text="Sair",
            width=290,
            height=42,
            fg_color="#8b3434",
            hover_color="#a84242",
            command=self.destroy,
        ).pack(pady=8)

    def _choose_csv(self) -> None:
        selected = filedialog.askopenfilename(
            title="Selecione um arquivo CSV",
            filetypes=[
                ("Arquivos CSV/TSV", "*.csv *.tsv *.txt"),
                ("Todos os arquivos", "*.*"),
            ],
        )
        if not selected:
            return
        try:
            self.dataset = load_csv(selected)
        except (CsvFormatError, OSError) as exc:
            messagebox.showerror("Falha ao carregar CSV", str(exc), parent=self)
            return
        self._column_choice.set(0)
        self.show_configuration()

    def _show_about(self) -> None:
        messagebox.showinfo(
            "Sobre",
            "Sorting Race possui dois modos:\n\n"
            "1. Corrida de Algoritmos (Benchmark): executa múltiplos algoritmos "
            "simultaneamente com barras de progresso visual ao vivo e gera o ranking.\n\n"
            "2. Visualizador Passo a Passo: tela dedicada para observar cada comparação "
            "e troca de barras em câmera lenta ou avançando passo a passo.",
            parent=self,
        )

    def show_configuration(self) -> None:
        if self.dataset is None:
            self._load_default_csv(go_to_config=False)
            if self.dataset is None:
                return
        dataset = self.dataset
        page = self._page(
            "Configuração da Corrida",
            f"Arquivo ativo: {dataset.path.name}   |   "
            f"{len(dataset.rows):,} linhas   |   {len(dataset.headers)} colunas   |   "
            f"Separador: {repr(dataset.delimiter)}   |   Codificação: {dataset.encoding}",
        )
        page.grid_columnconfigure(0, weight=1)
        page.grid_columnconfigure(1, weight=1)
        page.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(
            page, text="1. Escolha a coluna", font=ctk.CTkFont(size=18, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=(0, 12), pady=(0, 8))
        ctk.CTkLabel(
            page,
            text="2. Escolha os algoritmos para a Corrida",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=1, sticky="w", padx=(12, 0), pady=(0, 8))

        columns_box = ctk.CTkScrollableFrame(page, label_text="Colunas detectadas")
        columns_box.grid(row=1, column=0, sticky="nsew", padx=(0, 12), pady=(0, 12))
        for index, column in enumerate(dataset.columns):
            ctk.CTkRadioButton(
                columns_box,
                text=f"{column.name}  ·  {column.display_type}",
                variable=self._column_choice,
                value=index,
                command=self._column_changed,
            ).pack(fill="x", padx=10, pady=7)

        algorithms_panel = ctk.CTkFrame(page, fg_color="transparent")
        algorithms_panel.grid(row=1, column=1, sticky="nsew", padx=(12, 0), pady=(0, 12))
        actions = ctk.CTkFrame(algorithms_panel, fg_color="transparent")
        actions.pack(fill="x", pady=(0, 6))
        ctk.CTkButton(
            actions, text="Selecionar Todos", width=140, command=self._select_all
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            actions,
            text="Limpar Seleção",
            width=140,
            fg_color="transparent",
            border_width=1,
            command=self._clear_selection,
        ).pack(side="left")
        ctk.CTkCheckBox(
            actions,
            text="Corrida simultânea",
            variable=self._parallel_race,
        ).pack(side="right", padx=6)

        algorithm_list = ctk.CTkScrollableFrame(
            algorithms_panel, label_text="Algoritmos disponíveis"
        )
        algorithm_list.pack(fill="both", expand=True)

        if not self._algorithm_choices:
            self._algorithm_choices = {
                name: ctk.BooleanVar(
                    value=name in {"Bubble Sort", "Insertion Sort", "Merge Sort", "Quick Sort"}
                )
                for name in ALGORITHMS
            }
        self._algorithm_checks.clear()
        for name in ALGORITHMS:
            checkbox = ctk.CTkCheckBox(
                algorithm_list,
                text=name,
                variable=self._algorithm_choices[name],
            )
            checkbox.pack(fill="x", padx=10, pady=5)
            self._algorithm_checks[name] = checkbox

        footer = ctk.CTkFrame(page, fg_color="transparent")
        footer.grid(row=2, column=0, columnspan=2, sticky="ew")
        footer.grid_columnconfigure(0, weight=1)
        self._configuration_note = ctk.CTkLabel(
            footer,
            text="",
            text_color=("gray40", "gray70"),
            anchor="w",
        )
        self._configuration_note.grid(row=0, column=0, sticky="w", padx=(0, 12))

        ctk.CTkButton(
            footer,
            text="Menu",
            width=100,
            fg_color="transparent",
            border_width=1,
            command=self.show_menu,
        ).grid(row=0, column=1, padx=(0, 8))

        ctk.CTkButton(
            footer,
            text="📂 Subir outro CSV...",
            width=155,
            fg_color="transparent",
            border_width=1,
            command=self._choose_csv,
        ).grid(row=0, column=2, padx=(0, 8))

        ctk.CTkButton(
            footer,
            text="🔬 Visualizador Passo a Passo",
            width=220,
            height=44,
            fg_color="#2b5b84",
            hover_color="#1f4463",
            font=ctk.CTkFont(weight="bold"),
            command=self.show_visualizer,
        ).grid(row=0, column=3, padx=(0, 10))

        ctk.CTkButton(
            footer,
            text="🏁 INICIAR CORRIDA",
            width=190,
            height=44,
            font=ctk.CTkFont(weight="bold"),
            command=self._start_race,
        ).grid(row=0, column=4)
        self._column_changed()

    def _eligible_algorithms_for_column(self, column_idx: int) -> list[str]:
        if self.dataset is None:
            return list(ALGORITHMS.keys())
        column = self.dataset.columns[column_idx]
        eligible_list = []
        for name in ALGORITHMS:
            ok = (
                name not in {"Counting Sort", "Radix Sort LSD", "Radix Sort MSD"}
                or (column.kind == "numeric" and column.integer)
            ) and (name != "Bucket Sort" or column.kind == "numeric")
            if ok:
                eligible_list.append(name)
        return eligible_list

    def _column_changed(self) -> None:
        if self.dataset is None or not self._algorithm_checks:
            return
        col_idx = self._column_choice.get()
        column = self.dataset.columns[col_idx]
        eligible_set = set(self._eligible_algorithms_for_column(col_idx))
        for name, checkbox in self._algorithm_checks.items():
            eligible = name in eligible_set
            checkbox.configure(state="normal" if eligible else "disabled")
            if not eligible:
                self._algorithm_choices[name].set(False)
        if column.kind == "text":
            note = "Counting/Radix exigem inteiros; Bucket exige números. "
        elif column.integer:
            note = "Coluna inteira: todos os 11 algoritmos estão liberados! "
        else:
            note = "Coluna decimal: Bucket Sort ativo; Counting/Radix exigem inteiros. "
        if self.dataset and len(self.dataset.rows) > 5000:
            note += "Atenção: algoritmos O(n²) podem demorar bastante."
        self._configuration_note.configure(text=note)

    def _select_all(self) -> None:
        for name, choice in self._algorithm_choices.items():
            if self._algorithm_checks[name].cget("state") != "disabled":
                choice.set(True)

    def _clear_selection(self) -> None:
        for choice in self._algorithm_choices.values():
            choice.set(False)

    # =========================================================================
    # TELA DEDICADA: VISUALIZADOR PASSO A PASSO (LABORATÓRIO DE BARRAS)
    # =========================================================================
    def show_visualizer(self) -> None:
        if self.dataset is None and DEFAULT_CSV_PATH.is_file():
            try:
                self.dataset = load_csv(DEFAULT_CSV_PATH)
                self._column_choice.set(2 if len(self.dataset.columns) > 2 else 0)
            except (CsvFormatError, OSError):
                pass

        col_idx = self._column_choice.get() if self.dataset else 0
        col_name = (
            self.dataset.headers[col_idx] if self.dataset else "Valores Aleatórios"
        )
        eligible = self._eligible_algorithms_for_column(col_idx)
        if self._vis_algo_var.get() not in eligible and eligible:
            self._vis_algo_var.set(eligible[0])

        page = self._page(
            "🔬 Visualizador Passo a Passo (Laboratório)",
            f"Coluna base: {col_name}   |   Observe detalhadamente cada comparação, "
            "troca ou deslocamento. Pause a qualquer momento e use 'Passo +1' para avançar operação por operação.",
        )
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        top_bar = ctk.CTkFrame(page)
        top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        ctk.CTkLabel(top_bar, text="Algoritmo:", font=ctk.CTkFont(weight="bold")).pack(
            side="left", padx=(14, 6), pady=10
        )
        self._vis_algo_menu = ctk.CTkOptionMenu(
            top_bar,
            variable=self._vis_algo_var,
            values=eligible,
            width=175,
            command=lambda _v: self._vis_reset_data(),
        )
        self._vis_algo_menu.pack(side="left", padx=(0, 14), pady=10)

        if self.dataset:
            ctk.CTkLabel(top_bar, text="Coluna CSV:").pack(side="left", padx=(4, 6))
            col_names = [f"{i}: {c.name}" for i, c in enumerate(self.dataset.columns)]
            self._vis_col_menu = ctk.CTkOptionMenu(
                top_bar,
                values=col_names,
                width=190,
                command=self._vis_change_column,
            )
            self._vis_col_menu.set(col_names[col_idx])
            self._vis_col_menu.pack(side="left", padx=(0, 14))

        ctk.CTkLabel(top_bar, text="Qtd. Barras:").pack(side="left", padx=(4, 6))
        ctk.CTkOptionMenu(
            top_bar,
            variable=self._vis_size_var,
            values=["15", "25", "35", "50", "80", "100"],
            width=85,
            command=lambda _v: self._vis_reset_data(),
        ).pack(side="left", padx=(0, 14))

        ctk.CTkButton(
            top_bar,
            text="🎲 Embaralhar / Resetar",
            width=165,
            fg_color="transparent",
            border_width=1,
            command=lambda: self._vis_reset_data(shuffle=True),
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            top_bar,
            text="Voltar à Configuração",
            width=165,
            fg_color="transparent",
            border_width=1,
            command=self.show_configuration,
        ).pack(side="right", padx=12)

        stage = ctk.CTkFrame(page)
        stage.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        stage.grid_columnconfigure(0, weight=1)
        stage.grid_rowconfigure(1, weight=1)

        info_bar = ctk.CTkFrame(stage, fg_color="transparent")
        info_bar.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
        self._vis_action_label = ctk.CTkLabel(
            info_bar,
            text="Pronto para iniciar. Clique em 'Iniciar Animação' ou 'Passo +1'.",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#70d69b",
            anchor="w",
        )
        self._vis_action_label.pack(side="left")

        self._vis_metrics_label = ctk.CTkLabel(
            info_bar,
            text="Comparações: 0   |   Trocas: 0   |   Deslocamentos: 0",
            font=ctk.CTkFont(size=14),
            anchor="e",
        )
        self._vis_metrics_label.pack(side="right")

        self._vis_canvas = BarCanvas(
            stage, values=[], height=420, max_bars=120, show_labels=True
        )
        self._vis_canvas.grid(row=1, column=0, sticky="nsew", padx=14, pady=(4, 12))

        self._vis_theory_label = ctk.CTkLabel(
            stage,
            text="",
            text_color=("gray40", "gray70"),
            anchor="w",
        )
        self._vis_theory_label.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 8))

        controls = ctk.CTkFrame(page)
        controls.grid(row=2, column=0, sticky="ew")

        self._vis_play_btn = ctk.CTkButton(
            controls,
            text="▶ Iniciar Animação",
            width=165,
            height=40,
            font=ctk.CTkFont(weight="bold"),
            command=self._vis_toggle_play,
        )
        self._vis_play_btn.pack(side="left", padx=(14, 8), pady=10)

        self._vis_step_btn = ctk.CTkButton(
            controls,
            text="⏭ Passo +1",
            width=130,
            height=40,
            fg_color="#2b5b84",
            hover_color="#1f4463",
            command=self._vis_step_once,
        )
        self._vis_step_btn.pack(side="left", padx=6, pady=10)

        ctk.CTkLabel(controls, text="Velocidade (Atraso ms):").pack(
            side="left", padx=(24, 8)
        )
        self._vis_delay_value_lbl = ctk.CTkLabel(
            controls, text=f"{int(self._vis_delay_ms.get())} ms", width=55, anchor="w"
        )
        slider = ctk.CTkSlider(
            controls,
            from_=1,
            to=400,
            variable=self._vis_delay_ms,
            width=220,
            command=lambda val: self._vis_delay_value_lbl.configure(
                text=f"{int(val)} ms"
            ),
        )
        slider.pack(side="left", padx=6)
        self._vis_delay_value_lbl.pack(side="left", padx=(4, 12))

        ctk.CTkButton(
            controls,
            text="🏁 Ir para Corrida Completa",
            width=195,
            height=40,
            command=self._start_race,
        ).pack(side="right", padx=14, pady=10)

        self._vis_reset_data(shuffle=False)

    def _vis_change_column(self, selection: str) -> None:
        idx = int(selection.split(":", 1)[0])
        self._column_choice.set(idx)
        eligible = self._eligible_algorithms_for_column(idx)
        self._vis_algo_menu.configure(values=eligible)
        if self._vis_algo_var.get() not in eligible and eligible:
            self._vis_algo_var.set(eligible[0])
        self._vis_reset_data(shuffle=False)

    def _vis_reset_data(self, shuffle: bool = False) -> None:
        self._stop_event.set()
        self._pause_event.set()
        self._vis_running = False
        time.sleep(0.04)

        count = int(self._vis_size_var.get())
        if self.dataset is not None:
            raw = self.dataset.values_for(self._column_choice.get())
            sample = list(raw[:count])
            if shuffle:
                random.shuffle(sample)
            self._vis_values = sample
        else:
            self._vis_values = [random.randint(5, 99) for _ in range(count)]

        algo = self._vis_algo_var.get()
        theory = ALGORITHM_THEORY.get(algo, {})
        if hasattr(self, "_vis_theory_label") and self._vis_theory_label.winfo_exists():
            self._vis_theory_label.configure(
                text=(
                    f"Algoritmo: {algo}   |   Melhor caso: {theory.get('best', '-')}   ·   "
                    f"Caso médio: {theory.get('average', '-')}   ·   "
                    f"Pior caso: {theory.get('worst', '-')}   ·   "
                    f"Estável: {theory.get('stable', '-')}   ·   "
                    f"Memória: {theory.get('memory', '-')}"
                )
            )
        if hasattr(self, "_vis_play_btn") and self._vis_play_btn.winfo_exists():
            self._vis_play_btn.configure(text="▶ Iniciar Animação")
        if hasattr(self, "_vis_action_label") and self._vis_action_label.winfo_exists():
            self._vis_action_label.configure(
                text=f"Vetor carregado com {len(self._vis_values)} barras. Pronto para ordenar!",
                text_color="#70d69b",
            )
        if hasattr(self, "_vis_metrics_label") and self._vis_metrics_label.winfo_exists():
            self._vis_metrics_label.configure(
                text="Comparações: 0   |   Trocas: 0   |   Deslocamentos: 0"
            )
        if self._vis_canvas is not None and self._vis_canvas.winfo_exists():
            self._vis_canvas.set_dataset(self._vis_values)

    def _vis_start_worker(self, start_paused: bool = False) -> None:
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._step_event = threading.Event()
        if not start_paused:
            self._pause_event.set()
            self._paused = False
            self._vis_play_btn.configure(text="⏸ Pausar")
        else:
            self._paused = True
            self._vis_play_btn.configure(text="▶ Retomar")

        self._vis_running = True
        algo_name = self._vis_algo_var.get()
        working_copy = list(self._vis_values)

        def report(
            metrics: SortMetrics,
            snapshot: list[CellValue] | None,
            active: tuple[int, ...],
            action: str,
        ) -> None:
            self._race_events.put(
                ("vis_progress", (metrics, snapshot, active, action))
            )

        def worker() -> None:
            control = SortControl(
                pause_event=self._pause_event,
                stop_event=self._stop_event,
                step_event=self._step_event,
                progress_callback=report,
                delay_getter=lambda: max(0.001, self._vis_delay_ms.get() / 1000.0),
            )
            try:
                control.bind(working_copy)
                ALGORITHMS[algo_name](working_copy, control)
                self._race_events.put(
                    ("vis_done", (control.metrics, list(working_copy)))
                )
            except SortCancelled:
                pass
            except Exception as exc:
                self._race_events.put(("vis_error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def _vis_toggle_play(self) -> None:
        if not self._vis_running:
            self._vis_start_worker(start_paused=False)
            return
        if self._paused:
            self._pause_event.set()
            self._paused = False
            self._vis_play_btn.configure(text="⏸ Pausar")
        else:
            self._pause_event.clear()
            self._paused = True
            self._vis_play_btn.configure(text="▶ Retomar")

    def _vis_step_once(self) -> None:
        if not self._vis_running:
            self._vis_start_worker(start_paused=True)
            return
        if not self._paused:
            self._pause_event.clear()
            self._paused = True
            self._vis_play_btn.configure(text="▶ Retomar")
        self._step_event.set()

    # =========================================================================
    # TELA DA CORRIDA (BENCHMARK + BARRAS EM TEMPO REAL)
    # =========================================================================
    def _start_race(self) -> None:
        if self.dataset is None:
            return
        selected = [
            name for name, choice in self._algorithm_choices.items() if choice.get()
        ]
        if not selected:
            messagebox.showwarning(
                "Selecione algoritmos",
                "Escolha pelo menos um algoritmo para iniciar a corrida.",
                parent=self,
            )
            return
        column_index = self._column_choice.get()
        try:
            values = self.dataset.values_for(column_index)
        except CsvFormatError as exc:
            messagebox.showerror("Dados inválidos", str(exc), parent=self)
            return

        slower = {"Insertion Sort", "Selection Sort", "Bubble Sort"}
        if len(values) > 5000 and slower.intersection(selected):
            if not messagebox.askyesno(
                "Algoritmos quadráticos",
                "A seleção contém algoritmos O(n²) e o arquivo tem mais de "
                "5.000 linhas. A corrida pode demorar bastante. Deseja continuar?",
                parent=self,
            ):
                return

        # Ajusta o delay visual padrão dependendo do tamanho do arquivo:
        # Para arquivos pequenos (<= 250 linhas), ativa 12ms para ver as barras competindo!
        if len(values) <= 250:
            self._race_delay_ms.set(12.0)
        else:
            self._race_delay_ms.set(0.0)

        # IMPORTANTE: construir a tela ANTES de recriar os eventos de controle!
        self.show_race(selected, values, self.dataset.headers[column_index])

        self._results = []
        self._failures = []
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._stop_event = threading.Event()
        self._paused = False
        self._race_active = True

        thread = threading.Thread(
            target=self._run_race,
            args=(selected, values, self._parallel_race.get()),
            name="sorting-race-worker",
            daemon=True,
        )
        thread.start()

    def show_race(
        self, selected: list[str], initial_values: list[CellValue], column_name: str
    ) -> None:
        page = self._page(
            "🏁 Corrida em Tempo Real",
            f"Coluna: {column_name}   |   {len(initial_values):,} valores   |   "
            "Cada algoritmo ordena uma cópia independente com visualização de barras ao vivo.",
        )
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)

        progress_panel = ctk.CTkScrollableFrame(
            page, label_text="Competidores (Barras e Métricas em Tempo Real)"
        )
        progress_panel.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        progress_panel.grid_columnconfigure(0, weight=1)
        progress_panel.grid_columnconfigure(1, weight=1)

        use_two_cols = len(selected) > 2
        canvas_height = 135 if len(selected) <= 4 else 105

        for idx, name in enumerate(selected):
            r = idx // 2 if use_two_cols else idx
            c = idx % 2 if use_two_cols else 0
            col_span = 1 if use_two_cols else 2

            card = ctk.CTkFrame(progress_panel)
            card.grid(
                row=r, column=c, columnspan=col_span, sticky="nsew", padx=8, pady=6
            )
            card.grid_columnconfigure(0, weight=1)

            header_frame = ctk.CTkFrame(card, fg_color="transparent")
            header_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=(6, 2))
            label = ctk.CTkLabel(
                header_frame,
                text=f"{name}  ·  aguardando",
                font=ctk.CTkFont(size=14, weight="bold"),
                anchor="w",
            )
            label.pack(side="left")
            metrics_lbl = ctk.CTkLabel(
                header_frame,
                text="Comp: 0  |  Trocas: 0  |  Desloc: 0",
                text_color=("gray30", "gray75"),
                anchor="e",
            )
            metrics_lbl.pack(side="right")

            bar_canvas = BarCanvas(
                card, values=initial_values, height=canvas_height, max_bars=120
            )
            bar_canvas.grid(row=1, column=0, sticky="ew", padx=10, pady=(2, 8))
            self._race_rows[name] = (label, bar_canvas, metrics_lbl)

        log_panel = ctk.CTkFrame(page)
        log_panel.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        log_panel.grid_columnconfigure(0, weight=1)
        self._race_log = ctk.CTkTextbox(log_panel, height=70, state="disabled")
        self._race_log.grid(row=0, column=0, sticky="ew", padx=10, pady=6)
        self._append_log(f"Corrida iniciada com {len(selected)} algoritmo(s).")

        controls = ctk.CTkFrame(page, fg_color="transparent")
        controls.grid(row=2, column=0, sticky="ew")

        speed_box = ctk.CTkFrame(controls, fg_color="transparent")
        speed_box.pack(side="left")
        ctk.CTkLabel(
            speed_box, text="Ritmo visual da corrida (ms/passo):"
        ).pack(side="left", padx=(0, 8))
        self._race_delay_lbl = ctk.CTkLabel(
            speed_box, text=f"{int(self._race_delay_ms.get())} ms", width=50, anchor="w"
        )
        race_slider = ctk.CTkSlider(
            speed_box,
            from_=0,
            to=60,
            variable=self._race_delay_ms,
            width=180,
            command=lambda v: self._race_delay_lbl.configure(text=f"{int(v)} ms"),
        )
        race_slider.pack(side="left", padx=(0, 6))
        self._race_delay_lbl.pack(side="left")

        self._pause_button = ctk.CTkButton(
            controls, text="Pausar", width=130, command=self._toggle_pause
        )
        self._pause_button.pack(side="right", padx=(8, 0))
        self._stop_button = ctk.CTkButton(
            controls,
            text="Parar / Ver Ranking",
            width=160,
            fg_color="#8b3434",
            hover_color="#a84242",
            command=self._stop_race,
        )
        self._stop_button.pack(side="right")

    def _run_single_algorithm(
        self,
        name: str,
        values: list[CellValue],
        results: list[AlgorithmResult],
        failures: list[tuple[str, str]],
        lock: threading.Lock,
    ) -> bool:
        if self._stop_event.is_set():
            return True
        self._race_events.put(("algorithm_started", name))

        def report(
            metrics: SortMetrics,
            snapshot: list[CellValue] | None,
            active: tuple[int, ...],
            _action: str,
            algorithm: str = name,
        ) -> None:
            self._race_events.put(
                ("progress", (algorithm, metrics, snapshot, active))
            )

        control = SortControl(
            pause_event=self._pause_event,
            stop_event=self._stop_event,
            progress_callback=report,
            delay_getter=lambda: max(0.0, self._race_delay_ms.get() / 1000.0),
        )
        try:
            working_copy = list(values)
            control.bind(working_copy)
            control.checkpoint(force=True)
            started = time.perf_counter()
            ALGORITHMS[name](working_copy, control)
            finished = time.perf_counter()
            control.checkpoint(force=True)
            elapsed = max(0.0, finished - started - control.paused_seconds)
            result = AlgorithmResult(name, elapsed, control.metrics)
            with lock:
                results.append(result)
            self._race_events.put(("algorithm_done", (result, list(working_copy))))
            return False
        except SortCancelled:
            self._race_events.put(("algorithm_cancelled", (name, control.metrics)))
            return True
        except Exception as exc:
            failure = (name, str(exc) or exc.__class__.__name__)
            with lock:
                failures.append(failure)
            self._race_events.put(("algorithm_failed", failure))
            return False

    def _run_race(
        self, selected: list[str], values: list[CellValue], parallel: bool
    ) -> None:
        results: list[AlgorithmResult] = []
        failures: list[tuple[str, str]] = []
        lock = threading.Lock()
        stopped = False

        if parallel and len(selected) > 1:
            threads = [
                threading.Thread(
                    target=self._run_single_algorithm,
                    args=(name, values, results, failures, lock),
                    daemon=True,
                )
                for name in selected
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            stopped = self._stop_event.is_set()
        else:
            for name in selected:
                if self._run_single_algorithm(name, values, results, failures, lock):
                    stopped = True
                    break

        self._race_events.put(("race_done", (results, failures, stopped)))

    def _toggle_pause(self) -> None:
        if self._paused:
            self._pause_event.set()
            self._paused = False
            self._pause_button.configure(text="Pausar")
            self._append_log("Corrida retomada.")
        else:
            self._pause_event.clear()
            self._paused = True
            self._pause_button.configure(text="Retomar")
            self._append_log("Corrida pausada.")

    def _stop_race(self) -> None:
        self._stop_event.set()
        self._pause_event.set()
        self._stop_button.configure(state="disabled", text="Parando...")
        self._append_log("Parada solicitada; finalizando execução...")

    def _append_log(self, text: str) -> None:
        if not hasattr(self, "_race_log") or not self._race_log.winfo_exists():
            return
        self._race_log.configure(state="normal")
        self._race_log.insert("end", text + "\n")
        self._race_log.see("end")
        self._race_log.configure(state="disabled")

    def _poll_queue(self) -> None:
        try:
            for _ in range(45):
                event, payload = self._race_events.get_nowait()
                if event == "vis_progress":
                    metrics, snapshot, active, action = payload  # type: ignore[misc]
                    if self._vis_canvas is not None and self._vis_canvas.winfo_exists():
                        self._vis_canvas.update_bars(
                            values=snapshot, active=active, status="running"
                        )
                        self._vis_metrics_label.configure(
                            text=(
                                f"Comparações: {metrics.comparisons:,}   |   "
                                f"Trocas: {metrics.swaps:,}   |   "
                                f"Deslocamentos: {metrics.shifts:,}"
                            )
                        )
                        if action:
                            self._vis_action_label.configure(
                                text=action, text_color="#ff9f43"
                            )
                elif event == "vis_done":
                    metrics, final_vals = payload  # type: ignore[misc]
                    self._vis_running = False
                    if self._vis_canvas is not None and self._vis_canvas.winfo_exists():
                        self._vis_canvas.update_bars(
                            values=final_vals, active=(), status="done"
                        )
                        self._vis_metrics_label.configure(
                            text=(
                                f"Comparações: {metrics.comparisons:,}   |   "
                                f"Trocas: {metrics.swaps:,}   |   "
                                f"Deslocamentos: {metrics.shifts:,}"
                            )
                        )
                        self._vis_action_label.configure(
                            text="✅ Ordenação concluída com sucesso!",
                            text_color="#2ecc71",
                        )
                        self._vis_play_btn.configure(text="▶ Iniciar Animação")
                elif event == "vis_error":
                    self._vis_running = False
                    if hasattr(self, "_vis_action_label") and self._vis_action_label.winfo_exists():
                        self._vis_action_label.configure(
                            text=f"Erro: {payload}", text_color="#ff4757"
                        )
                elif event == "algorithm_started":
                    name = str(payload)
                    if name in self._race_rows:
                        label, bar_canvas, _ = self._race_rows[name]
                        label.configure(text=f"{name}  ·  executando")
                        bar_canvas.update_bars(status="running")
                    self._append_log(f"{name}: execução iniciada.")
                elif event == "progress":
                    name, metrics, snapshot, active = payload  # type: ignore[misc]
                    self._update_metrics(name, metrics, snapshot, active)
                elif event == "algorithm_done":
                    result, final_values = payload  # type: ignore[misc]
                    if isinstance(result, AlgorithmResult):
                        if result.name in self._race_rows:
                            label, bar_canvas, _ = self._race_rows[result.name]
                            label.configure(
                                text=f"{result.name}  ·  concluído ({result.seconds:.6f}s)",
                                text_color="#2ecc71",
                            )
                            bar_canvas.update_bars(
                                values=final_values, active=(), status="done"
                            )
                        self._update_metrics(result.name, result.metrics, None, ())
                        self._append_log(
                            f"{result.name}: concluído em {result.seconds:.6f} s."
                        )
                elif event == "algorithm_cancelled":
                    name, metrics = payload  # type: ignore[misc]
                    self._update_metrics(name, metrics, None, ())
                    if name in self._race_rows:
                        label, _, _ = self._race_rows[name]
                        label.configure(text=f"{name}  ·  interrompido")
                    self._append_log(f"{name}: interrompido pelo usuário.")
                elif event == "algorithm_failed":
                    name, error = payload  # type: ignore[misc]
                    if name in self._race_rows:
                        label, bar_canvas, _ = self._race_rows[name]
                        label.configure(
                            text=f"{name}  ·  falhou", text_color="#e9a23b"
                        )
                        bar_canvas.update_bars(status="failed")
                    self._append_log(f"{name}: falhou — {error}")
                elif event == "race_done":
                    results, failures, stopped = payload  # type: ignore[misc]
                    self._results = results
                    self._failures = failures
                    self._race_active = False
                    self._append_log(
                        "Corrida interrompida."
                        if stopped
                        else "Corrida finalizada! Abrindo ranking em 1.5s..."
                    )
                    self.after(
                        350 if stopped else 1500,
                        lambda s=stopped: self.show_results(stopped=s),
                    )
        except queue.Empty:
            pass
        self.after(25, self._poll_queue)

    def _update_metrics(
        self,
        name: str,
        metrics: SortMetrics,
        snapshot: list[CellValue] | None,
        active: tuple[int, ...],
    ) -> None:
        if name not in self._race_rows:
            return
        _, bar_canvas, metrics_lbl = self._race_rows[name]
        metrics_lbl.configure(
            text=(
                f"Comp: {metrics.comparisons:,}  |  "
                f"Trocas: {metrics.swaps:,}  |  "
                f"Desloc: {metrics.shifts:,}"
            )
        )
        if snapshot is not None:
            bar_canvas.update_bars(values=snapshot, active=active)

    def show_results(self, stopped: bool = False) -> None:
        ranked = sorted(self._results, key=lambda item: item.seconds)
        heading = "Ranking final" if not stopped else "Ranking da corrida interrompida"
        page = self._page(
            heading,
            "Resultados ordenados por tempo ativo de CPU (excluindo pausas e atrasos da animação visual).",
        )
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(0, weight=1)
        content = ctk.CTkScrollableFrame(page, label_text="Resultados e análise teórica")
        content.grid(row=0, column=0, sticky="nsew", pady=(0, 12))
        content.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            content, text="Classificação prática", font=ctk.CTkFont(size=19, weight="bold")
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 8))
        table = ctk.CTkFrame(content)
        table.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 16))
        headers = ["Posição", "Algoritmo", "Tempo (s)", "Comparações", "Trocas", "Deslocamentos"]
        for column, text in enumerate(headers):
            ctk.CTkLabel(
                table, text=text, font=ctk.CTkFont(weight="bold"), anchor="w"
            ).grid(row=0, column=column, sticky="ew", padx=8, pady=8)
        for column in range(len(headers)):
            table.grid_columnconfigure(column, weight=1)
        fastest = ranked[0] if ranked else None
        fewest = min(ranked, key=lambda item: item.metrics.comparisons) if ranked else None
        medals = ["🥇", "🥈", "🥉"]
        for index, result in enumerate(ranked, start=1):
            position = f"{medals[index - 1]} {index}" if index <= 3 else str(index)
            name = result.name
            if result is fastest:
                name += "  ·  mais rápido"
            if result is fewest:
                name += "  ·  menos comparações"
            cells = [
                position,
                name,
                f"{result.seconds:.6f}",
                f"{result.metrics.comparisons:,}",
                f"{result.metrics.swaps:,}",
                f"{result.metrics.shifts:,}",
            ]
            for column, value in enumerate(cells):
                ctk.CTkLabel(
                    table,
                    text=value,
                    anchor="w",
                    text_color="#70d69b" if result is fastest and column == 1 else None,
                ).grid(row=index, column=column, sticky="ew", padx=8, pady=6)
        details_row = 2
        if not ranked:
            ctk.CTkLabel(
                content,
                text="Nenhum algoritmo concluiu a ordenação.",
                anchor="w",
            ).grid(row=details_row, column=0, sticky="w", padx=14, pady=(0, 16))
            details_row += 1

        if self._failures:
            failure_text = "Falhas: " + "  |  ".join(
                f"{name}: {error}" for name, error in self._failures
            )
            ctk.CTkLabel(
                content,
                text=failure_text,
                text_color="#e9a23b",
                wraplength=1020,
                justify="left",
                anchor="w",
            ).grid(row=details_row, column=0, sticky="ew", padx=12, pady=(0, 16))
            details_row += 1

        selected_names = [result.name for result in ranked]
        selected_names.extend(name for name, _ in self._failures)
        if selected_names:
            ctk.CTkLabel(
                content,
                text="Teoria versus prática",
                font=ctk.CTkFont(size=19, weight="bold"),
            ).grid(row=details_row, column=0, sticky="w", padx=10, pady=(6, 8))
            theory = ctk.CTkFrame(content)
            theory.grid(row=details_row + 1, column=0, sticky="ew", padx=8)
            theory_headers = [
                "Algoritmo", "Melhor", "Médio", "Pior", "Estável", "Memória extra"
            ]
            for column, text in enumerate(theory_headers):
                ctk.CTkLabel(
                    theory, text=text, font=ctk.CTkFont(weight="bold"), anchor="w"
                ).grid(row=0, column=column, sticky="ew", padx=7, pady=8)
                theory.grid_columnconfigure(column, weight=1)
            for row_index, name in enumerate(dict.fromkeys(selected_names), start=1):
                properties = ALGORITHM_THEORY[name]
                cells = [
                    name, properties["best"], properties["average"],
                    properties["worst"], properties["stable"], properties["memory"],
                ]
                for column, value in enumerate(cells):
                    ctk.CTkLabel(theory, text=value, anchor="w").grid(
                        row=row_index, column=column, sticky="ew", padx=7, pady=5
                    )
            ctk.CTkLabel(
                content,
                text=(
                    "A notação descreve crescimento assintótico (n = quantidade de valores; "
                    "k = intervalo/baldes; d = dígitos; b = base). O tempo prático depende "
                    "também dos dados, do interpretador e do computador. Pausas são excluídas "
                    "do tempo registrado."
                ),
                text_color=("gray40", "gray70"),
                justify="left",
                wraplength=1020,
            ).grid(row=details_row + 2, column=0, sticky="ew", padx=12, pady=10)

        actions = ctk.CTkFrame(page, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew")
        actions.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(
            actions,
            text="Nova Corrida",
            width=150,
            command=self.show_configuration,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            actions,
            text="🔬 Visualizador Passo a Passo",
            width=210,
            fg_color="#2b5b84",
            hover_color="#1f4463",
            command=self.show_visualizer,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            actions,
            text="Exportar CSV",
            width=150,
            fg_color="transparent",
            border_width=1,
            command=self._export_results,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            actions,
            text="Ver Gráfico",
            width=150,
            command=self._show_chart,
        ).pack(side="right")
        ctk.CTkButton(
            actions,
            text="Carregar outro CSV",
            width=160,
            fg_color="transparent",
            border_width=1,
            command=self._choose_csv,
        ).pack(side="left")

    def _show_chart(self) -> None:
        if not self._results:
            messagebox.showinfo(
                "Sem resultados", "Não há resultados concluídos para gerar o gráfico.", parent=self
            )
            return
        ranked = sorted(self._results, key=lambda item: item.seconds)
        names = [item.name for item in ranked]
        figure = Figure(figsize=(11, 7), dpi=100, constrained_layout=True)
        metrics = [
            ("Tempo de execução (s)", [item.seconds for item in ranked], "#3b8ed0"),
            ("Comparações", [item.metrics.comparisons for item in ranked], "#54a878"),
            ("Trocas", [item.metrics.swaps for item in ranked], "#d08b3b"),
        ]
        for index, (title, values, color) in enumerate(metrics, start=1):
            axis = figure.add_subplot(3, 1, index)
            axis.bar(names, values, color=color)
            axis.set_title(title)
            axis.tick_params(axis="x", labelrotation=20)
            axis.grid(axis="y", alpha=0.25)
        window = ctk.CTkToplevel(self)
        window.title("Gráfico comparativo")
        window.geometry("1000x760")
        canvas = FigureCanvasTkAgg(figure, master=window)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=12, pady=12)

    def _export_results(self) -> None:
        if not self._results:
            messagebox.showinfo(
                "Sem resultados", "Não há resultados concluídos para exportar.", parent=self
            )
            return
        destination = filedialog.asksaveasfilename(
            title="Exportar relatório",
            defaultextension=".csv",
            filetypes=[("Arquivo CSV", "*.csv")],
            initialfile="sorting_race_resultados.csv",
        )
        if not destination:
            return
        try:
            with Path(destination).open(
                "w", encoding="utf-8-sig", newline=""
            ) as output:
                writer = csv.writer(output)
                writer.writerow(
                    ["algoritmo", "tempo_segundos", "comparacoes", "trocas", "deslocamentos"]
                )
                for result in sorted(self._results, key=lambda item: item.seconds):
                    writer.writerow(
                        [
                            result.name,
                            f"{result.seconds:.9f}",
                            result.metrics.comparisons,
                            result.metrics.swaps,
                            result.metrics.shifts,
                        ]
                    )
        except OSError as exc:
            messagebox.showerror("Falha ao exportar", str(exc), parent=self)
            return
        messagebox.showinfo("Exportação concluída", f"Relatório salvo em:\n{destination}", parent=self)


def main() -> None:
    app = SortingRaceApp()
    app.mainloop()