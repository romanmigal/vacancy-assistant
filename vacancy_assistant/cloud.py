"""Облачная модель GigaChat (Сбер) — по желанию, вместо Gemma на этом компьютере.

Ключ — один на компьютер: «профили/облако.json» (в git не попадает, читать может только владелец файла):
ключ авторизации из личного кабинета developers.sber.ru, тип доступа (scope) и модель GigaChat.
Пользоваться ли облаком — решает каждый профиль сам (профиль.json → «модель»): у каждого человека
своё согласие отправлять его резюме в Сбер. Запросы к модели идут туда, что выбрано в профиле,
для которого сейчас работает поток (use: задача окна, запрос окна, команда в терминале).
По ключу программа сама получает токен на 30 минут и обновляет его. Адреса GigaChat подписаны
сертификатами Минцифры — они лежат в certs/ и используются только для этих запросов.
С облачной моделью резюме, критерии и вакансии уходят в Сбер — поэтому включить её можно только
с явным согласием пользователя. ФИО, имена знакомых, ссылки на профили, телефоны, почта и адрес перед отправкой
заменяются метками (mask.py).
"""
import json
import os
import ssl
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from . import mask, settings, waiting
from .errors import AssistantError
from .textio import read_json, write_json

CONFIG = "облако.json"
OAUTH = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
# С июля 2026 года Сбер рекомендует api.giga.chat; прежний адрес работает — он запасной
BASES = ["https://api.giga.chat", "https://gigachat.devices.sberbank.ru"]
SCOPES = {"GIGACHAT_API_PERS": "физическое лицо",
          "GIGACHAT_API_B2B": "компания, предоплата",
          "GIGACHAT_API_CORP": "компания, постоплата"}
DEFAULT_MODEL = "GigaChat-2-Pro"
CA_FILE = Path(__file__).resolve().parent / "certs" / "russian_trusted_ca.pem"

_token = {"key": None, "value": None, "until": 0}
_base = {"url": None}
_lock = threading.Lock()


def folder():
    return settings.profiles_dir()


def load(root=None):
    return read_json((root or folder()) / CONFIG, {})


_current = threading.local()


def use(profile):
    """Для какого профиля работает этот поток — от него зависит, куда идут запросы к модели."""
    _current.profile = profile


def current_profile():
    return getattr(_current, "profile", None)


def active(profile=None):
    """Оценивает ли облачная модель: в профиле выбран GigaChat, и ключ на компьютере есть."""
    p = profile or current_profile()
    return bool(p is not None and p.use_cloud and load(p.dir.parent).get("auth_key"))


def model_name(profile=None):
    """Какой моделью сейчас оценивает программа — для журнала, карточки и паспорта разбора."""
    p = profile or current_profile()
    return (load(p.dir.parent).get("model") or DEFAULT_MODEL) if active(p) else settings.MODEL


def public(root=None, profile=None):
    """Настройки для окна — без ключа (только признак, что он есть, и последние символы);
    enabled — выбран ли GigaChat в этом профиле."""
    cfg = load(root)
    key = cfg.get("auth_key") or ""
    return {"enabled": active(profile) if profile else False, "has_key": bool(key), "key_tail": key[-4:] if key else "",
            "scope": cfg.get("scope", "GIGACHAT_API_PERS"), "model": cfg.get("model", DEFAULT_MODEL),
            "consent": bool(profile and profile.use_cloud), "scopes": SCOPES, "local_model": settings.MODEL}


def save(root, enabled, auth_key=None, scope=None, model=None, consent=None, profile=None):
    """Сохраняет ключ, тип доступа и модель (общие для компьютера) и — если указан профиль — выбор модели
    этого профиля. Включить GigaChat можно только с ключом и согласием — и если GigaChat отвечает."""
    root = root or folder()
    cfg = load(root)
    if auth_key:
        cfg["auth_key"] = auth_key.strip()
    if scope:
        if scope not in SCOPES:
            raise AssistantError("Неизвестный тип доступа к GigaChat.")
        cfg["scope"] = scope
    if model:
        cfg["model"] = model.strip()
    if enabled:
        if not cfg.get("auth_key"):
            raise AssistantError("Вставьте ключ авторизации GigaChat из личного кабинета developers.sber.ru.")
        if not consent:
            raise AssistantError("Подтвердите, что согласны отправлять резюме и вакансии в GigaChat.")
        check(cfg)                                     # не включаем то, что не работает
    if "enabled" in cfg:                               # прежняя общая настройка — раздаём профилям, потом убираем
        _split_legacy(root, bool(cfg.get("enabled") and cfg.get("consent")))
    cfg.pop("enabled", None)
    cfg.pop("consent", None)
    path = root / CONFIG
    write_json(path, cfg)
    try:
        os.chmod(path, 0o600)                          # ключ — секрет: только владельцу
    except OSError:
        pass
    _token.update(key=None, value=None, until=0)
    if profile is not None:
        profile.set_model(bool(enabled))
    return public(root, profile)


def _split_legacy(root, was_cloud):
    """Раньше облако включалось сразу для всех профилей. Профили, где своего выбора ещё нет,
    получают прежний — чтобы ни у кого модель не поменялась сама."""
    from .profile import CONFIG_FILE
    for f in Path(root).glob(f"*/{CONFIG_FILE}"):
        config = read_json(f, {})
        if config and "модель" not in config:
            config["модель"] = {"облако": was_cloud, **({"согласие": time.strftime("%Y-%m-%d")} if was_cloud else {})}
            write_json(f, config)


