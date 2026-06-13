import customtkinter as ctk
import json, os, sys, threading, zipfile, subprocess, webbrowser, uuid, time, ssl, datetime
from datetime import datetime, date, timedelta
import urllib.request as _ur
import urllib.parse

# ── SSL: доверяем и certifi, и системному хранилищу Windows ──
# (фикс ошибки "certificate verify failed" на старых системах и при антивирусном
#  перехвате HTTPS). Проверку сертификата НЕ отключаем.
def _make_ssl_ctx():
    cafile = None
    try:
        import certifi
        cafile = certifi.where()
    except Exception:
        pass
    try:
        ctx = ssl.create_default_context(cafile=cafile) if cafile else ssl.create_default_context()
    except Exception:
        ctx = ssl.create_default_context()
    try:
        ctx.load_default_certs(ssl.Purpose.SERVER_AUTH)  # + корни Windows (вкл. антивирусные)
    except Exception:
        pass
    return ctx

SSL_CTX = _make_ssl_ctx()
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
LAUNCHER_VERSION = "1.1.5"
CATALOG_URL  = "https://raw.githubusercontent.com/vasyapechen/launcher/main/catalog.json"
VERSION_URL  = "https://raw.githubusercontent.com/vasyapechen/launcher/main/launcher_version.json"
INSTALLER_URL= "https://github.com/vasyapechen/launcher/releases/latest/download/VasyaLauncher-Setup.exe"
AUTH_SERVER  = "https://auth-server-w8ra.onrender.com"
PATREON_URL  = "https://www.patreon.com/cw/vasya_pechen/membership"

# ── Пути ─────────────────────────────────────────────────
BASE_DIR    = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
ICON_FILE   = Path(sys._MEIPASS) / "icon.ico" if getattr(sys, 'frozen', False) else BASE_DIR / "icon.ico"

# Постоянные данные (состояние игр, конфиг, токен) храним в %LOCALAPPDATA%\VasyaLauncher,
# чтобы они не терялись при обновлении/переносе .exe.
DATA_DIR = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(BASE_DIR)) / "VasyaLauncher"
try: DATA_DIR.mkdir(parents=True, exist_ok=True)
except Exception: DATA_DIR = BASE_DIR
UPDATE_FLAG = DATA_DIR / "update_attempt.txt"   # целевая версия попытки апдейта (для проверки, применился ли он)

STATE_FILE  = DATA_DIR / "games_state.json"
CACHE_FILE  = DATA_DIR / "catalog_cache.json"
CONFIG_FILE = DATA_DIR / "launcher_config.json"

def _migrate_from_basedir(*names):
    """Переносит старые файлы, лежавшие рядом с .exe, в DATA_DIR (один раз)."""
    import shutil
    for n in names:
        old, new = BASE_DIR / n, DATA_DIR / n
        try:
            if old.exists() and not new.exists():
                shutil.copy2(old, new)
        except Exception: pass

_migrate_from_basedir("games_state.json", "catalog_cache.json",
                      "launcher_config.json", "auth_token.json", "device_id.txt")

DEFAULT_GAMES_DIR = Path("C:/Games")

def game_folder(game):
    """Имя папки игры на диске — по названию, с большой буквы, без пробелов."""
    name = (game.get('name') or game.get('id') or 'Game').strip()
    return name.replace(' ', '') or game.get('id', 'Game')

def ensure_dir_case(desired):
    """Привести регистр существующей папки к desired (Windows, регистр в путях не различается)."""
    try:
        desired = Path(desired)
        parent  = desired.parent
        if not parent.exists():
            return
        target = desired.name
        for entry in os.scandir(parent):
            if (entry.is_dir() and entry.name != target
                    and entry.name.lower() == target.lower()):
                src = parent / entry.name
                tmp = parent / (target + "_casetmp")
                try:
                    os.rename(src, tmp)   # двухшаговое переименование для смены регистра
                    os.rename(tmp, desired)
                except Exception:
                    try:
                        if tmp.exists() and not desired.exists():
                            os.rename(tmp, desired)
                    except Exception: pass
                break
    except Exception: pass

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
ensure_dir_case(GAMES_DIR)               # привести "games" -> "Games", если уже есть
GAMES_DIR.mkdir(parents=True, exist_ok=True)

# ── Локализация (RU/EN) ──────────────────────────────────
LANG = {
  "ru": {
    "my_access":"🎟 Мои доступы","games_folder":"Папка игр",
    "account_as":"👤 {name}","btn_login":"🔑 Войти","btn_logout":"🚪 Выйти","btn_switch_acc":"🔁 Сменить аккаунт",
    "btn_refresh_sub":"🔄 Обновить подписку","sub_refreshed":"Подписка обновлена: {tier}",
    "logged_out":"Вы вышли из аккаунта","not_logged_in":"Вход не выполнен",
    "guide":"📖 Инструкция","guide_window":"Инструкция","close":"Закрыть",
    "folder_changed":"Папка изменена","checking_auth":"Проверка входа...",
    "sign_in_to_play":"Войдите, чтобы играть","welcome":"Добро пожаловать, {name}!",
    "loading_catalog":"Загрузка каталога...","games_count":"{n} игр",
    "offline_cache":"Офлайн (кэш)","load_error":"Ошибка загрузки","no_connection":"Нет соединения",
    "file_not_found":"Файл не найден — переустановите игру","url_missing":"URL не указан в каталоге",
    "uninstalled":"{name} удалена","uninstall_error":"Ошибка удаления: {e}",
    "launched":"Запущено: {name}","close_before_update":"Закройте {name} перед обновлением",
    "installed_ok":"{name} установлена ✓","updated_ok":"{name} обновлена ✓","download_error":"Ошибка загрузки: {e}",
    "card_installed":"✓ установлена","card_play":"▶   Играть","card_update_tag":"обновление",
    "launching":"Запуск…","changelog_title":"Что нового","searching_games":"Поиск доступных игр…",
    "badge_early":"🌱 Ранний доступ","sub_title":"Подписка","sub_patreon":"Открыть Patreon",
    "ea_card":"🌱 Для Pro через {days} дн. · {date}",
    "ea_lock":"🌱 «{name}» выйдет из раннего доступа через {days} дн. — {date}.\nДо этого вход только по Pro Max или по коду.",
    "sub_body":"🎮 Доступ к играм — по подписке на Patreon.\n\n⭐ Pro — все обычные игры.\n👑 Pro Max — ВСЕ игры, включая ранний доступ.\n\n🌱 Ранний доступ: новые игры первые 14 дней доступны только по Pro Max, затем выходят из раннего доступа и открываются и для Pro.\n\nОформить или повысить подписку можно на Patreon.",
    "card_update":"🔄   Обновить","card_download":"⬇   Скачать","card_uninstall":"🗑  Удалить",
    "card_downloading":"Скачивание...","no_games":"Игр не найдено",
    "upd_available":"🔄  Доступно обновление","upd_new_version":"Новая версия v{v}",
    "upd_later":"Позже","upd_now":"Обновить сейчас","upd_no_link":"Нет ссылки на обновление",
    "upd_only_exe":"Автообновление работает только в собранном .exe","upd_downloading":"Скачивание обновления...",
    "upd_extracting":"Распаковка...","upd_restarting":"Перезапуск...",
    "upd_restarting_admin":"Перезапуск (подтвердите права администратора)...","upd_error":"Ошибка: {e}",
    "ma_title":"🎟  Мои доступы","ma_subtitle":"Подписка, покупки и коды на этом компьютере",
    "ma_loading":"Загрузка...","ma_fail":"Не удалось загрузить доступы","ma_none":"Активных доступов нет",
    "ma_sec_sub":"Подписка Patreon","ma_sec_buy":"Покупки (бессрочно)","ma_sec_codes":"Коды на этом компьютере",
    "ma_sub_active":"Подписка активна","ma_sub_inactive":"Подписка неактивна","ma_forever":"Доступ навсегда",
    "ma_all_games":"Все игры","ma_until":"{code} · до {when} (≈{days} дн.)",
    "ma_expired":"{code} · истёк","ma_permanent":"{code} · бессрочный",
    "tier_basic":"Basic","tier_pro":"Pro","tier_pro_max":"Pro Max","tier_buyer":"Покупатель","tier_guest":"Гость","tier_none":"Без подписки",
    "del_title":"🗑  Удалить {name}?","del_body":"Файлы игры будут удалены.\nЕё можно будет скачать снова.",
    "del_cancel":"Отмена","del_confirm":"🗑  Удалить",
    "login_window":"Вход","login_sub":"Нужна подписка Patreon","login_signin":"🔑  Войти через Patreon",
    "login_no_sub":"Ещё нет подписки?","login_subscribe":"❤  Оформить на Patreon","or":"  или  ",
    "enter_code":"🎟  Ввести код доступа","already_bought":"Уже купили {name} на Patreon?",
    "activate_game":"🔑  Активировать {name}","login_opening":"Открываю браузер...",
    "login_waiting":"Ожидание входа в браузере...","login_not_done":"❌ Вход не завершён. Попробуйте снова.",
    "code_enter_one":"❌ Введите код","code_verifying":"Проверка кода...","conn_error":"❌ Ошибка соединения",
    "code_invalid":"❌ Неверный код","code_expired_msg":"❌ Код истёк","code_limit":"❌ Достигнут лимит использований кода",
    "act_window":"Активация игры","act_no_access":"У вас нет доступа к этой игре.",
    "act_buy":"❤  Купить на Patreon","act_activate":"🔑  Активировать (уже куплено)",
    "act_opening":"Открываю браузер...","act_waiting":"Ожидание браузера...","act_not_done":"❌ Не завершено. Попробуйте снова.",
  },
  "en": {
    "my_access":"🎟 My access","games_folder":"Games folder",
    "account_as":"👤 {name}","btn_login":"🔑 Sign in","btn_logout":"🚪 Log out","btn_switch_acc":"🔁 Switch account",
    "btn_refresh_sub":"🔄 Refresh subscription","sub_refreshed":"Subscription updated: {tier}",
    "logged_out":"Logged out","not_logged_in":"Not signed in",
    "guide":"📖 Guide","guide_window":"Guide","close":"Close",
    "folder_changed":"Folder changed","checking_auth":"Checking auth...",
    "sign_in_to_play":"Sign in to play","welcome":"Welcome, {name}!",
    "loading_catalog":"Loading catalog...","games_count":"{n} games",
    "offline_cache":"Offline (cache)","load_error":"Load error","no_connection":"No connection",
    "file_not_found":"File not found — reinstall the game","url_missing":"URL not specified in catalog",
    "uninstalled":"{name} uninstalled","uninstall_error":"Uninstall error: {e}",
    "launched":"Launched: {name}","close_before_update":"Close {name} before updating",
    "installed_ok":"{name} installed ✓","updated_ok":"{name} updated ✓","download_error":"Download error: {e}",
    "card_installed":"✓ installed","card_play":"▶   Play","card_update_tag":"update",
    "launching":"Launching…","changelog_title":"What's new","searching_games":"Searching for games…",
    "badge_early":"🌱 Early access","sub_title":"Subscription","sub_patreon":"Open Patreon",
    "ea_card":"🌱 Pro in {days}d · {date}",
    "ea_lock":"🌱 \"{name}\" leaves early access in {days} days — {date}.\nUntil then it's Pro Max (or code) only.",
    "sub_body":"🎮 Game access is via a Patreon subscription.\n\n⭐ Pro — all regular games.\n👑 Pro Max — ALL games, including early access.\n\n🌱 Early access: new games are Pro Max-only for the first 14 days, then leave early access and become available to Pro too.\n\nSubscribe or upgrade on Patreon.",
    "card_update":"🔄   Update","card_download":"⬇   Download","card_uninstall":"🗑  Uninstall",
    "card_downloading":"Downloading...","no_games":"No games found",
    "upd_available":"🔄  Update available","upd_new_version":"New version v{v}",
    "upd_later":"Later","upd_now":"Update now","upd_no_link":"No update link",
    "upd_only_exe":"Auto-update works only in the built .exe","upd_downloading":"Downloading update...",
    "upd_extracting":"Extracting...","upd_restarting":"Restarting...",
    "upd_restarting_admin":"Restarting (confirm administrator rights)...","upd_error":"Error: {e}",
    "ma_title":"🎟  My access","ma_subtitle":"Subscription, purchases and codes on this computer",
    "ma_loading":"Loading...","ma_fail":"Failed to load access","ma_none":"No active access",
    "ma_sec_sub":"Patreon subscription","ma_sec_buy":"Purchases (permanent)","ma_sec_codes":"Codes on this computer",
    "ma_sub_active":"Subscription active","ma_sub_inactive":"Subscription inactive","ma_forever":"Permanent access",
    "ma_all_games":"All games","ma_until":"{code} · until {when} (≈{days} d.)",
    "ma_expired":"{code} · expired","ma_permanent":"{code} · permanent",
    "tier_basic":"Basic","tier_pro":"Pro","tier_pro_max":"Pro Max","tier_buyer":"Buyer","tier_guest":"Guest","tier_none":"No subscription",
    "del_title":"🗑  Delete {name}?","del_body":"Game files will be deleted.\nYou can download it again.",
    "del_cancel":"Cancel","del_confirm":"🗑  Delete",
    "login_window":"Sign in","login_sub":"Patreon subscription required","login_signin":"🔑  Sign in with Patreon",
    "login_no_sub":"No subscription yet?","login_subscribe":"❤  Subscribe on Patreon","or":"  or  ",
    "enter_code":"🎟  Enter access code","already_bought":"Already bought {name} on Patreon?",
    "activate_game":"🔑  Activate {name}","login_opening":"Opening browser...",
    "login_waiting":"Waiting for browser sign-in...","login_not_done":"❌ Sign-in not completed. Try again.",
    "code_enter_one":"❌ Enter a code","code_verifying":"Verifying code...","conn_error":"❌ Connection error",
    "code_invalid":"❌ Invalid code","code_expired_msg":"❌ Code has expired","code_limit":"❌ Code usage limit reached",
    "act_window":"Activate game","act_no_access":"You don't have access to this game.",
    "act_buy":"❤  Buy on Patreon","act_activate":"🔑  Activate (already bought)",
    "act_opening":"Opening browser...","act_waiting":"Waiting for browser...","act_not_done":"❌ Not completed. Try again.",
  },
}
_lang = _config.get("lang", "ru")
if _lang not in LANG: _lang = "ru"

