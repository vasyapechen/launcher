import customtkinter as ctk
import json, os, sys, threading, zipfile, subprocess, webbrowser, uuid, time
import urllib.request as _ur
import urllib.parse
from pathlib import Path
from tkinter import filedialog
from http.server import HTTPServer, BaseHTTPRequestHandler

# Отдельная AppUserModelID — Windows показывает нашу иконку в панели задач
try:
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
        "vasya_pechen.launcher.1.0")
except Exception:
    pass

# ── Версия и URLs ────────────────────────────────────────
LAUNCHER_VERSION = "1.0.4"
CATALOG_URL  = "https://raw.githubusercontent.com/vasyapechen/launcher/main/catalog.json"
VERSION_URL  = "https://raw.githubusercontent.com/vasyapechen/launcher/main/launcher_version.json"
AUTH_SERVER  = "https://auth-server-w8ra.onrender.com"
PATREON_URL  = "https://www.patreon.com/cw/vasya_pechen"

# ── Пути ─────────────────────────────────────────────────
BASE_DIR    = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
ICON_FILE   = Path(sys._MEIPASS) / "icon.ico" if getattr(sys, 'frozen', False) else BASE_DIR / "icon.ico"
STATE_FILE  = BASE_DIR / "games_state.json"
CACHE_FILE  = BASE_DIR / "catalog_cache.json"
CONFIG_FILE = BASE_DIR / "launcher_config.json"

DEFAULT_GAMES_DIR = Path("C:/games")

def load_config():
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
    except: pass
    return {}

def save_config(cfg):
    try: CONFIG_FILE.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding='utf-8')
    except: pass

_config   = load_config()
GAMES_DIR = Path(_config.get("games_dir", str(DEFAULT_GAMES_DIR)))
GAMES_DIR.mkdir(parents=True, exist_ok=True)

# ── Auth ──────────────────────────────────────────────────
TOKEN_FILE = BASE_DIR / "auth_token.json"

def get_device_id():
    """Возвращает хэш реального железа (CPU + материнка + MAC + диск).
    Файл device_id.txt используется только если ВСЕ аппаратные методы недоступны."""
    import subprocess as _sp, hashlib
    parts = []

    # 1. UUID материнской платы — wmic (Win 10)
    try:
        out = _sp.check_output("wmic csproduct get UUID",
                               shell=True, stderr=_sp.DEVNULL).decode()
        uid = out.split("\n")[1].strip()
        if uid and uid.upper() not in ("", "UUID"):
            parts.append("mb:" + uid)
    except: pass

    # 2. UUID материнской платы — PowerShell (Win 11)
    if not any(p.startswith("mb:") for p in parts):
        try:
            out = _sp.check_output(
                'powershell -Command "(Get-CimInstance Win32_ComputerSystemProduct).UUID"',
                shell=True, stderr=_sp.DEVNULL).decode()
            uid = out.strip()
            if uid:
                parts.append("mb:" + uid)
        except: pass

    # 3. ID процессора
    try:
        out = _sp.check_output("wmic cpu get ProcessorId /value",
                               shell=True, stderr=_sp.DEVNULL).decode()
        cpu = ''.join(out.split()).replace("ProcessorId=", "")
        if cpu:
            parts.append("cpu:" + cpu)
    except: pass

    if parts:
        combined = "|".join(parts)
        return hashlib.sha256(combined.encode()).hexdigest()[:40]

    # Последний резерв — если железо вообще не читается (очень редко)
    _id_file = BASE_DIR / "device_id.txt"
    if _id_file.exists():
        return _id_file.read_text().strip()
    _id = str(uuid.uuid4())
    _id_file.write_text(_id)
    return _id

DEVICE_ID = get_device_id()

def load_auth():
    try:
        if TOKEN_FILE.exists():
            return json.loads(TOKEN_FILE.read_text(encoding='utf-8'))
    except: pass
    return {}

def save_auth(data):
    try: TOKEN_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
    except: pass

def clear_auth():
    try: TOKEN_FILE.unlink(missing_ok=True)
    except: pass

def verify_token(token):
    """Возвращает {'ok':True,'name':...,'tier':...} или {'ok':False,'error':...}"""
    try:
        payload = json.dumps({"token": token, "device_id": DEVICE_ID}).encode()
        req = _ur.Request(f"{AUTH_SERVER}/auth/verify",
                          data=payload,
                          headers={"Content-Type":"application/json","User-Agent":"FlagRaceLauncher/1.0"})
        r = _ur.urlopen(req, timeout=10)
        return json.loads(r.read())
    except Exception as e:
        return {"ok": False, "error": str(e)}

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

