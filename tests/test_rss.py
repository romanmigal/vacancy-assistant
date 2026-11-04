"""Вакансии из RSS-лент Хабр Карьеры и GeekJob (#39): разбор ленты, отбор по названию, без дублей, раз в час."""
import json
import unittest
from datetime import datetime, timedelta

from helpers import TempProfile

from vacancy_assistant import app as A, rss
from vacancy_assistant.files import read_vacancy
from vacancy_assistant.textio import read_text

HABR = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Вакансии — Хабр Карьера</title>
<item><title>Требуется «CTO «Интерактивные сервисы»» (Москва)</title>
  <description>Компания «Пример Здоровье» ищет специалиста.</description><author>Пример Здоровье</author>
  <link>https://career.habr.com/vacancies/1000000001</link><guid>1000000001</guid></item>
<item><title>Требуется «Architect / CTO» (Москва, до 400 000 ₽)</title>
  <author>Пример Лаб</author><link>https://career.habr.com/vacancies/1000000002</link><guid>1000000002</guid></item>
<item><title>Требуется «Руководитель направления/Team Lead» (Москва)</title>
  <author>Пример Банк</author><link>https://career.habr.com/vacancies/1000000003</link><guid>1000000003</guid></item>
</channel></rss>"""

GEEK = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>Вакансии Geekjob</title>
<item><author>Клмпания Пример Роботикс</author><title>IT Sales manager</title>
  <link>https://geekjob.ru/vacancy/aaa111?utm_source=rss</link><guid>h1</guid></item>
<item><author>Агентство Пример & Партнёры</author><title>ML Engineer &amp; Lead</title>
  <link>https://geekjob.ru/vacancy/ccc333?utm_source=rss</link><guid>h3</guid></item>
<item><author>Компания Пример Софт</author><title>ИТ-директор</title>
  <description><![CDATA[Компания Пример Софт ищет специалиста.]]></description>
  <link>https://geekjob.ru/vacancy/bbb222?utm_source=rss</link><guid>h2</guid></item>
</channel></rss>"""


def page(title, company):
    jp = {"@type": "JobPosting", "title": title, "hiringOrganization": {"name": company},
          "description": "<p>" + "Обязанности: руководить ИТ, строить команду и платформу. " * 10 + "</p>"}
    return f'<html><script type="application/ld+json">{json.dumps(jp, ensure_ascii=False)}</script></html>'


PAGES = {"https://career.habr.com/vacancies/1000000001": page("CTO «Интерактивные сервисы»", "Пример Здоровье"),
         "https://career.habr.com/vacancies/1000000002": page("Architect / CTO", "Пример Лаб"),
         "https://geekjob.ru/vacancy/bbb222": page("ИТ-директор", "Пример Софт")}


class Fetch:
    def __init__(self):
        self.urls = []

    def __call__(self, url):
        self.urls.append(url)
        if url.startswith(rss.HABR_URL.split("?")[0]):
            return HABR
        if url == rss.GEEKJOB_URL:
            return GEEK
        return PAGES[url]


class Parse(unittest.TestCase):
    def test_habr(self):
        items = rss.parse(HABR, "habr")
        self.assertEqual([(i["id"], i["title"], i["company"], i["where"]) for i in items[:2]],
                         [("habr:1000000001", "CTO «Интерактивные сервисы»", "Пример Здоровье", "Москва"),
                          ("habr:1000000002", "Architect / CTO", "Пример Лаб", "Москва, до 400 000 ₽")])

    def test_geekjob(self):
        items = rss.parse(GEEK, "geekjob")
        self.assertEqual([(i["id"], i["company"], i["link"]) for i in items],
                         [("geekjob:h1", "Пример Роботикс", "https://geekjob.ru/vacancy/aaa111"),
                          ("geekjob:h3", "Агентство Пример & Партнёры", "https://geekjob.ru/vacancy/ccc333"),   # «&» без экранирования
                          ("geekjob:h2", "Пример Софт", "https://geekjob.ru/vacancy/bbb222")])
        self.assertEqual(items[1]["title"], "ML Engineer & Lead")

    def test_bad_feed(self):
        with self.assertRaises(Exception):
            rss.parse("<html>не лента", "habr")


class Search(unittest.TestCase):
    def test_fit_source_once_an_hour_no_dupes(self):
        with TempProfile() as t:
            p = t.profile
            rss.set_enabled(p, {"habr": True, "geekjob": True})
            self.assertEqual(rss.enabled(p), ["habr", "geekjob"])
            fetch, now = Fetch(), datetime(2026, 11, 3, 12, 0)
            saved = rss.search(p, log=lambda *_: None, fetch_page=fetch, sleep=lambda s: None, now=now)
            self.assertEqual(sorted(read_vacancy(f)[1]["title"] for f in saved),
                             ["Architect / CTO", "CTO «Интерактивные сервисы»", "ИТ-директор"])     # Team Lead, Sales — отсеяны
            self.assertEqual(sum("career.habr.com/vacancies/rss" in u for u in fetch.urls), 3)   # по запросу из поиски.txt
            text = read_text(next(f for f in saved if "ИТ-директор" in f.name))
            self.assertIn("**Источник:** GeekJob (RSS)", text)
            self.assertIn("**Ссылка:** https://geekjob.ru/vacancy/bbb222", text)
            seen = read_text(p.seen)
            self.assertIn("habr:1000000003\t", seen)
            self.assertIn("отсеяна", seen)

            fetch.urls.clear()                                       # через 10 минут — ленту не читаем
            self.assertEqual(rss.search(p, log=lambda *_: None, fetch_page=fetch, sleep=lambda s: None,
                                        now=now + timedelta(minutes=10)), [])
            self.assertEqual(fetch.urls, [])
            again = rss.search(p, log=lambda *_: None, fetch_page=fetch, sleep=lambda s: None,
                               now=now + timedelta(hours=2))              # через два часа — те же вакансии не скачиваем
            self.assertEqual((again, len(list(p.vacancies.glob("*.md")))), ([], 3))
            self.assertTrue(fetch.urls and all("/rss" in u for u in fetch.urls))

    def test_hh_recheck_ignores_rss(self):
        with TempProfile() as t:
            p = t.profile
            rss.set_enabled(p, {"geekjob": True})
            rss.search(p, log=lambda *_: None, fetch_page=Fetch(), sleep=lambda s: None)
            from vacancy_assistant import hh
            self.assertTrue(all(r["id"].isdigit() for r in hh.recheck_filtered(p)))

    def test_update_without_hh(self):
        """Поиск на hh.ru выключен, ленты включены — «Найти новые вакансии» читает только ленты."""
        with TempProfile() as t:
            p = t.profile
            p.config["hh_авто"] = {"включено": False}
            p.save_config()
            fetch = Fetch()
            with self.assertRaises(Exception):                     # ни hh, ни лент — отказ
                A.make_work(A.Profile("example", t.profiles), "update", {}, fetch_page=fetch, ask=lambda *a, **k: "")
            rss.set_enabled(p, {"geekjob": True})
            lines = []
            _, work = A.make_work(A.Profile("example", t.profiles), "update", {}, fetch_page=fetch,
                                  ask=lambda *a, **k: "Оценка: 5/10\nОткликаться: нет")
            work(lines.append)
            self.assertTrue(any("только ленты" in l for l in lines))
            self.assertFalse(any("hh.ru/" in u for u in fetch.urls))
            self.assertEqual(len(list(p.vacancies.glob("*.md"))), 1)


if __name__ == "__main__":
    unittest.main()
