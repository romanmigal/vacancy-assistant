"""Весь путь на копии профиля-примера: скачивание → разбор → письма → сводка → статусы → оценки → настройка.
Модель и hh.ru подменены — тесты работают без сети и без Ollama."""
import os
import shutil
import unittest

from helpers import SEARCH_HTML, VACANCY_HTML, TempProfile, fake_model, vacancy_page

from vacancy_assistant import AssistantError, analysis, cli, hh, ratings, summary as S, tune as T
from vacancy_assistant.files import read_meta
from vacancy_assistant.textio import read_json, read_text, write_json, write_text


class Pipeline(unittest.TestCase):
    def test_add_and_search(self):
        with TempProfile() as t:
            p = t.profile
            saved = hh.add_vacancies(p, ["123456"], log=lambda *_: None, fetch_page=lambda url: VACANCY_HTML)
            self.assertEqual([f.name for f in saved], ["01 ИТ-директор — ООО Пример.md"])
            again = hh.add_vacancies(p, ["123456"], log=lambda *_: None, fetch_page=lambda url: VACANCY_HTML)
            self.assertEqual(again, [])                                         # уже есть — не дублируем
            self.assertEqual(read_text(p.seen).count("123456\t"), 1)            # по ссылке — тоже в просмотренных
            self.assertIn("\tпо ссылке\t", read_text(p.seen))

            write_text(p.searches, "# запросы\nCTO\n")
            pages = lambda url: SEARCH_HTML if "search" in url and "page=0" in url else (
                "" if "search" in url else vacancy_page(url))
            found = hh.search(p, log=lambda *_: None, fetch_page=pages, sleep=lambda s: None)
            self.assertEqual(len(found), 2)                                      # «Начальник отдела» отсеян
            seen = read_text(p.seen)
            self.assertIn("222222\t", seen)
            self.assertIn("отсеяна\tНачальник отдела ИТ", seen)

    def test_search_limit_and_settings(self):
        from vacancy_assistant import setup
        from vacancy_assistant.profile import Profile
        with TempProfile() as t:
            setup.set_search_settings(t.profile, 14, 1)
            p = Profile("example", t.profiles)
            self.assertEqual((p.search_days, p.search_limit), (14, 1))
            write_text(p.searches, "CTO\n")
            pages = lambda url: SEARCH_HTML if "search" in url and "page=0" in url else (
                "" if "search" in url else vacancy_page(url))
            self.assertIn("search_period=14", hh.search_url("CTO", "area=1", p.search_days))
            first = hh.search(p, log=lambda *_: None, fetch_page=pages, sleep=lambda s: None)
            self.assertEqual(len(first), 1)                                    # лимит 1 из двух подходящих
            self.assertNotIn("333333", read_text(p.seen))                     # отложенная — не в просмотренных
            second = hh.search(p, log=lambda *_: None, fetch_page=pages, sleep=lambda s: None)
            self.assertEqual(len(second), 1)                                   # её берёт следующий поиск
            setup.set_search_settings(p, 7, "")
            self.assertIsNone(Profile("example", t.profiles).search_limit)    # пусто — все
            for days, limit in ((0, 5), (31, 5), (7, 0)):
                with self.assertRaises(setup.AssistantError):
                    setup.set_search_settings(p, days, limit)
        with TempProfile() as t:                                               # разовый лимит первого поиска
            write_text(t.profile.searches, "CTO\n")
            once = hh.search(t.profile, log=lambda *_: None, fetch_page=pages, sleep=lambda s: None, limit=1)
            self.assertEqual(len(once), 1)

    def test_search_salary_filter(self):
        """Зарплата на hh.ru: фильтр в каждом запросе выдачи; без настройки — адрес как раньше."""
        from vacancy_assistant import setup
        from vacancy_assistant.profile import Profile
        with TempProfile() as t:
            write_text(t.profile.searches, "CTO\n")
            urls = []
            fetch = lambda url: (urls.append(url), "")[1]
            hh.search(t.profile, log=lambda *_: None, fetch_page=fetch, sleep=lambda s: None)
            self.assertFalse(any("salary" in u for u in urls))
            self.assertIn("зарплата в поиске", setup.update_profile(t.profile, {"search_salary": "250 000", "search_salary_only": True},
                                                                      log=lambda *_: None)["changed"])
            p, urls[:] = Profile("example", t.profiles), []
            self.assertEqual(setup.answers_from_profile(p)["search_salary"], "250000")
            self.assertEqual((p.search_salary, p.search_salary_only), (250000, True))
            logs = []
            hh.search(p, log=logs.append, fetch_page=fetch, sleep=lambda s: None)
            self.assertTrue(urls and all("&salary=250000&only_with_salary=true" in u for u in urls))
            self.assertIn("зарплата от 250 000 ₽", " ".join(logs))
            setup.update_profile(p, {"search_salary": "", "search_salary_only": False}, log=lambda *_: None)
            self.assertEqual(hh.salary_filter(Profile("example", t.profiles)), "")

    def test_search_in_title_by_default(self):
        """Слова запроса — только в названии вакансии (как на сайте «в названии вакансии»); галочка — по всему тексту."""
        from vacancy_assistant import setup
        from vacancy_assistant.profile import Profile
        with TempProfile() as t:
            write_text(t.profile.searches, "CTO\n")
            urls, logs = [], []
            fetch = lambda url: (urls.append(url), "")[1]
            hh.search(t.profile, log=logs.append, fetch_page=fetch, sleep=lambda s: None)
            self.assertTrue(urls and all("&search_field=name" in u for u in urls))
            self.assertIn("слова запроса — в названии вакансии", " ".join(logs))
            self.assertIn("где искать слова запроса", setup.update_profile(t.profile, {"search_full_text": True}, log=lambda *_: None)["changed"])
            p, urls[:] = Profile("example", t.profiles), []
            self.assertTrue(setup.answers_from_profile(p)["search_full_text"])
            hh.search(p, log=lambda *_: None, fetch_page=fetch, sleep=lambda s: None)
            self.assertTrue(urls and not any("search_field" in u for u in urls))

    def test_search_salary_from_answers(self):
        """Фильтр на шаге «Отбор при поиске» не задавали — поиск берёт «Зарплата от» из опросника; сохранили пустым — без фильтра."""
        from vacancy_assistant import setup
        from vacancy_assistant.profile import ANSWERS_FILE, CONFIG_FILE, Profile
        with TempProfile() as t:
            d = t.profile.dir
            write_json(d / ANSWERS_FILE, {"salary": "600 000"})
            c = read_json(d / CONFIG_FILE)
            c["поиск"].pop("зарплата_от", None)
            write_json(d / CONFIG_FILE, c)
            p = Profile("example", t.profiles)
            self.assertEqual(hh.salary_filter(p), "&salary=600000")
            self.assertEqual(setup.answers_from_profile(p)["search_salary_set"], False)   # мастер подставит число из опросника
            setup.update_profile(p, {"search_salary": "", "search_salary_only": False, "search_salary_set": True}, log=lambda *_: None)
            self.assertEqual(hh.salary_filter(Profile("example", t.profiles)), "")       # сохранили пустым — без фильтра

    def test_analysis_letters_summary_statuses(self):
        with TempProfile() as t:
            p = t.profile
            t.add_vacancy(1, "ИТ-директор")
            t.add_vacancy(2, "Начальник отдела ИТ")
            done = analysis.analyze(p, log=lambda *_: None, ask=fake_model)
            self.assertEqual(len(done), 2)
            stages = {read_meta(f)["title"]: read_meta(f)["stage"] for f in done}
            self.assertEqual(stages, {"ИТ-директор": "full", "Начальник отдела ИТ": "short"})   # «нет» — только короткая
            self.assertEqual(read_meta(done[0])["score"], 8)
            self.assertEqual(analysis.analyze(p, log=lambda *_: None, ask=fake_model), [])   # только новые

            letters = analysis.write_letters(p, log=lambda *_: None, ask=fake_model)
            self.assertEqual([f.name for f in letters], ["01 ИТ-директор — ООО Пример.md"])  # только с оценкой 7+

            text = read_text(p.summary)
            self.assertIn("## Не обработано (2)", text)
            self.assertIn("vacancy-status#s1]", text)
            self.assertIn("[разбор](разборы/01%20ИТ-директор%20—%20ООО%20Пример.md)", text)

            S.set_status(p, "s2", "no")
            S.write_summary(p, log=lambda *_: None)
            text = read_text(p.summary)
            self.assertIn("## Не обработано (1)", text)
            self.assertIn("## Архив (1)", text)
            self.assertIn("## Интервью (0)", text)                            # новый раздел — между «Интересно» и «Архивом»
            self.assertLess(text.index("## Интересно"), text.index("## Интервью"))
            self.assertLess(text.index("## Интервью"), text.index("## Архив"))
            self.assertNotIn("\r", read_text(p.status_file))
            self.assertIn("`INPUT[toggle(onValue(yes), offValue(no)):профили/example/vacancy-status#f1]`", text)   # флаг в Obsidian
            write_text(p.status_file, read_text(p.status_file).replace("---\n", "---\nf1: yes\nf2: no\n", 1))
            self.assertEqual(S.read_flags(p), {1})                    # «no» из Obsidian — флага нет

    def test_full_analysis_failure_keeps_short(self):
        with TempProfile() as t:
            p = t.profile
            t.add_vacancy(1, "ИТ-директор")
            odd = lambda prompt, *a: (fake_model(prompt, *a) if "Ответь строго в таком формате, без пояснений" in prompt
                                      else "Пришлите полный текст вакансии.")
            done = analysis.analyze(p, log=lambda *_: None, ask=odd)
            meta = read_meta(done[0])
            self.assertEqual((meta["stage"], meta["score"], meta["decision"]), ("short", 8, "да"))   # короткая осталась

    def test_full_analysis_retry_and_local_fallback(self):
        """Модель ответила не по формату — ещё попытка; GigaChat отказался — разбирает локальная модель."""
        from unittest import mock
        from vacancy_assistant import cloud, settings
        REFUSAL = "К сожалению, иногда генеративные языковые модели могут создавать некорректные ответы…"
        with TempProfile() as t:
            p = t.profile
            path = t.add_vacancy(1, "ИТ-директор")
            calls, lines = [], []
            flaky = lambda prompt, *a: calls.append(1) or (REFUSAL if len(calls) == 1 else fake_model(prompt, *a))
            target, result, _ = analysis.full_analysis(p, path, log=lines.append, ask=flaky)
            self.assertEqual((len(calls), result["score"]), (2, 8))                       # со второй попытки
            self.assertTrue(any("ещё раз" in l for l in lines))

            refuse = lambda prompt, *a: REFUSAL
            with mock.patch.object(cloud, "active", lambda profile=None: True):
                target, result, _ = analysis.full_analysis(p, path, log=lines.append, ask=refuse, local=fake_model)
            self.assertEqual((result["score"], read_meta(target)["model"]), (8, settings.MODEL))   # разобрала локальная
            self.assertTrue(any("локальной моделью" in l for l in lines))

            target.unlink()                                                               # локальной нет — без оценки
            def offline(prompt, *a):
                raise AssistantError("Ollama не запущена.")
            with mock.patch.object(cloud, "active", lambda profile=None: True):
                with self.assertRaisesRegex(AssistantError, "пока без оценки"):
                    analysis.full_analysis(p, path, log=lines.append, ask=refuse, local=offline)
            self.assertFalse(target.exists())

    def test_ratings_and_tune(self):
        with TempProfile() as t:
            p = t.profile
            for n in range(1, 7):
                t.add_vacancy(n, "Начальник отдела ИТ" if n % 2 else "ИТ-директор")
            self.assertEqual(ratings.fill_ratings(p, log=lambda *_: None), [1, 2, 3, 4, 5, 6])
            lines = read_text(p.ratings).splitlines()
            filled = [l.replace("|  |  |  |", "| 3 | нет | отдел |") if l.startswith("| 01") else
                      l.replace("|  |  |  |", "| 8 | да | то, что ищу |") for l in lines if l.startswith("| 0")]
            write_text(p.ratings, "\n".join(lines[:9] + filled) + "\n")
            self.assertEqual(len(ratings.read_reference(p)), 6)

            def meta(prompt, model=None, options=None):
                if "Ты настраиваешь критерии" in prompt:
                    return "Что меняю: ничего\n=== КРИТЕРИИ ===\nЖёсткие:\nК1. Москва\n=== КОНЕЦ ==="
                return fake_model(prompt)
            best = T.tune(p, rounds=1, log=lambda *_: None, ask=meta)
            self.assertIn("решение совпало", best["metrics"])
            self.assertTrue((p.dir / "настройка" / "отчёт.md").exists())
            before = read_text(p.criteria_file)
            T.tune_apply(p, log=lambda *_: None)
            self.assertEqual(read_text(p.criteria_file), read_text(p.dir / "настройка" / "критерии — лучшие.txt"))
            self.assertTrue(any(f.name.startswith("критерии до применения") for f in (p.dir / "настройка").iterdir()))
            self.assertNotEqual(before, "")

    def test_cli(self):
        with TempProfile() as t:
            os.environ["VACANCY_ASSISTANT_HOME"] = str(t.tmp)
            try:
                cli.run(["--profile", "example", "summary"])
                self.assertTrue(t.profile.summary.exists())
                with self.assertRaises(SystemExit):
                    cli.main(["--profile", "nobody", "summary"])
                shutil.rmtree(t.profiles / "example")                       # профилей нет — подсказка про мастер
                with self.assertRaises(AssistantError) as e:
                    cli.run(["summary"])
                self.assertIn("razbor.py app", str(e.exception))
            finally:
                del os.environ["VACANCY_ASSISTANT_HOME"]


if __name__ == "__main__":
    unittest.main()
