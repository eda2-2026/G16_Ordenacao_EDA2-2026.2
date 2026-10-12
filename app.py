from __future__ import annotations

import csv
import queue
import threading
import time
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


@dataclass(frozen=True)
class AlgorithmResult:
    name: str
    seconds: float
    metrics: SortMetrics


class SortingRaceApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        self.title("Corrida de Algoritmos")
        self.geometry("1180x800")
        self.minsize(940, 650)

        self.dataset: CsvDataset | None = None
        self._column_choice = ctk.IntVar(value=0)
        self._algorithm_choices: dict[str, ctk.BooleanVar] = {}
        self._algorithm_checks: dict[str, ctk.CTkCheckBox] = {}
        self._race_rows: dict[str, tuple[ctk.CTkLabel, ctk.CTkProgressBar]] = {}
        self._results: list[AlgorithmResult] = []
        self._failures: list[tuple[str, str]] = []
        self._race_events: queue.Queue[tuple[str, object]] = queue.Queue()
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._stop_event = threading.Event()
        self._paused = False
        self._race_active = False

        self._poll_queue()
        self.show_menu()

    def _clear_screen(self) -> None:
        for widget in self.winfo_children():
            if widget is not self:
                widget.destroy()
        self._race_rows.clear()

    def _page(self, title: str, subtitle: str = "") -> ctk.CTkFrame:
        self._clear_screen()
        shell = ctk.CTkFrame(self, fg_color="transparent")
        shell.pack(fill="both", expand=True, padx=28, pady=24)
        header = ctk.CTkFrame(shell, fg_color="transparent")
        header.pack(fill="x")
        ctk.CTkLabel(
            header,
            text=title,
            font=ctk.CTkFont(size=29, weight="bold"),
            anchor="w",
        ).pack(fill="x", pady=(0, 5))
        if subtitle:
            ctk.CTkLabel(
                header,
                text=subtitle,
                text_color=("gray40", "gray70"),
                anchor="w",
                wraplength=1050,
                justify="left",
            ).pack(fill="x", pady=(0, 18))
        content = ctk.CTkFrame(shell, fg_color="transparent")
        content.pack(fill="both", expand=True)
        return content

    def show_menu(self) -> None:
        page = self._page("Sorting Race", "Corrida de Algoritmos de Ordenação")
        center = ctk.CTkFrame(page, fg_color="transparent")
        center.pack(expand=True)
        ctk.CTkLabel(
            center,
            text="Sorting Race - Corrida de Algoritmos",
            font=ctk.CTkFont(size=30, weight="bold"),
        ).pack(pady=(0, 34))
        ctk.CTkButton(
            center,
            text="Carregar CSV",
            width=250,
            height=48,
            command=self._choose_csv,
        ).pack(pady=9)
        ctk.CTkButton(
            center,
            text="Sobre",
            width=250,
            height=44,
            fg_color="transparent",
            border_width=1,
            command=self._show_about,
        ).pack(pady=9)
        ctk.CTkButton(
            center,
            text="Sair",
            width=250,
            height=44,
            fg_color="#8b3434",
            hover_color="#a84242",
            command=self.destroy,
        ).pack(pady=9)

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
            "Sorting Race compara algoritmos de ordenação sobre os valores de "
            "uma coluna de um arquivo CSV. As métricas são coletadas durante "
            "a execução; o tempo pode variar conforme o computador e o tamanho "
            "dos dados.",
            parent=self,
        )

    def show_configuration(self) -> None:
        if self.dataset is None:
            self.show_menu()
            return
        dataset = self.dataset
        page = self._page(
            "Configuração da corrida",
            f"Arquivo: {dataset.path.name}   |   "
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
            text="2. Escolha os algoritmos",
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
        algorithm_list = ctk.CTkScrollableFrame(
            algorithms_panel, label_text="Algoritmos disponíveis"
        )
        algorithm_list.pack(fill="both", expand=True)

        self._algorithm_choices = {
            name: ctk.BooleanVar(value=name in {
                "Merge Sort", "Quick Sort", "Heap Sort", "Shell Sort"
            })
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
            text="Voltar ao Menu",
            width=140,
            fg_color="transparent",
            border_width=1,
            command=self.show_menu,
        ).grid(row=0, column=1, padx=(0, 10))
        ctk.CTkButton(
            footer,
            text="INICIAR CORRIDA",
            width=190,
            height=44,
            font=ctk.CTkFont(weight="bold"),
            command=self._start_race,
        ).grid(row=0, column=2)
        self._column_changed()

    def _column_changed(self) -> None:
        if self.dataset is None or not self._algorithm_checks:
            return
        column = self.dataset.columns[self._column_choice.get()]
        for name, checkbox in self._algorithm_checks.items():
            eligible = (
                name not in {"Counting Sort", "Radix Sort LSD", "Radix Sort MSD"}
                or (column.kind == "numeric" and column.integer)
            ) and (name != "Bucket Sort" or column.kind == "numeric")
            checkbox.configure(state="normal" if eligible else "disabled")
            if not eligible:
                self._algorithm_choices[name].set(False)
        if column.kind == "text":
            note = "Counting/Radix exigem inteiros; Bucket exige números. "
        elif column.integer:
            note = "Valores vazios serão posicionados no final. "
        else:
            note = "Valores vazios serão posicionados no final. Counting/Radix exigem inteiros. "
        if self.dataset and len(self.dataset.rows) > 5000:
            note += "Atenção: algoritmos O(n²) podem demorar muito neste arquivo."
        self._configuration_note.configure(text=note)

    def _select_all(self) -> None:
        for name, choice in self._algorithm_choices.items():
            if self._algorithm_checks[name].cget("state") != "disabled":
                choice.set(True)

    def _clear_selection(self) -> None:
        for choice in self._algorithm_choices.values():
            choice.set(False)

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
        self._results = []
        self._failures = []
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._stop_event = threading.Event()
        self._paused = False
        self._race_active = True
        self.show_race(selected, len(values), self.dataset.headers[column_index])
        thread = threading.Thread(
            target=self._run_race,
            args=(selected, values),
            name="sorting-race-worker",
            daemon=True,
        )
        thread.start()

    def show_race(self, selected: list[str], value_count: int, column_name: str) -> None:
        page = self._page(
            "Corrida em tempo real",
            f"Coluna: {column_name}   |   {value_count:,} valores   |   "
            "Cada algoritmo recebe uma cópia independente.",
        )
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        progress_panel = ctk.CTkScrollableFrame(page, label_text="Progresso e métricas")
        progress_panel.grid(row=0, column=0, sticky="nsew", pady=(0, 12))
        progress_panel.grid_columnconfigure(0, weight=1)
        for row_index, name in enumerate(selected):
            line = ctk.CTkFrame(progress_panel)
            line.grid(row=row_index, column=0, sticky="ew", padx=8, pady=6)
            line.grid_columnconfigure(1, weight=1)
            label = ctk.CTkLabel(
                line, text=f"{name}  ·  aguardando", width=245, anchor="w"
            )
            label.grid(row=0, column=0, padx=10, pady=(8, 3), sticky="w")
            bar = ctk.CTkProgressBar(line, mode="indeterminate")
            bar.set(0)
            bar.grid(row=0, column=1, padx=10, pady=(8, 3), sticky="ew")
            metrics = ctk.CTkLabel(
                line, text="Comparações: 0  |  Trocas: 0", anchor="w"
            )
            metrics.grid(row=1, column=0, columnspan=2, padx=10, pady=(0, 8), sticky="w")
            self._race_rows[name] = (label, bar)

        log_panel = ctk.CTkFrame(page)
        log_panel.grid(row=1, column=0, sticky="nsew", pady=(0, 12))
        log_panel.grid_rowconfigure(1, weight=1)
        log_panel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            log_panel, text="Registro da corrida", anchor="w"
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 0))
        self._race_log = ctk.CTkTextbox(log_panel, height=110, state="disabled")
        self._race_log.grid(row=1, column=0, sticky="nsew", padx=10, pady=8)
        self._append_log(f"Corrida iniciada com {len(selected)} algoritmo(s).")

        controls = ctk.CTkFrame(page, fg_color="transparent")
        controls.grid(row=2, column=0, sticky="ew")
        controls.grid_columnconfigure(0, weight=1)
        self._pause_button = ctk.CTkButton(
            controls, text="Pausar", width=130, command=self._toggle_pause
        )
        self._pause_button.pack(side="right", padx=(8, 0))
        self._stop_button = ctk.CTkButton(
            controls,
            text="Parar",
            width=130,
            fg_color="#8b3434",
            hover_color="#a84242",
            command=self._stop_race,
        )
        self._stop_button.pack(side="right")

    def _run_race(self, selected: list[str], values: list[CellValue]) -> None:
        results: list[AlgorithmResult] = []
        failures: list[tuple[str, str]] = []
        stopped = False
        for name in selected:
            if self._stop_event.is_set():
                stopped = True
                break
            self._race_events.put(("algorithm_started", name))

            def report(metrics: SortMetrics, algorithm: str = name) -> None:
                self._race_events.put(("progress", (algorithm, metrics)))

            control = SortControl(
                pause_event=self._pause_event,
                stop_event=self._stop_event,
                progress_callback=report,
            )
            try:
                working_copy = list(values)
                control.checkpoint(force=True)
                started = time.perf_counter()
                ALGORITHMS[name](working_copy, control)
                finished = time.perf_counter()
                control.checkpoint(force=True)
                elapsed = max(
                    0.0, finished - started - control.paused_seconds
                )
                result = AlgorithmResult(name, elapsed, control.metrics)
                results.append(result)
                self._race_events.put(("algorithm_done", result))
            except SortCancelled:
                stopped = True
                self._race_events.put(("algorithm_cancelled", (name, control.metrics)))
                break
            except Exception as exc:
                failure = (name, str(exc) or exc.__class__.__name__)
                failures.append(failure)
                self._race_events.put(("algorithm_failed", failure))
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
        self._append_log("Parada solicitada; aguardando o algoritmo atual.")

    def _append_log(self, text: str) -> None:
        if not hasattr(self, "_race_log") or not self._race_log.winfo_exists():
            return
        self._race_log.configure(state="normal")
        self._race_log.insert("end", text + "\n")
        self._race_log.see("end")
        self._race_log.configure(state="disabled")

    def _poll_queue(self) -> None:
        try:
            while True:
                event, payload = self._race_events.get_nowait()
                if event == "algorithm_started":
                    name = str(payload)
                    if name in self._race_rows:
                        label, bar = self._race_rows[name]
                        label.configure(text=f"{name}  ·  executando")
                        bar.start()
                    self._append_log(f"{name}: execução iniciada.")
                elif event == "progress":
                    name, metrics = payload  # type: ignore[misc]
                    self._update_metrics(name, metrics)
                elif event == "algorithm_done":
                    result = payload
                    if isinstance(result, AlgorithmResult):
                        self._update_metrics(result.name, result.metrics)
                        if result.name in self._race_rows:
                            label, bar = self._race_rows[result.name]
                            bar.stop()
                            bar.set(1)
                            label.configure(text=f"{result.name}  ·  concluído")
                        self._append_log(
                            f"{result.name}: concluído em {result.seconds:.6f} s."
                        )
                elif event == "algorithm_cancelled":
                    name, metrics = payload  # type: ignore[misc]
                    self._update_metrics(name, metrics)
                    if name in self._race_rows:
                        label, bar = self._race_rows[name]
                        bar.stop()
                        label.configure(text=f"{name}  ·  interrompido")
                    self._append_log(f"{name}: interrompido pelo usuário.")
                elif event == "algorithm_failed":
                    name, error = payload  # type: ignore[misc]
                    if name in self._race_rows:
                        label, bar = self._race_rows[name]
                        bar.stop()
                        label.configure(text=f"{name}  ·  falhou", text_color="#e9a23b")
                    self._append_log(f"{name}: falhou — {error}")
                elif event == "race_done":
                    results, failures, stopped = payload  # type: ignore[misc]
                    self._results = results
                    self._failures = failures
                    self._race_active = False
                    self._append_log(
                        "Corrida interrompida." if stopped else "Corrida finalizada."
                    )
                    self.show_results(stopped=stopped)
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _update_metrics(self, name: str, metrics: SortMetrics) -> None:
        if name not in self._race_rows:
            return
        label, _ = self._race_rows[name]
        line = label.master
        metrics_label = line.grid_slaves(row=1, column=0)
        if metrics_label:
            metrics_label[0].configure(
                text=(
                    f"Comparações: {metrics.comparisons:,}  |  "
                    f"Trocas: {metrics.swaps:,}  |  "
                    f"Deslocamentos: {metrics.shifts:,}"
                )
            )

    def show_results(self, stopped: bool = False) -> None:
        ranked = sorted(self._results, key=lambda item: item.seconds)
        heading = "Ranking final" if not stopped else "Ranking da corrida interrompida"
        page = self._page(
            heading,
            "Resultados ordenados por tempo de execução. "
            "O tempo medido exclui períodos em que a corrida ficou pausada.",
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
            command=self.show_menu,
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
