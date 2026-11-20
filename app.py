# -*- coding: utf-8 -*-
"""
Hacim Radarı - Nasdaq anlık hacim tarayıcısı (Windows masaüstü)
Veri: Webull OpenAPI (MQTT canlı TICK + SNAPSHOT), saniyede bir güncellenir.
"""
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

import engine as eng

APP_NAME = "Hacim Radarı"
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

DEFAULTS = {
    "app_key": "",
    "app_secret": "",
    "region_id": "us",
    "top_n": 100,
    "rank_type": "VOLUME",
    "nasdaq_only": True,
    "extra_symbols": "",
    "refresh_min": 5,
    "spike_threshold": 3.0,
    "min_usd_1m": 50000,
    "sound": True,
}

REGIONS = ["us", "uk", "eu", "hk", "sg", "jp", "au", "th", "my", "br", "mx", "za"]
RANK_TYPES = ["VOLUME", "RELATIVE_VOLUME_10D", "TURNOVER", "TURNOVER_RATE", "AMPLITUDE"]

# Renkler
BG = "#0f1217"
PANEL = "#171b22"
FG = "#e6e9ef"
MUTED = "#8a93a3"
GREEN = "#2ecc71"
RED = "#ff5c5c"
ALERT_BG = "#5a4300"
ACCENT = "#3d8bfd"

COLUMNS = [
    # key, başlık, genişlik, hizalama
    ("symbol", "Sembol", 80, "w"),
    ("price", "Fiyat", 80, "e"),
    ("change", "% Değ.", 70, "e"),
    ("vol1s", "1 sn Hacim", 85, "e"),
    ("vol1m", "1 dk Hacim", 95, "e"),
    ("usd_1m", "1 dk $", 90, "e"),
    ("spike", "Patlama ×", 80, "e"),
    ("buy_pct", "Alış %", 65, "e"),
    ("net_usd_1m", "Net Akış 1dk $", 110, "e"),
    ("net_usd_5m", "Net Akış 5dk $", 110, "e"),
    ("day_volume", "Gün Hacmi", 100, "e"),
    ("rvol10", "RVOL 10g", 70, "e"),
]


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception as e:
        messagebox.showerror(APP_NAME, "Ayarlar kaydedilemedi: %s" % e)


def human(n, money=False, signed=False):
    if n is None:
        return "-"
    sign = ""
    if signed and n > 0:
        sign = "+"
    if n < 0:
        sign = "-"
    a = abs(n)
    if a >= 1e9:
        s = "%.2fB" % (a / 1e9)
    elif a >= 1e6:
        s = "%.2fM" % (a / 1e6)
    elif a >= 1e3:
        s = "%.1fK" % (a / 1e3)
    else:
        s = "%.0f" % a
    return sign + ("$" if money else "") + s


def beep():
    try:
        import winsound
        winsound.Beep(1200, 120)
        winsound.Beep(1600, 120)
    except Exception:
        pass


