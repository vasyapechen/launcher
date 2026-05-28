import customtkinter as ctk
import json, os, sys, threading, zipfile, subprocess
import urllib.request as _ur
from pathlib import Path

# ── Версия и URLs ────────────────────────────────────────
LAUNCHER_VERSION = "1.0.0"
CATALOG_URL  = "https://raw.githubusercontent.com/vasyapechen/launcher/main/catalog.json"
VERSION_URL  = "https://raw.githubusercontent.com/vasyapechen/launcher/main/launcher_version.json"

# ── Пути ─────────────────────────────────────────────────
BASE_DIR   = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
GAMES_DIR  = BASE_DIR / "games"
STATE_FILE = BASE_DIR / "games_state.json"
CACHE_FILE = BASE_DIR / "catalog_cache.json"
GAMES_DIR.mkdir(exist_ok=True)

# ── Состояние установленных игр ───────────────────────────
def load_state():
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding='utf-8'))
    except: pass
    return {}

def save_state(state):
    try: STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding='utf-8')
    except: pass

def fetch_json(url):
    try:
        r = _ur.urlopen(url, timeout=6)
        return json.loads(r.read().decode())
    except: return None

# ── Тема ─────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

COLORS = {
    "bg":       "#0f0f1a",
    "card":     "#1a1a2e",
    "card_hover":"#1f1f38",
    "header":   "#0a0a14",
    "footer":   "#0a0a14",
    "accent":   "#e0c060",
    "green":    "#44cc77",
    "orange":   "#ffaa33",
    "gray":     "#666688",
    "btn_play": "#1a5fa8",
    "btn_dl":   "#1a6b2a",
    "btn_upd":  "#7a4f00",
}


# ══════════════════════════════════════════════════════════
class GameCard(ctk.CTkFrame):
    ICONS = {
        "flagrace":  "🏁",
        "flaggame":  "🚩",
    }
    DEFAULT_ICON = "🎮"

    def __init__(self, master, game, state, on_action, **kw):
        super().__init__(master, corner_radius=14,
                         fg_color=COLORS["card"],
                         border_width=1, border_color="#2a2a44", **kw)
        self.game     = game
        self.state    = state
        self.on_action = on_action
        self._build()

    def _build(self):
        gid      = self.game['id']
        inst     = self.state.get(gid, {})
        inst_ver = inst.get('version')
        new_ver  = self.game['version']

        icon = self.ICONS.get(gid, self.DEFAULT_ICON)
        ctk.CTkLabel(self, text=icon,
                     font=ctk.CTkFont(size=44)).pack(pady=(18, 2))

        ctk.CTkLabel(self, text=self.game['name'],
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color="#e8e8f8").pack()

        # Статус
        if inst_ver == new_ver:
            s_text, s_col = f"v{inst_ver}  ✓ установлена", COLORS["green"]
            btn_text, btn_col = "▶   Играть", COLORS["btn_play"]
        elif inst_ver:
            s_text, s_col = f"v{inst_ver} → v{new_ver}  обновление", COLORS["orange"]
            btn_text, btn_col = "🔄   Обновить", COLORS["btn_upd"]
        else:
            size = self.game.get('size_mb', '?')
            s_text, s_col = f"v{new_ver}  •  {size} МБ", COLORS["gray"]
            btn_text, btn_col = "⬇   Скачать", COLORS["btn_dl"]

        ctk.CTkLabel(self, text=s_text,
                     font=ctk.CTkFont(size=11),
                     text_color=s_col).pack(pady=(3, 0))

        desc = self.game.get('description', '')
        if desc:
            ctk.CTkLabel(self, text=desc,
                         font=ctk.CTkFont(size=11),
                         text_color="#888899",
                         wraplength=170).pack(pady=(4, 0))

        # Прогресс-бар (скрыт по умолчанию)
        self._prog_frame = ctk.CTkFrame(self, fg_color="transparent")
        self._prog_frame.pack(pady=(8, 0), padx=16, fill="x")
        self.progress = ctk.CTkProgressBar(self._prog_frame, height=8, corner_radius=4)
        self.progress.set(0)
        self.prog_lbl = ctk.CTkLabel(self._prog_frame, text="",
                                      font=ctk.CTkFont(size=10),
                                      text_color=COLORS["gray"])
        self._prog_frame.pack_forget()   # скрыт

        # Кнопка
        self.btn = ctk.CTkButton(
            self, text=btn_text, width=170, height=38,
            fg_color=btn_col, hover_color=_brighten(btn_col),
            corner_radius=10, font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self.on_action(self.game)
        )
        self.btn.pack(pady=(10, 18))

    def show_progress(self, value, text=""):
        self._prog_frame.pack(pady=(8, 0), padx=16, fill="x")
        self.progress.pack(fill="x")
        self.prog_lbl.configure(text=text)
        self.prog_lbl.pack()
        self.progress.set(value)
        self.btn.configure(state="disabled", text="Загрузка...")

    def done_progress(self):
        self._prog_frame.pack_forget()
        self.btn.configure(state="normal")


