"""Разговор с моделью: Ollama на этом компьютере (по умолчанию) или облачный GigaChat, если он включён
в настройках (см. cloud.py). Вызывающему коду всё равно, куда ушёл запрос: промпт тот же, ответ — текст."""
import json
import urllib.error
import urllib.request

from . import cloud, settings, waiting
from .fact_check import same_script
from .errors import AssistantError

LOCAL_LIMIT = 900              # секунд на ответ локальной модели: Gemma на слабом компьютере думает долго


def current_model():
    """Какой моделью сейчас работает программа: имя локальной модели или облачной."""
    return cloud.model_name()


def ask_model(prompt, model=settings.MODEL, options=settings.OPTIONS):
    """Отправляет запрос модели и возвращает текст ответа. model — модель Ollama (для облака не нужна)."""
    if cloud.active():                               # слова с буквами двух алфавитов («Tехнологическая») — одним
        return same_script(cloud.ask(prompt, options))
    return ask_local(prompt, model, options)


def check_read(prompt, read, options):
    """Прочитала ли Ollama весь промпт: read — сколько токенов она прочитала (prompt_eval_count). В токене не больше
    CHARS_PER_TOKEN_MAX знаков — прочитано меньше, чем возможно для такого текста, и не больше окна, значит начало
    промпта (инструкция, критерии) отрезано окном модели, и ответ был бы неверным. Старые версии Ollama режут молча;
    новые (0.40) читают промпт целиком, даже если он длиннее num_ctx."""
    if read and read <= options.get("num_ctx", read) and read * settings.CHARS_PER_TOKEN_MAX < len(prompt):
        need = round(len(prompt) / settings.CHARS_PER_TOKEN)
        raise AssistantError(f"Промпт не поместился в окно локальной модели: она прочитала {read} токенов из примерно "
                             f"{need} — начало с инструкцией отрезано, ответ был бы неверным. Сократите резюме или "
                             f"«Дополнительно о себе» (Профиль → О себе) или обновите Ollama.")


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
                answer = json.load(response)
        except urllib.error.URLError as e:
            if isinstance(e.reason, ConnectionRefusedError):
                raise AssistantError("Ollama не запущена. Запустите её командой  ollama serve  и повторите.") from e
            raise
        check_read(prompt, answer.get("prompt_eval_count"), options)
        return same_script(answer["response"].strip())
    return waiting.run(call, "локальной модели", LOCAL_LIMIT,
                       AssistantError(f"Локальная модель не ответила за {LOCAL_LIMIT // 60} минут — пропускаю."))
