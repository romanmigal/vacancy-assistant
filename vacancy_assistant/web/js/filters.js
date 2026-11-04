// Фильтр таблицы по значениям колонок — как автофильтр в Excel. Хранится в окне (localStorage) у каждого
// профиля: это временный вид, а не настройка, Сводку.md он не меняет. Фильтры складываются (И); закрытые
// вакансии — флажок «Скрыть закрытые» в фильтре колонки «Вакансия». Отбор строк (filterRows и соседи) не трогает страницу —
// его проверяет тест через node (tests/test_filters.py).
const FILTER_KIND = {decision: "list", mine: "list", source: "list", stage: "list", company: "list", score: "range", salary: "salary",
                     added: "date", posted: "date", updated: "date", flag: "has", referrer: "has", note: "has", artifacts: "has", title: "text"};
const EMPTY_VALUE = "(пусто)";
const RANGES = [["score", "Оценка ИИ"], ["can", "Могу"], ["want", "Хочу"]];
let filters = {}, hideClosed = false, filtersFor = null;

// Значение строки для фильтра-списка — так, как его видно в таблице
function filterValue(key, r) {
  if (key === "decision") {
    if (r.stage === "none") return "без разбора";
    if (!r.analyzed) return "ждёт разбора";
    const rank = DECISION_RANK(r.decision);
    return rank === 3 ? "да" : rank === 2 ? "возможно" : rank === 1 ? "нет" : (r.decision || "?");
  }
  if (key === "stage") return r.funnel && r.funnel.stage ? stageName(r.funnel.stage) : "без этапа";
  if (key === "mine") return r.my_decision || "не оценивал";     // своя оценка: по своему решению
  return r[key] || EMPTY_VALUE;                       // источник, компания
}

const isoDay = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const rowDate = (key, r) => key === "added" ? (r.added_key || "") : key === "posted" ? (r.posted_key || "") : (r.updated || "").slice(0, 10);
const num = v => v === "" || v == null || isNaN(+v) ? null : +v;

function passes(key, f, r, today) {
  switch (FILTER_KIND[key]) {
    case "list": return !f.out.includes(filterValue(key, r));     // снятый флажок прячет только своё значение
    case "range": return RANGES.every(([k]) => {
      const from = num(f[k + "From"]), to = num(f[k + "To"]);
      if (from == null && to == null) return true;
      const v = !r.analyzed ? null : k === "want" ? wantOf(r) : r[k];      // «Хочу» — с надбавкой за сходство с откликами
      return v != null && (from == null || v >= from) && (to == null || v <= to);
    });
    case "salary": {
      const from = num(f.from);
      return r.salary_value == null ? !!f.unknown : from == null || r.salary_value >= from;
    }
    case "date": {
      const d = rowDate(key, r);
      if (!d) return false;
      if (num(f.days) != null) {
        const start = new Date(today); start.setDate(start.getDate() - num(f.days) + 1);
        return d >= isoDay(start);
      }
      return (!f.from || d >= f.from) && (!f.to || d <= f.to);
    }
    case "has": return !!(key === "flag" ? r.flag : r[key]) === f.has;
    case "text": return r.title.toLowerCase().includes(f.text.trim().toLowerCase());
  }
  return true;
}

// Пустой фильтр (всё выключено) — не фильтр: его не храним и не показываем
function filterOn(key, f) {
  if (!f) return false;
  switch (FILTER_KIND[key]) {
    case "list": return Array.isArray(f.out) && f.out.length > 0;
    case "range": return RANGES.some(([k]) => num(f[k + "From"]) != null || num(f[k + "To"]) != null);
    case "salary": return num(f.from) != null || !f.unknown;
    case "date": return num(f.days) != null || !!f.from || !!f.to;
    case "has": return typeof f.has === "boolean";
    case "text": return !!(f.text || "").trim();
  }
  return false;
}

// Строки, прошедшие все фильтры; except — колонка, фильтр которой не учитывать (для чисел в её списке)
function filterRows(rows, fs, closed, today, except) {
  const active = Object.entries(fs).filter(([k, f]) => k !== except && filterOn(k, f));
  return rows.filter(r => !(closed && r.actual && r.actual.closed) && active.every(([k, f]) => passes(k, f, r, today)));
}

