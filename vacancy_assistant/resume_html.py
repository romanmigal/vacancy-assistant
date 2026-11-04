"""Резюме из выгрузки hh.ru в «TXT» → markdown. hh отдаёт под этим именем HTML, где у каждого поля свой класс
(место работы, компания, период, должность…), поэтому разбор точный: не то что PDF, где колонки путают порядок."""
import re
from html.parser import HTMLParser

VOID = {"br", "img", "meta", "link", "hr", "input"}
# телефон, почта, «Женщина, 41 год, родилась…» — не переносятся; абзац убирается целиком
PRIVATE = re.compile(r"\+7[\d ()-]{9,}|@[\w.-]+\.\w+|родил(ся|ась)|^(Мужчина|Женщина),")
SKIP = ("info-footer",)                 # «Резюме обновлено …»


class Node:
    def __init__(self, tag, attrs, parent=None):
        self.tag, self.cls, self.parent, self.kids = tag, (dict(attrs).get("class") or "").split(), parent, []


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = self.cur = Node("root", [])

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.cur)
        self.cur.kids.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n.tag != tag:      # незакрытые теги закрываются вместе со своим
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.kids.append(data)


def is_hh_html(text):
    return "resume__title" in text or "resume-experience" in text


def text(node):
    """Текст узла: <br> — перенос строки; переносы в исходнике HTML — просто пробелы."""
    if isinstance(node, str):
        return re.sub(r"\s+", " ", node)
    if node.tag == "br":
        return "\n"
    return "".join(text(k) for k in node.kids)


def clean(s):
    return "\n".join(re.sub(r"\s+", " ", l).strip() for l in s.replace("\xa0", " ").split("\n")).strip()


def find(node, cls):
    for k in node.kids:
        if not isinstance(k, str):
            if cls in k.cls:
                yield k
            else:
                yield from find(k, cls)


def first(node, cls):
    return clean(text(next(find(node, cls), "")))


def lines_of(s):
    """Абзац с <br> → строки: «— пункт» → «- пункт», «ДОСТИЖЕНИЯ:» → «**Достижения:**»."""
    out = []
    for l in clean(s).split("\n"):
        if l.startswith("— "):
            l = "- " + l[2:]
        elif re.fullmatch(r"[А-ЯЁA-Z ]{4,}:.*", l):
            head, _, rest = l.partition(":")
            l = f"**{head.capitalize()}:**{(' ' + rest.strip()) if rest.strip() else ''}"
        out.append(l)
    return out


def experience(li):
    """Место работы. В HTML порядок «компания, город, отрасль, период, должность, текст»; в резюме —
    «### период (длительность)», а под ним остальное, как в разборе PDF."""
    period, body = "", []
    for k in li.kids:
        if isinstance(k, str):
            continue
        t = clean(text(k))
        if "bloko-form-hint" in k.cls:
            m = re.match(r"(.+?—\s*.+?)\s+(\d+ (?:год|года|лет|месяц).*)$", t.replace("\n", " "))
            period = f"{m[1]} ({m[2]})" if m else t
        elif k.tag == "ul":                              # подотрасли
            body += ["- " + clean(text(x)) for x in k.kids if not isinstance(x, str)]
        elif t:
            body += lines_of(text(k))
    return ["", f"### {period}", *body]


def walk(node, out):
    for k in node.kids:
        if isinstance(k, str):
            if clean(k):
                out.append(clean(k))
            continue
        if any(c in k.cls for c in SKIP) or k.tag in ("style", "head", "script"):
            continue
        if "resume__title" in k.cls:
            out.append("# " + clean(text(k)).replace("\n", " "))
        elif "resume__block" in k.cls:
            out += ["", "## " + clean(text(k)), ""]
        elif "resume-experience" in k.cls:
            out += experience(k)
        elif "resume-education" in k.cls:
            hints = [clean(text(h)) for h in find(k, "bloko-form-hint")]
            out += ["", f"**{first(k, 'resume-education__name')}**" + (f" — {', '.join(hints)}" if hints else "")]
        elif "resume-skils" in k.cls:                    # «Знание языков», «Навыки», «Обо мне»
            label = first(k, "bloko-form-hint")
            out += ["", f"**{label}**"] if label else [""]
            for it in find(k, "resume-skils__item"):
                if it.tag == "ul":                       # языки — списком
                    out += ["- " + clean(text(li)) for li in it.kids if not isinstance(li, str)]
                else:
                    out += lines_of(text(it))
        elif "resume-profession-role" in k.cls:
            out.append("- " + clean(text(k)))
        elif k.tag in ("p", "li", "span"):
            t = clean(text(k))
            if t and not PRIVATE.search(t.replace("\n", " ")):
                out += lines_of(t)
        else:
            walk(k, out)


def hh_html_markdown(src):
    """HTML выгрузки hh → markdown без телефона, почты, пола и даты рождения."""
    tree = Tree()
    tree.feed(src)
    out = []
    walk(tree.root, out)
    md = "\n".join(l for l in out if not PRIVATE.search(l))
    return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
