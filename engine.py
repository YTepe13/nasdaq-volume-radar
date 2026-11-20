# -*- coding: utf-8 -*-
"""
Hacim Radarı - veri motoru
Her işlem (tick) geldiğinde hisse bazında saniyelik hacim kovalarına yazar,
alış/satış baskısını ve "hacim patlaması" oranını hesaplar.
"""
import math
import random
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo
    NY = ZoneInfo("America/New_York")
except Exception:  # Windows'ta tzdata yoksa kaba yaklaşım
    NY = None

WINDOW_SEC = 15 * 60  # 15 dakikalık saniyelik geçmiş tutulur


def ny_now():
    if NY is not None:
        return datetime.now(NY)
    # Yaklaşık: ABD Doğu saati (yaz saati varsayımıyla UTC-4)
    return datetime.now(timezone.utc) - timedelta(hours=4)


def minutes_since_open(now=None):
    """Normal seans açılışından (09:30 ET) bu yana geçen dakika; seans dışıysa None."""
    now = now or ny_now()
    if now.weekday() >= 5:
        return None
    open_t = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if now < open_t or now > close_t:
        return None
    return max((now - open_t).total_seconds() / 60.0, 1.0)


def market_session(now=None):
    now = now or ny_now()
    if now.weekday() >= 5:
        return "Hafta sonu"
    hm = now.hour * 60 + now.minute
    if 4 * 60 <= hm < 9 * 60 + 30:
        return "Pre-market"
    if 9 * 60 + 30 <= hm < 16 * 60:
        return "Açık"
    if 16 * 60 <= hm < 20 * 60:
        return "After-hours"
    return "Kapalı"


def _f(x, default=None):
    try:
        if x is None or x == "":
            return default
        v = float(x)
        if math.isnan(v):
            return default
        return v
    except Exception:
        return default


class SymbolState:
    __slots__ = ("symbol", "name", "price", "last_tick_price", "pre_close", "change_ratio",
                 "day_volume", "rvol10", "buckets", "last_update", "alert_until",
                 "last_alert_ts", "tick_count")

    def __init__(self, symbol):
        self.symbol = symbol
        self.name = ""
        self.price = None
        self.last_tick_price = None
        self.pre_close = None
        self.change_ratio = None
        self.day_volume = None
        self.rvol10 = None
        # her eleman: [saniye, alış_hacmi, satış_hacmi, nötr_hacim, alış_$, satış_$]
        self.buckets = deque()
        self.last_update = 0.0
        self.alert_until = 0.0
        self.last_alert_ts = 0.0
        self.tick_count = 0


