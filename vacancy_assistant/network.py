"""Доступ к окну из домашней сети: второй сервер (порт 8766) на всех адресах компьютера — только с паролем.

Обычное окно (127.0.0.1:8765) остаётся как было. Второй сервер включается в «Параметры → Настройки»,
отвечает только адресам домашней сети (192.168.*, 10.*, 172.16–31.*) и пускает дальше страницы входа
после пароля. Пароль хранится солёным хэшем в «профили/доступ из сети.json» (в git не попадает).
Соединение без шифрования (http), поэтому режим — для домашней сети, не для кафе и офиса.
"""
import hashlib
import ipaddress
import re
import secrets
import socket
import subprocess
import sys
import time

from .textio import read_json, write_json

PORT = 8766
CONFIG = "доступ из сети.json"
MIN_PASSWORD = 6
SESSION_DAYS = 30
COOKIE = "va_session"
MAX_FAILS, BLOCK_SECONDS = 5, 60          # после 5 неверных паролей подряд — минута ожидания


def _hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 200_000).hex()


def load(folder):
    f = folder / CONFIG
    return read_json(f, {})


def save(folder, enabled, password=None):
    """Включает или выключает доступ; новый пароль (если задан) заменяет старый."""
    from .errors import AssistantError
    cfg = load(folder)
    if password:
        if len(password) < MIN_PASSWORD:
            raise AssistantError(f"Пароль — не короче {MIN_PASSWORD} символов.")
        cfg["salt"] = secrets.token_hex(16)
        cfg["hash"] = _hash(password, cfg["salt"])
    if enabled and not cfg.get("hash"):
        raise AssistantError("Задайте пароль для входа с других устройств.")
    cfg["enabled"] = bool(enabled)
    write_json(folder / CONFIG, cfg)
    return cfg


def password_ok(cfg, password):
    return bool(cfg.get("hash")) and secrets.compare_digest(_hash(password or "", cfg["salt"]), cfg["hash"])


def home_address(ip):
    """Адрес из домашней (частной) сети или сам компьютер."""
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return a.is_private or a.is_loopback


VIRTUAL = ("lo", "utun", "tun", "tap", "ppp", "ipsec", "wg", "docker", "br-", "veth", "vmnet", "vboxnet", "awdl", "llw", "bridge")


def _run(*cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def lan_ips():
    """IPv4-адреса компьютера в домашней сети. Сетевые карты VPN, Docker и виртуальных машин пропускаем:
    маршрут «в интернет» при включённом VPN ведёт через VPN, и его адрес с других устройств не открыть."""
    found = []
    if sys.platform == "win32":
        found = re.findall(r"IPv4[^:\n]*:\s*([\d.]+)", _run("ipconfig"))          # «IPv4 Address» / «IPv4-адрес»
    else:
        out = _run("ifconfig")
        if out:
            for block in re.split(r"\n(?=\S)", out):
                name = block.split(":", 1)[0]
                if name.startswith(VIRTUAL) or "POINTOPOINT" in block or "LOOPBACK" in block:
                    continue
                found += re.findall(r"inet (?:addr:)?([\d.]+)", block)
        else:                                                   # Linux без ifconfig
            for name, ip in re.findall(r"^\d+:\s+(\S+)\s+inet\s+([\d.]+)", _run("ip", "-4", "-o", "addr"), re.M):
                if not name.startswith(VIRTUAL):
                    found.append(ip)
    ips = [ip for ip in dict.fromkeys(found) if home_address(ip) and not ip.startswith(("127.", "169.254."))]
    if not ips:                                                 # запасной путь — адрес маршрута по умолчанию
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("10.255.255.255", 1))                # пакет не отправляется
                ips = [s.getsockname()[0]]
        except OSError:
            pass
    return ips


def addresses(port=PORT):
    """Адреса, по которым окно открывается с других устройств: IP компьютера в сети и его имя .local."""
    urls = [f"http://{ip}:{port}/" for ip in lan_ips()]
    name = socket.gethostname()
    if name and "." not in name:
        name += ".local"
    if name.endswith(".local"):
        urls.append(f"http://{name}:{port}/")
    return urls


class Gate:
    """Вход по паролю: сессии в памяти (после перезапуска программы — войти снова) и защита от подбора."""

    def __init__(self):
        self.sessions, self.fails = {}, {}

    def login(self, cfg, ip, password):
        """Возвращает ключ сессии или текст ошибки (ключ, None) / (None, ошибка)."""
        count, until = self.fails.get(ip, (0, 0))
        if time.time() < until:
            return None, f"Слишком много попыток. Подождите {int(until - time.time()) + 1} с."
        if not password_ok(cfg, password):
            count += 1
            self.fails[ip] = (0, time.time() + BLOCK_SECONDS) if count >= MAX_FAILS else (count, 0)
            return None, "Неверный пароль."
        self.fails.pop(ip, None)
        key = secrets.token_urlsafe(32)
        self.sessions[key] = time.time() + SESSION_DAYS * 86400
        return key, None

    def valid(self, cookie_header):
        for part in (cookie_header or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE and self.sessions.get(value, 0) > time.time():
                return True
        return False

    def clear(self):
        self.sessions.clear()


LOGIN_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Помощник по вакансиям — вход</title>
<style>
:root { color-scheme: light dark; --bg: #f4f5f7; --card: #fff; --text: #1d2125; --muted: #6b7280; --accent: #2f6b55; --err: #b42318; }
@media (prefers-color-scheme: dark) { :root { --bg: #16181b; --card: #22252a; --text: #e6e8eb; --muted: #9aa1aa; --accent: #4f9c80; --err: #f97066; } }
body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: var(--bg); color: var(--text);
       font: 15px/1.5 -apple-system, "Segoe UI", Roboto, sans-serif; padding: 16px; box-sizing: border-box; }
form { background: var(--card); padding: 28px; border-radius: 12px; width: 100%; max-width: 340px; box-shadow: 0 4px 24px rgba(0,0,0,.08); }
h1 { font-size: 18px; margin: 0 0 6px; } p { color: var(--muted); margin: 0 0 18px; font-size: 13px; }
input { width: 100%; box-sizing: border-box; padding: 10px 12px; font-size: 15px; border-radius: 8px; border: 1px solid #8884; background: transparent; color: inherit; }
button { margin-top: 14px; width: 100%; padding: 10px; font-size: 15px; border: 0; border-radius: 8px; background: var(--accent); color: #fff; cursor: pointer; }
.err { color: var(--err); font-size: 13px; margin: 10px 0 0; }
</style></head><body>
<form method="post" action="/login">
  <h1>Помощник по вакансиям</h1>
  <p>Вход с другого устройства домашней сети. Пароль задаётся на основном компьютере в «Параметры → Настройки».</p>
  <input type="password" name="password" placeholder="Пароль" autofocus autocomplete="current-password" required>
  {{ERROR}}
  <button type="submit">Войти</button>
</form></body></html>"""