// rows — все вакансии профиля: если оставлено меньше значений, чем снято, строка называет оставленные
function filterText(key, f, rows) {
  const name = key === "flag" ? "Флаг" : (COLUMNS.find(c => c[0] === key) || [, key])[1];
  const ddmmIso = d => d.slice(8, 10) + "." + d.slice(5, 7);
  switch (FILTER_KIND[key]) {
    case "list": {
      const few = list => list.slice(0, 3).join(", ") + (list.length > 3 ? ` и ещё ${list.length - 3}` : "");
      const kept = [...new Set((rows || []).map(r => filterValue(key, r)))].filter(v => !f.out.includes(v));
      return rows && kept.length < f.out.length ? `${name} = ${kept.length ? few(kept) : "ничего"}` : `${name}: кроме ${few(f.out)}`;
    }
    case "range": return RANGES.filter(([k]) => num(f[k + "From"]) != null || num(f[k + "To"]) != null).map(([k, n]) => {
      const from = num(f[k + "From"]), to = num(f[k + "To"]);
      return from != null && to != null ? `${n} ${from}–${to}` : from != null ? `${n} от ${from}` : `${n} до ${to}`;
    }).join(", ");
    case "salary": return num(f.from) != null ? `${name} от ${num(f.from).toLocaleString("ru-RU")}${f.unknown ? " или не указана" : ""}` : `${name} указана`;
    case "date": return num(f.days) != null ? `${name} за ${num(f.days)} ${plural(num(f.days), "день", "дня", "дней")}`
      : `${name}${f.from ? " с " + ddmmIso(f.from) : ""}${f.to ? " по " + ddmmIso(f.to) : ""}`;
    case "has": return `${name}: ${f.has ? "есть" : "нет"}`;
    case "text": return `${name}: «${f.text.trim()}»`;
  }
  return name;
}

// ---------- окно: хранение, строка «Фильтр: …», окошко фильтра колонки ----------
const filtersKey = () => "filters:" + state.profile;
function restoreFilters() {
  if (filtersFor === state.profile) return;
  filtersFor = state.profile;
  filters = {}; hideClosed = false;
  try { const saved = JSON.parse(localStorage.getItem(filtersKey())) || {}; filters = saved.f || {}; hideClosed = !!saved.closed; } catch (e) {}
}
function saveFilters() {
  for (const k of Object.keys(filters)) if (!filterOn(k, filters[k])) delete filters[k];
  remember(filtersKey(), JSON.stringify({f: filters, closed: hideClosed}));
}
const filtering = () => hideClosed || Object.keys(filters).some(k => filterOn(k, filters[k]));
const columnFiltered = key => filterOn(key, filters[key]) || (key === "title" && hideClosed);   // закрытые — в фильтре «Вакансии»

// Перед отрисовкой таблицы: фильтр скрытой колонки сбрасывается — его не видно, значит и не действует
function dropHiddenFilters(cols) {
  const shown = cols.map(c => c[0]);
  if (Object.keys(filters).some(k => !shown.includes(k))) {
    for (const k of Object.keys(filters)) if (!shown.includes(k)) delete filters[k];
    saveFilters();
  }
}

function renderFilterBar(tabRows) {
  const closedHere = tabRows.filter(r => r.actual && r.actual.closed).length;
  const parts = Object.keys(filters).filter(k => filterOn(k, filters[k])).map(k => filterText(k, filters[k], state.rows));
  if (hideClosed) parts.push(closedHere ? `без закрытых (скрыто: ${closedHere})` : "без закрытых");
  $("fbar").hidden = !parts.length;
  $("fbar").innerHTML = parts.length ? `<span class="grow ftext">Фильтр: ${esc(parts.join(", "))}</span><button type="button" class="linkbtn" id="fReset">Сбросить</button>` : "";
  if ($("fReset")) $("fReset").onclick = () => { filters = {}; hideClosed = false; saveFilters(); $("fmenu").hidden = true; render(); };
}

const FUNNEL = '<svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 4h18l-7 8.5V19l-4 2v-8.5z"/></svg>';
const filterButton = key => FILTER_KIND[key]
  ? `<button type="button" class="fbtn ${columnFiltered(key) ? "on" : ""}" data-filter="${key}" title="Фильтр по колонке" aria-label="Фильтр по колонке">${FUNNEL}</button>` : "";

