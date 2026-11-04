"""«Параметры → Помощь»: README и документы из docs/ — страницей в браузере, прямо из программы.

Репозиторий закрытый, у установленной программы его нет под рукой, поэтому README и docs/ кладутся
в сборку, а здесь Markdown превращается в HTML. Разбор простой — ровно то, что есть в наших
документах: заголовки, абзацы, списки, таблицы, блоки кода, цитаты, ссылки, картинки, **жирный**, `код`.
"""
import html
import re
from urllib.parse import unquote

from . import settings
from .textio import read_text

# /help/ — README; /help/docs/<имя>.md|.svg|.png — документы и картинки к ним. Только такие имена.
DOC = re.compile(r"docs/[^/\\]+\.(md|svg|png)")
TYPES = {"svg": "image/svg+xml", "png": "image/png"}


def page(path):
    """Ответ на /help/…: (тип, содержимое) или None, если такого документа нет."""
    rel = unquote(path[len("/help/"):])
    if rel in ("", "README.md"):
        return "text/html; charset=utf-8", render(read_text(settings.PROJECT_DIR / "README.md"), "Помощь")
    if not DOC.fullmatch(rel) or ".." in rel:
        return None
    f = settings.PROJECT_DIR / rel
    if not f.is_file():
        return None
    if f.suffix == ".md":
        return "text/html; charset=utf-8", render(read_text(f), f.stem, back=True)
    return TYPES[f.suffix[1:]], f.read_bytes()


def inline(text):
    """Строка Markdown → HTML: картинки, ссылки, `код`, **жирный**."""
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for p in parts:
        if p.startswith("`") and p.endswith("`") and len(p) > 1:
            out.append(f"<code>{html.escape(p[1:-1])}</code>")
            continue
        p = html.escape(p, quote=False)
        p = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", lambda m: f'<img src="{m.group(2)}" alt="{m.group(1)}">', p)
        p = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", lambda m: _link(m.group(1), m.group(2)), p)
        p = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", p)
        out.append(p)
    return "".join(out)


def _link(text, url):
    attrs = ' target="_blank" rel="noopener"' if re.match(r"https?://", url) else ""   # внешние — в новой вкладке
    return f'<a href="{url}"{attrs}>{text}</a>'


def render(md, title, back=False):
    lines, out, i = md.split("\n"), [], 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):                                     # блок кода
            block, i = [], i + 1
            while i < len(lines) and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(block))}</code></pre>")
        elif m := re.match(r"(#{1,4})\s+(.*)", line):                  # заголовок
            n = len(m.group(1))
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
        elif line.startswith("|"):                                     # таблица
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            i -= 1
            head, body = rows[0], rows[1:]
            out.append("<table><thead><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr></thead><tbody>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body)
                       + "</tbody></table>")
        elif re.match(r"\s*([-*]|\d+\.)\s+", line):                    # список (и вложенный — отступом)
            items = []
            while i < len(lines) and (re.match(r"\s*([-*]|\d+\.)\s+", lines[i]) or
                                      (lines[i].startswith("  ") and lines[i].strip() and items)):
                m = re.match(r"(\s*)([-*]|\d+\.)\s+(.*)", lines[i])
                if m:
                    items.append([len(m.group(1)), m.group(2)[0].isdigit(), m.group(3)])
                else:
                    items[-1][2] += " " + lines[i].strip()
                i += 1
            i -= 1
            out.append(_list(items))
        elif line.startswith(">"):                                     # цитата
            quote = []
            while i < len(lines) and lines[i].startswith(">"):
                quote.append(lines[i].lstrip("> "))
                i += 1
            i -= 1
            out.append(f"<blockquote>{inline(' '.join(quote))}</blockquote>")
        elif line.strip() == "---":
            out.append("<hr>")
        elif line.strip():                                             # абзац
            para = [line]
            while i + 1 < len(lines) and lines[i + 1].strip() and not re.match(r"(#|```|\||>|\s*([-*]|\d+\.)\s)", lines[i + 1]):
                i += 1
                para.append(lines[i])
            out.append(f"<p>{inline(' '.join(p.strip() for p in para))}</p>")
        i += 1
    nav = '<p class="nav"><a href="/help/">← Помощь</a></p>' if back else ""
    return PAGE.replace("{{TITLE}}", html.escape(title)).replace("{{BODY}}", nav + "\n".join(out))


def _list(items):
    """Пункты [отступ, нумерованный, текст] → вложенные <ul>/<ol>."""
    html_, stack = [], []
    for indent, ordered, text in items:
        while stack and indent < stack[-1][0]:
            html_.append(f"</li></{stack.pop()[1]}>")
        if not stack or indent > stack[-1][0]:
            tag = "ol" if ordered else "ul"
            stack.append((indent, tag))
            html_.append(f"<{tag}>")
        else:
            html_.append("</li>")
        html_.append(f"<li>{inline(text)}")
    while stack:
        html_.append(f"</li></{stack.pop()[1]}>")
    return "".join(html_)


PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}} — Помощник по вакансиям</title><link rel="icon" href="/icon.svg" type="image/svg+xml">
<style>
:root { color-scheme: light dark; --bg: #f6f6f3; --text: #1d1d1b; --muted: #6b6b66; --line: #e3e2dc; --code: #efeee8; --accent: #2f6b55; }
@media (prefers-color-scheme: dark) { :root { --bg: #131413; --text: #e8e8e3; --muted: #9c9c95; --line: #3a3c38; --code: #262826; --accent: #79c79a; } }
body { margin: 0; background: var(--bg); color: var(--text); font: 16px/1.6 -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 860px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 28px; margin: 8px 0 12px; } h2 { font-size: 21px; margin: 32px 0 8px; padding-top: 8px; border-top: 1px solid var(--line); }
h3 { font-size: 17px; margin: 22px 0 6px; } a { color: var(--accent); } img { max-width: 100%; height: auto; border: 1px solid var(--line); border-radius: 8px; }
code { background: var(--code); padding: 1px 5px; border-radius: 4px; font: 0.9em Menlo, Consolas, monospace; }
pre { background: var(--code); padding: 12px 14px; border-radius: 8px; overflow-x: auto; } pre code { padding: 0; background: none; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 14.5px; display: block; overflow-x: auto; }
th, td { border: 1px solid var(--line); padding: 6px 10px; text-align: left; vertical-align: top; }
blockquote { margin: 12px 0; padding: 4px 14px; border-left: 3px solid var(--accent); color: var(--muted); }
.nav { margin: 0 0 8px; font-size: 14px; } hr { border: 0; border-top: 1px solid var(--line); margin: 28px 0; }
</style></head><body><main>
{{BODY}}
</main></body></html>"""
