"""Описание вакансии hh.ru → markdown: заголовки секций после списка — с новой строки."""
import unittest

from vacancy_assistant.hh import DescriptionToMarkdown


def convert(html):
    p = DescriptionToMarkdown()
    p.feed(html)
    return p.text()


class Description(unittest.TestCase):
    def test_heading_after_list_starts_new_line(self):
        # hh.ru: заголовок «Требования:» идёт сразу после </ul>, без <p>
        t = convert("<p><strong>Обязанности:</strong></p><ul><li>Раз</li><li>Два</li></ul>"
                    "<strong>Требования:</strong><ul><li>Три</li></ul><strong>Условия:</strong><ul><li>Четыре</li></ul>")
        self.assertEqual(t, "**Обязанности:**\n\n- Раз\n- Два\n\n**Требования:**\n\n- Три\n\n**Условия:**\n\n- Четыре")

    def test_list_items_stay_together(self):
        self.assertEqual(convert("<ul><li>Раз</li><li><p>Два</p></li><li>Три</li></ul>"), "- Раз\n- Два\n- Три")


if __name__ == "__main__":
    unittest.main()
