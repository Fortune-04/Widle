"""Widle - a small Windows desktop widget showing monthly business profit (RM) with RM/USD conversion."""

import json
import os
import queue
import sys
import threading
import tkinter as tk
import urllib.request
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from tkinter import messagebox

tray = None
if sys.platform == "win32":
    import tray

__version__ = "1.2.0"

RATE_URL = "https://api.frankfurter.app/latest?from=MYR&to=USD"
RATE_REFRESH_MS = 6 * 60 * 60 * 1000
DATA_FILE = Path(os.environ.get("APPDATA", str(Path.home()))) / "Widle" / "data.json"
DEFAULT_BUSINESSES = ("Trading", "Investment", "Car Business")
MAX_NAME_LENGTH = 30
CENT = Decimal("0.01")
MAX_AMOUNT = Decimal("1e12")
SYMBOLS = {"MYR": "RM", "USD": "USD"}

BG, FG, MUTED, ACCENT, POSITIVE, NEGATIVE, FIELD = (
    "#1e1f26", "#f2f2f2", "#9a9cab", "#4f8cff", "#3ecf8e", "#ff6b6b", "#2b2d38",
)
FONT = "Segoe UI"
SCALE = 1.2


def scaled(value):
    return int(value * SCALE + 0.5)


def parse_amount(text):
    cleaned = text.strip().replace(",", "").replace(" ", "")
    for prefix in ("RM", "USD", "$"):
        if cleaned.upper().startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError("Enter a valid number")
    if not value.is_finite() or abs(value) >= MAX_AMOUNT:
        raise ValueError("Amount is out of range")
    return value.quantize(CENT, ROUND_HALF_UP)


def convert(amount, myr_to_usd, to_usd):
    result = amount * myr_to_usd if to_usd else amount / myr_to_usd
    return result.quantize(CENT, ROUND_HALF_UP)


def format_money(value, currency):
    sign = "-" if value < 0 else ""
    return f"{sign}{SYMBOLS[currency]} {abs(value):,.2f}"


def amount_color(value):
    return POSITIVE if value > 0 else NEGATIVE if value < 0 else FG


def month_key(d):
    return f"{d.year:04d}-{d.month:02d}"


def shift_month(key, delta):
    year, month = map(int, key.split("-"))
    index = year * 12 + (month - 1) + delta
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def month_label(key):
    return datetime.strptime(key, "%Y-%m").strftime("%B %Y")


def fetch_rate(timeout=10):
    with urllib.request.urlopen(RATE_URL, timeout=timeout) as resp:
        payload = json.loads(resp.read(10_000), parse_float=Decimal)
    rate = Decimal(payload["rates"]["USD"])
    if not Decimal("0.01") < rate < Decimal("10"):
        raise ValueError(f"Unexpected MYR/USD rate: {rate}")
    rate_date = date.fromisoformat(str(payload["date"])).isoformat()
    return rate, rate_date


class Store:
    def __init__(self, path=DATA_FILE):
        self.path = Path(path)
        self.businesses = list(DEFAULT_BUSINESSES)
        self.profits = {}
        self.rate = None
        self.rate_date = None
        self.position = None
        self.currency = "MYR"
        self._load()

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        names = data.get("businesses")
        if isinstance(names, list):
            self.businesses = []
            for name in names:
                try:
                    self.businesses.append(self.clean_name(str(name)))
                except ValueError:
                    continue
        profits = data.get("profits")
        for key, entries in (profits.items() if isinstance(profits, dict) else ()):
            if not isinstance(entries, dict):
                continue
            try:
                shift_month(key, 0)
            except ValueError:
                continue
            month = {}
            for name, value in entries.items():
                if name in self.businesses:
                    try:
                        month[name] = parse_amount(str(value))
                    except ValueError:
                        continue
            if month:
                self.profits[key] = month
        try:
            rate = Decimal(str(data["rate"]))
            if rate.is_finite() and rate > 0:
                self.rate, self.rate_date = rate, str(data.get("rate_date") or "")
        except (KeyError, InvalidOperation):
            pass
        pos = data.get("position")
        if isinstance(pos, list) and len(pos) == 2 and all(isinstance(v, int) for v in pos):
            self.position = pos
        if data.get("currency") in SYMBOLS:
            self.currency = data["currency"]

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "businesses": self.businesses,
            "profits": {month: {name: str(value) for name, value in entries.items()}
                        for month, entries in sorted(self.profits.items())},
            "rate": str(self.rate) if self.rate is not None else None,
            "rate_date": self.rate_date,
            "position": self.position,
            "currency": self.currency,
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def clean_name(self, name, exclude=None):
        name = " ".join(name.split())
        if not name:
            raise ValueError("Enter a business name")
        if len(name) > MAX_NAME_LENGTH:
            raise ValueError(f"Name is too long (max {MAX_NAME_LENGTH})")
        if any(n.lower() == name.lower() and n != exclude for n in self.businesses):
            raise ValueError("Business already exists")
        return name

    def add_business(self, name):
        self.businesses.append(self.clean_name(name))
        self.save()

    def rename_business(self, old, new):
        new = self.clean_name(new, exclude=old)
        self.businesses[self.businesses.index(old)] = new
        for entries in self.profits.values():
            if old in entries:
                entries[new] = entries.pop(old)
        self.save()

    def remove_business(self, name):
        self.businesses.remove(name)
        for month in list(self.profits):
            self.profits[month].pop(name, None)
            if not self.profits[month]:
                del self.profits[month]
        self.save()

    def set_profit(self, month, business, value):
        entries = self.profits.setdefault(month, {})
        if value is None:
            entries.pop(business, None)
        else:
            entries[business] = value
        if not entries:
            del self.profits[month]
        self.save()

    def month_total(self, month):
        entries = self.profits.get(month)
        return sum(entries.values(), Decimal(0)) if entries else None

    def set_rate(self, rate, rate_date):
        self.rate, self.rate_date = rate, rate_date
        self.save()

    def set_currency(self, currency):
        self.currency = currency
        self.save()