def _ver_tuple(s):
    """'1.0.2' -> (1, 0, 2). Нечисловые части игнорируются."""
    out = []
    for part in str(s).split('.'):
        digits = ''.join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)

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
            s_text, s_col = f"v{inst_ver}  ✓ installed", COLORS["green"]
            btn_text, btn_col = "▶   Play", COLORS["btn_play"]
        elif inst_ver:
            s_text, s_col = f"v{inst_ver} → v{new_ver}  update", COLORS["orange"]
            btn_text, btn_col = "🔄   Update", COLORS["btn_upd"]
        else:
            size = self.game.get('size_mb', '?')
            s_text, s_col = f"v{new_ver}  •  {size} MB", COLORS["gray"]
            btn_text, btn_col = "⬇   Download", COLORS["btn_dl"]

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

        # Кнопка основная
        self.btn = ctk.CTkButton(
            self, text=btn_text, width=170, height=38,
            fg_color=btn_col, hover_color=_brighten(btn_col),
            corner_radius=10, font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self.on_action(self.game)
        )
        self.btn.pack(pady=(10, 4))

        # Кнопка удаления (только если установлена)
        if inst_ver:
            self.del_btn = ctk.CTkButton(
                self, text="🗑  Uninstall", width=170, height=26,
                fg_color="transparent", hover_color="#3a1a1a",
                border_width=1, border_color="#552222",
                corner_radius=8, font=ctk.CTkFont(size=11),
                text_color="#994444",
                command=lambda: self.on_action(self.game, delete=True)
            )
            self.del_btn.pack(pady=(0, 14))
        else:
            ctk.CTkFrame(self, fg_color="transparent", height=14).pack()

    def show_progress(self, value, text=""):
        self._prog_frame.pack(pady=(8, 0), padx=16, fill="x")
        self.progress.pack(fill="x")
        self.prog_lbl.configure(text=text)
        self.prog_lbl.pack()
        self.progress.set(value)
        self.btn.configure(state="disabled", text="Downloading...")

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
        self.title("Vasya_pechen")
        self.geometry("780x520")
        self.minsize(500, 380)
        self.configure(fg_color=COLORS["bg"])
        try: self.iconbitmap(str(ICON_FILE))
        except: pass

        # Убираем стандартный заголовок и делаем свой
        self._state   = load_state()
        self._catalog = []
        self._cards   = {}

        self._auth           = load_auth()
        self._login_win      = None
        self._logged_in      = False
        self._pending_action = None  # действие, которое запустится после входа

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

        ctk.CTkLabel(hdr, text="⚔  VASYA_PECHEN",
                     font=ctk.CTkFont(size=22, weight="bold"),
                     text_color=COLORS["accent"]).pack(side="left", padx=20)

        self.refresh_btn = ctk.CTkButton(
            hdr, text="🔄", width=38, height=32,
            fg_color="transparent", hover_color="#222244",
            command=lambda: threading.Thread(
                target=self._load_catalog, daemon=True).start()
        )
        self.refresh_btn.pack(side="right", padx=4)

        ctk.CTkButton(
            hdr, text="❤  Patreon", width=100, height=32,
            fg_color="#FF424D", hover_color="#cc2f38",
            corner_radius=8, font=ctk.CTkFont(size=12, weight="bold"),
            text_color="white",
            command=lambda: webbrowser.open(PATREON_URL)
        ).pack(side="right", padx=(8, 4))

        self.folder_btn = ctk.CTkButton(
            hdr, text="📁", width=38, height=32,
            fg_color="transparent", hover_color="#222244",
            command=self._choose_games_dir
        )
        self.folder_btn.pack(side="right", padx=4)

        self.dir_lbl = ctk.CTkLabel(
            hdr, text=str(GAMES_DIR),
            font=ctk.CTkFont(size=10),
            text_color="#444466")
        self.dir_lbl.pack(side="right", padx=8)

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
        ctk.CTkLabel(ftr, text=f"vasya_pechen launcher v{LAUNCHER_VERSION}",
                     font=ctk.CTkFont(size=10),
                     text_color="#333355").pack(side="left", padx=12)

    # ── Выбор папки ─────────────────────────────────────
    def _choose_games_dir(self):
        global GAMES_DIR
        chosen = filedialog.askdirectory(
            title="Games folder",
            initialdir=str(GAMES_DIR)
        )
        if not chosen:
            return
        GAMES_DIR = Path(chosen)
        GAMES_DIR.mkdir(parents=True, exist_ok=True)
        _config["games_dir"] = str(GAMES_DIR)
        save_config(_config)
        self.dir_lbl.configure(text=str(GAMES_DIR))
        self._set_status("Folder changed")

    # ── Запуск ───────────────────────────────────────────
    def _has_game_access(self, game):
        """Проверяет, есть ли у текущего пользователя доступ к этой игре."""
        tier  = self._auth.get("tier", "")
        owned = self._auth.get("games", [])
        if not tier:
            return False
        # Покупатель: только купленные игры
        if tier == "buyer":
            return game["id"] in owned
        # Подписчик / гость-код: доступ ко всем играм
        return True

    def _startup(self):
        self._check_launcher_update()   # проверяем обновление лаунчера всегда при запуске
        self._set_status("Checking auth...")
        token = self._auth.get("token")
        last_verify = self._auth.get("last_verify", 0)
        need_verify = (time.time() - last_verify) > 3600   # раз в час

        if token and not need_verify:
            self._logged_in = True
            self._after_login()
            return

        if token:
            result = verify_token(token)
            if result.get("ok"):
                self._auth["last_verify"] = time.time()
                self._auth["name"]  = result.get("name", "")
                self._auth["games"] = result.get("games", [])
                save_auth(self._auth)
                self._logged_in = True
                self._after_login()
                return
            else:
                clear_auth()
                self._auth = {}

        # Нет токена — загружаем каталог, но без возможности играть
        self._set_status("Sign in to play")
        self._load_catalog()

    def _after_login(self):
        self._logged_in = True
        name = self._auth.get("name", "")
        self._set_status(f"Welcome, {name}!" if name else "")
        self._load_catalog()

    def _check_launcher_update(self):
        data = fetch_json(VERSION_URL)
        if not data: return
        if _ver_tuple(data.get('version', '0')) > _ver_tuple(LAUNCHER_VERSION):
            self.after(0, lambda: self._prompt_launcher_update(data))

    def _prompt_launcher_update(self, data):
        """Окно с предложением обновить лаунчер."""
        win = ctk.CTkToplevel(self)
        win.title("Обновление лаунчера")
        win.geometry("400x230")
        win.resizable(False, False)
        win.configure(fg_color=COLORS["bg"])
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        self._bring_to_front(win)

        ctk.CTkLabel(win, text="🔄  Доступно обновление",
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=COLORS["accent"]).pack(pady=(24, 4))
        ctk.CTkLabel(win, text=f"Новая версия v{data.get('version','')}",
                     font=ctk.CTkFont(size=13),
                     text_color=COLORS["gray"]).pack()
        cl = data.get('changelog', '')
        if cl:
            ctk.CTkLabel(win, text=cl, font=ctk.CTkFont(size=11),
                         text_color="#888899", wraplength=340).pack(pady=(8, 0))

        self._upd_status = ctk.CTkLabel(win, text="", font=ctk.CTkFont(size=11),
                                        text_color=COLORS["orange"])
        self._upd_status.pack(pady=(8, 0))

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(pady=(16, 0))
        ctk.CTkButton(btns, text="Позже", width=110, height=36,
                      fg_color="#33334d", hover_color="#44445d",
                      command=win.destroy).grid(row=0, column=0, padx=6)
        ctk.CTkButton(btns, text="Обновить сейчас", width=160, height=36,
                      fg_color=COLORS["btn_play"],
                      hover_color=_brighten(COLORS["btn_play"]),
                      font=ctk.CTkFont(weight="bold"),
                      command=lambda: threading.Thread(
                          target=self._do_launcher_update,
                          args=(data, win), daemon=True).start()
                      ).grid(row=0, column=1, padx=6)

    def _do_launcher_update(self, data, win=None):
        """Скачивает новый exe и запускает bat-помощник для подмены и перезапуска."""
        def status(t):
            try: self.after(0, lambda: self._upd_status.configure(text=t))
            except Exception: pass

        url = data.get('download_url', '')
        if not url:
            status("Нет ссылки на обновление"); return
        if not getattr(sys, 'frozen', False):
            status("Автообновление работает только в собранном .exe"); return

        try:
            cur_exe = Path(sys.executable)
            new_exe = cur_exe.with_name("Launcher_new.exe")
            status("Скачивание обновления...")
            req = _ur.Request(url, headers={"User-Agent": "Launcher"})
            with _ur.urlopen(req, timeout=120) as r, open(new_exe, "wb") as f:
                f.write(r.read())

            # bat-помощник: ждёт закрытия лаунчера, заменяет exe, перезапускает, удаляет себя
            bat = cur_exe.with_name("_update.bat")
            bat_text = (
                "@echo off\r\n"
                ":wait\r\n"
                "ping -n 2 127.0.0.1 >nul\r\n"
                f'tasklist /fi "imagename eq {cur_exe.name}" | find /i "{cur_exe.name}" >nul && goto wait\r\n'
                f'move /y "{new_exe.name}" "{cur_exe.name}" >nul\r\n'
                f'start "" "{cur_exe.name}"\r\n'
                'del "%~f0"\r\n'
            )
            bat.write_text(bat_text, encoding="utf-8")

            status("Перезапуск...")
            subprocess.Popen(
                ["cmd", "/c", str(bat)],
                cwd=str(cur_exe.parent),
                creationflags=0x08000000  # CREATE_NO_WINDOW
            )
            self.after(300, self.destroy)
        except Exception as e:
            status(f"Ошибка: {e}")

    # ── Каталог ──────────────────────────────────────────
    def _load_catalog(self):
        self._set_status("Loading catalog...")
        data = fetch_json(CATALOG_URL)
        if data and 'games' in data:
            self._catalog = data['games']
            try: CACHE_FILE.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
            except: pass
            self._set_status(f"{len(self._catalog)} games")
        else:
            # Offline — use cache
            if CACHE_FILE.exists():
                try:
                    self._catalog = json.loads(
                        CACHE_FILE.read_text(encoding='utf-8')).get('games', [])
                    self._set_status("Offline (cache)")
                except: self._set_status("Load error")
            else:
                self._set_status("No connection")
                return
        self.after(0, self._render)

    # ── Рендер карточек ──────────────────────────────────
    def _render(self):
        for w in self.scroll.winfo_children():
            w.destroy()
        self._cards.clear()

        if not self._catalog:
            ctk.CTkLabel(self.scroll, text="No games found",
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
    def _bring_to_front(self, win):
        """Поднять окно поверх остальных и дать фокус."""
        try:
            win.transient(self)
            win.lift()
            win.focus_force()
            win.attributes("-topmost", True)
            win.after(300, lambda: win.attributes("-topmost", False))
        except Exception:
            pass

    def _confirm_delete(self, game):
        """Окно подтверждения удаления игры."""
        win = ctk.CTkToplevel(self)
        win.title("Удаление")
        win.geometry("360x190")
        win.resizable(False, False)
        win.configure(fg_color=COLORS["bg"])
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        self._bring_to_front(win)

        ctk.CTkLabel(win, text=f"🗑  Удалить {game['name']}?",
                     font=ctk.CTkFont(size=17, weight="bold"),
                     text_color=COLORS["accent"]).pack(pady=(26, 6))
        ctk.CTkLabel(win, text="Файлы игры будут удалены.\nЕё можно будет скачать снова.",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["gray"]).pack()

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(pady=(20, 0))
        ctk.CTkButton(
            btn_row, text="Отмена", width=120, height=36,
            fg_color="#2a2a44", hover_color="#3a3a5a",
            corner_radius=10, font=ctk.CTkFont(size=13),
            command=win.destroy
        ).pack(side="left", padx=(0, 10))
        ctk.CTkButton(
            btn_row, text="🗑  Удалить", width=120, height=36,
            fg_color="#8a2a2a", hover_color="#aa3a3a",
            corner_radius=10, font=ctk.CTkFont(size=13, weight="bold"),
            text_color="white",
            command=lambda: (win.destroy(), self._delete(game))
        ).pack(side="left")

    def _on_action(self, game, delete=False):
        # Удаление доступно всегда — даже без входа/подписки
        if delete:
            self._confirm_delete(game)
            return
        if not self._logged_in:
            self._pending_action = lambda: self._on_action(game, delete)
            self._show_login_screen(game=game)
            return
        # Проверяем доступ к конкретной игре
        if not self._has_game_access(game):
            self._show_activate_screen(game)
            return
        inst = self._state.get(game['id'], {})
        if inst.get('version') == game['version']:
            self._launch(game)
        else:
            threading.Thread(target=self._download,
                             args=(game,), daemon=True).start()

    # ── Удаление игры ────────────────────────────────────
    def _delete(self, game):
        import shutil
        gid = game['id']
        game_dir = GAMES_DIR / gid
        try:
            if game_dir.exists():
                shutil.rmtree(game_dir)
        except Exception as e:
            self._set_status(f"Uninstall error: {e}")
            return
        self._state.pop(gid, None)
        save_state(self._state)
        self._set_status(f"{game['name']} uninstalled")
        self.after(0, self._render)

    # ── Запуск игры ──────────────────────────────────────
    def _launch(self, game):
        exe = self._state.get(game['id'], {}).get('exe')
        if exe and os.path.exists(exe):
            token = self._auth.get("token", "")
            cmd = [exe, "--token", token, "--device", DEVICE_ID] if token else [exe]
            subprocess.Popen(cmd, cwd=os.path.dirname(exe))
            self._set_status(f"Launched: {game['name']}")
        else:
            self._set_status("File not found — reinstall the game")
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
            if card: self.after(0, lambda: card.show_progress(0, "Connecting..."))

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
                                       card.show_progress(p, f"{d:.1f} / {t:.1f} MB"))

            # Extracting
            if card: self.after(0, lambda: card.show_progress(1.0, "Extracting..."))
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
            self._set_status(f"{game['name']} installed ✓")

        except Exception as e:
            self._set_status(f"Download error: {e}")
            if card: self.after(0, card.done_progress)
            # Убрать незавершённый zip
            zip_path.unlink(missing_ok=True)

    # ── Экран входа ──────────────────────────────────────
    def _show_login_screen(self, game=None):
        self._login_game = game   # игра, для которой открывается вход
        self._login_win = ctk.CTkToplevel(self)
        self._login_win.title("Sign in")
        h = 570 if game else 480
        self._login_win.geometry(f"460x{h}")
        self._login_win.resizable(False, False)
        self._login_win.configure(fg_color=COLORS["bg"])
        self._login_win.protocol("WM_DELETE_WINDOW", self._login_win.destroy)
        self._bring_to_front(self._login_win)

        ctk.CTkLabel(self._login_win, text="⚔  VASYA_PECHEN",
                     font=ctk.CTkFont(size=26, weight="bold"),
                     text_color=COLORS["accent"]).pack(pady=(30, 8))

        ctk.CTkLabel(self._login_win, text="Patreon subscription required",
                     font=ctk.CTkFont(size=13),
                     text_color=COLORS["gray"]).pack()

        self._login_status = ctk.CTkLabel(self._login_win, text="",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["orange"])
        self._login_status.pack(pady=(6, 0))

        ctk.CTkButton(
            self._login_win, text="🔑  Sign in with Patreon",
            width=240, height=44,
            fg_color=COLORS["btn_play"], hover_color=_brighten(COLORS["btn_play"]),
            corner_radius=12, font=ctk.CTkFont(size=14, weight="bold"),
            command=lambda: threading.Thread(target=self._do_login, daemon=True).start()
        ).pack(pady=(16, 0))

        ctk.CTkLabel(self._login_win, text="No subscription yet?",
                     font=ctk.CTkFont(size=11), text_color="#444466").pack(pady=(10, 0))

        ctk.CTkButton(
            self._login_win, text="❤  Subscribe on Patreon",
            width=240, height=34,
            fg_color="#FF424D", hover_color="#cc2f38",
            corner_radius=10, font=ctk.CTkFont(size=12, weight="bold"),
            text_color="white",
            command=lambda: webbrowser.open(PATREON_URL)
        ).pack(pady=(4, 0))

        # Разделитель "— или —"
        sep_frame = ctk.CTkFrame(self._login_win, fg_color="transparent")
        sep_frame.pack(pady=(18, 0), fill="x", padx=60)
        ctk.CTkFrame(sep_frame, fg_color="#2a2a44", height=1).pack(
            fill="x", side="left", expand=True, pady=9)
        ctk.CTkLabel(sep_frame, text="  or  ", font=ctk.CTkFont(size=11),
                     text_color="#444466").pack(side="left")
        ctk.CTkFrame(sep_frame, fg_color="#2a2a44", height=1).pack(
            fill="x", side="left", expand=True, pady=9)

        # Секция «Ввести код» — контейнер держит позицию в layout,
        # внутри переключаем кнопку <-> поле ввода (без хрупкого after)
        self._code_section = ctk.CTkFrame(self._login_win, fg_color="transparent")
        self._code_section.pack(pady=(6, 0))

        # Кнопка «Ввести код»
        self._code_toggle_btn = ctk.CTkButton(
            self._code_section, text="🎟  Enter access code",
            width=240, height=38,
            fg_color="transparent", hover_color="#1a1a2e",
            border_width=1, border_color="#444466",
            corner_radius=10, font=ctk.CTkFont(size=13),
            text_color="#aaaacc",
            command=self._show_code_entry
        )
        self._code_toggle_btn.pack()

        # Поле ввода кода (скрыто до нажатия)
        self._code_entry_frame = ctk.CTkFrame(self._code_section, fg_color="transparent")
        self._code_entry = ctk.CTkEntry(
            self._code_entry_frame,
            placeholder_text="GUEST-XXXXXX",
            width=190, height=38,
            font=ctk.CTkFont(size=13, family="Courier"),
            justify="center"
        )
        self._code_entry.grid(row=0, column=0, padx=(0, 8))
        self._add_entry_context_menu(self._code_entry)
        self._code_entry.bind("<Return>", lambda e: threading.Thread(
            target=self._do_redeem_code, daemon=True).start())
        ctk.CTkButton(
            self._code_entry_frame, text="→", width=46, height=38,
            fg_color=COLORS["btn_play"], hover_color=_brighten(COLORS["btn_play"]),
            corner_radius=8, font=ctk.CTkFont(size=18, weight="bold"),
            command=lambda: threading.Thread(
                target=self._do_redeem_code, daemon=True).start()
        ).grid(row=0, column=1)

        # Блок активации купленной игры (показывается только если нажали Play на игре)
        if game:
            sep2 = ctk.CTkFrame(self._login_win, fg_color="transparent")
            sep2.pack(pady=(14, 0), fill="x", padx=60)
            ctk.CTkFrame(sep2, fg_color="#2a2a44", height=1).pack(
                fill="x", side="left", expand=True, pady=9)
            ctk.CTkLabel(sep2, text="  or  ", font=ctk.CTkFont(size=11),
                         text_color="#444466").pack(side="left")
            ctk.CTkFrame(sep2, fg_color="#2a2a44", height=1).pack(
                fill="x", side="left", expand=True, pady=9)

            ctk.CTkLabel(
                self._login_win,
                text=f"Already bought {game['name']} on Patreon?",
                font=ctk.CTkFont(size=11), text_color="#444466"
            ).pack(pady=(2, 0))

            ctk.CTkButton(
                self._login_win,
                text=f"🔑  Activate {game['name']}",
                width=240, height=38,
                fg_color="#2a4a2a", hover_color="#3a6a3a",
                border_width=1, border_color="#446644",
                corner_radius=10, font=ctk.CTkFont(size=13, weight="bold"),
                text_color="#aaffaa",
                command=lambda g=game: threading.Thread(
                    target=self._do_activate_game, args=(g,), daemon=True).start()
            ).pack(pady=(4, 16))

    def _add_entry_context_menu(self, entry):
        """Контекстное меню (ПКМ) + вставка при любой раскладке (по физическому keycode)."""
        import tkinter as tk
        try:
            inner = entry._entry   # tk.Entry внутри CTkEntry
        except AttributeError:
            return
        try:
            menu = tk.Menu(
                inner, tearoff=0,
                bg="#1a1a2e", fg="#e8e8f8",
                activebackground="#2a2a4e", activeforeground="#e8e8f8",
                bd=0
            )
            menu.add_command(label="Вырезать",     command=lambda: inner.event_generate("<<Cut>>"))
            menu.add_command(label="Копировать",   command=lambda: inner.event_generate("<<Copy>>"))
            menu.add_command(label="Вставить",     command=lambda: inner.event_generate("<<Paste>>"))
            menu.add_separator()
            menu.add_command(label="Выделить всё", command=lambda: inner.event_generate("<<SelectAll>>"))

            def _show_menu(ev):
                try:    menu.tk_popup(ev.x_root, ev.y_root)
                finally: menu.grab_release()

            inner.bind("<Button-3>", _show_menu)

            # Ctrl+клавиша по физическому keycode — не зависит от раскладки (V/C/X/A)
            def _ctrl_key(ev):
                if not (ev.state & 0x4):   # Control зажат
                    return
                kc = ev.keycode
                if   kc == 86: inner.event_generate("<<Paste>>");     return "break"  # V
                elif kc == 67: inner.event_generate("<<Copy>>");      return "break"  # C
                elif kc == 88: inner.event_generate("<<Cut>>");       return "break"  # X
                elif kc == 65: inner.event_generate("<<SelectAll>>"); return "break"  # A
            inner.bind("<Control-KeyPress>", _ctrl_key)
        except Exception:
            pass

    def _do_login(self):
        self._set_login_status("Opening browser...")

        # Найти свободный порт
        import socket
        with socket.socket() as s:
            s.bind(('', 0))
            port = s.getsockname()[1]

        result_holder = [None]

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                result_holder[0] = {
                    "token": params.get("token", [""])[0],
                    "name":  params.get("name",  [""])[0],
                    "tier":  params.get("tier",  [""])[0],
                    "games": params.get("games", [""])[0],
                }
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("<html><body style='background:#111;color:#8f8;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0'><h2>&#10003; Done! You can close this window.</h2></body></html>".encode())
            def log_message(self, *a): pass

        srv = HTTPServer(("localhost", port), Handler)
        srv.timeout = 1

        params = urllib.parse.urlencode({"device_id": DEVICE_ID, "local_port": port})
        url = f"{AUTH_SERVER}/auth/start?{params}"
        webbrowser.open(url)
        self._set_login_status("Waiting for browser sign-in...")

        for _ in range(180):  # ждём до 3 минут
            srv.handle_request()
            if result_holder[0]:
                break

        srv.server_close()

        r = result_holder[0]
        if not r or not r.get("token"):
            self._set_login_status("❌ Sign-in not completed. Try again.")
            return

        games_str = r.get("games", "")
        self._auth = {
            "token":       r["token"],
            "name":        r["name"],
            "tier":        r["tier"],
            "games":       [g for g in games_str.split(",") if g],
            "last_verify": time.time(),
        }
        save_auth(self._auth)

        if self._login_win:
            self._login_win.after(0, self._login_win.destroy)

        self._after_login()
        self._run_pending_action()

    def _show_code_entry(self):
        """Заменить кнопку «Ввести код» полем ввода в том же месте."""
        if self._code_entry_frame.winfo_ismapped():
            self._code_entry.focus()
            return
        self._code_toggle_btn.pack_forget()
        self._code_entry_frame.pack()
        self._code_entry.focus()

    def _do_redeem_code(self):
        code = self._code_entry.get().strip().upper()
        if not code:
            self._set_login_status("❌ Enter a code")
            return
        self._set_login_status("Verifying code...")
        try:
            payload = json.dumps({
                "code": code,
                "device_id": DEVICE_ID,
                "name": "Гость"
            }).encode()
            req = _ur.Request(
                f"{AUTH_SERVER}/auth/redeem_code", data=payload,
                headers={"Content-Type": "application/json",
                         "User-Agent": "FlagRaceLauncher/1.0"}
            )
            try:
                r = _ur.urlopen(req, timeout=15)
                result = json.loads(r.read())
            except Exception as e:
                # HTTPError (4xx/5xx) тоже содержит тело с деталями ошибки
                try:
                    result = json.loads(e.read())  # type: ignore
                except Exception:
                    self._set_login_status("❌ Connection error")
                    return
        except Exception:
            self._set_login_status("❌ Connection error")
            return

        if not result.get("ok"):
            err = result.get("error", "")
            msgs = {
                "invalid_code":       "❌ Invalid code",
                "code_expired":       "❌ Code has expired",
                "code_limit_reached": "❌ Code usage limit reached",
            }
            self._set_login_status(msgs.get(err, f"❌ {err}"))
            return

        self._auth = {
            "token":       result["token"],
            "name":        result.get("name", "Guest"),
            "tier":        result.get("tier", "guest"),
            "games":       result.get("games", []),
            "last_verify": time.time(),
        }
        save_auth(self._auth)

        if self._login_win:
            self._login_win.after(0, self._login_win.destroy)

        self._after_login()
        self._run_pending_action()

    def _show_activate_screen(self, game):
        """Окно для активации игры, купленной на Patreon (пользователь уже вошёл, но без доступа)."""
        win = ctk.CTkToplevel(self)
        win.title("Activate game")
        win.geometry("360x230")
        win.resizable(False, False)
        win.configure(fg_color=COLORS["bg"])
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        self._activate_win = win
        self._bring_to_front(win)

        ctk.CTkLabel(win, text=f"🔒  {game['name']}",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=COLORS["accent"]).pack(pady=(28, 4))

        ctk.CTkLabel(win, text="You don't have access to this game.",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["gray"]).pack()

        self._activate_status = ctk.CTkLabel(win, text="",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["orange"])
        self._activate_status.pack(pady=(4, 0))

        ctk.CTkButton(
            win, text="❤  Buy on Patreon",
            width=240, height=38,
            fg_color="#FF424D", hover_color="#cc2f38",
            corner_radius=10, font=ctk.CTkFont(size=13, weight="bold"),
            text_color="white",
            command=lambda: webbrowser.open(PATREON_URL)
        ).pack(pady=(14, 4))

        ctk.CTkButton(
            win, text="🔑  Activate (already bought)",
            width=240, height=38,
            fg_color="#2a4a2a", hover_color="#3a6a3a",
            border_width=1, border_color="#446644",
            corner_radius=10, font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#aaffaa",
            command=lambda g=game: threading.Thread(
                target=self._do_activate_game, args=(g,), daemon=True).start()
        ).pack()

    def _do_activate_game(self, game):
        """OAuth через /auth/start_game — активирует купленную игру."""
        import socket as _sock

        def _status(msg):
            # Обновляем статус в том окне, которое открыто
            if self._login_win:
                self._set_login_status(msg)
            elif hasattr(self, '_activate_win') and self._activate_win:
                self._activate_win.after(
                    0, lambda: self._activate_status.configure(text=msg))

        _status("Opening browser...")

        with _sock.socket() as s:
            s.bind(('', 0))
            port = s.getsockname()[1]

        result_holder = [None]

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(parsed.query)
                result_holder[0] = {
                    "token": params.get("token", [""])[0],
                    "name":  params.get("name",  [""])[0],
                    "tier":  params.get("tier",  [""])[0],
                    "games": params.get("games", [""])[0],
                }
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(
                    b"<html><body style='background:#111;color:#8f8;"
                    b"font-family:sans-serif;display:flex;align-items:center;"
                    b"justify-content:center;height:100vh;margin:0'>"
                    b"<h2>\xe2\x9c\x85 Done! You can close this window.</h2>"
                    b"</body></html>"
                )
            def log_message(self, *a): pass

        srv = HTTPServer(("localhost", port), Handler)
        srv.timeout = 1

        url_params = urllib.parse.urlencode({
            "game_id":   game["id"],
            "device_id": DEVICE_ID,
            "local_port": port,
        })
        webbrowser.open(f"{AUTH_SERVER}/auth/start_game?{url_params}")
        _status("Waiting for browser...")

        for _ in range(180):
            srv.handle_request()
            if result_holder[0]:
                break
        srv.server_close()

        r = result_holder[0]
        if not r or not r.get("token"):
            _status("❌ Not completed. Try again.")
            return

        games_str = r.get("games", "")
        self._auth = {
            "token":       r["token"],
            "name":        r["name"],
            "tier":        r["tier"],
            "games":       [g for g in games_str.split(",") if g],
            "last_verify": time.time(),
        }
        save_auth(self._auth)
        self._logged_in = True

        # Закрыть окно входа или активации
        if self._login_win:
            self._login_win.after(0, self._login_win.destroy)
        elif hasattr(self, '_activate_win') and self._activate_win:
            self._activate_win.after(0, self._activate_win.destroy)

        self._after_login()
        self._run_pending_action()

    def _run_pending_action(self):
        """Выполнить действие, которое пользователь пытался сделать до входа."""
        if self._pending_action:
            action = self._pending_action
            self._pending_action = None
            self.after(150, action)

    def _set_login_status(self, text):
        if self._login_win:
            self._login_win.after(0, lambda: self._login_status.configure(text=text))

    # ── Хелпер статуса ───────────────────────────────────
    def _set_status(self, text):
        self.after(0, lambda: self.status_lbl.configure(text=text))


# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = LauncherApp()
    app.mainloop()
