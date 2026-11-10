"""Разбор ответа модели: все встречавшиеся варианты формата — образцы в fixtures/ответы/."""
import unittest
from pathlib import Path

from helpers import TempProfile

from vacancy_assistant import answer, files, vacancies as V

SAMPLES = Path(__file__).parent / "fixtures" / "ответы"


def sample(name):
    return (SAMPLES / f"{name}.txt").read_text(encoding="utf-8")


def scores(p):
    return tuple(p[k]["score"] if p[k] else None for k in ("can", "want", "total"))


class Samples(unittest.TestCase):
    def test_every_sample_has_scores_and_decision(self):
        """Каждый образец: три оценки, решение, отметки критериев, ни одной строки вне разделов."""
        for f in sorted(SAMPLES.glob("*.txt")):
            with self.subTest(f.stem):
                p = answer.parse(f.read_text(encoding="utf-8"))
                self.assertNotIn(None, scores(p))
                self.assertNotEqual(p["decision"], "?")
                self.assertTrue(p["criteria"])
                self.assertEqual(p["other"], [])

    def test_gemma(self):
        p = answer.parse(sample("полный Gemma"))
        self.assertEqual([(c["k"], c["mark"]) for c in p["criteria"]], [("1", "✅"), ("2", "❓"), ("3", "❌")])
        self.assertEqual([r["ok"] for r in p["requirements"]], [True, False])
        self.assertEqual(scores(p), (7, 3, 4))
        self.assertEqual(p["can"]["why"], ["опыт совпадает, кроме ERP"])
        self.assertEqual(p["strengths"], ["Перевод ИТ в облако", "Команда 60 человек"])
        self.assertEqual(p["gaps"], ["Нет опыта ERP — рассказать про учётные системы в рознице"])

    def test_gigachat_markup(self):
        p = answer.parse(sample("заголовки и жирный GigaChat"))
        self.assertEqual(scores(p), (8, 6, 7))
        self.assertEqual(p["can"]["why"], ["одно требование под вопросом"])     # пояснение в скобках
        self.assertEqual((p["decision"], p["decision_note"]), ("да, но с оговорками", "(уточнить зарплату)"))
        self.assertEqual(p["requirements"][0]["text"], "Команды от 50 человек — ✅ (60 человек в рознице)")

    def test_why_lines_below_score(self):
        """Вакансия 25: пояснения строками с тире под оценкой — к своей оценке, а не новым разделом."""
        p = answer.parse(sample("пояснения строками ниже"))
        self.assertEqual(p["can"]["why"], ["Нет опыта управления коммерческими продуктами", "Нет опыта в роли CTO"])
        self.assertEqual(p["want"]["why"], ["Интересная сфера"])
        self.assertEqual(p["strengths"], ["Большие команды"])

    def test_dot_after_score(self):
        """Вакансия 41: «Оценка: 4/10.» — общая оценка есть."""
        p = answer.parse(sample("точка после оценки"))
        self.assertEqual(scores(p), (9, 3, 4))
        self.assertEqual(p["want"]["why"], ["нарушен К1 (релокация)."])

    def test_total_after_gaps(self):
        """Вакансия 93: «Оценка» после «Пробелов», пункты «Сильных сторон» сразу после «Хочу» — на своих местах."""
        p = answer.parse(sample("оценка в конце"))
        self.assertEqual(scores(p), (9, 8, 8))
        self.assertEqual(p["strengths"], ["Стратегия и большие команды", "Архитектура и безопасность"])
        self.assertEqual(p["want"]["why"], ["интересная компания, но зарплата неизвестна"])

    def test_empty_section_and_inline(self):
        p = answer.parse(sample("пустые разделы"))
        self.assertIn("Сильные стороны", p["sections"])
        self.assertEqual(p["strengths"], [])
        self.assertEqual(len(p["gaps"]), 1)                                         # текст в строке заголовка
        self.assertIn("раздел «Сильные стороны» пустой", answer.problems(sample("пустые разделы")))

    def test_absent_as_text(self):
        p = answer.parse(sample("отсутствуют текстом"))
        self.assertEqual(p["strengths"], ["Отсутствуют — ни одного совпадения с требованиями вакансии нет."])
        self.assertEqual(len(p["gaps"]), 2)                                         # совет после пункта — отдельным пунктом

    def test_short(self):
        p = answer.parse(sample("короткая оценка"))
        self.assertEqual((len(p["criteria"]), scores(p), p["sections"]), (3, (9, 2, 2), []))
        self.assertEqual(answer.problems(sample("короткая оценка"), {"stage": "short", "score": 2, "can": 9, "want": 2}), [])

    def test_typo(self):
        """«Оцена: 4/10» (так ответила Gemma) — общая оценка не теряется."""
        self.assertEqual(scores(answer.parse(sample("опечатка в оценке"))), (8, 3, 4))


    def test_addressed_to_person(self):
        """«Хочешь: 7/10» (так ответил GigaChat) — оценка «Хочу» не теряется; «Можете» — это «Могу»."""
        text = "### Могу: 3/10 (мало опыта)\nХочешь: 7/10 (интересная отрасль)\nОценка: 4/10\n\n### Откликаться: нет"
        self.assertEqual(answer.result(text), {"score": 4, "can": 3, "want": 7, "decision": "нет"})
        self.assertEqual(answer.result("Можете: 5/10\nХотите: 6/10\nОценка: 5/10")["can"], 5)

class Users(unittest.TestCase):
    """Таблица, окно «Мои оценки» и письмо берут разбор отсюда же."""
    def test_parse_answer(self):
        self.assertEqual(files.parse_answer(sample("оценка в конце")), {"score": 8, "can": 9, "want": 8, "decision": "да"})

    def test_strengths_for_letter(self):
        self.assertEqual(files.strengths(sample("полный Gemma")), "- Перевод ИТ в облако\n- Команда 60 человек")

    def test_problems_against_meta(self):
        meta = {"stage": "full", "score": 5, "can": 9, "want": 8}
        self.assertEqual(answer.problems(sample("оценка в конце"), meta), ["«Оценка» 8 в тексте, 5 в таблице"])
        self.assertIn("нет оценки «Хочу»", answer.problems("К1: ✅\nМогу: 5/10\nОценка: 4/10\nОткликаться: нет"))

    def test_card_scores_from_meta(self):
        """Карточка получает разбор по разделам; числа плашек — из паспорта, как в таблице."""
        with TempProfile() as t:
            path = t.profile.results / "01 Тест — Компания.md"
            meta = {"title": "Тест", "score": 5, "can": 9, "want": 8, "decision": "да", "stage": "full"}
            import json
            path.write_text(f"<!-- {json.dumps(meta, ensure_ascii=False)} -->\n# Тест — Компания\n\n" + sample("оценка в конце"), encoding="utf-8")
            p = V.parsed_analysis(path)
            self.assertEqual(scores(p), (9, 8, 5))
            self.assertEqual(p["total"]["why"], [])
            self.assertEqual(answer.check_profile(t.profile), [(path.name, ["«Оценка» 8 в тексте, 5 в таблице"])])


if __name__ == "__main__":
    unittest.main()
