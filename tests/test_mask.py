"""Скрытие личных данных перед GigaChat: метки в запросе, обратная замена в ответе."""
import unittest

from helpers import TempProfile

from vacancy_assistant import app as A, cloud, contacts, mask

TEXT = ("Иван Петров, ivan.petrov@example.com, +7 (916) 123-45-67, https://www.linkedin.com/in/ivan-petrov-123, "
        "t.me/ivanp, живу: ул. Ленина, д. 5.\nПисьмо Ивану Петрову от Ivan Petrov. Знакомая — Мария Сидорова "
        "(у Марии Сидоровой), ещё Anna Smith.")


def masked(**kw):
    return mask.Mask(["Иван Петров"], ["Мария Сидорова", "Anna Smith", "Иван"], **kw)


class Hide(unittest.TestCase):
    def test_nothing_personal_left(self):
        m = masked(addresses=["ул. Ленина, д. 5"])
        out = m.hide(TEXT)
        for secret in ("Иван", "Петров", "Ivan", "Petrov", "Мари", "Сидоров", "Anna", "Smith", "@", "916", "linkedin",
                       "t.me", "Ленина"):
            with self.subTest(secret):
                self.assertNotIn(secret, out)
        self.assertIn("[Кандидат]", out)
        self.assertEqual(out.count("[Контакт 1]"), 2)                    # падежи — одна метка

    def test_words_are_not_names(self):
        """Обычные слова и чужие фамилии не скрываются: регистр и окончания."""
        m = mask.Mask(["Вера Романова"], [])
        text = "Вера в успех. Опыт: роман с данными, вера в команду. Сергей Иванов, Романовский."
        self.assertEqual(m.hide(text), "[Кандидат] в успех. Опыт: роман с данными, вера в команду. Сергей Иванов, Романовский.")

    def test_soft_sign_and_order(self):
        """Фамилия на «ь» в именительном падеже и порядок «Фамилия Имя» — одна метка."""
        m = mask.Mask(["Олег Коваль"], [])
        self.assertEqual(m.hide("# Коваль Олег\nКовалю, Ковалем, Koval Oleg"), "# [Кандидат]\n[Кандидат], [Кандидат], [Кандидат]")

    def test_contact_needs_full_name(self):
        """У знакомых одно имя («Иван») не скрывается — только имя с фамилией."""
        self.assertEqual(mask.Mask([], ["Иван"]).hide("Иван Грозный"), "Иван Грозный")

    def test_hh_export_experience(self):
        """Резюме из выгрузки hh: компания — строкой после периода работы, сайт — после города."""
        from pathlib import Path
        from vacancy_assistant import resume_html
        md = resume_html.hh_html_markdown((Path(__file__).parent / "fixtures" / "резюме" / "Смирнова — выгрузка hh.html").read_text(encoding="utf-8"))
        past = mask.past_employers(md)
        self.assertEqual([p[0] for p in past], ["ООО «Северный Завод Металлоконструкций»", "ООО «Балтийская Логистическая Компания»"])
        out = mask.Mask([], [], companies=past).hide(md)
        self.assertNotIn("Северный Завод", out)
        self.assertNotIn("szmk.example", out)

    def test_plain_text_experience(self):
        """Резюме простым текстом: период, должность и компания в одной строке."""
        md = ("Опыт работы — 10 лет\n\n"
              "2021 — н.в. — Team Lead Java, «Северный ритейл» (e-commerce, 4 000 сотрудников)\n"
              "- Руковожу командой из 9 разработчиков, 2019 — 2020 — миграция\n"
              "Март 2017 – 2021: ООО Финтех Решения, Senior Java Developer\n"
              "01.2015 - 12.2016, Java Developer в АО «Интеграционные системы»\n"
              "2014 — 2015 — Java Developer, стартап\n")
        self.assertEqual([p[0] for p in mask.past_employers(md)],
                         ["«Северный ритейл»", "ООО Финтех Решения", "АО «Интеграционные системы»"])
        out = mask.Mask([], [], companies=mask.past_employers(md)).hide(md)
        self.assertNotIn("Северный ритейл", out)
        self.assertNotIn("Финтех Решения", out)

    def test_vacancy_company_stays(self):
        m = masked(companies=mask.past_employers("**ООО «Пример Ритейл» (Москва)** · ИТ-директор · 2021 — 2026\n"))
        out = m.hide("Был в ООО «Пример Ритейл», потом в Пример Ритейл. Вакансия: ООО «Ромашка».")
        self.assertEqual(out, "Был в [Компания 1], потом в [Компания 1]. Вакансия: ООО «Ромашка».")