def tr(key, **kw):
    s = LANG.get(_lang, LANG["ru"]).get(key, LANG["ru"].get(key, key))
    try: return s.format(**kw) if kw else s
    except Exception: return s

def set_app_lang(l):
    global _lang
    _lang = l if l in LANG else "ru"
    _config["lang"] = _lang
    save_config(_config)

# ── Auth ──────────────────────────────────────────────────
TOKEN_FILE = DATA_DIR / "auth_token.json"

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
    _id_file = DATA_DIR / "device_id.txt"
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
        r = _ur.urlopen(req, timeout=10, context=SSL_CTX)
        return json.loads(r.read())
    except Exception as e:
        # 401 = сервер реально отверг токен (недействителен/нет подписки) → разлогин.
        # Прочие ошибки (нет сети, таймаут) → не трогаем сохранённый вход.
        if getattr(e, "code", None) == 401:
            return {"ok": False, "auth_failed": True, "error": "unauthorized"}
        return {"ok": False, "network": True, "error": str(e)}

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
        r = _ur.urlopen(url, timeout=6, context=SSL_CTX)
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
            s_text, s_col = f"v{inst_ver}  {tr('card_installed')}", COLORS["green"]
            btn_text, btn_col = tr('card_play'), COLORS["btn_play"]
        elif inst_ver:
            s_text, s_col = f"v{inst_ver} → v{new_ver}  {tr('card_update_tag')}", COLORS["orange"]
            btn_text, btn_col = tr('card_update'), COLORS["btn_upd"]
        else:
            size = self.game.get('size_mb', '?')
            s_text, s_col = f"v{new_ver}  •  {size} MB", COLORS["gray"]
            btn_text, btn_col = tr('card_download'), COLORS["btn_dl"]

        ctk.CTkLabel(self, text=s_text,
                     font=ctk.CTkFont(size=11),
                     text_color=s_col).pack(pady=(3, 0))

        desc = self.game.get('description', '')
        if desc:
            ctk.CTkLabel(self, text=desc,
                         font=ctk.CTkFont(size=11),
                         text_color="#888899",
                         wraplength=170).pack(pady=(4, 0))

        # Отсчёт до выхода из раннего доступа (виден всем)
        _ea, _ea_days = early_access_info(self.game)
        if _ea:
            _ea_end = early_access_end_date(self.game)
            _ea_when = _ea_end.strftime('%d.%m') if _ea_end else '—'
            ctk.CTkLabel(self, text=tr('ea_card', days=max(1, _ea_days), date=_ea_when),
                         font=ctk.CTkFont(size=10, weight="bold"),
                         text_color=BADGE_EARLY,
                         wraplength=170).pack(pady=(3, 0))

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

        # Кнопка инструкции (если в каталоге есть guide)
        if self.game.get('guide'):
            ctk.CTkButton(
                self, text=tr('guide'), width=170, height=24,
                fg_color="transparent", hover_color="#1a1a2e",
                border_width=1, border_color="#33335a",
                corner_radius=8, font=ctk.CTkFont(size=11),
                text_color="#9999bb",
                command=lambda: self.on_action(self.game, guide=True)
            ).pack(pady=(0, 4))

        # Кнопка удаления (только если установлена)
        if inst_ver:
            self.del_btn = ctk.CTkButton(
                self, text=tr('card_uninstall'), width=170, height=26,
                fg_color="transparent", hover_color="#3a1a1a",
                border_width=1, border_color="#552222",
                corner_radius=8, font=ctk.CTkFont(size=11),
                text_color="#994444",
                command=lambda: self.on_action(self.game, delete=True)
            )
            self.del_btn.pack(pady=(0, 14))
        else:
            ctk.CTkFrame(self, fg_color="transparent", height=14).pack()

        self._build_badges()

    def _chip(self, parent, text, bg, fg):
        c = ctk.CTkLabel(parent, text=f" {text} ", fg_color=bg, text_color=fg,
                         corner_radius=5, height=14,
                         font=ctk.CTkFont(size=8, weight="bold"))
        c.bind("<Button-1>", lambda e: show_subscription_info(self, self.game))
        c.configure(cursor="hand2")
        return c

    def _build_badges(self):
        early, _days = early_access_info(self.game)
        if early:
            f_tl = ctk.CTkFrame(self, fg_color="transparent"); f_tl.place(x=8, y=8, anchor="nw")
            self._chip(f_tl, tr('badge_early'), BADGE_EARLY, "#ffffff").pack()
            f_tr = ctk.CTkFrame(self, fg_color="transparent"); f_tr.place(relx=1.0, x=-8, y=8, anchor="ne")
            self._chip(f_tr, "PRO MAX", BADGE_PROMAX, "#1a1a2a").pack()
        else:
            f_tr = ctk.CTkFrame(self, fg_color="transparent"); f_tr.place(relx=1.0, x=-8, y=8, anchor="ne")
            self._chip(f_tr, "PRO MAX", BADGE_PROMAX, "#1a1a2a").pack(anchor="e")
            self._chip(f_tr, "PRO", BADGE_PRO, "#ffffff").pack(anchor="e", pady=(3, 0))

    def show_progress(self, value, text=""):
        self._stop_spin()                       # прогресс пошёл — гасим спиннер ожидания
        self._prog_frame.pack(pady=(8, 0), padx=16, fill="x")
        self.progress.pack(fill="x")
        self.prog_lbl.configure(text=text)
        self.prog_lbl.pack()
        self.progress.set(value)
        self.btn.configure(state="disabled", text=tr('card_downloading'))

    def done_progress(self):
        self._stop_spin()
        self._prog_frame.pack_forget()
        self.btn.configure(state="normal")

    # ── Спиннер на кнопке (ожидание: запуск игры / подключение к серверу) ──
    _SPIN_FRAMES = ["◐", "◓", "◑", "◒"]
    def _start_spin(self, label):
        self._spin_i = 0
        self._spin_text = label
        try: self.btn.configure(state="disabled")
        except Exception: pass
        self._spin_anim()
    def _spin_anim(self):
        try:
            f = self._SPIN_FRAMES[self._spin_i % len(self._SPIN_FRAMES)]
            self._spin_i += 1
            self.btn.configure(text=f"{f}  {self._spin_text}")
            self._spin_job = self.after(120, self._spin_anim)
        except Exception:
            pass
    def _stop_spin(self):
        try: self.after_cancel(self._spin_job)
        except Exception: pass
        self._spin_job = None
    # анимация ожидания запуска игры
    def show_launching(self, duration=9000):
        self._start_spin(tr('launching'))
        try: self.after(duration, self.stop_launching)
        except Exception: pass
    def stop_launching(self):
        self._stop_spin()
        try: self.btn.configure(state="normal", text=tr('card_play'))
        except Exception: pass
    # анимация сразу по клику «Скачать» — пока идёт запрос ссылки/подключение к серверу
    def show_connecting(self):
        self._start_spin(tr('card_downloading'))