def virtual_screen(root):
    try:
        import ctypes
        metrics = ctypes.windll.user32.GetSystemMetrics
        return metrics(76), metrics(77), metrics(78), metrics(79)
    except (AttributeError, OSError):
        return 0, 0, root.winfo_screenwidth(), root.winfo_screenheight()


class Widget:
    def __init__(self, root, store):
        self.root = root
        self.store = store
        self.month = month_key(date.today())
        self.editing = None
        self.rate_queue = queue.Queue()
        self.tray_events = queue.Queue()
        self.fetching = False
        self._drag = (0, 0)
        self.tray = None
        if tray:
            try:
                self.tray = tray.Tray(self.tray_events.put)
            except OSError:
                self.tray = None

        root.overrideredirect(True)
        root.configure(bg=BG)
        root.attributes("-alpha", 0.96)
        root.attributes("-topmost", True)
        root.minsize(scaled(300), 1)
        self._build()
        self.refresh_profit()
        self.update_rate_status()
        self._place_window()
        self.fetch_rate_async()
        root.after(100, self._poll)
        root.after(RATE_REFRESH_MS, self._scheduled_refresh)

    def show(self):
        self.root.deiconify()
        self.root.lift()

    def hide(self):
        if self.tray:
            self.root.withdraw()
        else:
            self.exit()

    def exit(self):
        if self.tray:
            self.tray.remove()
        self.root.destroy()

    def update_tray_tooltip(self):
        if not self.tray:
            return
        current = month_key(date.today())
        total = self.store.month_total(current)
        amount = self.money(total) if total is not None else "no profit recorded"
        self.tray.set_tooltip(f"Widle v{__version__} \u00b7 {month_label(current)}: {amount}")

    def _place_window(self):
        self.root.update_idletasks()
        width = self.root.winfo_reqwidth()
        vx, vy, vw, vh = virtual_screen(self.root)
        x, y = self.store.position or (vx + self.root.winfo_screenwidth() - width - 40, 60)
        x = min(max(vx, x), vx + vw - width)
        y = min(max(vy, y), vy + vh - 80)
        self.root.geometry(f"+{x}+{y}")

    def _label(self, parent, text="", size=10, color=FG, bold=False, **kw):
        return tk.Label(parent, text=text, bg=BG, fg=color,
                        font=(FONT, scaled(size), "bold" if bold else "normal"), **kw)

    def _button(self, parent, text, command, size=10, color=FG):
        btn = tk.Label(parent, text=text, bg=BG, fg=color, cursor="hand2", font=(FONT, scaled(size)))
        btn.bind("<Button-1>", lambda _e: command())
        btn.bind("<Enter>", lambda _e: btn.configure(fg=ACCENT))
        btn.bind("<Leave>", lambda _e: btn.configure(fg=color))
        return btn

    def _entry(self, parent, var, width):
        entry = tk.Entry(parent, textvariable=var, width=width, bg=FIELD, fg=FG, insertbackground=FG,
                         relief="flat", font=(FONT, scaled(10)), highlightthickness=1,
                         highlightbackground=FIELD, highlightcolor=ACCENT)
        entry.bind("<Button-1>", lambda _e: entry.focus_force())
        return entry

    def _build(self):
        outer = tk.Frame(self.root, bg=BG, padx=scaled(14), pady=scaled(10))
        outer.pack(fill="both", expand=True)

        header = tk.Frame(outer, bg=BG)
        header.pack(fill="x")
        title = self._label(header, "Monthly Profit", 10, MUTED, bold=True)
        title.pack(side="left")
        self._button(header, "\u2715", self.hide, 10, MUTED).pack(side="right")
        toggle = tk.Frame(header, bg=FIELD, cursor="hand2")
        toggle.pack(side="right", padx=(0, scaled(10)))
        self.currency_lbls = {}
        for currency in SYMBOLS:
            lbl = tk.Label(toggle, text=SYMBOLS[currency], bg=FIELD, padx=scaled(6), cursor="hand2",
                           font=(FONT, scaled(8), "bold"))
            lbl.pack(side="left")
            lbl.bind("<Button-1>", lambda _e: self.toggle_currency())
            self.currency_lbls[currency] = lbl
        for w in (header, title):
            w.bind("<ButtonPress-1>", self._start_drag)
            w.bind("<B1-Motion>", self._on_drag)
            w.bind("<ButtonRelease-1>", self._end_drag)

        nav = tk.Frame(outer, bg=BG)
        nav.pack(fill="x", pady=(scaled(6), 0))
        self._button(nav, "\u2039", lambda: self.change_month(-1), 16).pack(side="left")
        self._button(nav, "\u203a", lambda: self.change_month(1), 16).pack(side="right")
        self.month_lbl = self._label(nav, "", 11, FG)
        self.month_lbl.pack(expand=True)

        self.profit_lbl = self._label(outer, "", 22, FG, bold=True)
        self.profit_lbl.pack(pady=(scaled(2), 0))
        self.profit_usd_lbl = self._label(outer, "", 10, MUTED)
        self.profit_usd_lbl.pack()

        tk.Frame(outer, bg=FIELD, height=1).pack(fill="x", pady=(scaled(10), scaled(6)))
        self.list_frame = tk.Frame(outer, bg=BG)
        self.list_frame.pack(fill="x")
        self.list_frame.columnconfigure(0, weight=1)
        self.error_lbl = self._label(outer, "", 8, NEGATIVE)
        self.hint_lbl = self._label(outer, "Click an amount to edit (in RM) \u00b7 right-click for more",
                                    8, MUTED)
        self.hint_lbl.pack(anchor="w", pady=(scaled(4), 0))

        tk.Frame(outer, bg=FIELD, height=1).pack(fill="x", pady=(scaled(10), scaled(6)))
        status = tk.Frame(outer, bg=BG)
        status.pack(fill="x")
        self.rate_lbl = self._label(status, "", 8, MUTED)
        self.rate_lbl.pack(side="left")
        self._button(status, "\u21bb", self.fetch_rate_async, 10, MUTED).pack(side="right")

    def _start_drag(self, event):
        self._drag = (event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())

    def _on_drag(self, event):
        self.root.geometry(f"+{event.x_root - self._drag[0]}+{event.y_root - self._drag[1]}")

    def _end_drag(self, _event):
        self.store.position = [self.root.winfo_x(), self.root.winfo_y()]
        self.store.save()

    def change_month(self, delta):
        self.month = shift_month(self.month, delta)
        self.editing = None
        self.refresh_profit()

    def display_currency(self):
        return self.store.currency if self.store.rate else "MYR"

    def money(self, rm_value, currency=None):
        currency = currency or self.display_currency()
        value = convert(rm_value, self.store.rate, to_usd=True) if currency == "USD" else rm_value
        return format_money(value, currency)

    def toggle_currency(self):
        self.store.set_currency("USD" if self.store.currency == "MYR" else "MYR")
        self.refresh_profit()

    def refresh_profit(self):
        shown = self.display_currency()
        for currency, lbl in self.currency_lbls.items():
            lbl.configure(fg=FG if currency == shown else MUTED, bg=ACCENT if currency == shown else FIELD)
        self.month_lbl.configure(text=month_label(self.month))
        total = self.store.month_total(self.month)
        other = "MYR" if shown == "USD" else "USD"
        if total is None:
            self.profit_lbl.configure(text=self.money(Decimal(0)), fg=amount_color(Decimal(0)))
            self.profit_usd_lbl.configure(text="No profit recorded")
        else:
            self.profit_lbl.configure(text=self.money(total), fg=amount_color(total))
            if self.store.rate:
                self.profit_usd_lbl.configure(text=f"Total \u2248 {self.money(total, other)}")
            else:
                self.profit_usd_lbl.configure(text="USD rate unavailable")
        self.render_businesses()
        self.update_tray_tooltip()

    def render_businesses(self):
        for child in self.list_frame.winfo_children():
            child.destroy()
        self.show_error("")
        entries = self.store.profits.get(self.month, {})
        mode, target = self.editing or (None, None)
        for row, name in enumerate(self.store.businesses):
            value = entries.get(name)
            if mode == "rename" and target == name:
                self._inline_entry(row, 0, name, lambda text, n=name: self.store.rename_business(n, text))
            else:
                lbl = self._label(self.list_frame, name, 10, FG, anchor="w")
                lbl.grid(row=row, column=0, sticky="w", pady=1)
                self._bind_row(lbl, name)
            if mode == "amount" and target == name:
                self._inline_entry(row, 1, "" if value is None else str(value),
                                   lambda text, n=name: self.store.set_profit(
                                       self.month, n, parse_amount(text) if text else None))
            else:
                text = "\u2014" if value is None else self.money(value)
                color = MUTED if value is None else amount_color(value)
                amt = self._label(self.list_frame, text, 10, color, cursor="hand2")
                amt.grid(row=row, column=1, sticky="e", pady=1)
                self._bind_row(amt, name)
        last = len(self.store.businesses)
        if mode == "add":
            self._inline_entry(last, 0, "", self.store.add_business, columnspan=2)
        else:
            self._button(self.list_frame, "+ Add business", self.start_add, 9, ACCENT).grid(
                row=last, column=0, sticky="w", pady=(scaled(4), 0))

    def _bind_row(self, widget, name):
        widget.bind("<Button-1>", lambda _e: self.start_edit("amount", name))
        widget.bind("<Button-3>", lambda e: self._row_menu(e, name))

    def _row_menu(self, event, name):
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Edit amount", command=lambda: self.start_edit("amount", name))
        menu.add_command(label="Rename", command=lambda: self.start_edit("rename", name))
        menu.add_separator()
        menu.add_command(label="Remove", command=lambda: self.remove_business(name))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _inline_entry(self, row, column, initial, on_save, columnspan=1):
        var = tk.StringVar(value=initial)
        entry = self._entry(self.list_frame, var, 14)
        entry.grid(row=row, column=column, columnspan=columnspan, sticky="ew", pady=1)
        entry.bind("<Return>", lambda _e: self._commit(on_save, var.get()))
        entry.bind("<Escape>", lambda _e: self.cancel_edit())
        entry.after_idle(lambda: (entry.focus_force(), entry.select_range(0, "end")))

    def _commit(self, action, text):
        try:
            action(text.strip())
        except ValueError as exc:
            self.show_error(str(exc))
            return
        self.editing = None
        self.refresh_profit()

    def show_error(self, message):
        self.error_lbl.configure(text=message)
        if message:
            self.error_lbl.pack(anchor="w", after=self.list_frame)
        else:
            self.error_lbl.pack_forget()

    def start_edit(self, mode, name):
        self.editing = (mode, name)
        self.render_businesses()

    def start_add(self):
        self.editing = ("add", None)
        self.render_businesses()

    def cancel_edit(self):
        self.editing = None
        self.render_businesses()

    def remove_business(self, name):
        if messagebox.askyesno("Remove business",
                               f"Remove '{name}' and all of its recorded profits?", parent=self.root):
            self.store.remove_business(name)
            self.editing = None
            self.refresh_profit()

    def update_rate_status(self, error=None):
        if self.store.rate:
            text = f"1 RM = {self.store.rate:.4f} USD \u00b7 {self.store.rate_date}"
            if error:
                text += " (offline)"
        else:
            text = "Fetching rate..." if self.fetching else "Rate unavailable"
        self.rate_lbl.configure(text=text)

    def fetch_rate_async(self):
        if self.fetching:
            return
        self.fetching = True
        self.update_rate_status()

        def worker():
            try:
                self.rate_queue.put(("ok", fetch_rate()))
            except Exception as exc:
                self.rate_queue.put(("error", exc))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self):
        while not self.tray_events.empty():
            action = self.tray_events.get_nowait()
            {"show": self.show, "hide": self.hide, "exit": self.exit}[action]()
            if action == "exit":
                return
        try:
            status, payload = self.rate_queue.get_nowait()
        except queue.Empty:
            pass
        else:
            self.fetching = False
            if status == "ok":
                self.store.set_rate(*payload)
                self.update_rate_status()
            else:
                self.update_rate_status(error=payload)
            if not self.editing:
                self.refresh_profit()
        self.root.after(100, self._poll)

    def _scheduled_refresh(self):
        self.fetch_rate_async()
        self.root.after(RATE_REFRESH_MS, self._scheduled_refresh)


def already_running():
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except (AttributeError, OSError):
        return False
    already_running.mutex = kernel32.CreateMutexW(None, False, "Local\\WidleDesktopWidget")
    return ctypes.get_last_error() == 183


def main():
    if already_running():
        if tray:
            tray.show_existing()
        return
    root = tk.Tk()
    root.title("Widle")
    widget = Widget(root, store=Store())
    try:
        root.mainloop()
    finally:
        if widget.tray:
            widget.tray.remove()


if __name__ == "__main__":
    main()