class Show(unittest.TestCase):
    def test_round_trip(self):
        m = masked(addresses=["ул. Ленина, д. 5"])
        hidden = m.prompt("Напиши письмо. Подпись: Иван Петров, ivan.petrov@example.com, https://www.linkedin.com/in/ivan-petrov-123")
        self.assertTrue(hidden.startswith(mask.NOTE))
        reply = "Добрый день! … С уважением, [Кандидат], [Почта 1], [Ссылка 1]"
        self.assertEqual(m.show(reply), "Добрый день! … С уважением, Иван Петров, ivan.petrov@example.com, "
                                        "https://www.linkedin.com/in/ivan-petrov-123")

    def test_inflected_label(self):
        m = masked()
        m.hide("Мария Сидорова")
        self.assertEqual(m.show("Передайте [Контакту 1] и [Кандидата] привет, [Контакт 9]"),
                         "Передайте Мария Сидорова и [Кандидата] привет, [Контакт 9]")

    def test_no_note_when_nothing_hidden(self):
        self.assertEqual(mask.Mask([], []).prompt("Оцени вакансию"), "Оцени вакансию")


class Profile(unittest.TestCase):
    def test_for_profile(self):
        with TempProfile() as t:
            contacts.save(t.profile, [{"id": "c1", "name": "Мария Сидорова", "company": "Ромашка"}])
            m = mask.Mask.for_profile(t.profile)
            out = m.hide(t.profile.read_resume())
            self.assertNotIn("Петров", out)
            self.assertNotIn("@", out)
            self.assertIn("Пример Ритейл", out)                       # прошлые работодатели — по выключателю
            self.assertNotIn("Сидорова", m.hide("Референсер: Мария Сидорова"))
            mask.set_hide_companies(t.profile, True)
            self.assertNotIn("Пример Ритейл", mask.Mask.for_profile(t.profile).hide(t.profile.read_resume()))

    def test_cloud_sends_masked(self):
        """В GigaChat уходит запрос с метками, а программа получает ответ с настоящими данными."""
        with TempProfile() as t:
            sent = []
            old = cloud._api
            cloud._api = lambda cfg, path, body, timeout=300: sent.append(body) or {
                "choices": [{"message": {"content": "С уважением, [Кандидат]"}}]}
            try:
                cloud.use(t.profile)
                reply = cloud.ask("Резюме: Иван Петров, ivan.petrov@example.com", cfg={"auth_key": "x"})
            finally:
                cloud._api = old
                cloud.use(None)
            text = sent[0]["messages"][0]["content"]
            self.assertNotIn("Петров", text)
            self.assertNotIn("ivan.petrov", text)
            self.assertEqual(reply, "С уважением, Иван Петров")

    def test_route(self):
        with TempProfile() as t:
            app = A.App(t.profiles, fetch_page=None, ask=None, check=lambda: {"ollama": True, "model_ok": True})
            r = app.handle("GET", "/api/mask", {"profile": ["example"]}, {})
            self.assertEqual((r["companies"], r["past"][0]), (False, "ООО «Пример Ритейл»"))
            self.assertNotIn("Петров", r["resume"])
            self.assertNotIn("Пример Ритейл", app.handle("GET", "/api/mask", {"profile": ["example"], "companies": ["1"]}, {})["resume"])
            app.handle("POST", "/api/profile/settings", {}, {"profile": "example", "hide_companies": True})
            self.assertTrue(mask.hide_companies(t.profile.__class__("example", t.profiles)))


if __name__ == "__main__":
    unittest.main()