class VolumeEngine:
    """Thread-safe hacim hesaplayıcı. Veri akışı thread'leri yazar, arayüz okur."""

    def __init__(self):
        self.lock = threading.Lock()
        self.states = {}
        self.alerts = deque(maxlen=300)
        self.total_ticks = 0
        self.last_msg_ts = 0.0

    # ---------- yazma ----------
    def _get(self, symbol):
        st = self.states.get(symbol)
        if st is None:
            st = SymbolState(symbol)
            self.states[symbol] = st
        return st

    def set_meta(self, symbol, name=None, rvol10=None, price=None, change_ratio=None,
                 day_volume=None, pre_close=None):
        with self.lock:
            st = self._get(symbol)
            if name:
                st.name = name
            if rvol10 is not None:
                st.rvol10 = rvol10
            if price is not None and st.price is None:
                st.price = price
            if change_ratio is not None and st.change_ratio is None:
                st.change_ratio = change_ratio
            if day_volume is not None and st.day_volume is None:
                st.day_volume = day_volume
            if pre_close is not None and st.pre_close is None:
                st.pre_close = pre_close

    def on_snapshot(self, symbol, price=None, change_ratio=None, day_volume=None, pre_close=None):
        with self.lock:
            st = self._get(symbol)
            if price is not None:
                st.price = price
            if change_ratio is not None:
                st.change_ratio = change_ratio
            if day_volume is not None:
                st.day_volume = day_volume
            if pre_close is not None:
                st.pre_close = pre_close
            st.last_update = time.time()
            self.last_msg_ts = st.last_update

    def on_tick(self, symbol, price, volume, side=None, ts=None):
        """side: 'B'/'BUY' -> alış, 'S'/'SELL' -> satış, diğer -> tick kuralı."""
        price = _f(price)
        volume = _f(volume, 0.0)
        if not volume or volume <= 0:
            return
        now = ts or time.time()
        sec = int(now)
        with self.lock:
            st = self._get(symbol)
            s = (str(side).strip().upper() if side is not None else "")
            if s.startswith("B") or s in ("1", "UP"):
                direction = 1
            elif s.startswith("S") or s in ("2", "-1", "DOWN"):
                direction = -1
            else:
                # Tick kuralı: fiyat yükseldiyse alıcı, düştüyse satıcı inisiyatifi
                direction = 0
                if price is not None and st.last_tick_price is not None:
                    if price > st.last_tick_price:
                        direction = 1
                    elif price < st.last_tick_price:
                        direction = -1
            if price is not None:
                st.last_tick_price = price
                st.price = price
                if st.pre_close:
                    st.change_ratio = (price - st.pre_close) / st.pre_close
            notional = volume * (price or 0.0)
            if not st.buckets or st.buckets[-1][0] != sec:
                st.buckets.append([sec, 0.0, 0.0, 0.0, 0.0, 0.0])
            b = st.buckets[-1]
            if direction > 0:
                b[1] += volume
                b[4] += notional
            elif direction < 0:
                b[2] += volume
                b[5] += notional
            else:
                b[3] += volume
            cutoff = sec - WINDOW_SEC
            while st.buckets and st.buckets[0][0] < cutoff:
                st.buckets.popleft()
            st.tick_count += 1
            st.last_update = now
            self.total_ticks += 1
            self.last_msg_ts = now

    # ---------- okuma ----------
    @staticmethod
    def _sum(buckets, since):
        buy = sell = neu = buy_usd = sell_usd = 0.0
        for b in reversed(buckets):
            if b[0] < since:
                break
            buy += b[1]
            sell += b[2]
            neu += b[3]
            buy_usd += b[4]
            sell_usd += b[5]
        return buy, sell, neu, buy_usd, sell_usd

    def snapshot_rows(self, spike_threshold=3.0, min_dollar_1m=50_000, alert_cooldown=120):
        now = time.time()
        sec = int(now)
        mso = minutes_since_open()
        rows = []
        new_alerts = []
        with self.lock:
            for st in self.states.values():
                # son tamamlanmış saniyenin hacmi
                vol1s = 0.0
                for bk in reversed(st.buckets):
                    if bk[0] == sec - 1:
                        vol1s = bk[1] + bk[2] + bk[3]
                        break
                    if bk[0] < sec - 1:
                        break
                b60, s60, n60, bu60, su60 = self._sum(st.buckets, sec - 60)
                b5, s5, n5, bu5, su5 = self._sum(st.buckets, sec - 300)
                bA, sA, nA, _, _ = self._sum(st.buckets, sec - WINDOW_SEC)
                vol1m = b60 + s60 + n60
                vol5m = b5 + s5 + n5
                # Taban: seansın dakikalık ortalaması (anlık hacim verisinden),
                # yoksa uygulama açıldığından beri izlenen ortalama.
                base = None
                if mso and st.day_volume:
                    base = st.day_volume / mso
                if not base and st.buckets:
                    span_min = max((sec - st.buckets[0][0]) / 60.0, 1.0)
                    if span_min >= 2:
                        base = (bA + sA + nA) / span_min
                spike = (vol1m / base) if base else None
                directional = b60 + s60
                buy_pct = (b60 / directional) if directional > 0 else None
                net_usd_1m = bu60 - su60
                price = st.price
                usd_1m = vol1m * (price or 0.0)

                if (spike is not None and spike >= spike_threshold and usd_1m >= min_dollar_1m
                        and now - st.last_alert_ts > alert_cooldown):
                    st.last_alert_ts = now
                    st.alert_until = now + 8
                    yon = "ALIŞ" if net_usd_1m > 0 else ("SATIŞ" if net_usd_1m < 0 else "-")
                    a = {
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "symbol": st.symbol, "spike": spike, "price": price,
                        "usd_1m": usd_1m, "net_usd_1m": net_usd_1m, "yon": yon,
                        "change": st.change_ratio,
                    }
                    self.alerts.appendleft(a)
                    new_alerts.append(a)

                rows.append({
                    "symbol": st.symbol, "name": st.name, "price": price,
                    "change": st.change_ratio, "day_volume": st.day_volume,
                    "rvol10": st.rvol10, "vol1s": vol1s, "vol1m": vol1m, "vol5m": vol5m,
                    "usd_1m": usd_1m, "spike": spike, "buy_pct": buy_pct,
                    "net_usd_1m": net_usd_1m, "net_usd_5m": bu5 - su5,
                    "alerting": now < st.alert_until,
                    "stale": (now - st.last_update) > 120 if st.last_update else True,
                })
        return rows, new_alerts

    def symbols(self):
        with self.lock:
            return list(self.states.keys())

    def remove(self, symbols):
        with self.lock:
            for s in symbols:
                self.states.pop(s, None)


