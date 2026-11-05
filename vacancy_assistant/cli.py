"""Командная строка: python3 razbor.py [--profile ИМЯ] [команда] …  (или python3 -m vacancy_assistant)

Команды. Профиль по умолчанию — имя из файла профили/по_умолчанию.txt (он не хранится в git).
Новый профиль создаётся мастером в окне программы (app):
    app                  окно программы в браузере (работает только на этом компьютере)
    (без команды)        разобрать новые вакансии и обновить сводку; --all — разобрать заново все
    add [ССЫЛКИ…]        скачать вакансии по ссылкам — hh.ru или любой сайт (без ссылок — из буфера обмена)
    search               найти новые вакансии: hh.ru по запросам из поиски.txt (если поиск включён)
                         и ленты Хабр Карьеры и GeekJob (если включены)
    summary              только пересобрать сводку
    letters [--all]      написать письма для вакансий с оценкой не ниже порога профиля (новые; --all — все)
    ratings [НОМЕРА]     добавить вакансии в мои-оценки.md пустыми строками (номера: 17 18 20-25)
    tune [РАУНДЫ]        автонастройка критериев по мои-оценки.md (модель профиля, по умолчанию 3 раунда)
    tune apply           применить лучшую версию критериев из настройка/
    resume ФАЙЛ          заполнить резюме.md из выгрузки резюме с hh.ru (TXT; можно PDF)
    prompt [НОМЕР]       показать промпт разбора целиком (для вакансии с номером или с заглушками)
    check-analyses [--all]  проверить разборы: все ли оценки, разделы и решение на месте (--all — все профили)

Что нужно: запущенный Ollama (ollama serve) и модель gemma4:12b.
"""
import sys

from . import analysis, answer, cloud, hh, ratings, resume_pdf, rss, sites, summary, tune
from .clipboard import clipboard_text
from .errors import AssistantError
from .files import numbered_files, read_vacancy
from .profile import Profile, default_profile_name, profile_names


def _utf8_console():
    """Кириллица в консоли Windows и при перенаправлении вывода в файл."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def run(args):
    profile_name = None
    if "--profile" in args:                       # --profile ИМЯ можно ставить в любом месте
        i = args.index("--profile")
        if i + 1 >= len(args):
            raise AssistantError("После --profile укажите имя профиля.")
        profile_name = args[i + 1]
        del args[i:i + 2]
    command = args[0] if args else ""

    if command == "app":
        from .app import serve
        serve(open_browser="--no-browser" not in args)
        return
    if command in ("help", "-h", "--help"):
        print(__doc__)
        return

    if command == "check-analyses":
        names = profile_names() if "--all" in args else [profile_name or default_profile_name()]
        for name in filter(None, names):
            found = answer.check_profile(Profile(name))
            print(f"{name}: {'замечаний нет' if not found else f'замечания в {len(found)}'}")
            for file, items in found:
                print(f"  {file}: " + "; ".join(items))
        return

    name = profile_name or default_profile_name()
    if not name:
        raise AssistantError("Профилей пока нет. Создайте профиль в окне программы: python3 razbor.py app")
    profile = Profile(name)
    cloud.use(profile)                                  # модель — та, что выбрана в профиле
    if command == "add":
        sites.add_any(profile, " ".join(args[1:]) or clipboard_text())      # hh.ru и любые другие сайты
    elif command == "search":
        feeds = rss.enabled(profile)
        if not feeds:
            hh.require_auto(profile)                    # ни hh, ни лент — понятная ошибка без обращения к сети
        found = (hh.search(profile) or []) if profile.hh_auto else []
        left = rss.leftover(profile.search_limit, len(found))          # лимит общий: ленты — остаток после hh.ru
        found += rss.search(profile, limit=left) if feeds and left != 0 else []
        if found:
            print("\nДальше:  python3 razbor.py  — разобрать, затем  python3 razbor.py letters")
    elif command == "summary":
        summary.write_summary(profile)
    elif command == "letters":
        analysis.write_letters(profile, redo="--all" in args)
    elif command == "ratings":
        ratings.fill_ratings(profile, ratings.parse_numbers(args[1:]))
    elif command == "tune":
        if len(args) > 1 and args[1] == "apply":
            tune.tune_apply(profile)
        else:
            tune.tune(profile, int(args[1]) if len(args) > 1 else 3)
    elif command in ("resume", "resume-pdf"):
        if len(args) < 2:
            raise AssistantError("Укажите файл: python3 razbor.py resume путь/к/резюме.txt")
        resume_pdf.resume_from_file(profile, args[1])
    elif command == "prompt":
        vacancy = "<ВАКАНСИЯ>"
        if len(args) > 1:
            files = numbered_files(profile.vacancies)
            n = int(args[1])
            if n not in files:
                raise AssistantError(f"Нет вакансии с номером {n} в {profile.vacancies.name}/")
            vacancy = read_vacancy(files[n])[0]
        print(profile.analysis_prompt(profile.read_resume(), vacancy))
    elif command in ("", "--all"):
        analysis.analyze(profile, redo="--all" in args)
    else:
        raise AssistantError(f"Неизвестная команда «{command}». Список команд: python3 razbor.py help")


def main(argv=None):
    _utf8_console()
    try:
        run(list(sys.argv[1:] if argv is None else argv))
    except AssistantError as e:
        sys.exit(str(e))
    except KeyboardInterrupt:
        sys.exit("Остановлено.")


if __name__ == "__main__":
    main()