def _brighten(hex_col):
    """Чуть осветлить цвет для hover."""
    try:
        h = hex_col.lstrip('#')
        r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
        r,g,b = min(255,r+30), min(255,g+30), min(255,b+30)
        return f"#{r:02x}{g:02x}{b:02x}"
    except: return hex_col


# ══════════════════════════════════════════════════════════
class LauncherApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("My Games")
        self.geometry("780x520")
        self.minsize(500, 380)
        self.configure(fg_color=COLORS["bg"])

        # Убираем стандартный заголовок и делаем свой
        self._state   = load_state()
        self._catalog = []
        self._cards   = {}

        self._build_ui()
        self.after(200, lambda: threading.Thread(
            target=self._startup, daemon=True).start())

    # ── UI ───────────────────────────────────────────────
    def _build_ui(self):
        # Хедер
        hdr = ctk.CTkFrame(self, fg_color=COLORS["header"],
                            corner_radius=0, height=56)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        ctk.CTkLabel(hdr, text="⚔  MY GAMES",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=COLORS["accent"]).pack(side="left", padx=20)

        self.refresh_btn = ctk.CTkButton(
            hdr, text="🔄", width=38, height=32,
            fg_color="transparent", hover_color="#222244",
            command=lambda: threading.Thread(
                target=self._load_catalog, daemon=True).start()
        )
        self.refresh_btn.pack(side="right", padx=12)

        self.status_lbl = ctk.CTkLabel(
            hdr, text="...",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["gray"])
        self.status_lbl.pack(side="right", padx=4)

        # Скроллируемая область с играми
        self.scroll = ctk.CTkScrollableFrame(
            self, fg_color=COLORS["bg"], corner_radius=0)
        self.scroll.pack(fill="both", expand=True)

        # Футер
        ftr = ctk.CTkFrame(self, fg_color=COLORS["footer"],
                            corner_radius=0, height=28)
        ftr.pack(fill="x")
        ftr.pack_propagate(False)
        ctk.CTkLabel(ftr, text=f"Launcher v{LAUNCHER_VERSION}",
                     font=ctk.CTkFont(size=10),
                     text_color="#333355").pack(side="left", padx=12)

    # ── Запуск ───────────────────────────────────────────
    def _startup(self):
        self._set_status("Проверка обновлений...")
        self._check_launcher_update()
        self._load_catalog()

    def _check_launcher_update(self):
        data = fetch_json(VERSION_URL)
        if not data: return
        if data.get('version', '0') > LAUNCHER_VERSION:
            mandatory = data.get('mandatory', False)
            msg = f"Доступно обновление лаунчера v{data['version']}"
            self._set_status(msg)
            # TODO: скачать и заменить лаунчер

    # ── Каталог ──────────────────────────────────────────
    def _load_catalog(self):
        self._set_status("Загрузка каталога...")
        data = fetch_json(CATALOG_URL)
        if data and 'games' in data:
            self._catalog = data['games']
            try: CACHE_FILE.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
            except: pass
            self._set_status(f"{len(self._catalog)} игр")
        else:
            # Офлайн — берём кеш
            if CACHE_FILE.exists():
                try:
                    self._catalog = json.loads(
                        CACHE_FILE.read_text(encoding='utf-8')).get('games', [])
                    self._set_status("Офлайн (кеш)")
                except: self._set_status("Ошибка загрузки")
            else:
                self._set_status("Нет соединения и кеша")
                return
        self.after(0, self._render)

    # ── Рендер карточек ──────────────────────────────────
    def _render(self):
        for w in self.scroll.winfo_children():
            w.destroy()
        self._cards.clear()

        if not self._catalog:
            ctk.CTkLabel(self.scroll, text="Игры не найдены",
                         font=ctk.CTkFont(size=16),
                         text_color=COLORS["gray"]).pack(pady=60)
            return

        grid = ctk.CTkFrame(self.scroll, fg_color="transparent")
        grid.pack(padx=20, pady=20)

        COLS = 3
        for i, game in enumerate(self._catalog):
            row, col = divmod(i, COLS)
            card = GameCard(grid, game, self._state,
                            self._on_action, width=200)
            card.grid(row=row, column=col, padx=10, pady=10, sticky="n")
            self._cards[game['id']] = card

    # ── Действие по кнопке ───────────────────────────────
    def _on_action(self, game):
        inst = self._state.get(game['id'], {})
        if inst.get('version') == game['version']:
            self._launch(game)
        else:
            threading.Thread(target=self._download,
                             args=(game,), daemon=True).start()

    # ── Запуск игры ──────────────────────────────────────
    def _launch(self, game):
        exe = self._state.get(game['id'], {}).get('exe')
        if exe and os.path.exists(exe):
            subprocess.Popen([exe], cwd=os.path.dirname(exe))
            self._set_status(f"Запущена: {game['name']}")
        else:
            self._set_status("Файл не найден — переустановите игру")
            # Сбросить состояние чтобы можно было скачать снова
            self._state.pop(game['id'], None)
            save_state(self._state)
            self.after(0, self._render)

    # ── Скачивание ───────────────────────────────────────
    def _download(self, game):
        card = self._cards.get(game['id'])
        url  = game.get('download_url', '')

        if not url:
            self._set_status("URL не указан в каталоге")
            return

        game_dir = GAMES_DIR / game['id']
        game_dir.mkdir(parents=True, exist_ok=True)
        zip_path = game_dir / f"{game['id']}.zip"

        try:
            if card: self.after(0, lambda: card.show_progress(0, "Подключение..."))

            req = _ur.Request(url, headers={"User-Agent": "FlagRaceLauncher/1.0"})
            with _ur.urlopen(req, timeout=60) as resp:
                total = int(resp.getheader("Content-Length") or 0)
                done  = 0
                chunk = 65536
                with open(zip_path, "wb") as f:
                    while True:
                        buf = resp.read(chunk)
                        if not buf:
                            break
                        f.write(buf)
                        done += len(buf)
                        if total > 0 and card:
                            pct = min(1.0, done / total)
                            d_mb = done / 1_048_576
                            t_mb = total / 1_048_576
                            self.after(0, lambda p=pct, d=d_mb, t=t_mb:
                                       card.show_progress(p, f"{d:.1f} / {t:.1f} МБ"))

            # Распаковка
            if card: self.after(0, lambda: card.show_progress(1.0, "Распаковка..."))
            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall(game_dir)
            zip_path.unlink(missing_ok=True)

            # Найти .exe
            exes = sorted(game_dir.rglob("*.exe"),
                          key=lambda p: len(p.parts))  # берём самый верхний
            exe_path = str(exes[0]) if exes else None

            # Сохранить состояние
            self._state[game['id']] = {
                'version': game['version'],
                'exe': exe_path
            }
            save_state(self._state)

            if card: self.after(0, card.done_progress)
            self.after(0, self._render)
            self._set_status(f"{game['name']} установлена ✓")

        except Exception as e:
            self._set_status(f"Ошибка загрузки: {e}")
            if card: self.after(0, card.done_progress)
            # Убрать незавершённый zip
            zip_path.unlink(missing_ok=True)

    # ── Хелпер статуса ───────────────────────────────────
    def _set_status(self, text):
        self.after(0, lambda: self.status_lbl.configure(text=text))


# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = LauncherApp()
    app.mainloop()