def _context():
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cafile=str(CA_FILE))     # к обычным корневым — сертификаты Минцифры
    return ctx


NET_RETRIES = 3                  # связь иногда пропадает на секунды — повторяем, прежде чем сдаться
CHAT_TIMEOUT = 120               # секунд тишины на один запрос: дольше GigaChat не думает, значит, связь повисла
CHAT_LIMIT = 240                 # секунд на вакансию со всеми повторами — дальше ошибка и следующая вакансия


def _request(url, data=None, headers=None, timeout=60):
    for attempt in range(NET_RETRIES):
        try:
            return _request_once(url, data, headers, timeout)
        except CloudNetError:
            if attempt == NET_RETRIES - 1:
                raise
            time.sleep(2 * (attempt + 1))


def _request_once(url, data=None, headers=None, timeout=60):
    request = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_context()) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise CloudHTTPError(e.code, detail) from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise CloudNetError(f"GigaChat недоступен: {getattr(e, 'reason', e)}. Проверьте интернет (VPN не нужен).") from e


class CloudNetError(AssistantError):
    """Адрес не ответил (нет сети, таймаут)."""


class CloudHTTPError(AssistantError):
    def __init__(self, code, detail):
        super().__init__(f"GigaChat ответил {code}: {detail}")
        self.code = code


def token(cfg, force=False):
    """Токен доступа на 30 минут — по ключу авторизации; обновляется заранее, за минуту до конца."""
    with _lock:
        if not force and _token["key"] == cfg["auth_key"] and _token["until"] > time.time() + 60:
            return _token["value"]
        try:
            answer = _request(OAUTH, f"scope={cfg.get('scope', 'GIGACHAT_API_PERS')}".encode(),
                              {"Authorization": f"Basic {cfg['auth_key']}", "RqUID": str(uuid.uuid4()),
                               "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}, 30)
        except CloudHTTPError as e:
            if e.code in (400, 401):
                raise AssistantError("GigaChat не принял ключ авторизации. Проверьте ключ и тип доступа "
                                     "(физическое лицо или компания) в личном кабинете developers.sber.ru.") from e
            raise
        _token.update(key=cfg["auth_key"], value=answer["access_token"],
                      until=answer.get("expires_at", 0) / 1000 or time.time() + 25 * 60)
        return _token["value"]


def _api(cfg, path, body=None, timeout=300):
    """Запрос к GigaChat API: основной адрес, при отказе — запасной; истёкший токен — обновить и повторить."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    bases = [_base["url"]] if _base["url"] else BASES
    last = None
    for base in bases:
        for attempt in range(2):
            headers = {"Authorization": f"Bearer {token(cfg, force=attempt > 0)}", "Accept": "application/json"}
            if data:
                headers["Content-Type"] = "application/json"
            try:
                result = _request(base + path, data, headers, timeout)
                _base["url"] = base
                return result
            except CloudNetError as e:
                last = e
                if base != bases[-1]:
                    break                              # адрес не отвечает — пробуем запасной
                raise
            except CloudHTTPError as e:
                last = e
                if e.code == 401 and attempt == 0:
                    continue                           # токен истёк раньше срока — новый и ещё раз
                if e.code in (403, 404) and base != bases[-1]:
                    break                              # этот адрес не пускает — пробуем запасной
                raise
    raise last


def models(cfg):
    """Модели для текста, доступные по ключу (для выбора в настройках); модели эмбеддингов — не для нас."""
    return sorted(m["id"] for m in _api(cfg, "/api/v1/models", timeout=30).get("data", [])
                  if "embed" not in m["id"].lower())


def check(cfg):
    """Проверка подключения: токен, список моделей и короткий ответ выбранной модели."""
    available = models(cfg)
    model = cfg.get("model") or DEFAULT_MODEL
    if available and model not in available:
        raise AssistantError(f"Модели {model} нет среди доступных по этому ключу: {', '.join(available)}.")
    reply = ask("Ответь одним словом: работает?", {"temperature": 0.1, "num_predict": 10}, cfg)
    return {"models": available, "model": model, "reply": reply}


def ask(prompt, options=None, cfg=None):
    """Запрос к GigaChat: тот же промпт, что получила бы Gemma. Параметры Ollama переводятся
    в параметры GigaChat (temperature, max_tokens). «Зерна» случайности (seed) у GigaChat нет.
    Личные данные профиля в запросе заменяются метками, в ответе — обратно (mask.py)."""
    p = current_profile()
    cfg = cfg or load(p.dir.parent if p else None)
    options = options or {}
    hidden = mask.Mask.for_profile(p) if p is not None else None
    body = {"model": cfg.get("model") or DEFAULT_MODEL,
            "messages": [{"role": "user", "content": hidden.prompt(prompt) if hidden else prompt}],
            "temperature": max(0.01, float(options.get("temperature", 0.3))),
            "max_tokens": int(options.get("num_predict", 1500))}
    answer = waiting.run(lambda: _api(cfg, "/api/v1/chat/completions", body, timeout=CHAT_TIMEOUT), "GigaChat", CHAT_LIMIT,
                         AssistantError(f"GigaChat не ответил за {CHAT_LIMIT // 60} минуты — пропускаю. Разобрать можно "
                                        "позже кнопкой «Разобрать заново»."))
    try:
        text = answer["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as e:
        raise AssistantError(f"GigaChat ответил не по формату: {str(answer)[:200]}") from e
    return hidden.show(text) if hidden else text