def _brighten(hex_col):
    """Чуть осветлить цвет для hover."""
    try:
        h = hex_col.lstrip('#')
        r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
        r,g,b = min(255,r+30), min(255,g+30), min(255,b+30)
        return f"#{r:02x}{g:02x}{b:02x}"
    except: return hex_col


# ── Подписки / ранний доступ ──
BADGE_PRO    = "#3a7bd5"
BADGE_PROMAX = "#e6b422"
BADGE_EARLY  = "#e0712a"

def early_access_info(game):
    """(is_early, days_left) — игра в раннем доступе, если released + early_access_days ещё не прошли."""
    rel = game.get('released')
    days = int(game.get('early_access_days', 14) or 14)
    if not rel: return (False, 0)
    try:
        d = date.fromisoformat(str(rel)[:10])
    except Exception:
        return (False, 0)
    end = d + timedelta(days=days)
    today = date.today()
    return (True, (end - today).days) if today < end else (False, 0)

def early_access_end_date(game):
    """Дата выхода из раннего доступа (date) или None."""
    rel = game.get('released')
    days = int(game.get('early_access_days', 14) or 14)
    if not rel: return None
    try:
        return date.fromisoformat(str(rel)[:10]) + timedelta(days=days)
    except Exception:
        return None

def show_subscription_info(master, game=None):
    win = ctk.CTkToplevel(master)
    win.title(tr('sub_title'))
    _has_guide = bool(game and game.get('guide') and hasattr(master, '_show_guide'))
    win.geometry("450x520" if _has_guide else ("450x470" if game else "450x430"))
    win.resizable(False, False)
    win.configure(fg_color=COLORS["bg"])
    try: win.after(60, lambda: (win.lift(), win.attributes("-topmost", True)))
    except Exception: pass
    ctk.CTkLabel(win, text="💎 " + tr('sub_title'),
                 font=ctk.CTkFont(size=20, weight="bold"),
                 text_color=COLORS["accent"]).pack(pady=(20, 4))

    # Точный срок выхода игры из раннего доступа (вариант 3)
    if game:
        _ea, _ea_days = early_access_info(game)
        if _ea:
            _end = early_access_end_date(game)
            _when = _end.strftime('%d.%m.%Y') if _end else '—'
            ctk.CTkLabel(win, text=tr('ea_lock', name=game.get('name', ''),
                                      days=max(1, _ea_days), date=_when),
                         font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=BADGE_EARLY, justify="left",
                         wraplength=410).pack(padx=18, pady=(2, 6))
    box = ctk.CTkTextbox(win, width=410, height=270, fg_color="#16162a",
                         font=ctk.CTkFont(size=12), wrap="word")
    box.pack(padx=18, pady=10, fill="both", expand=True)
    box.insert("1.0", tr('sub_body'))
    box.configure(state="disabled")
    ctk.CTkButton(win, text="🟠 " + tr('sub_patreon'), height=40,
                  fg_color="#e0712a", hover_color=_brighten("#e0712a"),
                  corner_radius=10, font=ctk.CTkFont(size=13, weight="bold"),
                  command=lambda: webbrowser.open(PATREON_URL)).pack(pady=(0, 8))
    # Инструкция к игре доступна прямо отсюда, даже без доступа к игре
    if _has_guide:
        ctk.CTkButton(win, text="📖 " + tr('guide'), width=200, height=34,
                      fg_color="transparent", hover_color="#1a1a2e",
                      border_width=1, border_color="#33335a",
                      corner_radius=10, font=ctk.CTkFont(size=12),
                      text_color="#9999bb",
                      command=lambda: master._show_guide(game)).pack(pady=(0, 8))
    ctk.CTkButton(win, text="OK", width=120, fg_color=COLORS["btn_play"],
                  hover_color=_brighten(COLORS["btn_play"]), corner_radius=10,
                  command=win.destroy).pack(pady=(0, 14))


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

        # Текущий аккаунт (обновляется в _update_account_ui)
        self.account_lbl = ctk.CTkLabel(hdr, text="",
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["gray"])
        self.account_lbl.pack(side="left", padx=(0, 8))

        self.lang_btn = ctk.CTkButton(
            hdr, text=f"🌐 {_lang.upper()}", width=58, height=32,
            fg_color="transparent", hover_color="#222244",
            corner_radius=8, font=ctk.CTkFont(size=12),
            command=self._toggle_lang
        )
        self.lang_btn.pack(side="right", padx=4)

        ctk.CTkButton(
            hdr, text="❤  Patreon", width=100, height=32,
            fg_color="#FF424D", hover_color="#cc2f38",
            corner_radius=8, font=ctk.CTkFont(size=12, weight="bold"),
            text_color="white",
            command=lambda: webbrowser.open(PATREON_URL)
        ).pack(side="right", padx=(8, 4))

        self.mycodes_btn = ctk.CTkButton(
            hdr, text=tr('my_access'), width=130, height=32,
            fg_color="#2a2a44", hover_color="#3a3a5a",
            corner_radius=8, font=ctk.CTkFont(size=12),
            command=self._show_my_codes
        )
        self.mycodes_btn.pack(side="right", padx=(8, 4))

        # Кнопка входа — видна, когда вход не выполнен.
        # Управление аккаунтом (Выйти / Обновить подписку) — в окне «Мои доступы».
        self.login_btn = ctk.CTkButton(
            hdr, text=tr('btn_login'), width=110, height=32,
            fg_color=COLORS["btn_play"], hover_color=_brighten(COLORS["btn_play"]),
            corner_radius=8, font=ctk.CTkFont(size=12, weight="bold"),
            text_color="white", command=lambda: self._show_login_screen())

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

        self._update_account_ui()

    # ── Выбор папки ─────────────────────────────────────
    def _choose_games_dir(self):
        global GAMES_DIR
        chosen = filedialog.askdirectory(
            title=tr('games_folder'),
            initialdir=str(GAMES_DIR)
        )
        if not chosen:
            return
        GAMES_DIR = Path(chosen)
        GAMES_DIR.mkdir(parents=True, exist_ok=True)
        _config["games_dir"] = str(GAMES_DIR)
        save_config(_config)
        self.dir_lbl.configure(text=str(GAMES_DIR))
        self._status('folder_changed')

    # ── Запуск ───────────────────────────────────────────
    def _has_game_access(self, game):
        """Доступ: pro_max → все; pro → всё кроме раннего доступа; купленная/по коду игра → эта игра.
        Коды устройства складываются с подпиской."""
        tier  = self._auth.get("tier", "")
        owned = self._auth.get("games", [])
        dev   = self._auth.get("device_games", [])
        gid   = game["id"]
        if gid in owned or gid in dev or "all" in dev:   # покупка / код на эту игру / код «все игры»
            return True
        if tier == "pro_max":
            return True
        if tier == "pro":
            early, _ = early_access_info(game)
            return not early             # pro — всё, кроме раннего доступа (нужен Pro Max)
        return False                     # без подписки и без кода на эту игру

    def _startup(self):
        self.after(0, self._show_loading)   # бегущая полоса, пока ищем игры
        self._check_update_result()     # применилось ли прошлое обновление?
        self._check_launcher_update()   # проверяем обновление лаунчера всегда при запуске
        self._status('checking_auth')
        token = self._auth.get("token")

        # Проверяем тариф ПРИ КАЖДОМ открытии — сервер перечитывает подписку с Patreon
        # (апгрейд/смена тарифа применяются без перелогина).
        if token:
            result = verify_token(token)
            if result.get("ok"):
                self._auth["last_verify"] = time.time()
                self._auth["name"]  = result.get("name", "")
                self._auth["email"] = result.get("email", self._auth.get("email", ""))
                self._auth["games"] = result.get("games", [])
                if result.get("tier"): self._auth["tier"] = result.get("tier")
                save_auth(self._auth)
                self._logged_in = True
                self._after_login()
                return
            elif result.get("auth_failed"):
                clear_auth()            # токен реально недействителен → разлогин
                self._auth = {}
            else:
                # Нет сети — работаем оффлайн с сохранённым входом, не разлогиниваем
                self._logged_in = True
                self._after_login()
                return

        # Нет токена — загружаем каталог, но без возможности играть
        self._status('sign_in_to_play')
        self._load_catalog()

    def _after_login(self):
        self._logged_in = True
        dg = self._fetch_device_codes()           # коды устройства складываются с подпиской
        if dg is not None:
            self._auth["device_games"] = dg
            save_auth(self._auth)
        name = self._auth.get("name", "")
        self.after(0, self._update_account_ui)
        self._status('welcome', name=name) if name else self._status(None)
        self._load_catalog()

    # ── Аккаунт: отображение, выход, быстрое обновление подписки ──
    def _tier_label(self, tier):
        return {"basic": tr('tier_basic'), "pro": tr('tier_pro'), "pro_max": tr('tier_pro_max'),
                "buyer": tr('tier_buyer'), "guest": tr('tier_guest'),
                "none": tr('tier_none')}.get(tier, tier or "")

    def _update_account_ui(self):
        lbl = getattr(self, 'account_lbl', None)
        if lbl is None:
            return
        logged = self._logged_in and self._auth.get("token")
        if logged:
            name = self._auth.get("name") or "—"
            tier = self._tier_label(self._auth.get("tier", ""))
            txt  = tr('account_as', name=name) + (f" · {tier}" if tier else "")
            lbl.configure(text=txt, text_color=COLORS["accent"])
            try: self.login_btn.pack_forget()
            except Exception: pass
        else:
            lbl.configure(text=tr('not_logged_in'), text_color=COLORS["gray"])
            try: self.login_btn.pack(side="right", padx=4)
            except Exception: pass

    def _logout(self):
        clear_auth()
        self._auth = {}
        self._logged_in = False
        self._catalog = self._catalog or []
        self._update_account_ui()
        try: self._render()
        except Exception: pass
        self._status('logged_out')
        self._show_login_screen()

    def _refresh_subscription(self):
        """Быстрая проверка актуальной подписки без перелогина (перечитывает тариф с сервера)."""
        def work():
            token = self._auth.get("token")
            if not token:
                self.after(0, self._show_login_screen)
                return
            self.after(0, lambda: self._status('checking_auth'))
            result = verify_token(token)
            if result.get("ok"):
                if result.get("tier"): self._auth["tier"] = result.get("tier")
                self._auth["name"]  = result.get("name", self._auth.get("name", ""))
                self._auth["email"] = result.get("email", self._auth.get("email", ""))
                self._auth["games"] = result.get("games", self._auth.get("games", []))
                self._auth["last_verify"] = time.time()
                save_auth(self._auth)
                self.after(0, self._update_account_ui)
                self.after(0, self._render)
                self.after(0, lambda: self._status('sub_refreshed',
                                                   tier=self._tier_label(self._auth.get("tier", ""))))
            elif result.get("auth_failed"):
                self.after(0, self._logout)
            else:
                self.after(0, lambda: self._status('no_connection'))
        threading.Thread(target=work, daemon=True).start()

    def _fetch_device_codes(self):
        """Игры, выданные действующими кодами на ЭТОМ устройстве. None — если сеть недоступна."""
        try:
            payload = json.dumps({"device_id": DEVICE_ID}).encode()
            req = _ur.Request(f"{AUTH_SERVER}/auth/my_codes", data=payload,
                              headers={"Content-Type": "application/json",
                                       "User-Agent": "FlagRaceLauncher/1.0"})
            r = _ur.urlopen(req, timeout=12, context=SSL_CTX)
            data = json.loads(r.read())
            now = time.time(); games = []
            for c in data.get("codes", []):
                exp = c.get("expires_at")
                if exp and now > exp:
                    continue
                gid = c.get("game_id")
                if gid and gid not in games:
                    games.append(gid)
            return games
        except Exception:
            return None

    def _check_update_result(self):
        """Если в прошлый раз пытались обновиться, но версия не поднялась —
        новые файлы не записались (антивирус/защита папок/OneDrive). Показываем переустановку."""
        self._update_failed = False
        try:
            if not UPDATE_FLAG.exists(): return
            target = UPDATE_FLAG.read_text(encoding="utf-8").strip()
            UPDATE_FLAG.unlink()
            if target and _ver_tuple(target) > _ver_tuple(LAUNCHER_VERSION):
                self._update_failed = True
                self.after(500, self._show_reinstall_dialog)
        except Exception:
            pass

    def _show_reinstall_dialog(self):
        ru = _lang != 'en'
        win = ctk.CTkToplevel(self)
        win.title("Обновление" if ru else "Update")
        win.geometry("460x300"); win.resizable(False, False)
        win.configure(fg_color=COLORS["bg"])
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        self._bring_to_front(win)
        ctk.CTkLabel(win, text=("⚠ Обновление не применилось" if ru else "⚠ Update didn't apply"),
                     font=ctk.CTkFont(size=18, weight="bold"), text_color=COLORS["accent"]).pack(pady=(24, 8))
        msg = ("Новые файлы не удалось записать — обычно мешают антивирус,\n«Контролируемый доступ к папкам» Windows или OneDrive.\n\nПереустанови лаунчер установщиком — игры и вход сохранятся."
               if ru else
               "The new files couldn't be written — usually blocked by antivirus,\nWindows Controlled Folder Access or OneDrive.\n\nReinstall via the installer — your games and login are kept.")
        ctk.CTkLabel(win, text=msg, font=ctk.CTkFont(size=12), text_color=COLORS["gray"], justify="center").pack(pady=(0, 6), padx=20)
        btns = ctk.CTkFrame(win, fg_color="transparent"); btns.pack(pady=(14, 0))
        ctk.CTkButton(btns, text=("Закрыть" if ru else "Close"), width=110, height=38,
                      fg_color="#33334d", hover_color="#44445d", command=win.destroy).grid(row=0, column=0, padx=6)
        ctk.CTkButton(btns, text=("⬇ Скачать установщик" if ru else "⬇ Download installer"), width=210, height=38,
                      fg_color=COLORS["btn_play"], hover_color=_brighten(COLORS["btn_play"]),
                      font=ctk.CTkFont(weight="bold"),
                      command=lambda: (webbrowser.open(INSTALLER_URL), win.destroy())).grid(row=0, column=1, padx=6)

    def _check_launcher_update(self):
        if getattr(self, '_update_failed', False): return   # уже показали окно переустановки
        data = fetch_json(VERSION_URL)
        if not data: return
        if _ver_tuple(data.get('version', '0')) > _ver_tuple(LAUNCHER_VERSION):
            self.after(0, lambda: self._prompt_launcher_update(data))

    def _prompt_launcher_update(self, data):
        """Окно с предложением обновить лаунчер."""
        win = ctk.CTkToplevel(self)
        win.title("Обновление лаунчера")
        win.geometry("400x320")
        win.resizable(False, False)
        win.configure(fg_color=COLORS["bg"])
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        self._bring_to_front(win)

        ctk.CTkLabel(win, text=tr('upd_available'),
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=COLORS["accent"]).pack(pady=(24, 4))
        ctk.CTkLabel(win, text=tr('upd_new_version', v=data.get('version','')),
                     font=ctk.CTkFont(size=13),
                     text_color=COLORS["gray"]).pack()
        cl = data.get('changelog', '')
        if cl:
            # Прокручиваемая область фикс. высоты — длинный changelog не выталкивает кнопки
            clbox = ctk.CTkTextbox(win, width=350, height=96, fg_color="#16162a",
                                   font=ctk.CTkFont(size=11), wrap="word")
            clbox.pack(pady=(8, 0), padx=20)
            clbox.insert("1.0", cl)
            clbox.configure(state="disabled")

        self._upd_status = ctk.CTkLabel(win, text="", font=ctk.CTkFont(size=11),
                                        text_color=COLORS["orange"])
        self._upd_status.pack(pady=(8, 0))

        self._upd_bar = ctk.CTkProgressBar(win, width=320, height=8, corner_radius=4)
        self._upd_bar.set(0)
        self._upd_bar.pack(pady=(6, 0))
        self._upd_bar.pack_forget()   # показываем только во время загрузки

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(pady=(16, 0))
        ctk.CTkButton(btns, text=tr('upd_later'), width=110, height=36,
                      fg_color="#33334d", hover_color="#44445d",
                      command=win.destroy).grid(row=0, column=0, padx=6)
        ctk.CTkButton(btns, text=tr('upd_now'), width=160, height=36,
                      fg_color=COLORS["btn_play"],
                      hover_color=_brighten(COLORS["btn_play"]),
                      font=ctk.CTkFont(weight="bold"),
                      command=lambda: threading.Thread(
                          target=self._do_launcher_update,
                          args=(data, win), daemon=True).start()
                      ).grid(row=0, column=1, padx=6)

    def _upd_progress(self, pct, text):
        """Обновляет прогресс-бар и текст в окне обновления лаунчера."""
        def apply():
            try:
                self._upd_status.configure(text=text)
                if not self._upd_bar.winfo_ismapped():
                    self._upd_bar.pack(pady=(6, 0))
                self._upd_bar.set(max(0.0, min(1.0, pct)))
            except Exception: pass
        self.after(0, apply)

    def _do_launcher_update(self, data, win=None):
        """Скачивает zip новой версии (onedir) и заменяет папку лаунчера через bat."""
        import shutil
        def status(t):
            try: self.after(0, lambda: self._upd_status.configure(text=t))
            except Exception: pass

        url = data.get('download_url', '')
        if not url:
            status(tr('upd_no_link')); return
        if not getattr(sys, 'frozen', False):
            status(tr('upd_only_exe')); return

        try:
            install_dir = Path(sys.executable).parent   # папка с Launcher.exe и _internal
            exe_name    = Path(sys.executable).name
            work        = DATA_DIR / "update"
            try: shutil.rmtree(work)
            except Exception: pass
            work.mkdir(parents=True, exist_ok=True)
            zip_path = work / "launcher.zip"

            status(tr('upd_downloading'))
            req = _ur.Request(url, headers={"User-Agent": "Launcher"})
            with _ur.urlopen(req, timeout=300, context=SSL_CTX) as r, open(zip_path, "wb") as f:
                total = int(r.getheader("Content-Length") or 0)
                done = 0; chunk = 65536; t0 = time.time(); last = 0.0
                while True:
                    buf = r.read(chunk)
                    if not buf: break
                    f.write(buf); done += len(buf)
                    now = time.time()
                    if now - last >= 0.2:
                        last = now
                        spd = done / (now - t0) / 1048576 if now > t0 else 0
                        d_mb = done / 1048576
                        if total > 0:
                            t_mb = total / 1048576
                            self._upd_progress(done / total,
                                f"{d_mb:.1f} / {t_mb:.1f} MB · {spd:.1f} MB/s")
                        else:
                            self._upd_progress(0, f"{d_mb:.1f} MB · {spd:.1f} MB/s")
                if total > 0:
                    self._upd_progress(1.0, f"{total/1048576:.1f} / {total/1048576:.1f} MB")

            status(tr('upd_extracting'))
            extract_dir = work / "files"
            with zipfile.ZipFile(zip_path, 'r') as z:
                if z.testzip() is not None:
                    raise IOError("архив повреждён")
                z.extractall(extract_dir)

            # внутри архива папка с exe — находим её
            found = list(extract_dir.rglob(exe_name))
            if not found:
                raise IOError(f"{exe_name} не найден в архиве")
            new_root = found[0].parent

            # bat (вне рабочей папки, чтобы можно было её удалить):
            # ждёт закрытия лаунчера → копирует новые файлы поверх папки → перезапуск
            # помечаем целевую версию: при следующем старте сверим — реально ли поднялась
            try: UPDATE_FLAG.write_text(str(data.get('version','')).strip(), encoding="utf-8")
            except Exception: pass
            bat = DATA_DIR / "_update.bat"
            bat_text = (
                "@echo off\r\n"
                ":waitproc\r\n"
                f'tasklist /fi "imagename eq {exe_name}" 2>nul | find /i "{exe_name}" >nul\r\n'
                "if not errorlevel 1 (\r\n"
                "  ping -n 2 127.0.0.1 >nul\r\n"
                "  goto waitproc\r\n"
                ")\r\n"
                "ping -n 2 127.0.0.1 >nul\r\n"
                # /E все подпапки, /IS /IT перезаписать существующие, повторы при блокировке
                f'robocopy "{new_root}" "{install_dir}" /E /IS /IT /R:10 /W:2 >nul\r\n'
                f'start "" "{install_dir}\\{exe_name}"\r\n'
                f'rmdir /s /q "{work}" >nul 2>&1\r\n'
                'del "%~f0"\r\n'
            )
            bat.write_text(bat_text, encoding="utf-8")

            # Проверяем, можем ли писать в папку установки без прав администратора
            def _writable(p):
                try:
                    t = Path(p) / ".w_test"
                    t.write_text("x", encoding="utf-8"); t.unlink()
                    return True
                except Exception:
                    return False

            if _writable(install_dir):
                status(tr('upd_restarting'))
                subprocess.Popen(
                    ["cmd", "/c", str(bat)],
                    cwd=str(DATA_DIR),
                    creationflags=0x08000000  # CREATE_NO_WINDOW
                )
            else:
                # Папка защищена (например Program Files) — нужны права администратора
                status(tr('upd_restarting_admin'))
                ps_cmd = (
                    "Start-Process -FilePath 'cmd.exe' "
                    f"-ArgumentList '/c','\"{bat}\"' -Verb RunAs -WindowStyle Hidden"
                )
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-WindowStyle", "Hidden",
                     "-Command", ps_cmd],
                    creationflags=0x08000000
                )
            self.after(800, self.destroy)
        except Exception as e:
            status(tr('upd_error', e=e))

    # ── Каталог ──────────────────────────────────────────
    def _load_catalog(self):
        self._status('loading_catalog')
        data = fetch_json(CATALOG_URL)
        if data and 'games' in data:
            self._catalog = data['games']
            try: CACHE_FILE.write_text(
                    json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
            except: pass
            self._status('games_count', n=len(self._catalog))
        else:
            # Offline — use cache
            if CACHE_FILE.exists():
                try:
                    self._catalog = json.loads(
                        CACHE_FILE.read_text(encoding='utf-8')).get('games', [])
                    self._status('offline_cache')
                except: self._status('load_error')
            else:
                self._status('no_connection')
                return
        self.after(0, self._render)

    # ── Автоопределение уже скачанных игр ────────────────
    def _reconcile_disk(self):
        """Если игра скачана (папка с .exe есть), но в состоянии её нет —
        восстанавливаем запись, чтобы лаунчер видел её установленной."""
        changed = False
        for game in (self._catalog or []):
            gid = game['id']
            gdir = GAMES_DIR / game_folder(game)
            ensure_dir_case(gdir)        # привести "flagrace" -> "FlagRace", если уже есть
            if self._state.get(gid, {}).get('version'):
                continue
            if gdir.exists():
                exes = sorted(gdir.rglob("*.exe"), key=lambda p: len(p.parts))
                if exes:
                    self._state[gid] = {'version': game['version'],
                                        'exe': str(exes[0])}
                    changed = True
        if changed:
            save_state(self._state)

    # ── Экран загрузки каталога (бегущая полоса) ─────────
    def _show_loading(self):
        try:
            for w in self.scroll.winfo_children():
                w.destroy()
        except Exception:
            return
        self._cards.clear()
        box = ctk.CTkFrame(self.scroll, fg_color="transparent")
        box.pack(expand=True, pady=130)
        ctk.CTkLabel(box, text="🔍", font=ctk.CTkFont(size=42)).pack(pady=(0, 10))
        ctk.CTkLabel(box, text=tr('searching_games'),
                     font=ctk.CTkFont(size=14, weight="bold"),
                     text_color="#aaaacc").pack(pady=(0, 14))
        bar = ctk.CTkProgressBar(box, width=240, height=8, corner_radius=4,
                                 mode="indeterminate")
        bar.pack()
        bar.start()

    # ── Рендер карточек ──────────────────────────────────
    def _render(self):
        self._reconcile_disk()
        for w in self.scroll.winfo_children():
            w.destroy()
        self._cards.clear()

        if not self._catalog:
            ctk.CTkLabel(self.scroll, text=tr('no_games'),
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

    # ── Мои доступы: подписка, покупки и коды ────────────
    def _show_my_codes(self):
        win = ctk.CTkToplevel(self)
        win.title(tr('my_access'))
        win.geometry("470x548")
        win.configure(fg_color=COLORS["bg"])
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        self._bring_to_front(win)

        ctk.CTkLabel(win, text=tr('ma_title'),
                     font=ctk.CTkFont(size=18, weight="bold"),
                     text_color=COLORS["accent"]).pack(pady=(18, 2))
        ctk.CTkLabel(win, text=tr('ma_subtitle'),
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["gray"]).pack()

        # ── Текущий аккаунт + управление ──
        acc_box = ctk.CTkFrame(win, fg_color=COLORS["card"], corner_radius=10)
        acc_box.pack(fill="x", padx=14, pady=(10, 0))
        if self._logged_in and self._auth.get("token"):
            nm  = self._auth.get("name") or "—"
            em  = self._auth.get("email") or ""
            tl  = self._tier_label(self._auth.get("tier", ""))
            ctk.CTkLabel(acc_box, text=tr('account_as', name=nm) + (f" · {tl}" if tl else ""),
                         font=ctk.CTkFont(size=13, weight="bold"),
                         text_color="#e8e8f8").pack(anchor="w", padx=12, pady=(8, 4 if em else 4))
            if em:
                ctk.CTkLabel(acc_box, text=f"✉ {em}",
                             font=ctk.CTkFont(size=11), text_color=COLORS["gray"]).pack(anchor="w", padx=12, pady=(0, 2))
            ab = ctk.CTkFrame(acc_box, fg_color="transparent"); ab.pack(anchor="w", padx=10, pady=(0, 8))
            ctk.CTkButton(ab, text=tr('btn_refresh_sub'), width=180, height=30,
                          fg_color="#22335a", hover_color="#2e447a", corner_radius=8,
                          font=ctk.CTkFont(size=12),
                          command=lambda: self._refresh_subscription()).pack(side="left", padx=(2, 6))
            ctk.CTkButton(ab, text=tr('btn_switch_acc'), width=160, height=30,
                          fg_color="#3a2a2a", hover_color="#4a3434", corner_radius=8,
                          font=ctk.CTkFont(size=12),
                          command=lambda: (win.destroy(), self._logout())).pack(side="left", padx=2)
        else:
            ctk.CTkLabel(acc_box, text=tr('not_logged_in'),
                         font=ctk.CTkFont(size=13), text_color=COLORS["gray"]).pack(anchor="w", padx=12, pady=(8, 4))
            ctk.CTkButton(acc_box, text=tr('btn_login'), width=180, height=30,
                          fg_color=COLORS["btn_play"], hover_color=_brighten(COLORS["btn_play"]),
                          corner_radius=8, font=ctk.CTkFont(size=12, weight="bold"), text_color="white",
                          command=lambda: (win.destroy(), self._show_login_screen())).pack(anchor="w", padx=10, pady=(0, 8))

        # ── Ввести код доступа (внизу окна) ──
        code_box = ctk.CTkFrame(win, fg_color="transparent")
        code_box.pack(side="bottom", pady=(0, 14))
        ma_status = ctk.CTkLabel(code_box, text="", font=ctk.CTkFont(size=11), text_color=COLORS["orange"])
        ma_status.pack()
        self._code_win = win; self._code_status_lbl = ma_status
        self._code_section = ctk.CTkFrame(code_box, fg_color="transparent")
        self._code_section.pack(pady=(4, 0))
        self._code_toggle_btn = ctk.CTkButton(
            self._code_section, text=tr('enter_code'),
            width=240, height=34, fg_color="transparent", hover_color="#1a1a2e",
            border_width=1, border_color="#444466", corner_radius=10,
            font=ctk.CTkFont(size=12), text_color="#aaaacc", command=self._show_code_entry)
        self._code_toggle_btn.pack()
        self._code_entry_frame = ctk.CTkFrame(self._code_section, fg_color="transparent")
        self._code_entry = ctk.CTkEntry(
            self._code_entry_frame, placeholder_text="GAME-XXXXXX",
            width=190, height=36, font=ctk.CTkFont(size=13, family="Courier"), justify="center")
        self._code_entry.grid(row=0, column=0, padx=(0, 8))
        self._add_entry_context_menu(self._code_entry)
        self._code_entry.bind("<Return>", lambda e: threading.Thread(
            target=self._do_redeem_code, daemon=True).start())
        ctk.CTkButton(
            self._code_entry_frame, text="→", width=46, height=36,
            fg_color=COLORS["btn_play"], hover_color=_brighten(COLORS["btn_play"]),
            corner_radius=8, font=ctk.CTkFont(size=18, weight="bold"),
            command=lambda: threading.Thread(target=self._do_redeem_code, daemon=True).start()
        ).grid(row=0, column=1)

        body = ctk.CTkScrollableFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=14, pady=12)
        status = ctk.CTkLabel(body, text=tr('ma_loading'),
                              font=ctk.CTkFont(size=12),
                              text_color=COLORS["gray"])
        status.pack(pady=20)

        def load():
            try:
                payload = json.dumps({"token": self._auth.get("token", ""),
                                      "device_id": DEVICE_ID}).encode()
                req = _ur.Request(f"{AUTH_SERVER}/auth/my_access", data=payload,
                                  headers={"Content-Type": "application/json",
                                           "User-Agent": "FlagRaceLauncher/1.0"})
                data = json.loads(_ur.urlopen(req, timeout=10, context=SSL_CTX).read())
            except Exception as e:
                data = {"ok": False, "error": str(e)}
            self.after(0, lambda: render(data))

        def section(title):
            ctk.CTkLabel(body, text=title, font=ctk.CTkFont(size=12, weight="bold"),
                         text_color=COLORS["accent"]).pack(anchor="w", padx=4, pady=(10, 2))

        def item(title, sub, col):
            card = ctk.CTkFrame(body, fg_color=COLORS["card"], corner_radius=10)
            card.pack(fill="x", pady=4)
            ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=13, weight="bold"),
                         text_color="#e8e8f8").pack(anchor="w", padx=12, pady=(8, 0))
            ctk.CTkLabel(card, text=sub, font=ctk.CTkFont(size=11),
                         text_color=col).pack(anchor="w", padx=12, pady=(0, 8))

        def render(data):
            try: status.destroy()
            except Exception: pass
            if not data or not data.get("ok"):
                ctk.CTkLabel(body, text=tr('ma_fail'),
                             text_color=COLORS["orange"]).pack(pady=20)
                return

            now = time.time()
            names = {g['id']: g['name'] for g in (self._catalog or [])}
            gname = lambda gid: (names.get(gid, gid) if gid else tr('ma_all_games'))
            tier_names = {"basic": tr('tier_basic'), "pro": tr('tier_pro'), "pro_max": tr('tier_pro_max'),
                          "buyer": tr('tier_buyer'), "guest": tr('tier_guest')}
            shown = False

            # 1) Подписка Patreon
            acc = data.get("account")
            if acc and acc.get("tier") in ("basic", "pro", "pro_max"):
                shown = True
                section(tr('ma_sec_sub'))
                col = COLORS["green"] if acc.get("active") else COLORS["gray"]
                st  = tr('ma_sub_active') if acc.get("active") else tr('ma_sub_inactive')
                item(f"❤ {tier_names.get(acc['tier'], acc['tier'])}", st, col)

            # 2) Покупки (бессрочно) — лицензии не от кодов
            purchases = [l for l in data.get("licenses", [])
                         if not str(l.get("post_id", "")).startswith("code:")]
            if purchases:
                shown = True
                section(tr('ma_sec_buy'))
                for l in purchases:
                    item(f"🎮 {gname(l.get('game_id'))}", tr('ma_forever'), COLORS["green"])

            # 3) Коды (по железу)
            codes = data.get("codes", [])
            if codes:
                shown = True
                section(tr('ma_sec_codes'))
                for c in codes:
                    exp = c.get("expires_at")
                    code = c.get('code','')
                    if exp:
                        left = (exp - now) / 86400
                        if left > 0:
                            when = datetime.fromtimestamp(exp).strftime("%d.%m.%Y %H:%M")
                            sub, col = tr('ma_until', code=code, when=when, days=f"{left:.1f}"), COLORS["green"]
                        else:
                            sub, col = tr('ma_expired', code=code), COLORS["gray"]
                    else:
                        sub, col = tr('ma_permanent', code=code), COLORS["green"]
                    item(f"🎟 {gname(c.get('game_id'))}", sub, col)

            if not shown:
                ctk.CTkLabel(body, text=tr('ma_none'),
                             text_color=COLORS["gray"]).pack(pady=20)

        threading.Thread(target=load, daemon=True).start()

    # ── Инструкция по игре (из catalog.json) ─────────────
    def _show_guide(self, game):
        guide = game.get('guide') or {}
        text = guide.get(_lang) or guide.get('ru') or guide.get('en') or ""
        win = ctk.CTkToplevel(self)
        win.title(f"{game['name']} — {tr('guide_window')}")
        win.geometry("620x560")
        win.configure(fg_color=COLORS["bg"])
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        self._bring_to_front(win)

        ctk.CTkLabel(win, text=f"📖  {game['name']} — {tr('guide_window')}",
                     font=ctk.CTkFont(size=17, weight="bold"),
                     text_color=COLORS["accent"]).pack(pady=(16, 8))

        box = ctk.CTkTextbox(win, fg_color=COLORS["card"], corner_radius=10,
                             font=ctk.CTkFont(size=13), wrap="word")
        box.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        box.insert("1.0", text)
        self._add_textbox_context_menu(box)   # копирование (любая раскладка) + ПКМ-меню

        ctk.CTkButton(win, text=tr('close'), width=120, height=34,
                      fg_color="#2a2a44", hover_color="#3a3a5a",
                      corner_radius=10, command=win.destroy).pack(pady=(0, 14))

    def _confirm_delete(self, game):
        """Окно подтверждения удаления игры."""
        win = ctk.CTkToplevel(self)
        win.title("")
        win.geometry("360x190")
        win.resizable(False, False)
        win.configure(fg_color=COLORS["bg"])
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        self._bring_to_front(win)

        ctk.CTkLabel(win, text=tr('del_title', name=game['name']),
                     font=ctk.CTkFont(size=17, weight="bold"),
                     text_color=COLORS["accent"]).pack(pady=(26, 6))
        ctk.CTkLabel(win, text=tr('del_body'),
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["gray"]).pack()

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(pady=(20, 0))
        ctk.CTkButton(
            btn_row, text=tr('del_cancel'), width=120, height=36,
            fg_color="#2a2a44", hover_color="#3a3a5a",
            corner_radius=10, font=ctk.CTkFont(size=13),
            command=win.destroy
        ).pack(side="left", padx=(0, 10))
        ctk.CTkButton(
            btn_row, text=tr('del_confirm'), width=120, height=36,
            fg_color="#8a2a2a", hover_color="#aa3a3a",
            corner_radius=10, font=ctk.CTkFont(size=13, weight="bold"),
            text_color="white",
            command=lambda: (win.destroy(), self._delete(game))
        ).pack(side="left")

    def _on_action(self, game, delete=False, guide=False):
        if guide:
            self._show_guide(game)
            return
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
            tier = self._auth.get("tier", "")
            if tier in ("pro", "pro_max") or self._auth.get("games"):
                show_subscription_info(self, game)  # подписка есть, но уровня не хватает (нужен Pro Max)
            else:
                self._show_activate_screen(game)    # нет подписки/кода — экран активации
            return
        inst = self._state.get(game['id'], {})
        if inst.get('version') == game['version']:
            card = self._cards.get(game['id'])
            if card: card.show_launching()
            threading.Thread(target=self._launch, args=(game,), daemon=True).start()
        else:
            # мгновенный фидбэк: спиннер + блокировка кнопки ДО сетевого запроса
            # (иначе кнопка «висит» активной пока сервер просыпается → двойные клики)
            card = self._cards.get(game['id'])
            if card: card.show_connecting()
            threading.Thread(target=self._download,
                             args=(game,), daemon=True).start()

    # ── Удаление игры ────────────────────────────────────
    def _delete(self, game):
        import shutil
        gid = game['id']
        game_dir = GAMES_DIR / game_folder(game)
        try:
            if game_dir.exists():
                shutil.rmtree(game_dir)
        except Exception as e:
            self._status('uninstall_error', e=e)
            return
        self._state.pop(gid, None)
        save_state(self._state)
        self._status('uninstalled', name=game['name'])
        self.after(0, self._render)

    # ── Запуск игры ──────────────────────────────────────
    def _launch(self, game):
        exe = self._state.get(game['id'], {}).get('exe')
        if exe and os.path.exists(exe):
            token = self._auth.get("token", "")
            cmd = [exe, "--token", token, "--device", DEVICE_ID] if token else [exe]
            subprocess.Popen(cmd, cwd=os.path.dirname(exe))
            self._status('launched', name=game['name'])
        else:
            self._status('file_not_found')
            # Сбросить состояние чтобы можно было скачать снова
            self._state.pop(game['id'], None)
            save_state(self._state)
            self.after(0, self._render)

    # ── Проверка, запущена ли игра ───────────────────────
    def _game_process_running(self, game):
        """True, если exe игры сейчас запущен (чтобы не обновлять заблокированные файлы)."""
        exe = self._state.get(game['id'], {}).get('exe')
        if not exe:
            return False
        name = os.path.basename(exe)
        try:
            out = subprocess.check_output(
                ["tasklist", "/fi", f"imagename eq {name}"],
                creationflags=0x08000000, stderr=subprocess.DEVNULL
            ).decode(errors="ignore")
            return name.lower() in out.lower()
        except Exception:
            return False

    # ── Скачивание / обновление ──────────────────────────
    def _download(self, game):
        import hashlib
        card = self._cards.get(game['id'])
        url  = game.get('download_url', '')

        if not url:
            self._status('url_missing')
            return

        gid       = game['id']
        old_ver   = self._state.get(gid, {}).get('version')
        is_update = bool(old_ver)

        # Скачивание по подписке: просим у auth-server короткую подписанную ссылку.
        # Сервер не настроен/недоступен → откат на публичную ссылку из каталога.
        try:
            tok = self._auth.get("token", "")
            if tok:
                payload = json.dumps({"token": tok, "device_id": DEVICE_ID, "game_id": gid}).encode()
                req0 = _ur.Request(f"{AUTH_SERVER}/auth/download", data=payload,
                                   headers={"Content-Type": "application/json",
                                            "User-Agent": "FlagRaceLauncher/1.0"})
                gj = json.loads(_ur.urlopen(req0, timeout=15, context=SSL_CTX).read())
                if gj.get("ok") and gj.get("url"):
                    url = gj["url"]
        except Exception:
            pass
        # отметка в лог: через гейт (signed) или откат на публичную ссылку — для проверки перед приватизацией
        try:
            _mode = "gated(signed)" if "release-assets.githubusercontent.com" in url else "public-fallback"
            (DATA_DIR / "download_log.txt").open("a", encoding="utf-8").write(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} {gid} -> {_mode}\n")
        except Exception:
            pass

        # При обновлении нельзя трогать файлы, если игра запущена
        if is_update and self._game_process_running(game):
            self._status('close_before_update', name=game['name'])
            return

        game_dir = GAMES_DIR / game_folder(game)
        game_dir.mkdir(parents=True, exist_ok=True)
        zip_path  = game_dir / f"{gid}.zip"
        part_path = game_dir / f"{gid}.zip.part"   # качаем во временный файл

        try:
            if card: self.after(0, lambda: card.show_progress(0, "Connecting..."))

            req = _ur.Request(url, headers={"User-Agent": "FlagRaceLauncher/1.0"})
            with _ur.urlopen(req, timeout=60, context=SSL_CTX) as resp:
                total = int(resp.getheader("Content-Length") or 0)
                done  = 0
                chunk = 65536
                with open(part_path, "wb") as f:
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

            # Загрузка не оборвалась посередине?
            if total > 0 and done < total:
                raise IOError(f"загрузка прервана ({done}/{total} байт)")

            # Проверка целостности
            if card: self.after(0, lambda: card.show_progress(1.0, "Checking..."))
            expected = (game.get('sha256') or "").lower().strip()
            if expected:
                h = hashlib.sha256()
                with open(part_path, "rb") as f:
                    for b in iter(lambda: f.read(1 << 20), b""):
                        h.update(b)
                if h.hexdigest().lower() != expected:
                    raise IOError("контрольная сумма не совпала (битый файл)")

            # Полностью скачанный файл переименовываем в .zip
            zip_path.unlink(missing_ok=True)
            part_path.replace(zip_path)

            # Архив валиден? (защита от повреждённого zip перед распаковкой)
            with zipfile.ZipFile(zip_path, 'r') as z:
                if z.testzip() is not None:
                    raise IOError("архив повреждён")
                # Распаковка поверх (сохранения/настройки/panels не трогаем)
                if card: self.after(0, lambda: card.show_progress(1.0, "Extracting..."))
                z.extractall(game_dir)
            zip_path.unlink(missing_ok=True)

            # Найти .exe
            exes = sorted(game_dir.rglob("*.exe"),
                          key=lambda p: len(p.parts))  # берём самый верхний
            exe_path = str(exes[0]) if exes else None

            # Сохранить состояние (только после успешной распаковки)
            self._state[gid] = {
                'version': game['version'],
                'exe': exe_path
            }
            save_state(self._state)

            if card: self.after(0, card.done_progress)
            self.after(0, self._render)
            self._status('updated_ok' if is_update else 'installed_ok', name=game['name'])
            if is_update and (game.get('changelogs') or game.get('changelog')):
                self.after(300, lambda: self._show_changelog(game, old_ver))

        except Exception as e:
            self._status('download_error', e=e)
            if card: self.after(0, card.done_progress)
            # Убрать незавершённые временные файлы; старая установка остаётся как была
            part_path.unlink(missing_ok=True)
            zip_path.unlink(missing_ok=True)

    # ── Окно «Что нового» (патчноуты всех обновлённых версий) ────
    def _show_changelog(self, game, from_ver=None):
        def _pick(v):
            if isinstance(v, dict):
                return (v.get(_lang) or v.get('ru') or v.get('en') or '').strip()
            return (v or '').strip()
        new_ver = game.get('version', '')
        hist = game.get('changelogs') or {}
        cl = ''
        if hist:
            ft = _ver_tuple(from_ver) if from_ver else (-1,)
            items = [(v, _pick(n)) for v, n in hist.items()
                     if _ver_tuple(v) > ft and _ver_tuple(v) <= _ver_tuple(new_ver) and _pick(n)]
            items.sort(key=lambda x: _ver_tuple(x[0]), reverse=True)   # новые сверху
            cl = "\n\n".join(f"▎v{v}\n{n}" for v, n in items)
        if not cl:
            cl = _pick(game.get('changelog'))
        if not cl:
            return
        win = ctk.CTkToplevel(self)
        win.title(tr('changelog_title'))
        win.geometry("440x380")
        win.resizable(False, False)
        win.configure(fg_color=COLORS["bg"])
        self._bring_to_front(win)
        ctk.CTkLabel(win, text=f"🎉 {game['name']} — v{game['version']}",
                     font=ctk.CTkFont(size=17, weight="bold"),
                     text_color=COLORS["accent"]).pack(pady=(20, 2))
        ctk.CTkLabel(win, text=tr('changelog_title'),
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["gray"]).pack()
        box = ctk.CTkTextbox(win, width=400, height=250, fg_color="#16162a",
                             font=ctk.CTkFont(size=12), wrap="word")
        box.pack(padx=18, pady=12, fill="both", expand=True)
        box.insert("1.0", cl)
        box.configure(state="disabled")
        ctk.CTkButton(win, text="OK", width=130, height=36,
                      fg_color=COLORS["btn_play"], hover_color=_brighten(COLORS["btn_play"]),
                      corner_radius=10, command=win.destroy).pack(pady=(0, 16))

    # ── Экран входа ──────────────────────────────────────
    def _show_login_screen(self, game=None):
        self._login_game = game   # игра, для которой открывается вход
        self._login_win = ctk.CTkToplevel(self)
        self._login_win.title(tr('login_window'))
        h = 570 if game else 480
        self._login_win.geometry(f"460x{h}")
        self._login_win.resizable(False, False)
        self._login_win.configure(fg_color=COLORS["bg"])
        self._login_win.protocol("WM_DELETE_WINDOW", self._login_win.destroy)
        self._bring_to_front(self._login_win)

        ctk.CTkLabel(self._login_win, text="⚔  VASYA_PECHEN",
                     font=ctk.CTkFont(size=26, weight="bold"),
                     text_color=COLORS["accent"]).pack(pady=(30, 8))

        ctk.CTkLabel(self._login_win, text=tr('login_sub'),
                     font=ctk.CTkFont(size=13),
                     text_color=COLORS["gray"]).pack()

        self._login_status = ctk.CTkLabel(self._login_win, text="",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["orange"])
        self._login_status.pack(pady=(6, 0))

        ctk.CTkButton(
            self._login_win, text=tr('login_signin'),
            width=240, height=44,
            fg_color=COLORS["btn_play"], hover_color=_brighten(COLORS["btn_play"]),
            corner_radius=12, font=ctk.CTkFont(size=14, weight="bold"),
            command=lambda: threading.Thread(target=self._do_login, daemon=True).start()
        ).pack(pady=(16, 0))

        ctk.CTkLabel(self._login_win, text=tr('login_no_sub'),
                     font=ctk.CTkFont(size=11), text_color="#444466").pack(pady=(10, 0))

        ctk.CTkButton(
            self._login_win, text=tr('login_subscribe'),
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
        ctk.CTkLabel(sep_frame, text=tr('or'), font=ctk.CTkFont(size=11),
                     text_color="#444466").pack(side="left")
        ctk.CTkFrame(sep_frame, fg_color="#2a2a44", height=1).pack(
            fill="x", side="left", expand=True, pady=9)

        # Секция «Ввести код» — контейнер держит позицию в layout,
        # внутри переключаем кнопку <-> поле ввода (без хрупкого after)
        self._code_win = self._login_win; self._code_status_lbl = self._login_status
        self._code_section = ctk.CTkFrame(self._login_win, fg_color="transparent")
        self._code_section.pack(pady=(6, 0))

        # Кнопка «Ввести код»
        self._code_toggle_btn = ctk.CTkButton(
            self._code_section, text=tr('enter_code'),
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
            ctk.CTkLabel(sep2, text=tr('or'), font=ctk.CTkFont(size=11),
                         text_color="#444466").pack(side="left")
            ctk.CTkFrame(sep2, fg_color="#2a2a44", height=1).pack(
                fill="x", side="left", expand=True, pady=9)

            ctk.CTkLabel(
                self._login_win,
                text=tr('already_bought', name=game['name']),
                font=ctk.CTkFont(size=11), text_color="#444466"
            ).pack(pady=(2, 0))

            ctk.CTkButton(
                self._login_win,
                text=tr('activate_game', name=game['name']),
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

    def _add_textbox_context_menu(self, box):
        """Текстовое поле только для чтения: копирование по физ. клавише (любая раскладка) + ПКМ-меню."""
        import tkinter as tk
        try:
            inner = box._textbox   # tk.Text внутри CTkTextbox
        except AttributeError:
            return

        def _copy_text():
            try:
                sel = inner.get("sel.first", "sel.last")   # копируем выделение
            except Exception:
                sel = inner.get("1.0", "end-1c")            # нет выделения → копируем весь текст
            if sel:
                self.clipboard_clear(); self.clipboard_append(sel)

        def _select_all():
            inner.tag_add("sel", "1.0", "end-1c"); inner.focus_set()

        # Только чтение: блокируем ввод/правку, но разрешаем выделение, Ctrl и навигацию
        def _block_keys(ev):
            if ev.state & 0x4:      # Ctrl зажат — пропускаем (копирование/выделить всё)
                return
            if ev.keysym in ("Left","Right","Up","Down","Home","End","Prior","Next"):
                return
            return "break"
        inner.bind("<KeyPress>", _block_keys)

        try:
            menu = tk.Menu(inner, tearoff=0, bg="#1a1a2e", fg="#e8e8f8",
                           activebackground="#2a2a4e", activeforeground="#e8e8f8", bd=0)
            menu.add_command(label="Копировать",   command=_copy_text)
            menu.add_command(label="Выделить всё", command=_select_all)

            def _show_menu(ev):
                try:    menu.tk_popup(ev.x_root, ev.y_root)
                finally: menu.grab_release()
            inner.bind("<Button-3>", _show_menu)

            def _ctrl_key(ev):
                if not (ev.state & 0x4):
                    return
                kc = ev.keycode
                if   kc == 67: _copy_text();   return "break"   # C
                elif kc == 65: _select_all();  return "break"   # A
            inner.bind("<Control-KeyPress>", _ctrl_key)
        except Exception:
            pass

    def _do_login(self):
        self._set_login_status(tr('login_opening'))

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
                    "email": params.get("email", [""])[0],
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
        self._set_login_status(tr('login_waiting'))

        for _ in range(180):  # ждём до 3 минут
            srv.handle_request()
            if result_holder[0]:
                break

        srv.server_close()

        r = result_holder[0]
        if not r or not r.get("token"):
            self._set_login_status(tr('login_not_done'))
            return

        games_str = r.get("games", "")
        self._auth = {
            "token":       r["token"],
            "name":        r["name"],
            "email":       r.get("email", ""),
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
            self._set_code_status(tr('code_enter_one'))
            return
        self._set_code_status(tr('code_verifying'))
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
                r = _ur.urlopen(req, timeout=15, context=SSL_CTX)
                result = json.loads(r.read())
            except Exception as e:
                # HTTPError (4xx/5xx) тоже содержит тело с деталями ошибки
                try:
                    result = json.loads(e.read())  # type: ignore
                except Exception:
                    self._set_code_status(tr('conn_error'))
                    return
        except Exception:
            self._set_code_status(tr('conn_error'))
            return

        if not result.get("ok"):
            err = result.get("error", "")
            msgs = {
                "invalid_code":       tr('code_invalid'),
                "code_expired":       tr('code_expired_msg'),
                "code_limit_reached": tr('code_limit'),
            }
            self._set_code_status(msgs.get(err, f"❌ {err}"))
            return

        if self._logged_in and self._auth.get("tier") in ("pro", "pro_max"):
            # Подписчик: НЕ затираем подписку — код просто добавляется к устройству.
            dev = self._fetch_device_codes()
            if dev is not None:
                self._auth["device_games"] = dev
            else:
                merged = list(dict.fromkeys((self._auth.get("device_games") or []) + result.get("games", [])))
                self._auth["device_games"] = merged
            save_auth(self._auth)
        else:
            # Без подписки: код становится основной личностью.
            self._auth = {
                "token":       result["token"],
                "name":        result.get("name", "Guest"),
                "tier":        result.get("tier", "guest"),
                "games":       result.get("games", []),
                "device_games": result.get("games", []),
                "last_verify": time.time(),
            }
            save_auth(self._auth)

        w = getattr(self, '_code_win', None)
        if w:
            try: w.after(0, w.destroy)
            except Exception: pass
        self._code_win = None; self._login_win = None; self._activate_win = None

        self._after_login()
        self._run_pending_action()

    def _show_activate_screen(self, game):
        """Окно для активации игры, купленной на Patreon (пользователь уже вошёл, но без доступа)."""
        win = ctk.CTkToplevel(self)
        win.title(tr('act_window'))
        win.geometry("360x346" if game.get('guide') else "360x298")
        win.resizable(False, False)
        win.configure(fg_color=COLORS["bg"])
        win.protocol("WM_DELETE_WINDOW", win.destroy)
        self._activate_win = win
        self._login_win = None      # код-редем будет целиться в это окно
        self._bring_to_front(win)

        ctk.CTkLabel(win, text=f"🔒  {game['name']}",
                     font=ctk.CTkFont(size=20, weight="bold"),
                     text_color=COLORS["accent"]).pack(pady=(28, 4))

        ctk.CTkLabel(win, text=tr('act_no_access'),
                     font=ctk.CTkFont(size=12),
                     text_color=COLORS["gray"]).pack()

        self._activate_status = ctk.CTkLabel(win, text="",
                     font=ctk.CTkFont(size=11),
                     text_color=COLORS["orange"])
        self._activate_status.pack(pady=(4, 0))

        ctk.CTkButton(
            win, text=tr('act_buy'),
            width=240, height=38,
            fg_color="#FF424D", hover_color="#cc2f38",
            corner_radius=10, font=ctk.CTkFont(size=13, weight="bold"),
            text_color="white",
            command=lambda: webbrowser.open(PATREON_URL)
        ).pack(pady=(14, 4))

        ctk.CTkButton(
            win, text=tr('act_activate'),
            width=240, height=38,
            fg_color="#2a4a2a", hover_color="#3a6a3a",
            border_width=1, border_color="#446644",
            corner_radius=10, font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#aaffaa",
            command=lambda g=game: threading.Thread(
                target=self._do_activate_game, args=(g,), daemon=True).start()
        ).pack()

        # ── Ввести код доступа (кнопка ⇄ поле) ──
        self._code_win = win; self._code_status_lbl = self._activate_status
        self._code_section = ctk.CTkFrame(win, fg_color="transparent")
        self._code_section.pack(pady=(8, 0))
        self._code_toggle_btn = ctk.CTkButton(
            self._code_section, text=tr('enter_code'),
            width=240, height=34, fg_color="transparent", hover_color="#1a1a2e",
            border_width=1, border_color="#444466", corner_radius=10,
            font=ctk.CTkFont(size=12), text_color="#aaaacc",
            command=self._show_code_entry)
        self._code_toggle_btn.pack()
        self._code_entry_frame = ctk.CTkFrame(self._code_section, fg_color="transparent")
        self._code_entry = ctk.CTkEntry(
            self._code_entry_frame, placeholder_text="GAME-XXXXXX",
            width=190, height=36, font=ctk.CTkFont(size=13, family="Courier"), justify="center")
        self._code_entry.grid(row=0, column=0, padx=(0, 8))
        self._add_entry_context_menu(self._code_entry)
        self._code_entry.bind("<Return>", lambda e: threading.Thread(
            target=self._do_redeem_code, daemon=True).start())
        ctk.CTkButton(
            self._code_entry_frame, text="→", width=46, height=36,
            fg_color=COLORS["btn_play"], hover_color=_brighten(COLORS["btn_play"]),
            corner_radius=8, font=ctk.CTkFont(size=18, weight="bold"),
            command=lambda: threading.Thread(target=self._do_redeem_code, daemon=True).start()
        ).grid(row=0, column=1)

        # Инструкция доступна даже без доступа к игре
        if game.get('guide'):
            ctk.CTkButton(
                win, text="📖 " + tr('guide'),
                width=240, height=30,
                fg_color="transparent", hover_color="#1a1a2e",
                border_width=1, border_color="#33335a",
                corner_radius=8, font=ctk.CTkFont(size=11),
                text_color="#9999bb",
                command=lambda g=game: self._show_guide(g)
            ).pack(pady=(8, 0))

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

        _status(tr('act_opening'))

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
                    "email": params.get("email", [""])[0],
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
        _status(tr('act_waiting'))

        for _ in range(180):
            srv.handle_request()
            if result_holder[0]:
                break
        srv.server_close()

        r = result_holder[0]
        if not r or not r.get("token"):
            _status(tr('act_not_done'))
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

    def _set_code_status(self, text):
        """Статус ввода кода в активной форме (вход / активация / мои доступы)."""
        w = getattr(self, '_code_win', None); lbl = getattr(self, '_code_status_lbl', None)
        if w and lbl:
            try: w.after(0, lambda: lbl.configure(text=text))
            except Exception: pass

    # ── Переключение языка ───────────────────────────────
    def _toggle_lang(self):
        set_app_lang('en' if _lang == 'ru' else 'ru')
        self._apply_lang()

    def _apply_lang(self):
        try:
            self.lang_btn.configure(text=f"🌐 {_lang.upper()}")
            self.mycodes_btn.configure(text=tr('my_access'))
        except Exception: pass
        self._render()            # пересобрать карточки на новом языке
        self._refresh_status()    # перерисовать текущий статус

    # ── Хелпер статуса ───────────────────────────────────
    def _status(self, key, **kw):
        self._status_kv = (key, kw)
        txt = tr(key, **kw) if key else ""
        self.after(0, lambda: self.status_lbl.configure(text=txt))

    def _refresh_status(self):
        kv = getattr(self, '_status_kv', None)
        if kv:
            key, kw = kv
            self.status_lbl.configure(text=tr(key, **kw) if key else "")

    def _set_status(self, text):
        self.after(0, lambda: self.status_lbl.configure(text=text))


# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    app = LauncherApp()
    app.mainloop()