# =====================================================================
# Veri akışları
# =====================================================================

def _extract_rank_list(payload):
    """Screener yanıtı liste ya da {'data': [...]} gibi sarılı olabilir."""
    if isinstance(payload, list):
        if payload and isinstance(payload[0], dict) and "symbol" in payload[0]:
            return payload
        for item in payload:
            r = _extract_rank_list(item)
            if r:
                return r
        return []
    if isinstance(payload, dict):
        for key in ("data", "list", "items", "rows", "result", "results", "ranks"):
            if key in payload:
                r = _extract_rank_list(payload[key])
                if r:
                    return r
        for v in payload.values():
            if isinstance(v, (list, dict)):
                r = _extract_rank_list(v)
                if r:
                    return r
    return []


NASDAQ_CODES = {"NAS", "NSQ", "NASDAQ", "XNAS", "NSDQ", "NMS", "NGS", "NCM", "NGM"}


def is_nasdaq(code):
    if not code:
        return False
    c = str(code).upper()
    return c in NASDAQ_CODES or "NAS" in c or "NSQ" in c


class BaseFeed:
    def __init__(self, engine, log):
        self.engine = engine
        self.log = log
        self.running = False

    def start(self):
        raise NotImplementedError

    def stop(self):
        self.running = False


class DemoFeed(BaseFeed):
    """Anahtar olmadan arayüzü denemek için sahte işlem akışı."""

    SYMBOLS = ["NVDA", "TSLA", "AAPL", "AMD", "PLTR", "SOFI", "MARA", "RIOT", "INTC", "LCID",
               "NIO", "AMZN", "META", "MSFT", "SMCI", "HOOD", "COIN", "RGTI", "QUBT", "IONQ",
               "SOUN", "MSTR", "AVGO", "MU", "GOOGL", "OPEN", "BBAI", "ACHR", "RKLB", "ASTS"]

    def start(self):
        self.running = True
        self._px = {}
        for s in self.SYMBOLS:
            p = random.uniform(3, 400)
            self._px[s] = p
            pre = p * random.uniform(0.95, 1.05)
            dv = random.uniform(12000, 25000) * (minutes_since_open() or 120)
            self.engine.set_meta(s, name=s + " (demo)", rvol10=random.uniform(0.5, 3))
            self.engine.on_snapshot(s, price=p, pre_close=pre, change_ratio=(p - pre) / pre,
                                    day_volume=dv)
        self._hot = {}
        threading.Thread(target=self._loop, daemon=True).start()
        self.log("DEMO modu: sahte veri akışı başladı (gerçek piyasa verisi değildir).")

    def _loop(self):
        while self.running:
            now = time.time()
            if random.random() < 0.01:
                s = random.choice(self.SYMBOLS)
                self._hot[s] = (now + random.uniform(20, 90), random.choice([1, -1]))
            for s in self.SYMBOLS:
                hot = self._hot.get(s)
                mult, bias = 1.0, 0
                if hot and hot[0] > now:
                    mult, bias = random.uniform(6, 15), hot[1]
                n = int(random.random() * 3 * mult)
                added = 0.0
                for _ in range(n):
                    drift = random.gauss(0.000004 * bias * mult, 0.00015)
                    self._px[s] *= (1 + drift)
                    side = None
                    if random.random() < 0.6:
                        side = "B" if (drift > 0) else "S"
                    v = random.choice([10, 50, 100, 100, 200, 500]) * mult
                    added += v
                    self.engine.on_tick(s, self._px[s], v, side=side)
                st = self.engine.states.get(s)
                if st and st.day_volume is not None and added:
                    with self.engine.lock:
                        st.day_volume += added
            time.sleep(0.2)