function openFilter(key, th) {
  const m = $("fmenu");
  if (!m.hidden && m.dataset.key === key) { m.hidden = true; return; }
  m.dataset.key = key;
  const f = filters[key] || {}, kind = FILTER_KIND[key];
  const tabRows = state.rows.filter(r => r.status === tab);
  const name = key === "flag" ? "Флаг" : COLUMNS.find(c => c[0] === key)[1];
  let body = "";
  if (kind === "list") {
    const counts = new Map();
    filterRows(tabRows, filters, hideClosed, new Date(), key).forEach(r => { const v = filterValue(key, r); counts.set(v, (counts.get(v) || 0) + 1); });
    (f.out || []).forEach(v => { if (!counts.has(v)) counts.set(v, 0); });      // снятое, которого во вкладке нет, — чтобы вернуть
    const values = [...counts.keys()].sort((a, b) => key === "decision" || key === "stage" ? counts.get(b) - counts.get(a) : a.localeCompare(b, "ru"));
    body = `${key === "company" ? `<input type="search" id="fSearch" placeholder="Поиск компании">` : ""}
      <div class="fquick"><button type="button" class="linkbtn" id="fAll">Все</button><button type="button" class="linkbtn" id="fNone">Ни одного</button></div>
      <div class="flist">${values.map(v => `<label data-v="${esc(v.toLowerCase())}"><input type="checkbox" value="${esc(v)}" ${(f.out || []).includes(v) ? "" : "checked"}> <span>${esc(v)}</span> <span class="muted">${counts.get(v)}</span></label>`).join("")
        || '<p class="hint">Во вкладке нет значений</p>'}</div>`;
  } else if (kind === "range") {
    body = RANGES.map(([k, n]) => `<div class="frow"><span>${n}</span> от <input type="number" min="0" max="10" data-f="${k}From" value="${esc(f[k + "From"] ?? "")}"> до <input type="number" min="0" max="10" data-f="${k}To" value="${esc(f[k + "To"] ?? "")}"></div>`).join("")
      + '<p class="hint">Оценки от 0 до 10. Вакансии без оценки при таком фильтре скрываются.</p>';
  } else if (kind === "salary") {
    body = `<div class="frow">от <input type="number" min="0" step="10000" data-f="from" value="${esc(f.from ?? "")}" style="width:120px"> ₽</div>
      <label class="checks"><input type="checkbox" data-f="unknown" ${f.unknown === false ? "" : "checked"}> и вакансии, где зарплата не указана</label>`;
  } else if (kind === "date") {
    body = `<div class="frow">за последние <input type="number" min="1" data-f="days" value="${esc(f.days ?? "")}"> дней</div>
      <div class="frow">или с <input type="date" data-f="from" value="${esc(f.from || "")}"> по <input type="date" data-f="to" value="${esc(f.to || "")}"></div>`;
  } else if (kind === "has") {
    const v = typeof f.has === "boolean" ? String(f.has) : "";
    body = `<div class="checks stack">${[["", "все"], ["true", "есть"], ["false", "нет"]].map(([val, label]) =>
      `<label><input type="radio" name="fhas" value="${val}" ${v === val ? "checked" : ""}> ${label}</label>`).join("")}</div>`;
  } else {
    const closedHere = tabRows.filter(r => r.actual && r.actual.closed).length;
    body = `<input type="search" data-f="text" placeholder="Слово из названия" value="${esc(f.text || "")}">
      <label class="checks" title="Вакансии, которые сняли с сайта (в таблице зачёркнуты), — во всех вкладках"><input type="checkbox" id="fClosed" ${hideClosed ? "checked" : ""}> Скрыть закрытые${closedHere ? ` <span class="muted">(во вкладке ${closedHere})</span>` : ""}</label>`;
  }
  m.innerHTML = `<div class="mhead">${esc(name)}</div><div class="fbody">${body}</div>
    <div class="msep"></div><div class="ffoot"><button type="button" class="linkbtn" id="fClear">Сбросить фильтр</button><button type="button" id="fClose">Готово</button></div>`;
  m.hidden = false;
  const b = th.getBoundingClientRect();
  m.style.top = Math.min(b.bottom + 4, innerHeight - m.offsetHeight - 8) + "px";
  m.style.left = Math.max(8, Math.min(b.left, innerWidth - m.offsetWidth - 8)) + "px";

  const apply = next => {
    if (next && filterOn(key, next)) filters[key] = next; else delete filters[key];
    saveFilters(); render();
  };
  if (kind === "list") {
    const read = () => {
      const out = [...m.querySelectorAll(".flist input")].filter(c => !c.checked).map(c => c.value);
      apply(out.length ? {out} : null);
    };
    m.querySelectorAll(".flist input").forEach(c => c.onchange = read);
    // «Все» при поиске — только найденные (как в Excel): так выбирают одну компанию; «Ни одного» — снять все
    $("fAll").onclick = () => { m.querySelectorAll(".flist label").forEach(l => l.querySelector("input").checked = !l.hidden); read(); };
    $("fNone").onclick = () => { m.querySelectorAll(".flist input").forEach(c => c.checked = false); read(); };
    if ($("fSearch")) {
      $("fSearch").oninput = () => {
        const q = $("fSearch").value.trim().toLowerCase();
        m.querySelectorAll(".flist label").forEach(l => l.hidden = !!q && !l.dataset.v.includes(q));
        $("fAll").textContent = q ? "Только найденные" : "Все";
      };
      $("fSearch").focus();
    }
  } else if (kind === "has") {
    m.querySelectorAll('input[name="fhas"]').forEach(r => r.onchange = () => apply(r.value ? {has: r.value === "true"} : null));
  } else {
    const read = () => {
      const next = {};
      m.querySelectorAll("[data-f]").forEach(i => next[i.dataset.f] = i.type === "checkbox" ? i.checked : i.value);
      apply(next);
    };
    m.querySelectorAll("[data-f]").forEach(i => { i.oninput = read; i.onchange = read; });
    if (kind === "date") {                            // «за N дней» или даты — что-то одно
      m.querySelector('[data-f="days"]').oninput = e => {
        if (e.target.value) m.querySelectorAll('input[type="date"]').forEach(d => d.value = "");
        read();
      };
      m.querySelectorAll('input[type="date"]').forEach(d => d.onchange = d.oninput = () => { m.querySelector('[data-f="days"]').value = ""; read(); });
    }
    if ($("fClosed")) $("fClosed").onchange = () => { hideClosed = $("fClosed").checked; saveFilters(); render(); };
    const first = m.querySelector("input:not([type=checkbox])");
    if (first) first.focus();
  }
  $("fClear").onclick = () => { delete filters[key]; if (key === "title") hideClosed = false; saveFilters(); m.hidden = true; render(); };
  $("fClose").onclick = () => { m.hidden = true; };
}
