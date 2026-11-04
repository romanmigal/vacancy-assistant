// Общее: ключ запросов, обращение к серверу, разметка разбора и решения.
// Обычные скрипты (не модули): подключаются по порядку в index.html и видят функции друг друга.

const $ = id => document.getElementById(id);
// Выпадающие меню шапки и таблицы: открыто только одно; keep — то, что сейчас открывают
const MENUS = ["infoMenu", "paramsMenu", "themeMenu", "favMenu", "colsMenu"];
function closeMenus(keep) { MENUS.forEach(id => { if (id !== keep && $(id)) $(id).hidden = true; }); }
function fitMenu(m) {                          // меню не выходит за левый край узкого окна
  m.style.right = "0px";
  const left = m.getBoundingClientRect().left;
  if (left < 8) m.style.right = (left - 8) + "px";
}
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
// Колонки таблицы: ключ сортировки, заголовок, значение для сортировки (null — всегда в конце)
// «Хочу» с надбавкой за сходство со свежими откликами: модель поставила want, программа добавила want_bonus
const wantOf = r => r.want == null ? null : Math.min(10, r.want + (r.want_bonus || 0));
const wantText = r => r.want == null ? "?" : `${r.want}${r.want_bonus ? `<span class="wbonus">+${r.want_bonus}</span>` : ""}`;
const likeTip = r => r.want_bonus ? `\n«Хочу» +${r.want_bonus}: похожа на ваши отклики — ${r.want_like.map(l => `${l.title}, ${l.company}`).join("; ")}` : "";
const DECISION_RANK = d => !d ? null : d.startsWith("да,") ? 2 : d.startsWith("да") ? 3 : d.startsWith("нет") ? 1 : 0;
// «Моя оценка»: по убыванию — свежие даты выше, в одной дате «да» → «возможно» → «нет», дальше — оценка;
// оценки без даты (старые, до появления дат у оценок) — после датированных, неоценённые — внизу
const MY_RANK = {"нет": 1, "возможно": 2, "да": 3};
const myKey = r => r.my_decision ? `${r.my_date || "0000-00-00"}|${MY_RANK[r.my_decision]}|${String(r.my_score ?? 0).padStart(2, "0")}` : null;
const COLUMNS = [
  ["flag", "⚑", r => r.flag ? 1 : null, "num"],
  ["score", "Оценка ИИ", r => r.score, "num"],
  ["decision", "Решение ИИ", r => DECISION_RANK(r.decision), ""],
  ["mine", "Моя оценка", r => myKey(r), ""],                                // своя оценка: дата → решение → оценка
  ["title", "Вакансия", r => r.title.toLowerCase(), ""],
  ["company", "Компания", r => r.company.toLowerCase(), ""],
  ["source", "Источник", r => (r.source || "").toLowerCase(), ""],
  ["posted", "Опубликовано", r => r.posted_key || null, ""],                 // дата публикации на сайте
  ["salary", "Зарплата", r => r.salary_value, ""],
  ["added", "Сохранено", r => r.added_key || null, ""],
  ["updated", "Обновлено", r => r.updated || null, ""],                     // смена этапа или правка комментария
  ["stage", "Этап", r => r.funnel && r.funnel.stage ? state.stages.findIndex(s => s[0] === r.funnel.stage) : null, ""],   // по ходу воронки
  ["referrer", "Референсер", r => r.referrer ? r.referrer.toLowerCase() : null, ""],
  ["note", "Комментарий", r => r.note ? r.note.toLowerCase() : null, ""],
  ["artifacts", "Артефакты", r => r.artifacts || null, "num"],              // сколько артефактов
];
// Какие колонки показывать и в каком порядке — из профиля (state.columns). Пустой порядок — настройки нет,
// всё по умолчанию: порядок COLUMNS, скрыты DEFAULT_HIDDEN. Окно сохраняет порядок целиком, поэтому своя
// настройка — всегда с порядком. Новой колонки в ней нет — она встаёт за своей соседкой слева по COLUMNS
// («Обновлено» — за «Сохранено»); «Вакансию» не скрыть: без неё строку не узнать
const LOCKED_COLUMN = "title";
const DEFAULT_HIDDEN = ["posted", "mine", "referrer", "artifacts"];
const customColumns = () => !!(state && state.columns && state.columns.order.length);
function tableColumns() {
  const cfg = customColumns() ? state.columns : {order: [], hidden: DEFAULT_HIDDEN}, keys = COLUMNS.map(c => c[0]);
  const order = cfg.order.filter(k => keys.includes(k));
  keys.forEach((k, i) => { if (!order.includes(k)) order.splice(i ? order.indexOf(keys[i - 1]) + 1 : 0, 0, k); });
  // колонка, которой не было, когда настраивали таблицу, — как по умолчанию (новые необязательные — скрыты)
  const isNew = k => customColumns() && !cfg.order.includes(k);
  return order.map(k => ({col: COLUMNS.find(c => c[0] === k),
                          hidden: k !== LOCKED_COLUMN && (cfg.hidden.includes(k) || (isNew(k) && DEFAULT_HIDDEN.includes(k)))}));
}
const shownColumns = () => tableColumns().filter(x => !x.hidden).map(x => x.col);
let sort = {key: "score", dir: -1};
let letterVersion = {n: null, i: 0, kind: "cover"};   // какая версия письма открыта в карточке
let fitVersion = {n: null, i: 0};                      // какая версия «Резюме под вакансию» открыта
let letterKind = "cover";                // вкладка «Письма»: сопроводительное (cover) или референсеру (referrer)
try { sort = JSON.parse(localStorage.getItem("sort")) || sort; } catch (e) {}
if (!COLUMNS.some(c => c[0] === sort.key)) sort = {key: "score", dir: -1};   // колонки «Могу» и «Хочу» больше нет
// Порядок «лучше — выше»: оценка, при равной — решение («да» выше «да, но…»), потом «Хочу», потом «Могу»
const RANK = [r => r.score, r => DECISION_RANK(r.decision), r => wantOf(r), r => r.can];
function byRank(a, b) {
  for (const f of RANK) { const d = (f(b) ?? -1) - (f(a) ?? -1); if (d) return d; }
  return 0;
}
function sorted(rows) {
  const key = shownColumns().some(c => c[0] === sort.key) ? sort.key : "score";   // скрыли колонку — по оценке
  const dir = key === sort.key ? sort.dir : -1;
  const get = (COLUMNS.find(c => c[0] === key) || COLUMNS[0])[2];
  return rows.slice().sort((a, b) => {
    if (key === "score" && a.score != null && b.score != null) return byRank(a, b) * -dir;   // по возрастанию — наоборот
    const x = get(a), y = get(b);
    if (x == null && y == null) return byRank(a, b);
    if (x == null) return 1;
    if (y == null) return -1;                              // пустые — всегда внизу
    const c = typeof x === "string" ? x.localeCompare(y, "ru") : x - y;
    return c ? c * dir : byRank(a, b);
  });
}
let state = null, tab = "new", selected = null, detailTab = "analysis", polling = null;

