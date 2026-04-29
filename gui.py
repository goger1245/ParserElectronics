from __future__ import annotations

import asyncio
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from browser_config import CamoufoxBrowserConfig
from logger import get_logger
from product_parser import SearchSummary, search_all_shops


logger = get_logger(__name__)


class ParserGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Parser Electronics")
        self.geometry("1180x720")
        self.minsize(960, 620)
        self.configure(bg="#101827")

        self._is_loading = False
        self._animation_step = 0
        self._row_urls: dict[str, str] = {}
        self._best_url: str | None = None

        self._setup_styles()
        self._build_layout()

    def _setup_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Main.TFrame",
            background="#101827",
        )
        style.configure(
            "Card.TFrame",
            background="#172033",
            relief="flat",
        )
        style.configure(
            "Title.TLabel",
            background="#101827",
            foreground="#f8fafc",
            font=("Segoe UI", 24, "bold"),
        )
        style.configure(
            "Muted.TLabel",
            background="#101827",
            foreground="#94a3b8",
            font=("Segoe UI", 10),
        )
        style.configure(
            "Card.TLabel",
            background="#172033",
            foreground="#e2e8f0",
            font=("Segoe UI", 11),
        )
        style.configure(
            "Link.TLabel",
            background="#172033",
            foreground="#38bdf8",
            font=("Segoe UI", 10, "underline"),
        )
        style.configure(
            "Best.TLabel",
            background="#172033",
            foreground="#5eead4",
            font=("Segoe UI", 14, "bold"),
        )
        style.configure(
            "Search.TButton",
            background="#38bdf8",
            foreground="#06111f",
            borderwidth=0,
            focusthickness=0,
            font=("Segoe UI", 11, "bold"),
            padding=(16, 10),
        )
        style.map(
            "Search.TButton",
            background=[("disabled", "#334155"), ("active", "#7dd3fc")],
            foreground=[("disabled", "#94a3b8")],
        )
        style.configure(
            "Dark.Horizontal.TProgressbar",
            background="#38bdf8",
            troughcolor="#243044",
            bordercolor="#243044",
            lightcolor="#38bdf8",
            darkcolor="#0ea5e9",
        )
        style.configure(
            "Treeview",
            background="#111827",
            foreground="#e5e7eb",
            fieldbackground="#111827",
            borderwidth=0,
            rowheight=34,
            font=("Segoe UI", 10),
        )
        style.configure(
            "Treeview.Heading",
            background="#22304a",
            foreground="#f8fafc",
            borderwidth=0,
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Treeview",
            background=[("selected", "#0f766e")],
            foreground=[("selected", "#ffffff")],
        )

    def _build_layout(self) -> None:
        root = ttk.Frame(self, style="Main.TFrame", padding=28)
        root.pack(fill=tk.BOTH, expand=True)

        ttk.Label(root, text="Parser Electronics", style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            root,
            text="Параллельный поиск техники в DNS, Citilink и М.Видео через Camoufox.",
            style="Muted.TLabel",
        ).pack(anchor=tk.W, pady=(6, 24))

        search_card = ttk.Frame(root, style="Card.TFrame", padding=22)
        search_card.pack(fill=tk.X)

        fields = ttk.Frame(search_card, style="Card.TFrame")
        fields.pack(fill=tk.X)
        fields.columnconfigure(0, weight=1, uniform="search_fields")
        fields.columnconfigure(1, weight=1, uniform="search_fields")
        fields.columnconfigure(2, weight=0)

        query_box = ttk.Frame(fields, style="Card.TFrame")
        query_box.grid(row=0, column=0, sticky=tk.EW, padx=(0, 12))
        ttk.Label(query_box, text="Что ищем", style="Card.TLabel").pack(anchor=tk.W)
        self.query_entry = tk.Entry(
            query_box,
            bg="#0f172a",
            fg="#f8fafc",
            insertbackground="#f8fafc",
            relief=tk.FLAT,
            font=("Segoe UI", 13),
            highlightthickness=1,
            highlightbackground="#334155",
            highlightcolor="#38bdf8",
        )
        self.query_entry.pack(fill=tk.X, ipady=11, pady=(8, 0))
        self.query_entry.bind("<Return>", lambda _event: self.start_search())

        proxy_box = ttk.Frame(fields, style="Card.TFrame")
        proxy_box.grid(row=0, column=1, sticky=tk.EW, padx=(0, 12))
        ttk.Label(proxy_box, text="Прокси, если нужен", style="Card.TLabel").pack(anchor=tk.W)
        self.proxy_entry = tk.Entry(
            proxy_box,
            bg="#0f172a",
            fg="#f8fafc",
            insertbackground="#f8fafc",
            relief=tk.FLAT,
            font=("Segoe UI", 13),
            highlightthickness=1,
            highlightbackground="#334155",
            highlightcolor="#38bdf8",
        )
        self.proxy_entry.pack(fill=tk.X, ipady=11, pady=(8, 0))

        self.search_button = ttk.Button(
            fields,
            text="Найти дешевле",
            style="Search.TButton",
            width=16,
            command=self.start_search,
        )
        self.search_button.grid(row=0, column=2, sticky=tk.E, pady=(28, 0))

        loader = ttk.Frame(search_card, style="Card.TFrame")
        loader.pack(fill=tk.X, pady=(18, 0))
        self.loading_label = ttk.Label(
            loader,
            text="Готов к поиску",
            style="Card.TLabel",
            width=28,
        )
        self.loading_label.pack(side=tk.LEFT)
        self.progress = ttk.Progressbar(
            loader,
            mode="indeterminate",
            style="Dark.Horizontal.TProgressbar",
        )
        self.progress.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(18, 0))

        result_card = ttk.Frame(root, style="Card.TFrame", padding=22)
        result_card.pack(fill=tk.BOTH, expand=True, pady=(22, 0))

        self.best_label = ttk.Label(
            result_card,
            text="Лучший результат появится здесь",
            style="Best.TLabel",
            justify=tk.LEFT,
            wraplength=920,
        )
        self.best_label.pack(anchor=tk.W, pady=(0, 16))
        result_card.bind(
            "<Configure>",
            lambda event: self.best_label.configure(
                wraplength=max(420, event.width - 44),
            ),
        )
        self.best_url_label = ttk.Label(
            result_card,
            text="",
            style="Link.TLabel",
            cursor="hand2",
            wraplength=920,
        )
        self.best_url_label.pack(anchor=tk.W, pady=(0, 16))
        self.best_url_label.bind("<Button-1>", self._open_best_url)
        result_card.bind(
            "<Configure>",
            lambda event: self.best_url_label.configure(
                wraplength=max(420, event.width - 44),
            ),
            add="+",
        )

        columns = ("shop", "title", "price", "status", "url")
        table_frame = ttk.Frame(result_card, style="Card.TFrame")
        table_frame.pack(fill=tk.BOTH, expand=True)

        self.result_table = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        self.result_table.heading("shop", text="Магазин")
        self.result_table.heading("title", text="Товар")
        self.result_table.heading("price", text="Цена")
        self.result_table.heading("status", text="Статус")
        self.result_table.heading("url", text="Ссылка")
        self.result_table.column("shop", width=105, minwidth=90, anchor=tk.W, stretch=False)
        self.result_table.column("title", width=430, minwidth=260, anchor=tk.W, stretch=True)
        self.result_table.column("price", width=110, minwidth=95, anchor=tk.CENTER, stretch=False)
        self.result_table.column("status", width=130, minwidth=110, anchor=tk.W, stretch=False)
        self.result_table.column("url", width=250, minwidth=170, anchor=tk.W, stretch=False)
        self.result_table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.result_table.bind("<Button-1>", self._open_clicked_url)
        self.result_table.bind("<Double-1>", self._open_selected_url)

        ttk.Label(
            result_card,
            text="Клик по ссылке или двойной клик по строке откроет товар в браузере.",
            style="Card.TLabel",
        ).pack(anchor=tk.W, pady=(14, 0))

    def start_search(self) -> None:
        if self._is_loading:
            return

        query = self.query_entry.get().strip()
        proxy = self.proxy_entry.get().strip() or None
        if not query:
            messagebox.showwarning("Нет запроса", "Введите название техники для поиска.")
            return

        logger.info("Старт поиска из GUI: %s", query)
        self._clear_results()
        self._set_loading(True)
        thread = threading.Thread(
            target=self._run_search_worker,
            args=(query, proxy),
            daemon=True,
        )
        thread.start()

    def _run_search_worker(self, query: str, proxy: str | None) -> None:
        try:
            browser_config = CamoufoxBrowserConfig(proxy=proxy)
            summary = asyncio.run(search_all_shops(query, browser_config))
            self.after(0, self._show_results, summary)
        except Exception as exc:
            self.after(0, self._show_error, str(exc))

    def _show_results(self, summary: SearchSummary) -> None:
        self._set_loading(False)
        logger.info("Поиск завершён: %s", summary.query)

        for result in summary.results:
            if result.offer is None:
                self.result_table.insert(
                    "",
                    tk.END,
                    values=(
                        result.shop,
                        "-",
                        "-",
                        "нету",
                        "-",
                    ),
                )
                continue

            row_id = self.result_table.insert(
                "",
                tk.END,
                values=(
                    result.shop,
                    self._shorten_text(result.offer.title, 78),
                    result.offer.formatted_price,
                    "Найдено",
                    self._shorten_url(result.offer.url),
                ),
            )
            self._row_urls[row_id] = result.offer.url

        best = summary.best_offer
        if best is None:
            self.best_label.configure(text="Не удалось найти товары с ценой")
            self.best_url_label.configure(text="")
            self._best_url = None
            return

        self._best_url = best.url
        self.best_label.configure(
            text=(
                f"Самый дешёвый: {best.shop} • {best.formatted_price}\n"
                f"{best.title}"
            )
        )
        self.best_url_label.configure(text=best.url)

    def _show_error(self, error: str) -> None:
        self._set_loading(False)
        logger.error("Поиск остановлен из-за ошибки: %s", error)
        self.best_label.configure(text="Поиск остановлен из-за ошибки")
        messagebox.showerror("Ошибка", error)

    def _set_loading(self, is_loading: bool) -> None:
        self._is_loading = is_loading
        state = tk.DISABLED if is_loading else tk.NORMAL
        self.search_button.configure(state=state)
        self.query_entry.configure(state=state)
        self.proxy_entry.configure(state=state)

        if is_loading:
            self.progress.start(12)
            self._animate_loading()
        else:
            self.progress.stop()
            self.loading_label.configure(text="Готов к поиску")

    def _animate_loading(self) -> None:
        if not self._is_loading:
            return

        frames = (
            "Открываю Camoufox",
            "Ввожу поисковые запросы",
            "Собираю HTML и цены",
            "Сравниваю предложения",
        )
        dots = "." * ((self._animation_step % 3) + 1)
        text = frames[self._animation_step % len(frames)]
        self.loading_label.configure(text=f"{text}{dots}")
        self._animation_step += 1
        self.after(450, self._animate_loading)

    def _clear_results(self) -> None:
        self._row_urls.clear()
        self._best_url = None
        for row in self.result_table.get_children():
            self.result_table.delete(row)
        self.best_label.configure(text="Ищу лучший вариант...")
        self.best_url_label.configure(text="")

    def _open_best_url(self, _event: tk.Event) -> None:
        if self._best_url:
            webbrowser.open(self._best_url)

    def _open_clicked_url(self, event: tk.Event) -> None:
        if self.result_table.identify_column(event.x) != "#5":
            return

        row_id = self.result_table.identify_row(event.y)
        url = self._row_urls.get(row_id)
        if url:
            webbrowser.open(url)

    def _open_selected_url(self, _event: tk.Event) -> None:
        selected = self.result_table.selection()
        if not selected:
            return

        url = self._row_urls.get(selected[0])
        if url:
            webbrowser.open(url)

    @staticmethod
    def _shorten_text(text: str, max_length: int) -> str:
        text = " ".join(text.split())
        if len(text) <= max_length:
            return text
        return text[: max_length - 1].rstrip() + "…"

    @staticmethod
    def _shorten_url(url: str, max_length: int = 44) -> str:
        if len(url) <= max_length:
            return url
        return url[: max_length - 1].rstrip("/") + "…"


def run_gui() -> None:
    app = ParserGui()
    app.mainloop()
