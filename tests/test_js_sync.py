"""Списки, которые окно держит у себя, совпадают с серверными: иначе кнопка и сервер ведут себя по-разному."""
import re
import unittest
from pathlib import Path

from vacancy_assistant import legal, work

JS = Path(__file__).resolve().parent.parent / "vacancy_assistant" / "web" / "js"


class Sync(unittest.TestCase):
    def test_needs_model(self):
        src = (JS / "tasks.js").read_text(encoding="utf-8")
        listed = re.search(r"const NEEDS_MODEL = \[([^\]]*)\]", src).group(1)
        self.assertEqual(set(re.findall(r'"(\w+)"', listed)), set(work.NEEDS_MODEL))

    def test_legal_forms(self):
        src = (JS / "filters.js").read_text(encoding="utf-8")
        forms = re.search(r"const companyTerm = name => name\.replace\(/\^\(\?:([^)]*)\)", src).group(1)
        self.assertEqual(forms.split("|"), list(legal.FORMS))


class Legal(unittest.TestCase):
    def test_short_names(self):
        from vacancy_assistant import contacts, sites
        for name, short in (("ООО «Ромашка»", "Ромашка"), ("Chamomile, LLC", "Chamomile"), ("Группа компаний ПИК", "ПИК"),
                            ("JSC Kaspi", "Kaspi"), ("ФГУП Почта", "Почта"), ("Ltd. Acme", "Acme")):
            self.assertEqual(sites.company_name(name), short)
        self.assertEqual(contacts.company_key("МУП Водоканал"), contacts.company_key("Водоканал"))


if __name__ == "__main__":
    unittest.main()