class WebullFeed(BaseFeed):
    """Webull OpenAPI: Top Active listesi + MQTT TICK/SNAPSHOT akışı."""

    def __init__(self, engine, log, app_key, app_secret, region_id="us", top_n=100,
                 rank_type="VOLUME", nasdaq_only=True, extra_symbols=None, refresh_min=5,
                 batch_size=50, token_dir=None):
        super().__init__(engine, log)
        self.app_key = app_key
        self.app_secret = app_secret
        self.region_id = region_id or "us"
        self.top_n = int(top_n)
        self.rank_type = rank_type
        self.nasdaq_only = nasdaq_only
        self.extra_symbols = [s.strip().upper() for s in (extra_symbols or []) if s.strip()]
        self.refresh_min = refresh_min
        self.batch_size = batch_size
        self.token_dir = token_dir
        self.subscribed = set()
        self.stream = None
        self.data_client = None
        self._lock = threading.Lock()

    # --- yardımcılar ---
    def _setup(self):
        import os
        import uuid
        if self.token_dir:
            os.makedirs(self.token_dir, exist_ok=True)
            os.environ["WEBULL_OPENAPI_TOKEN_DIR"] = self.token_dir
        from webull.core.client import ApiClient
        from webull.data.data_client import DataClient
        from webull.data.data_streaming_client import DataStreamingClient

        api_client = ApiClient(self.app_key, self.app_secret, self.region_id)
        self.data_client = DataClient(api_client)
        self.stream = DataStreamingClient(self.app_key, self.app_secret, self.region_id,
                                          uuid.uuid4().hex)
        if self.token_dir and hasattr(self.stream, "set_token_dir"):
            try:
                self.stream.set_token_dir(self.token_dir)
            except Exception:
                pass

    def fetch_top(self):
        """En aktif hisseleri çeker -> [(symbol, row_dict)]"""
        res = None
        sc = self.data_client.screener
        try:
            res = sc.list_most_active(category="US_STOCK", rank_type=self.rank_type,
                                      sort_by=self.rank_type, direction="DESC")
        except AttributeError:
            res = sc.get_most_active(category="US_STOCK", rank_type=self.rank_type,
                                     sort_by=self.rank_type, direction="DESC", page_size=100)
        if res is None or getattr(res, "status_code", 0) != 200:
            txt = getattr(res, "text", "")
            raise RuntimeError("Top Active isteği başarısız: %s %s" % (getattr(res, "status_code", "?"), txt[:300]))
        rows = _extract_rank_list(res.json())
        if not rows:
            self.log("Uyarı: Top Active yanıtında liste bulunamadı.")
        if self.nasdaq_only:
            nas = [r for r in rows if is_nasdaq(r.get("exchange_code") or r.get("exchangeCode"))]
            if nas:
                rows = nas
            else:
                codes = sorted({str(r.get("exchange_code")) for r in rows})[:10]
                self.log("Uyarı: Nasdaq borsa kodu tanınamadı (%s) - tüm liste kullanılıyor." % ", ".join(codes))
        out = []
        for r in rows[: self.top_n]:
            sym = str(r.get("symbol", "")).upper()
            if sym:
                out.append((sym, r))
        return out

    def _apply_meta(self, items):
        for sym, r in items:
            self.engine.set_meta(
                sym,
                name=r.get("name"),
                rvol10=_f(r.get("relative_volume_10d")),
                price=_f(r.get("price")) or _f(r.get("close")),
                change_ratio=_f(r.get("change_ratio")),
                day_volume=_f(r.get("volume")),
                pre_close=_f(r.get("pre_close")),
            )

    def _subscribe(self, symbols):
        symbols = list(symbols)
        for i in range(0, len(symbols), self.batch_size):
            chunk = symbols[i:i + self.batch_size]
            try:
                self.stream.subscribe(chunk, "US_STOCK", ["SNAPSHOT", "TICK"])
                with self._lock:
                    self.subscribed.update(chunk)
            except Exception as e:
                self.log("Abonelik hatası (%s...): %s" % (chunk[0], e))

    def _unsubscribe(self, symbols):
        symbols = list(symbols)
        if not symbols:
            return
        try:
            self.stream.unsubscribe(symbols=symbols, category="US_STOCK", sub_types=["SNAPSHOT", "TICK"])
        except Exception as e:
            self.log("Abonelikten çıkma hatası: %s" % e)
        with self._lock:
            self.subscribed.difference_update(symbols)

    # --- SDK geri çağırmaları ---
    def _on_connect(self, client, api_client, session_id):
        self.log("Webull akışına bağlanıldı. Abone olunuyor: %d hisse" % len(self.engine.symbols()))
        with self._lock:
            self.subscribed.clear()
        self._subscribe(self.engine.symbols())
        self.log("Abonelik tamam: %d hisse canlı izleniyor." % len(self.subscribed))

    def _on_message(self, client, topic, data):
        try:
            if topic == "tick":
                sym = data.basic.symbol
                self.engine.on_tick(sym, data.price, data.volume, side=data.side)
            elif topic == "snapshot":
                sym = data.basic.symbol
                price = _f(data.price)
                # Pre/after-market'te güncel fiyat ext_price alanında gelir
                if data.ext_price and (data.ext_trade_time or 0) > (data.last_trade_time or 0):
                    price = _f(data.ext_price) or price
                self.engine.on_snapshot(sym, price=price, change_ratio=_f(data.change_ratio),
                                        day_volume=_f(data.volume), pre_close=_f(data.pre_close))
        except Exception as e:
            self.log("Mesaj işleme hatası: %s" % e)

    def _refresh_loop(self):
        while self.running:
            for _ in range(int(self.refresh_min * 60)):
                if not self.running:
                    return
                time.sleep(1)
            try:
                items = self.fetch_top()
                self._apply_meta(items)
                new = {s for s, _ in items} | set(self.extra_symbols)
                with self._lock:
                    cur = set(self.subscribed)
                add, rem = new - cur, cur - new
                if rem:
                    self._unsubscribe(rem)
                    self.engine.remove(rem)
                if add:
                    self._subscribe(add)
                if add or rem:
                    self.log("Liste yenilendi: +%d / -%d hisse" % (len(add), len(rem)))
            except Exception as e:
                self.log("Liste yenileme hatası: %s" % e)

    def start(self):
        self.running = True
        threading.Thread(target=self._start_bg, daemon=True).start()

    def _start_bg(self):
        try:
            self.log("Webull'a bağlanılıyor (bölge: %s)..." % self.region_id)
            self._setup()
            items = self.fetch_top()
            self._apply_meta(items)
            for s in self.extra_symbols:
                self.engine.set_meta(s)
            self.log("En aktif %d hisse alındı (%s)." % (len(items), self.rank_type))
            self.stream.on_connect_success = self._on_connect
            self.stream.on_quotes_message = self._on_message
            self.stream.connect_and_loop_async(thread_daemon=True)
            threading.Thread(target=self._refresh_loop, daemon=True).start()
        except ImportError:
            self.log("HATA: webull-openapi-python-sdk kurulu değil. KUR_VE_CALISTIR.bat ile kurun.")
            self.running = False
        except Exception as e:
            self.log("HATA: %s" % e)
            self.log("İpucu: App Key/Secret ve bölgeyi kontrol edin. İlk bağlantıda Webull "
                     "uygulamanızdan onay (2FA) istenebilir.")
            self.running = False

    def stop(self):
        self.running = False
        try:
            if self.stream:
                self.stream.disconnect()
                self.stream.loop_stop()
        except Exception:
            pass
