"""Резюме из файла → резюме.md профиля. Лучше всего — выгрузка hh.ru в «TXT» (resume_html); PDF разбирается
правилами под выгрузку hh и хуже: колонки PDF путают порядок блоков. Модель в разборе не участвует."""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

from .errors import AssistantError
from .resume_html import PRIVATE, hh_html_markdown, is_hh_html
from .textio import log_print, read_text, write_text

JXA_PDF_TEXT = """ObjC.import('PDFKit');
function run(argv) {
  var d = $.PDFDocument.alloc.initWithURL($.NSURL.fileURLWithPath(argv[0]));
  return d ? ObjC.unwrap(d.string) : '';
}"""
MONTHS = "Январь|Февраль|Март|Апрель|Май|Июнь|Июль|Август|Сентябрь|Октябрь|Ноябрь|Декабрь"
HH_SECTIONS = ("Желаемая должность и зарплата", "Опыт работы", "Образование", "Повышение квалификации, курсы",
               "Повышение квалификации",
               "Тесты, экзамены", "Электронные сертификаты", "Ключевые навыки", "Навыки", "Опыт вождения",
               "Дополнительная информация", "Обо мне", "Рекомендации", "Портфолио", "Знание языков",
               "Гражданство, время в пути до работы")


def pdf_text(path):
    """Текст PDF: pdftotext, если установлен; иначе pypdf; иначе встроенный в macOS PDFKit."""
    if shutil.which("pdftotext"):
        r = subprocess.run(["pdftotext", "-layout", str(path), "-"], capture_output=True)
        text = r.stdout.decode("utf-8", errors="replace")
        if r.returncode == 0 and text.strip():
            return text
    try:
        import pypdf
        return "\n".join(page.extract_text() or "" for page in pypdf.PdfReader(str(path)).pages)
    except ImportError:
        pass
    if sys.platform == "darwin":
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(JXA_PDF_TEXT)
        r = subprocess.run(["osascript", "-l", "JavaScript", f.name, str(path)], capture_output=True)
        Path(f.name).unlink()
        text = r.stdout.decode("utf-8", errors="replace")
        if r.returncode == 0 and text.strip():
            return text
    raise AssistantError("Не удалось прочитать PDF. Установите pypdf (pip3 install pypdf) "
                         "или poppler (на Mac: brew install poppler).")


def hh_resume_markdown(text):
    """Текст выгрузки hh → markdown: заголовки разделов, периоды работы, списки, склеенные строки.
    Телефон, почта и дата рождения убираются: модели для разбора они не нужны."""
    text = text.replace("\r", "").replace("\xa0", " ").replace(" ", " ")
    lines = [l.strip() for l in text.split("\n")]
    period_re = rf"({MONTHS}) \d{{4}}"
    is_period = lambda s: bool(re.match(period_re, s))
    out, pending = [], []          # pending — периоды, которые PDF выдал раньше их блока компании

    def add_period(period):
        if out and out[-1].startswith("### ") and pending is not None and out[-1] != "":
            pending.append([period, 1])            # два периода подряд: второй — для следующей компании,
                                                   # а ближайший блок компании — ещё для первого
        else:
            out.extend(["", f"### {period}"])

    i = 0
    while i < len(lines):
        l = lines[i]
        i += 1
        page = re.fullmatch(r"\d{1,3}", l) and (not out or re.search(r"[.!?;:»)]$", out[-1]))   # номер страницы,
        if not l or "Резюме обновлено" in l or page or PRIVATE.search(l):          # а не «…подрядчика из / 20»
            continue                                            # служебное и личные контакты
        if not out:
            out.append(f"# {l}")                               # первая строка — имя
            continue
        section = next((s for s in sorted(HH_SECTIONS, key=len, reverse=True) if l.startswith(s)), None)
        if section:
            for p_, _ in pending:                              # раздел закончился — выложить отложенные периоды
                out.extend(["", f"### {p_}"])
            pending.clear()
            if section in ("Опыт работы", "Желаемая должность и зарплата") or l == section:
                out += ["", f"## {l}", ""]
            else:                                              # «Обо мне CIO с…» → заголовок + текст
                out += ["", f"## {section}", "", l[len(section):].strip(" :")]
            continue
        if is_period(l):                                       # период работы: склеиваем даты и длительность
            period = l
            while i < len(lines) and (period.endswith("—") or re.fullmatch(
                    rf"({MONTHS})( \d{{4}})?|\d{{4}}|(по )?настоящее( время)?|время", lines[i])):
                period += " " + lines[i]
                i += 1
            if i < len(lines) and re.match(r"\d+ (год|года|лет|месяц)", lines[i]):
                duration = lines[i]
                i += 1
                if i < len(lines) and re.fullmatch(r"(\d+ )?месяц\w*", lines[i]):   # «3 года 11» + «месяцев»
                    duration += " " + lines[i]
                    i += 1
                period += f" ({duration})"
            add_period(period)
            continue
        if pending and i < len(lines) and re.search(r"www\.|\.\w{2,4}/", lines[i]):   # начало блока компании
            if pending[0][1]:
                pending[0][1] -= 1                             # этот блок — для уже выведенного периода
            else:
                out.extend(["", f"### {pending.pop(0)[0]}"])
        if l.startswith(("— ", "• ", "- ")):
            out.append("- " + l[2:].strip())
            continue
        if re.fullmatch(r"[А-ЯЁA-Z ]{4,}:.*", l):              # ДОСТИЖЕНИЯ:, ИТОГ: …
            head, _, rest = l.partition(":")
            out.append(f"**{head.capitalize()}:**{(' ' + rest.strip()) if rest.strip() else ''}")
            continue
        prev = out[-1] if out else ""
        list_tail = prev.startswith("- ") and l[0].islower()      # пункт списка, порванный переносом
        wrapped = prev and not prev.startswith(("#", "**")) and (list_tail or not prev.endswith((".", "!", "?", ";", ":"))) and (
            list_tail or (prev.startswith("- ") and len(prev) >= 40)        # продолжение длинного пункта списка
            or l[0].islower() or l[0] in "(«,;"                 # продолжение предложения
            or len(prev) >= 60)                                # длинная строка, порванная переносом
        if wrapped:
            out[-1] = prev + " " + l
        else:
            out.append(l)
    for p_, _ in pending:
        out.extend(["", f"### {p_}"])
    md = "\n".join(out)
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip() + "\n"


