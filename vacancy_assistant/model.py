"""Разговор с моделью: Ollama на этом компьютере (по умолчанию) или облачный GigaChat, если он включён
в настройках (см. cloud.py). Вызывающему коду всё равно, куда ушёл запрос: промпт тот же, ответ — текст."""
import json
import urllib.error
import urllib.request

from . import cloud, settings, waiting
from .errors import AssistantError

LOCAL_LIMIT = 900              # секунд на ответ локальной модели: Gemma на слабом компьютере думает долго


def current_model():
    """Какой моделью сейчас работает программа: имя локальной модели или облачной."""
    return cloud.model_name()


def ask_model(prompt, model=settings.MODEL, options=settings.OPTIONS):
    """Отправляет запрос модели и возвращает текст ответа. model — модель Ollama (для облака не нужна)."""
    if cloud.active():
        return cloud.ask(prompt, options)
    return ask_local(prompt, model, options)


def ask_local(prompt, model=settings.MODEL, options=settings.OPTIONS):
    """Запрос к локальной модели (Ollama) — даже если в профиле выбран GigaChat: когда облачная модель
    отказалась отвечать, вакансию разбирает локальная."""
    body = {"model": model, "prompt": prompt, "stream": False,
            "think": False,          # без рассуждений вслух
            "options": options}
    request = urllib.request.Request(settings.OLLAMA, json.dumps(body).encode("utf-8"),
                                     {"Content-Type": "application/json"})

    def call():
        try:
            with urllib.request.urlopen(request, timeout=LOCAL_LIMIT) as response:
                return json.load(response)["response"].strip()
        except urllib.error.URLError as e:
            if isinstance(e.reason, ConnectionRefusedError):
                raise AssistantError("Ollama не запущена. Запустите её командой  ollama serve  и повторите.") from e
            raise
    return waiting.run(call, "локальной модели", LOCAL_LIMIT,
                       AssistantError(f"Локальная модель не ответила за {LOCAL_LIMIT // 60} минут — пропускаю."))
