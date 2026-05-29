import customtkinter as ctk
import json, os, sys, threading, zipfile, subprocess, webbrowser, uuid, time
import urllib.request as _ur
import urllib.parse
from pathlib import Path
from tkinter import filedialog
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── Версия и URLs ────────────────────────────────────────
LAUNCHER_VERSION = "1.0.0"
CATALOG_URL  = "https://raw.githubusercontent.com/vasyapechen/launcher/main/catalog.json"
VERSION_URL  = "https://raw.githubusercontent.com/vasyapechen/launcher/main/launcher_version.json"
AUTH_SERVER  = "https://auth-server-w8ra.onrender.com"

# ── Пути ─────────────────────────────────────────────────
BASE_DIR    = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
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
    try:
        import subprocess as _sp
        out = _sp.check_output("wmic csproduct get UUID", shell=True).decode()
        return out.split("\n")[1].strip()
    except:
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
                self, text="🗑  Удалить", width=170, height=26,
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

        self._auth      = load_auth()
        self._login_win = None

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
        self.refresh_btn.pack(side="right", padx=4)

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
        ctk.CTkLabel(ftr, text=f"Launcher v{LAUNCHER_VERSION}",
                     font=ctk.CTkFont(size=10),
                     text_color="#333355").pack(side="left", padx=12)

    # ── Выбор папки ─────────────────────────────────────
    def _choose_games_dir(self):
        global GAMES_DIR
        chosen = filedialog.askdirectory(
            title="Папка для игр",
            initialdir=str(GAMES_DIR)
        )
        if not chosen:
            return
        GAMES_DIR = Path(chosen)
        GAMES_DIR.mkdir(parents=True, exist_ok=True)
        _config["games_dir"] = str(GAMES_DIR)
        save_config(_config)
        self.dir_lbl.configure(text=str(GAMES_DIR))
        self._set_status("Папка изменена")

    # ── Запуск ───────────────────────────────────────────
    def _startup(self):
        self._set_status("Проверка авторизации...")
        token = self._auth.get("token")
        last_verify = self._auth.get("last_verify", 0)
        need_verify = (time.time() - last_verify) > 86400  # раз в день

        if token and not need_verify:
            # Токен свежий — пропускаем онлайн-проверку
            self._after_login()
            return

        if token:
            result = verify_token(token)
            if result.get("ok"):
                self._auth["last_verify"] = time.time()
                self._auth["name"] = result.get("name", "")
                save_auth(self._auth)
                self._after_login()
                return
            else:
                clear_auth()
                self._auth = {}

        # Нет токена или истёк — показываем экран входа
        self.after(0, self._show_login_screen)

    def _after_login(self):
        name = self._auth.get("name", "")
        self._set_status(f"Привет, {name}!" if name else "")
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
    def _on_action(self, game, delete=False):
        if delete:
            self._delete(game)
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
            self._set_status(f"Ошибка удаления: {e}")
            return
        self._state.pop(gid, None)
        save_state(self._state)
        self._set_status(f"{game['name']} удалена")
        self.after(0, self._render)

    # ── Запуск игры ──────────────────────────────────────
    def _launch(self, game):
        exe = self._state.get(game['id'], {}).get('exe')
        if exe and os.path.exists(exe):
            token = self._auth.get("token", "")
            cmd = [exe, "--token", token, "--device", DEVICE_ID] if token else [exe]
            subprocess.Popen(cmd, cwd=os.path.dirname(exe))
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

    # ── Экран входа ──────────────────────────────────────
    def _show_login_screen(self):
        self._login_win = ctk.CTkToplevel(self)
        self._login_win.title("Войти")
        self._login_win.geometry("420x420")
        self._login_win.resizable(False, False)
        self._login_win.configure(fg_color=COLORS["bg"])
        self._login_win.grab_set()
        self._login_win.protocol("WM_DELETE_WINDOW", self.destroy)  # закрыть = выйти из лаунчера

        ctk.CTkLabel(self._login_win, text="⚔  MY GAMES",
                     font=ctk.CTkFont(size=26, weight="bold"),
                     text_color=COLORS["accent"]).pack(pady=(30, 8))

        ctk.CTkLabel(self._login_win, text="Требуется подписка Patreon",
                     font=ctk.CTkFont(size=13),
                     text_color=COLORS["gray"]).pack()

        self._login_status = ctk.CTkLabel(self._login_win, text="",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["orange"])
        self._login_status.pack(pady=(6, 0))

        ctk.CTkButton(
            self._login_win, text="🔑  Войти через Patreon",
            width=240, height=44,
            fg_color=COLORS["btn_play"], hover_color=_brighten(COLORS["btn_play"]),
            corner_radius=12, font=ctk.CTkFont(size=14, weight="bold"),
            command=lambda: threading.Thread(target=self._do_login, daemon=True).start()
        ).pack(pady=(16, 0))

        # Разделитель "— или —"
        sep_frame = ctk.CTkFrame(self._login_win, fg_color="transparent")
        sep_frame.pack(pady=(18, 0), fill="x", padx=60)
        ctk.CTkFrame(sep_frame, fg_color="#2a2a44", height=1).pack(
            fill="x", side="left", expand=True, pady=9)
        ctk.CTkLabel(sep_frame, text="  или  ", font=ctk.CTkFont(size=11),
                     text_color="#444466").pack(side="left")
        ctk.CTkFrame(sep_frame, fg_color="#2a2a44", height=1).pack(
            fill="x", side="left", expand=True, pady=9)

        # Кнопка «Ввести код»
        self._code_toggle_btn = ctk.CTkButton(
            self._login_win, text="🎟  Ввести код доступа",
            width=240, height=38,
            fg_color="transparent", hover_color="#1a1a2e",
            border_width=1, border_color="#444466",
            corner_radius=10, font=ctk.CTkFont(size=13),
            text_color="#aaaacc",
            command=self._show_code_entry
        )
        self._code_toggle_btn.pack(pady=(6, 0))

        # Поле ввода кода (скрыто до нажатия)
        self._code_entry_frame = ctk.CTkFrame(self._login_win, fg_color="transparent")
        entry_row = ctk.CTkFrame(self._code_entry_frame, fg_color="transparent")
        entry_row.pack()
        self._code_entry = ctk.CTkEntry(
            entry_row,
            placeholder_text="GUEST-XXXXXX",
            width=190, height=36,
            font=ctk.CTkFont(size=13, family="Courier"),
            justify="center"
        )
        self._code_entry.pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            entry_row, text="→", width=44, height=36,
            fg_color=COLORS["btn_play"], hover_color=_brighten(COLORS["btn_play"]),
            corner_radius=8, font=ctk.CTkFont(size=16, weight="bold"),
            command=lambda: threading.Thread(
                target=self._do_redeem_code, daemon=True).start()
        ).pack(side="left")

    def _do_login(self):
        self._set_login_status("Открываю браузер...")

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
                }
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write("<html><body style='background:#111;color:#8f8;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0'><h2>✅ Готово! Можешь закрыть это окно.</h2></body></html>".encode())
            def log_message(self, *a): pass

        srv = HTTPServer(("localhost", port), Handler)
        srv.timeout = 1

        params = urllib.parse.urlencode({"device_id": DEVICE_ID, "local_port": port})
        url = f"{AUTH_SERVER}/auth/start?{params}"
        webbrowser.open(url)
        self._set_login_status("Жду авторизации в браузере...")

        for _ in range(180):  # ждём до 3 минут
            srv.handle_request()
            if result_holder[0]:
                break

        srv.server_close()

        r = result_holder[0]
        if not r or not r.get("token"):
            self._set_login_status("❌ Авторизация не завершена. Попробуй снова.")
            return

        self._auth = {
            "token":       r["token"],
            "name":        r["name"],
            "tier":        r["tier"],
            "last_verify": time.time(),
        }
        save_auth(self._auth)

        if self._login_win:
            self._login_win.after(0, self._login_win.destroy)

        self._after_login()

    def _show_code_entry(self):
        """Показать/скрыть поле ввода кода."""
        if self._code_entry_frame.winfo_ismapped():
            self._code_entry_frame.pack_forget()
        else:
            self._code_entry_frame.pack(pady=(10, 0))
            self._code_entry.focus()

    def _do_redeem_code(self):
        code = self._code_entry.get().strip().upper()
        if not code:
            self._set_login_status("❌ Введи код")
            return
        self._set_login_status("Проверяю код...")
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
            r = _ur.urlopen(req, timeout=10)
            result = json.loads(r.read())
        except Exception as e:
            self._set_login_status(f"❌ Ошибка соединения")
            return

        if not result.get("ok"):
            err = result.get("error", "")
            msgs = {
                "invalid_code":       "❌ Неверный код",
                "code_expired":       "❌ Срок действия кода истёк",
                "code_limit_reached": "❌ Код уже использован максимальное число раз",
            }
            self._set_login_status(msgs.get(err, f"❌ {err}"))
            return

        self._auth = {
            "token":       result["token"],
            "name":        result.get("name", "Гость"),
            "tier":        result.get("tier", "guest"),
            "last_verify": time.time(),
        }
        save_auth(self._auth)

        if self._login_win:
            self._login_win.after(0, self._login_win.destroy)

        self._after_login()

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