function remember(k, v) { try { localStorage.setItem(k, v); } catch (e) {} }
function recall(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }

async function api(path, body) {
  const opts = {headers: {"X-Token": TOKEN}};
  if (body) { opts.method = "POST"; opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
  const r = await fetch(path, opts);
  if (r.status === 401 && REMOTE) { location.reload(); throw new Error("Войдите заново"); }   // сессия истекла — на вход
  const data = await r.json().catch(() => ({error: "Нет ответа от программы — она закрыта?"}));
  if (!r.ok || data.error) throw new Error(data.error || r.statusText);
  return data;
}
// Короткое сообщение внизу; action = {label, onClick} — с кнопкой (тогда висит дольше)
function toast(text, action) {
  const t = $("toast");
  t.innerHTML = esc(text) + (action ? ` <button>${esc(action.label)}</button>` : "");
  t.classList.toggle("act", !!action);
  if (action) t.querySelector("button").onclick = () => { t.classList.remove("on"); action.onClick(); };
  t.classList.add("on"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("on"), action ? 6000 : 2200);
}
const fail = e => toast(e.message || String(e));
// Даты этапов и контактов: «2026-10-28» → «28.10»; сегодня в формате ISO — по местному времени
const ddmm = iso => iso ? iso.slice(8, 10) + "." + iso.slice(5, 7) : "";
const ddmmyyyy = iso => iso ? ddmm(iso) + "." + iso.slice(0, 4) : "";
const todayIso = (plus = 0) => { const d = new Date(); d.setDate(d.getDate() + plus); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`; };
const stageName = k => ((state?.stages || []).find(s => s[0] === k) || ["", ""])[1];
// Склонение: plural(21, "вакансия", "вакансии", "вакансий") → «вакансия»
const plural = (n, one, few, many) => n % 10 === 1 && n % 100 !== 11 ? one
  : [2, 3, 4].includes(n % 10) && ![12, 13, 14].includes(n % 100) ? few : many;

// Простой Markdown → HTML: заголовки, жирный, ссылки, списки, линии. Сначала всё экранируем.
function md(text) {
  const inline = s => esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?![*\w])/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/(^|\s)(https?:\/\/[^\s<]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>');
  const out = []; let list = null, para = [];
  const flushPara = () => { if (para.length) { out.push("<p>" + para.join("<br>") + "</p>"); para = []; } };
  const flushList = () => { if (list) { out.push(`<${list.tag}>` + list.items.map(i => `<li>${i}</li>`).join("") + `</${list.tag}>`); list = null; } };
  for (const raw of text.split("\n")) {
    const line = raw.replace(/\s+$/, "");
    let m;
    if (!line.trim()) { flushPara(); flushList(); continue; }
    if (/^(-{3,}|\*{3,})$/.test(line.trim())) { flushPara(); flushList(); out.push("<hr>"); continue; }
    if ((m = line.match(/^(#{1,4})\s+(.*)/))) { flushPara(); flushList(); const h = Math.min(m[1].length + 1, 4); out.push(`<h${h}>${inline(m[2])}</h${h}>`); continue; }
    if ((m = line.match(/^\s*(?:[-*•]|(\d+)[.)])\s+(.*)/))) {
      flushPara(); const tag = m[1] ? "ol" : "ul";
      if (!list || list.tag !== tag) { flushList(); list = {tag, items: []}; }
      list.items.push(inline(m[2])); continue;
    }
    flushList(); para.push(inline(line.trim()));
  }
  flushPara(); flushList();
  return out.join("\n");
}

// Разбор модели: крупные заголовки разделов, «Могу», «Хочу» и общая оценка — плашками
// Критерии профиля по номерам: {1: "Локация: Москва или удалённо…"} — для подсказок у К1, К2…
function criteriaMap(text) {
  const map = {};
  let cur = null;
  for (const line of (text || "").split("\n")) {
    const m = line.match(/^К(\d+)\.\s*(.*)$/);
    if (m) { cur = m[1]; map[cur] = m[2]; }
    else if (cur && /^\s+\S/.test(line)) map[cur] += " " + line.trim();      // продолжение критерия (• …)
    else cur = null;
  }
  return map;
}

// Заголовок «Критерии»: значок со списком критериев; если оценка сделана по прежним критериям —
// отметка об этом (пересчитать — кнопкой «Разобрать заново» в шапке карточки)
// Кто оценивал: облако GigaChat или модель на этом компьютере (Gemma) — значок с названием модели
const modelBadge = model => !model ? "" : /^gigachat/i.test(model)
  ? `<span class="mbadge cloud" title="Разобрано облачной моделью ${esc(model)} (Сбер)"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 18a4.5 4.5 0 0 1-.6-8.96A6 6 0 0 1 18 9a4 4 0 0 1 0 9z"/></svg>GigaChat</span>`
  : `<span class="mbadge local" title="Разобрано моделью ${esc(model)} на этом компьютере"><svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/></svg>${esc(model.split(":")[0].replace(/^gemma\d*/i, "Gemma"))}</span>`;
// Дата разбора — рядом со значком модели: «2026-10-23» → «23.10.2026»
const analysisDate = date => date ? `<span class="mdate" title="Когда сделан этот разбор">${esc(date.split("-").reverse().join("."))}</span>` : "";
const critHead = (changed, model, date) => `<h3 class="sec">Критерии <button class="info" id="critInfo" title="Показать полный список критериев" aria-label="Полный список критериев">i</button>${modelBadge(model)}${analysisDate(date)}`
  + (changed ? `<span class="cchanged" title="После этой оценки поменялись резюме, критерии профиля или «Дополнительно о себе» — оценка сделана по прежним. Пересчитать по новым — кнопка «Разобрать заново» вверху карточки">оценка по прежним данным</span>` : "")
  + `</h3><div id="critPop"></div>`;

const EMPTY_SECTION = {"Сильные стороны": "Модель не нашла сильных сторон под эту вакансию.",
                       "Пробелы": "Модель не нашла пробелов.", "Требования": "Модель не выписала требования."};

// Карточка разбора по структуре от сервера (answer.py): текст ответа модели окно само не разбирает —
// порядок строк в ответе не важен, оценки — одним блоком плашек с теми же числами, что в таблице
function analysisHtml(p, criteria = "", changed = false, model = "", date = "", wantNote = "") {
  if (!p) return "";
  const kmap = criteriaMap(criteria), out = [];
  const section = (name, items, list) => {
    if (!p.sections.includes(name) && !items.length) return;
    out.push(`<h3 class="sec">${name}</h3>`);
    out.push(items.length ? md(list(items)) : `<p class="muted">${EMPTY_SECTION[name]}</p>`);
  };
  if (p.criteria.length || p.sections.includes("Критерии")) {
    out.push(critHead(changed, model, date));
    p.criteria.forEach(c => out.push(`<p class="kline"><span class="k" ${kmap[c.k] ? `title="${esc(kmap[c.k])}"` : ""}>К${c.k}</span>: ${esc([c.mark, c.text].filter(Boolean).join(" "))}</p>`));
  }
  section("Требования", p.requirements, items => items.map((r, i) => `${i + 1}. ${r.text}`).join("\n"));
  const scores = [["Могу", p.can], ["Хочу", p.want], ["Общая оценка", p.total]].filter(([, s]) => s);
  if (scores.length) {
    out.push(`<h3 class="sec">Оценка <a class="helplink" href="/help/docs/${encodeURIComponent("Оценка не совпадает с вашей.md")}" target="_blank" rel="noopener"
      title="Что проверить и что поправить: резюме, «Дополнительно о себе», критерии, калибровка">не совпадает с вашей?</a></h3><div class="scores">`
      + scores.map(([lbl, s]) => `<div class="scorebox ${s === p.total ? "total" : ""}"><div class="lbl">${lbl}</div><div class="val ${scoreClass(s.score)}">${esc(s.score)}<small>/10</small></div></div>`).join("")
      + "</div>" + scores.filter(([, s]) => s.why.length)
        .map(([lbl, s]) => `<p class="why"><b>${lbl === "Общая оценка" ? "Оценка" : lbl}:</b> ${s.why.map(esc).join("<br>")}</p>`).join("") + wantNote);
  }
  section("Сильные стороны", p.strengths, items => items.map(x => `- ${x}`).join("\n"));
  section("Пробелы", p.gaps, items => items.map(x => `- ${x}`).join("\n"));
  if (p.other.length) out.push(md(p.other.join("\n\n")));
  if (p.decision !== "?") out.push(`<h3 class="sec">Резюме</h3><p class="verdict">Откликаться: <b>${esc(p.decision)}</b> ${esc(p.decision_note)}</p>`);
  return out.join("\n");
}

// Решение модели в таблице: «да» — зелёным, «да, но…» — «возможно» оранжевым, «нет» — красным
function decisionHtml(d) {
  const rank = DECISION_RANK(d);
  if (rank === 3) return '<span class="d-yes">да</span>';
  if (rank === 2) return '<span class="d-maybe">возможно</span>';
  if (rank === 1) return '<span class="d-no">нет</span>';
  return esc(d || "?");
}

// Своё решение из мои-оценки.md одним словом: «да, но с оговорками» — «возможно» (окно «Мои оценки»)
const decWord = d => !d ? "" : d.startsWith("да,") || d.startsWith("возможно") ? "возможно" : d.startsWith("да") ? "да" : d.startsWith("нет") ? "нет" : d;

function scoreClass(s) { return s == null ? "" : s >= 7 ? "s-good" : s >= 5 ? "s-mid" : "s-bad"; }

// Поиск на hh.ru программой — только с согласия: соглашение hh запрещает программы для поиска и сбора данных.
// Один и тот же блок — в мастере (шаг «Сайты»), в настройках и в разовом вопросе для прежних профилей.
const HH_AGREEMENT = "https://hh.ru/account/agreement";
const HH_MANUAL = "Найдите вакансию на hh.ru в браузере, сохраните страницу (⌘S или Ctrl+S) и перетащите файл в окно программы или нажмите «Загрузить файл…» — программа прочитает её без обращения к hh.ru. Или вставьте текст вакансии.";
function hhAutoBlock(on, risk) {
  return `<div class="hhauto">
    <label class="hhswitch"><input type="checkbox" id="hhOn" data-a="hh_auto" ${on ? "checked" : ""}> <b>Искать вакансии на hh.ru программой</b></label>
    <p class="hint">Программа сама ищет на hh.ru по вашим должностям и скачивает новые вакансии — как браузер, с паузами, не больше 300 запросов в день. В ваш аккаунт она не входит и не откликается.</p>
    <p class="cwarn"><b>Это нарушает соглашение hh.ru.</b> Оно запрещает программы для поиска и сбора данных с сайта (пп. 5.1.6, 5.1.7, 8.6 и 8.8 <a href="${HH_AGREEMENT}" target="_blank" rel="noopener">соглашения</a>). Отвечает за нарушение пользователь: hh может заблокировать аккаунт или доступ к сайту — в том числе по одному подозрению.</p>
    <p class="hint">Без поиска вакансии с hh.ru добавляются вручную. ${HH_MANUAL} Вакансии с других сайтов добавляются по ссылке, как обычно.</p>
    <div class="checks" id="hhRiskBox" ${on ? "" : "hidden"}><label><input type="checkbox" id="hhRisk" data-a="hh_risk" ${risk ? "checked" : ""}> Понимаю, что это нарушает соглашение hh, и принимаю риск <span class="req">*</span></label></div>
  </div>`;
}
function bindHhAuto() {
  $("hhOn").onchange = () => { $("hhRiskBox").hidden = !$("hhOn").checked; if (!$("hhOn").checked) $("hhRisk").checked = false; };
}
const hhOn = () => state.hh?.state === "on";
const rssOn = () => !!state.rss?.length;                 // включены ленты Хабр Карьеры или GeekJob

// Подсказки .tip (текст — в data-tip): перед показом сдвигаем так, чтобы не вылезали за край окна
function placeTip(e) {
  const el = e.target.closest?.(".tip");
  if (!el) return;
  const r = el.getBoundingClientRect(), w = Math.min(420, innerWidth * 0.8);     // ширина — как max-width в style.css
  const left = Math.max(8, Math.min(r.left + r.width / 2 - w * 0.3, innerWidth - w - 8));
  el.style.setProperty("--tip-left", `${Math.round(left - r.left)}px`);
  el.style.setProperty("--tip-shift", "none");
}
document.addEventListener("mouseover", placeTip);
document.addEventListener("focusin", placeTip);

// Своя оценка: «Могу» и «Хочу» — раздельно, как у модели; общая — расчётная, её не вводят.
// Правило то же, что ratings.total на сервере и шаблон разбора у модели: середина между «Могу» и «Хочу»,
// но не выше меньшей из них плюс 1; при «нет» — не выше 4
const myTotal = (can, want, dec) => {
  if (!can || !want) return null;
  const score = Math.min(Math.round((can + want) / 2), Math.min(can, want) + 1);
  return dec === "нет" ? Math.min(score, 4) : score;
};
const MY_AXES = [["can", "Могу", "Насколько ваш опыт закрывает требования вакансии", "1 — почти ничего", "10 — всё"],
                 ["want", "Хочу", "Насколько вакансия подходит вам: город, деньги, роль, отрасль — ваши критерии", "1 — совсем не моё", "10 — идеально"]];

// Поля своей оценки; o — {can, want, decision}, id — приставка для полей (у окна свой набор)
function myScoreHtml(o, id) {
  const pick = (key, label, sub, lo, hi) => field(label, `<div class="scalewrap"><div class="scorepick" data-axis="${key}">${[1,2,3,4,5,6,7,8,9,10].map(s =>
      `<button type="button" data-my="${key}" data-v="${s}" class="${o[key] === s ? "on" : ""}">${s}</button>`).join("")}</div>
    <div class="scaleends"><span>${lo}</span><span>${hi}</span></div></div>`, sub, true);
  return MY_AXES.map(a => pick(...a)).join("")
    + field("Откликаться?", `<div class="checks">${["да", "возможно", "нет"].map(v =>
        `<label><input type="radio" name="${id}dec" value="${v}" ${o.decision === v ? "checked" : ""}> ${v}</label>`).join("")}</div>`, "", true)
    + `<p class="hint mytotal" id="${id}Total">${myTotalText(o)}</p>`;
}

function myTotalText(o) {
  const t = myTotal(o.can, o.want, o.decision);
  return t == null ? "Общая оценка посчитается сама из «Могу» и «Хочу»."
    : `Общая оценка: <b class="${scoreClass(t)}">${t}</b> — посчитана сама: середина между «Могу» и «Хочу», не выше меньшей из них плюс 1${o.decision === "нет" ? ", при «нет» — не выше 4" : ""}.`;
}

// Щелчки по полям своей оценки: меняют o и общую оценку; changed() — после каждой правки
function myScoreBind(o, id, changed = () => {}) {
  document.querySelectorAll("#wbody [data-my]").forEach(b => b.onclick = () => {
    o[b.dataset.my] = +b.dataset.v;
    document.querySelectorAll(`#wbody [data-my="${b.dataset.my}"]`).forEach(x => x.classList.toggle("on", x === b));
    clearInvalid(b);
    $(`${id}Total`).innerHTML = myTotalText(o);
    changed();
  });
  document.querySelectorAll(`#wbody input[name="${id}dec"]`).forEach(r => r.onchange = () => {
    o.decision = r.value;
    clearInvalid(r);
    $(`${id}Total`).innerHTML = myTotalText(o);
    changed();
  });
}

// Список «Дополнительно о себе»: каждый факт — с «- », Enter начинает следующий, длинный факт переносится и
// остаётся одним пунктом (сервер склеивает строки без «-» с предыдущим фактом — profile.parse_facts)
function bulletArea(el) {
  if (!el || el.readOnly) return;
  const changed = () => el.dispatchEvent(new Event("input", {bubbles: true}));
  el.addEventListener("focus", () => { if (!el.value.trim()) { el.value = "- "; changed(); } });
  el.addEventListener("blur", () => {
    const v = el.value.replace(/^\s*-\s*$/gm, "").replace(/\n{2,}/g, "\n").trim();
    if (v !== el.value) { el.value = v ? v + "\n" : ""; changed(); }
  });
  el.addEventListener("keydown", e => {
    if (e.key !== "Enter" || e.shiftKey || e.isComposing) return;     // Shift+Enter — перенос внутри факта
    e.preventDefault();
    const at = el.selectionStart, line = el.value.slice(el.value.lastIndexOf("\n", at - 1) + 1, at);
    if (/^\s*-\s*$/.test(line)) return;                              // пустой пункт — новый не нужен
    el.setRangeText("\n- ", at, el.selectionEnd, "end");
    changed();
  });
}
