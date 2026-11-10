"""Фильтр таблицы по колонкам: отбор строк в web/js/filters.js — через node, если он есть."""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

JS = Path(__file__).resolve().parent.parent / "vacancy_assistant" / "web" / "js" / "filters.js"

# Заглушки того, что filters.js берёт из core.js и funnel.js
PRELUDE = """
const wantOf = r => r.want == null ? null : Math.min(10, r.want + (r.want_bonus || 0));
const DECISION_RANK = d => !d ? null : d.startsWith("да,") ? 2 : d.startsWith("да") ? 3 : d.startsWith("нет") ? 1 : 0;
const stageName = s => ({applied: "Отклик", interview: "Интервью"})[s] || s;
const COLUMNS = [["flag", "⚑"], ["score", "Оценка ИИ"], ["decision", "Решение ИИ"], ["mine", "Моя оценка"], ["title", "Вакансия"], ["company", "Компания"],
  ["source", "Источник"], ["posted", "Опубликовано"], ["salary", "Зарплата"], ["added", "Сохранено"], ["updated", "Обновлено"], ["stage", "Этап"],
  ["referrer", "Референсер"], ["note", "Комментарий"]];
const plural = (n, a, b, c) => n % 10 === 1 && n % 100 !== 11 ? a : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20) ? b : c;
"""

ROWS = [
    {"n": 1, "analyzed": True, "decision": "да", "score": 8, "can": 7, "want": 9, "title": "ИТ-директор", "company": "Сбер",
     "source": "HH", "salary_value": 500000, "added_key": "2026-10-27", "posted_key": "2026-10-25", "updated": "2026-10-28T10:00", "flag": True,
     "referrer": "Иван", "note": "", "funnel": {"stage": "applied"}, "actual": {"closed": False}, "my_decision": "да"},
    {"n": 2, "analyzed": True, "decision": "да, но зарплата", "score": 6, "can": 6, "want": 6, "title": "CTO", "company": "ВТБ",
     "source": "HH", "want_bonus": 1, "salary_value": None, "added_key": "2026-10-10", "updated": None, "flag": False,
     "referrer": "", "note": "позвонить", "funnel": {}, "actual": {"closed": True}},
    {"n": 3, "analyzed": True, "decision": "нет", "score": 3, "can": 4, "want": 2, "title": "Начальник отдела ИТ", "company": "Сбер",
     "source": "Хабр Карьера", "salary_value": 250000, "added_key": "2026-10-20", "posted_key": "2026-09-01", "updated": None, "flag": False,
     "referrer": "", "note": "", "funnel": {}, "actual": {}, "my_decision": "возможно"},
    {"n": 4, "analyzed": False, "decision": "", "score": None, "can": None, "want": None, "title": "Директор по ИТ", "company": "",
     "source": "", "salary_value": None, "added_key": "2026-10-28", "updated": None, "flag": False,
     "referrer": "", "note": "", "funnel": {}, "actual": {}},
]

CASES = [  # фильтры, скрыть закрытые, какие строки остаются
    ({}, False, [1, 2, 3, 4]),
    ({}, True, [1, 3, 4]),
    ({"decision": {"out": ["нет", "возможно", "ждёт разбора"]}, "source": {"out": ["Хабр Карьера", "(пусто)"]}}, False, [1]),
    ({"decision": {"out": ["нет"]}}, False, [1, 2, 4]),           # снятое — только своё значение
    ({"company": {"out": ["ВТБ"]}}, False, [1, 3, 4]),
    ({"stage": {"out": ["Отклик"]}}, True, [3, 4]),
    ({"decision": {"out": []}}, False, [1, 2, 3, 4]),             # ничего не снято — фильтра нет
    ({"decision": {"in": ["да"]}}, False, [1, 2, 3, 4]),          # старый вид фильтра не действует
    ({"score": {"scoreFrom": "6"}}, False, [1, 2]),
    ({"score": {"scoreFrom": "", "wantTo": "5"}}, False, [3]),
    ({"salary": {"from": "300000", "unknown": False}}, False, [1]),
    ({"salary": {"from": "300000", "unknown": True}}, False, [1, 2, 4]),
    ({"salary": {"from": "", "unknown": False}}, False, [1, 3]),
    ({"added": {"days": "2"}}, False, [1, 4]),
    ({"added": {"from": "2026-10-15", "to": "2026-10-27"}}, False, [1, 3]),
    ({"updated": {"days": "7"}}, False, [1]),
    ({"flag": {"has": True}}, False, [1]),
    ({"referrer": {"has": False}, "note": {"has": False}}, False, [3, 4]),
    ({"title": {"text": "  ит "}}, False, [1, 3, 4]),
    ({"title": {"text": ""}, "score": {}}, False, [1, 2, 3, 4]),   # пустые фильтры не действуют
    ({"posted": {"from": "2026-10-01"}}, False, [1]),             # дата публикации: без даты — не проходят
    ({"posted": {"days": "60"}}, False, [1, 3]),
    ({"score": {"wantFrom": "7"}}, False, [1, 2]),                 # «Хочу» с надбавкой за сходство с откликами
    ({"mine": {"out": ["не оценивал"]}}, False, [1, 3]),          # «Моя оценка»: только оценённые сами
    ({"mine": {"out": ["да", "не оценивал"]}}, False, [3]),
    ({"company": {"only": ["Сбер"]}}, False, [1, 3]),            # «только эти» (вкладка «Фильтр»): новые компании не проходят
    ({"company": {"only": []}}, False, []),
    ({"company": {"only": ["Сбер"]}, "posted": {"from": "2026-09-20"}}, False, [1]),       # компания и дата публикации
]

SCRIPT = PRELUDE + JS.read_text(encoding="utf-8") + """
const rows = ROWS_JSON, cases = CASES_JSON, today = new Date(2026, 9, 28);
const out = cases.map(([fs, closed]) => filterRows(rows, fs, closed, today).map(r => r.n));
out.push(filterRows(rows, cases[2][0], false, today, "decision").map(r => r.n));   // без своей колонки
out.push([filterText("decision", cases[3][0].decision, rows), filterText("decision", cases[2][0].decision, rows),
  filterText("salary", cases[11][0].salary), filterText("added", cases[13][0].added), filterText("score", cases[8][0].score)]);
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "нет node")
class Filters(unittest.TestCase):
    def test_rows(self):
        script = SCRIPT.replace("ROWS_JSON", json.dumps(ROWS, ensure_ascii=False)).replace(
            "CASES_JSON", json.dumps([[f, c] for f, c, _ in CASES], ensure_ascii=False))
        out = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
        for (fs, closed, want), got in zip(CASES, out):
            self.assertEqual(got, want, (fs, closed))
        self.assertEqual(out[len(CASES)], [1, 2])
        self.assertEqual(out[len(CASES) + 1], ["Решение ИИ: кроме нет", "Решение ИИ = да",
                                               "Зарплата от 300\xa0000 или не указана", "Сохранено за 2 дня", "Оценка ИИ от 6"])


if __name__ == "__main__":
    unittest.main()