class SettingsDialog(tk.Toplevel):
    def __init__(self, master, cfg, on_save):
        super().__init__(master)
        self.title("Ayarlar - Webull OpenAPI")
        self.configure(bg=PANEL)
        self.resizable(False, False)
        self.cfg = dict(cfg)
        self.on_save = on_save
        self.transient(master)
        self.grab_set()

        self.vars = {
            "app_key": tk.StringVar(value=cfg["app_key"]),
            "app_secret": tk.StringVar(value=cfg["app_secret"]),
            "region_id": tk.StringVar(value=cfg["region_id"]),
            "top_n": tk.IntVar(value=int(cfg["top_n"])),
            "rank_type": tk.StringVar(value=cfg["rank_type"]),
            "nasdaq_only": tk.BooleanVar(value=bool(cfg["nasdaq_only"])),
            "extra_symbols": tk.StringVar(value=cfg["extra_symbols"]),
            "refresh_min": tk.IntVar(value=int(cfg["refresh_min"])),
        }
        rows = [
            ("App Key", ttk.Entry(self, textvariable=self.vars["app_key"], width=46)),
            ("App Secret", ttk.Entry(self, textvariable=self.vars["app_secret"], width=46, show="•")),
            ("Hesap bölgesi", ttk.Combobox(self, textvariable=self.vars["region_id"], values=REGIONS,
                                           state="readonly", width=10)),
            ("Kaç hisse izlensin", ttk.Spinbox(self, from_=10, to=200, increment=10,
                                               textvariable=self.vars["top_n"], width=8)),
            ("Sıralama ölçütü", ttk.Combobox(self, textvariable=self.vars["rank_type"], values=RANK_TYPES,
                                             state="readonly", width=24)),
            ("Sadece Nasdaq", ttk.Checkbutton(self, variable=self.vars["nasdaq_only"])),
            ("Ek semboller (virgülle)", ttk.Entry(self, textvariable=self.vars["extra_symbols"], width=46)),
            ("Liste yenileme (dk)", ttk.Spinbox(self, from_=1, to=60, textvariable=self.vars["refresh_min"],
                                                width=8)),
        ]
        for i, (label, widget) in enumerate(rows):
            ttk.Label(self, text=label, style="Panel.TLabel").grid(row=i, column=0, sticky="w", padx=12, pady=5)
            widget.grid(row=i, column=1, sticky="w", padx=12, pady=5)
        ttk.Label(self, style="Muted.TLabel",
                  text="Anahtarları developer.webull.com > hesabınız > API Management bölümünden alırsınız.\n"
                       "Bölge: Webull hesabınızın açıldığı ülke (ABD hesabı = us).").grid(
            row=len(rows), column=0, columnspan=2, sticky="w", padx=12, pady=(4, 8))
        btns = ttk.Frame(self, style="Panel.TFrame")
        btns.grid(row=len(rows) + 1, column=0, columnspan=2, sticky="e", padx=12, pady=10)
        ttk.Button(btns, text="İptal", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(btns, text="Kaydet", style="Accent.TButton", command=self._save).pack(side="right", padx=4)

    def _save(self):
        try:
            for k, v in self.vars.items():
                val = v.get()
                self.cfg[k] = val.strip() if isinstance(val, str) else val
        except tk.TclError:
            messagebox.showerror(APP_NAME, "Sayısal alanları kontrol edin.", parent=self)
            return
        self.on_save(self.cfg)
        self.destroy()


class App:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        self.engine = eng.VolumeEngine()
        self.feed = None
        self.log_q = queue.Queue()
        self.sort_key = "spike"
        self.sort_desc = True
        self.last_ticks = 0
        self.last_tick_check = time.time()
        self.tps = 0.0
        self.mode = ""

        root.title("%s - Nasdaq anlık hacim" % APP_NAME)
        root.geometry("1380x820")
        root.minsize(1000, 600)
        root.configure(bg=BG)
        self._style()
        self._build()
        self.log("Hazır. 'Ayarlar' ile Webull anahtarlarınızı girin, sonra 'Başlat'. "
                 "Denemek için 'Demo' düğmesi.")
        self.root.after(1000, self._tick)
        root.protocol("WM_DELETE_WINDOW", self._close)

    # ---------- görünüm ----------
    def _style(self):
        st = ttk.Style(self.root)
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure(".", background=BG, foreground=FG, fieldbackground=PANEL, font=("Segoe UI", 10))
        st.configure("TFrame", background=BG)
        st.configure("Panel.TFrame", background=PANEL)
        st.configure("TLabel", background=BG, foreground=FG)
        st.configure("Panel.TLabel", background=PANEL, foreground=FG)
        st.configure("Muted.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        st.configure("Status.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 10))
        st.configure("Title.TLabel", background=BG, foreground=FG, font=("Segoe UI Semibold", 15))
        st.configure("TButton", background=PANEL, foreground=FG, borderwidth=1, padding=(10, 5))
        st.map("TButton", background=[("active", "#252b35")])
        st.configure("Accent.TButton", background=ACCENT, foreground="white")
        st.map("Accent.TButton", background=[("active", "#2f6fd0")])
        st.configure("TCheckbutton", background=BG, foreground=FG)
        st.map("TCheckbutton", background=[("active", BG)])
        st.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                     rowheight=24, borderwidth=0, font=("Consolas", 10))
        st.configure("Treeview.Heading", background="#202632", foreground=FG,
                     font=("Segoe UI Semibold", 9), relief="flat")
        st.map("Treeview.Heading", background=[("active", "#2a3140")])
        st.map("Treeview", background=[("selected", "#2a3550")])
        st.configure("TEntry", fieldbackground=PANEL, foreground=FG, insertcolor=FG)
        st.configure("TSpinbox", fieldbackground=PANEL, foreground=FG, arrowcolor=FG)
        st.configure("TCombobox", fieldbackground=PANEL, foreground=FG)

    def _build(self):
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=12, pady=(10, 4))
        ttk.Label(top, text="Hacim Radarı", style="Title.TLabel").pack(side="left")
        self.status = ttk.Label(top, text="Bağlı değil", style="Status.TLabel")
        self.status.pack(side="left", padx=16)
        ttk.Button(top, text="Ayarlar", command=self._settings).pack(side="right", padx=3)
        ttk.Button(top, text="Durdur", command=self._stop).pack(side="right", padx=3)
        ttk.Button(top, text="Demo", command=self._start_demo).pack(side="right", padx=3)
        ttk.Button(top, text="▶ Başlat (Webull)", style="Accent.TButton",
                   command=self._start_webull).pack(side="right", padx=3)

        flt = ttk.Frame(self.root)
        flt.pack(fill="x", padx=12, pady=4)
        ttk.Label(flt, text="Ara:").pack(side="left")
        self.search = tk.StringVar()
        ttk.Entry(flt, textvariable=self.search, width=10).pack(side="left", padx=(4, 14))
        ttk.Label(flt, text="Uyarı eşiği (1dk hacim / dk ort.) ×").pack(side="left")
        self.spike_var = tk.DoubleVar(value=float(self.cfg["spike_threshold"]))
        ttk.Spinbox(flt, from_=1.5, to=50, increment=0.5, textvariable=self.spike_var,
                    width=6).pack(side="left", padx=(4, 14))
        ttk.Label(flt, text="Min. 1dk $ hacim:").pack(side="left")
        self.minusd_var = tk.IntVar(value=int(self.cfg["min_usd_1m"]))
        ttk.Spinbox(flt, from_=0, to=10_000_000, increment=25_000, textvariable=self.minusd_var,
                    width=10).pack(side="left", padx=(4, 14))
        self.only_hot = tk.BooleanVar(value=False)
        ttk.Checkbutton(flt, text="Sadece eşiği geçenler", variable=self.only_hot).pack(side="left", padx=6)
        self.only_buy = tk.BooleanVar(value=False)
        ttk.Checkbutton(flt, text="Sadece net alış", variable=self.only_buy).pack(side="left", padx=6)
        self.sound_var = tk.BooleanVar(value=bool(self.cfg["sound"]))
        ttk.Checkbutton(flt, text="Sesli uyarı", variable=self.sound_var).pack(side="left", padx=6)

        paned = ttk.PanedWindow(self.root, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=12, pady=(4, 6))

        # Ana tablo
        left = ttk.Frame(paned)
        self.tree = ttk.Treeview(left, columns=[c[0] for c in COLUMNS], show="headings", selectmode="browse")
        for key, title, w, anchor in COLUMNS:
            self.tree.heading(key, text=title, command=lambda k=key: self._sort_by(k))
            self.tree.column(key, width=w, anchor=anchor, stretch=(key == "symbol"))
        ysb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        ysb.pack(side="right", fill="y")
        self.tree.tag_configure("up", foreground=GREEN)
        self.tree.tag_configure("down", foreground=RED)
        self.tree.tag_configure("flat", foreground=FG)
        self.tree.tag_configure("alert", background=ALERT_BG)
        self.tree.tag_configure("stale", foreground=MUTED)
        self.tree.bind("<Double-1>", self._open_chart)
        paned.add(left, weight=4)

        # Sağ panel: uyarılar + günlük
        right = ttk.Frame(paned)
        ttk.Label(right, text="Hacim patlaması uyarıları", style="TLabel",
                  font=("Segoe UI Semibold", 11)).pack(anchor="w", pady=(0, 4))
        acols = [("time", "Saat", 64), ("symbol", "Sembol", 64), ("spike", "×", 50),
                 ("yon", "Yön", 56), ("usd", "1dk $", 72), ("chg", "%", 56)]
        self.atree = ttk.Treeview(right, columns=[c[0] for c in acols], show="headings", height=16)
        for k, t, w in acols:
            self.atree.heading(k, text=t)
            self.atree.column(k, width=w, anchor="center")
        self.atree.tag_configure("buy", foreground=GREEN)
        self.atree.tag_configure("sell", foreground=RED)
        self.atree.bind("<Double-1>", self._open_chart_alert)
        self.atree.pack(fill="both", expand=True)
        ttk.Label(right, text="Günlük", font=("Segoe UI Semibold", 10)).pack(anchor="w", pady=(8, 2))
        self.logbox = tk.Text(right, height=9, bg=PANEL, fg=MUTED, relief="flat", wrap="word",
                              font=("Consolas", 9), insertbackground=FG)
        self.logbox.pack(fill="both")
        paned.add(right, weight=1)

        foot = ttk.Frame(self.root)
        foot.pack(fill="x", padx=12, pady=(0, 8))
        ttk.Label(foot, style="Status.TLabel",
                  text="Patlama × = son 1 dk hacmi ÷ bugünkü dakika başı ortalama hacim.  "
                       "Alış % ve Net Akış: alıcı/satıcı inisiyatifli işlemler.  "
                       "Satıra çift tıkla → TradingView grafiği.  Bu bir yatırım tavsiyesi değildir.").pack(anchor="w")

    # ---------- olaylar ----------
    def log(self, msg):
        self.log_q.put("%s  %s" % (time.strftime("%H:%M:%S"), msg))

    def _settings(self):
        def on_save(cfg):
            self.cfg.update(cfg)
            self._persist()
            self.log("Ayarlar kaydedildi.")
        SettingsDialog(self.root, self.cfg, on_save)

    def _persist(self):
        try:
            self.cfg["spike_threshold"] = float(self.spike_var.get())
            self.cfg["min_usd_1m"] = int(self.minusd_var.get())
        except tk.TclError:
            pass
        self.cfg["sound"] = bool(self.sound_var.get())
        save_config(self.cfg)

    def _reset(self):
        if self.feed:
            self.feed.stop()
            self.feed = None
        self.engine = eng.VolumeEngine()
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        for iid in self.atree.get_children():
            self.atree.delete(iid)

    def _start_webull(self):
        if not self.cfg.get("app_key") or not self.cfg.get("app_secret"):
            messagebox.showinfo(APP_NAME, "Önce Ayarlar'dan Webull App Key ve App Secret girin.")
            self._settings()
            return
        self._reset()
        extra = [s for s in str(self.cfg.get("extra_symbols", "")).replace(";", ",").split(",") if s.strip()]
        self.feed = eng.WebullFeed(
            self.engine, self.log,
            app_key=self.cfg["app_key"], app_secret=self.cfg["app_secret"],
            region_id=self.cfg["region_id"], top_n=self.cfg["top_n"],
            rank_type=self.cfg["rank_type"], nasdaq_only=self.cfg["nasdaq_only"],
            extra_symbols=extra, refresh_min=self.cfg["refresh_min"],
            token_dir=os.path.join(BASE_DIR, "conf"),
        )
        self.feed.start()
        self.mode = "Webull"

    def _start_demo(self):
        self._reset()
        self.feed = eng.DemoFeed(self.engine, self.log)
        self.feed.start()
        self.mode = "DEMO"

    def _stop(self):
        if self.feed:
            self.feed.stop()
            self.feed = None
            self.log("Akış durduruldu.")

    def _sort_by(self, key):
        if self.sort_key == key:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_key, self.sort_desc = key, key != "symbol"
        for k, t, _, _ in COLUMNS:
            arrow = (" ▼" if self.sort_desc else " ▲") if k == self.sort_key else ""
            self.tree.heading(k, text=t + arrow)

    def _open_chart(self, _evt=None):
        sel = self.tree.selection()
        if sel:
            webbrowser.open("https://www.tradingview.com/chart/?symbol=%s" % sel[0])

    def _open_chart_alert(self, _evt=None):
        sel = self.atree.selection()
        if sel:
            sym = self.atree.item(sel[0], "values")[1]
            webbrowser.open("https://www.tradingview.com/chart/?symbol=%s" % sym)

    # ---------- saniyelik döngü ----------
    def _tick(self):
        try:
            self._refresh()
        except Exception as e:
            self.log("Arayüz hatası: %s" % e)
        self.root.after(1000, self._tick)

    def _refresh(self):
        # günlük
        while True:
            try:
                line = self.log_q.get_nowait()
            except queue.Empty:
                break
            self.logbox.insert("end", line + "\n")
            self.logbox.see("end")
        if int(self.logbox.index("end-1c").split(".")[0]) > 500:
            self.logbox.delete("1.0", "100.0")

        try:
            thr = float(self.spike_var.get())
            min_usd = float(self.minusd_var.get())
        except (tk.TclError, ValueError):
            thr, min_usd = 3.0, 50000.0

        rows, new_alerts = self.engine.snapshot_rows(spike_threshold=thr, min_dollar_1m=min_usd)

        # tick/sn ve durum satırı
        now = time.time()
        dt = now - self.last_tick_check
        if dt >= 1:
            self.tps = (self.engine.total_ticks - self.last_ticks) / dt
            self.last_ticks, self.last_tick_check = self.engine.total_ticks, now
        live = self.feed is not None and self.feed.running
        lag = now - self.engine.last_msg_ts if self.engine.last_msg_ts else None
        ny = eng.ny_now().strftime("%H:%M:%S")
        self.status.configure(
            text="%s  |  NY %s (%s)  |  %d hisse  |  %.0f işlem/sn  |  son veri: %s" % (
                ("● " + getattr(self, "mode", "")) if live else "○ Bağlı değil",
                ny, eng.market_session(), len(rows), self.tps,
                ("%.0f sn önce" % lag) if lag is not None else "-"),
            foreground=(GREEN if live and lag is not None and lag < 10 else MUTED))

        # filtre
        q = self.search.get().strip().upper()
        if q:
            rows = [r for r in rows if q in r["symbol"]]
        if self.only_hot.get():
            rows = [r for r in rows if (r["spike"] or 0) >= thr]
        if self.only_buy.get():
            rows = [r for r in rows if (r["net_usd_1m"] or 0) > 0]

        k = self.sort_key
        if k == "symbol":
            rows.sort(key=lambda r: r["symbol"], reverse=self.sort_desc)
        else:
            rows.sort(key=lambda r: (r[k] is not None, r[k] or 0), reverse=self.sort_desc)

        # tabloyu güncelle (item id = sembol)
        wanted = [r["symbol"] for r in rows]
        existing = set(self.tree.get_children())
        for iid in existing - set(wanted):
            self.tree.delete(iid)
        for idx, r in enumerate(rows):
            ch = r["change"]
            vals = (
                r["symbol"],
                ("%.2f" % r["price"]) if r["price"] else "-",
                ("%+.2f%%" % (ch * 100)) if ch is not None else "-",
                human(r["vol1s"]),
                human(r["vol1m"]),
                human(r["usd_1m"], money=True),
                ("%.1f×" % r["spike"]) if r["spike"] is not None else "-",
                ("%.0f%%" % (r["buy_pct"] * 100)) if r["buy_pct"] is not None else "-",
                human(r["net_usd_1m"], money=True, signed=True),
                human(r["net_usd_5m"], money=True, signed=True),
                human(r["day_volume"]),
                ("%.2f" % r["rvol10"]) if r["rvol10"] is not None else "-",
            )
            tags = []
            if r["stale"]:
                tags.append("stale")
            elif ch is not None and ch > 0:
                tags.append("up")
            elif ch is not None and ch < 0:
                tags.append("down")
            else:
                tags.append("flat")
            if r["alerting"]:
                tags.append("alert")
            sym = r["symbol"]
            if sym in existing:
                self.tree.item(sym, values=vals, tags=tags)
            else:
                self.tree.insert("", "end", iid=sym, values=vals, tags=tags)
            if self.tree.index(sym) != idx:
                self.tree.move(sym, "", idx)

        # uyarılar
        for a in reversed(new_alerts):
            tag = "buy" if a["yon"] == "ALIŞ" else ("sell" if a["yon"] == "SATIŞ" else "")
            self.atree.insert("", 0, values=(
                a["time"], a["symbol"], "%.1f" % a["spike"], a["yon"], human(a["usd_1m"], money=True),
                ("%+.1f" % (a["change"] * 100)) if a["change"] is not None else "-"), tags=(tag,))
            self.log("UYARI %s: 1 dk hacim ortalamanın %.1f katı, net %s %s" % (
                a["symbol"], a["spike"], a["yon"], human(a["net_usd_1m"], money=True, signed=True)))
        kids = self.atree.get_children()
        for iid in kids[200:]:
            self.atree.delete(iid)
        if new_alerts and self.sound_var.get():
            threading.Thread(target=beep, daemon=True).start()

    def _close(self):
        self._persist()
        if self.feed:
            self.feed.stop()
        self.root.destroy()


def main():
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # Windows'ta net yazı
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