def file_markdown(data):
    """Файл резюме (байты) → markdown без телефона, почты и даты рождения: выгрузка hh в «TXT» (HTML),
    PDF или простой текст (его — как есть)."""
    if data.startswith(b"%PDF"):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "резюме.pdf")
            with open(path, "wb") as f:
                f.write(data)
            return hh_resume_markdown(pdf_text(path))
    if data.startswith(b"PK") or b"\0" in data[:4096]:          # docx, архив, картинка
        raise AssistantError("Этот формат не читается. На hh.ru: резюме → «Скачать» → TXT; "
                             "или вставьте текст резюме в поле ниже.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1251")
    if is_hh_html(text):
        return hh_html_markdown(text)
    if re.search(r"<(html|body|div)\b", text, re.I):
        raise AssistantError("Это страница, а не выгрузка резюме с hh.ru. На hh.ru: резюме → «Скачать» → TXT.")
    lines = [l.rstrip() for l in text.replace("\r", "").split("\n") if not PRIVATE.search(l.strip())]
    return "\n".join(lines).strip() + "\n"


def resume_from_file(profile, path, log=None):
    """Записывает резюме.md профиля из файла; прежнее резюме сохраняется рядом. Возвращает путь резюме."""
    log = log or log_print
    path = Path(path).expanduser()
    if not path.exists():
        raise AssistantError(f"Нет файла: {path}")
    md = file_markdown(path.read_bytes())
    target = profile.dir / "резюме.md"
    if target.exists() and "ЗАМЕНИТЬ" not in read_text(target):
        backup = target.with_name(f"резюме (до {date.today().strftime('%d.%m.%Y')}).md")
        shutil.copy(target, backup)
        log(f"Прежнее резюме сохранено: {backup.name}")
    write_text(target, md)
    log(f"Записано: {target} ({len(md)} знаков). Телефон, почта и дата рождения не переносятся.")
    if (profile.dir / profile.config["резюме"]).resolve() != target.resolve():
        log(f"Внимание: профиль сейчас берёт резюме из «{profile.config['резюме']}». "
            "Чтобы использовался этот файл, поставьте в профиль.json: \"резюме\": \"резюме.md\"")
    log("Проверьте файл: разборы опираются только на то, что в резюме"
        + (", а порядок блоков в PDF иногда путается." if path.suffix.lower() == ".pdf" else "."))
    return target
