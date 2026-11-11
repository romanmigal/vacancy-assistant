// Окно «Зарплаты»: вилки из вакансий профиля — медиана, квартили, разброс, группы и своя планка. Без модели
let salBasis = "net", salData = null;
const SAL_BASIS = {net: "На руки", gross: "До вычета"};
const thous = v => v == null ? "—" : `${Math.round(v / 1000).toLocaleString("ru-RU")} тыс.`;
const share = (a, b) => b ? `${Math.round(a / b * 100)}%` : "—";

async function openSalaries() {
  closeMenus();
  const res = await api(`/api/salaries?profile=${encodeURIComponent(state.profile)}`).catch(fail);
  if (!res) return;
  salData = res;
  dialog("Зарплаты", `<div id="salBody">${salariesHtml(res)}</div>`, [{label: "Закрыть"}]);
  $("wiz").classList.add("wide");
  bindSalaries();
}

function salariesHtml(s) {
  const b = salBasis, st = s[b];
  const other = b === "net" ? "до вычета" : "на руки";
  // сумма или диапазон в тысячах: число крупно, «тыс.» мелко — помещается и «416–624 тыс.»
  const tys = (a, c) => `${Math.round(a / 1000).toLocaleString("ru-RU")}${c == null ? "" : "–" + Math.round(c / 1000).toLocaleString("ru-RU")}<span class="stunit"> тыс.</span>`;
  // карточка — кнопка: по щелчку вкладка «Фильтр» с этими вакансиями (salPick)
  const card = (label, value, sub, pick) => `<button type="button" class="stcard salpick" data-pick="${pick}" title="Показать эти вакансии в таблице"><div class="muted">${label}</div><div class="stnum">${value}</div>${sub ? `<div class="small">${sub}</div>` : ""}</button>`;
  const rates = Object.entries(s.rates || {}).map(([c, r]) => `${c} — ${r.toLocaleString("ru-RU")} ₽`).join(", ");
  const groups = (title, list) => `<div><h3>${title}</h3><table class="stat saltab"><thead><tr><th></th><th>Вакансий</th><th>Медиана</th><th>Квартили</th></tr></thead>
    ${list.map(g => { const x = g[b]; return `<tr><td>${esc(g.label)}</td><td>${x.count}</td><td>${thous(x.median)}</td>
      <td class="muted">${x.q1 == null ? "мало данных" : `${thous(x.q1)} – ${thous(x.q3)}`}</td></tr>`; }).join("")}</table></div>`;
  return `
    <div class="lkinds">${Object.entries(SAL_BASIS).map(([k, v]) => `<button type="button" class="lkind ${k === b ? "on" : ""}" data-basis="${k}">${v}</button>`).join("")}</div>
    <p class="hint">Это не весь рынок — только ${s.total} ${plural(s.total, "вакансия", "вакансии", "вакансий")}, которые видел профиль.
      Вилка «от–до» считается по середине, «от» и «до» — как есть, всё за месяц. Суммы ${other} пересчитаны по прогрессивному НДФЛ
      (13–22 % от годового дохода)${rates ? `, валюта — по курсу ЦБ на ${ddmmyyyy(s.rate_date)}: ${rates}` : ""}.</p>
    ${s.note ? `<p class="hint">${esc(s.note)}${s.skipped.length ? ` (${s.skipped.length} ${plural(s.skipped.length, "вакансия", "вакансии", "вакансий")})` : ""}.</p>` : ""}
    ${st ? `<div class="stcards salcards">
      ${card("Типичная зарплата", tys(st.median), `медиана по ${st.count} ${plural(st.count, "вакансии", "вакансиям", "вакансиям")}: у половины выше, у половины ниже`, "median")}
      ${st.q1 != null ? card("У половины вакансий", tys(st.q1, st.q3), "средняя половина: четверть вакансий ниже, четверть выше", "half") : ""}
      ${card("Разброс", tys(st.min, st.max), "от самой низкой зарплаты до самой высокой", "all")}
      ${s.planka ? card("Не ниже вашей планки", share(s.above[b], st.count), `${s.above[b]} из ${st.count} ${plural(st.count, "вакансии", "вакансий", "вакансий")}, планка ${thous(s.planka)}`, "planka") : ""}
      ${card("Зарплата не указана", share(s.without, s.total), `в ${s.without} из ${s.total} ${plural(s.total, "вакансии", "вакансий", "вакансий")} — их нет в расчёте`, "none")}
    </div>
    <div id="salChart">${salChart(s)}</div>
    <p class="hint">Точка — вакансия, нажмите, чтобы открыть карточку. Прямоугольник — средняя половина вакансий (от нижнего до верхнего квартиля), черта в нём — медиана.
      ${s.planka ? "Красная линия — ваша планка из анкеты профиля (шаг «Критерии»)." : "Планка не задана: её можно указать в анкете профиля."}</p>
    <h3 class="salh">По группам</h3>
    ${[["Уровень должности", s.groups.level, "level"], ["Город", s.groups.city, "city"], ["Формат работы", s.groups.format, "format"]]
      .map(([t, list, key]) => `<div class="salgrp">${salGroupChart(s, t, key, list, [...s.groups.level, ...s.groups.city, ...s.groups.format].filter(g => g[b].median != null))}</div>`).join("")}
    <p class="hint">Полоса — средняя половина вакансий группы, черта — медиана, бледная точка — мало данных для вилки.
      ${s.planka ? "Красная линия — планка. " : ""}Шкала — общая у этих трёх графиков, медиана — в тысячах. Наведите на строку, чтобы увидеть суммы.</p>
    <details class="saltables"><summary>Показать таблицей</summary>
      ${groups("По уровню должности", s.groups.level)}${groups("По городу", s.groups.city)}${groups("По формату работы", s.groups.format)}
    </details>
    <p class="hint">Уровень — слово из фильтра по названию должности («Редактировать профиль → Поиск»). Формат — из шапки вакансии; у многих вакансий он не указан.</p>`
    : `<p class="muted">Ни в одной вакансии зарплата не указана.</p>`}
    ${salCalcHtml()}`;
}

// Калькулятор: своя сумма (оклад от рекрутёра, планка) «до вычета» ↔ «на руки», за месяц и за год, валюта — по курсу ЦБ.
// Считает сервер (salaries.calc) — те же формулы, что у вилок в окне. Поля помнятся, пока открыта программа
let salCalc = {amount: "", net: "0", period: "month", currency: "RUB"}, salCalcTimer = null;
const SAL_CUR = ["RUB", "USD", "EUR", "KZT", "UZS", "BYN"];
const SAL_MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"];
const SAL_CALC_HINT = `<p class="hint">Введите сумму — оклад, который назвал рекрутёр, или свою планку: программа покажет, сколько это до вычета и на руки, в месяц и за год.</p>`;
const rub = v => `${Math.round(v).toLocaleString("ru-RU")} ₽`;
// «800 тыс.», «1,2 млн», «250k», «300 000» → число; не число — null
function salAmount(text) {
  const t = String(text).toLowerCase().replace(/[\s\u00a0]/g, "").replace(",", ".");
  const m = t.match(/^(\d+(?:\.\d+)?)(тыс\.?|т|k|к|млн\.?|m|м)?(?:₽|руб\.?|\$|€)?$/);
  if (!m) return null;
  const mult = !m[2] ? 1 : /^(млн|m|м)/.test(m[2]) ? 1e6 : 1e3;
  return +m[1] * mult;
}
function salCalcHtml() {
  const c = salCalc, opt = (v, label, cur) => `<option value="${v}" ${v === cur ? "selected" : ""}>${label}</option>`;
  return `<h3 class="salh salcalch">Калькулятор</h3>
    <div class="salcalc">
      <input type="text" id="salAmount" inputmode="decimal" placeholder="Сумма, например 400 тыс." value="${esc(c.amount)}" aria-label="Сумма">
      <select id="salCur" aria-label="Валюта">${SAL_CUR.map(v => opt(v, v === "RUB" ? "₽" : v, c.currency)).join("")}</select>
      <select id="salNet" aria-label="До вычета или на руки">${opt("0", "до вычета", c.net)}${opt("1", "на руки", c.net)}</select>
      <select id="salPeriod" aria-label="За месяц или за год">${opt("month", "в месяц", c.period)}${opt("year", "в год", c.period)}</select>
    </div>
    <div id="salCalcOut">${SAL_CALC_HINT}</div>`;
}
function bindSalCalc() {
  const read = () => {
    salCalc = {amount: $("salAmount").value, net: $("salNet").value, period: $("salPeriod").value, currency: $("salCur").value};
    clearTimeout(salCalcTimer);
    salCalcTimer = setTimeout(runSalCalc, 300);
  };
  $("salAmount").oninput = read;
  ["salNet", "salPeriod", "salCur"].forEach(id => $(id).onchange = read);
  if (salCalc.amount) runSalCalc();
}
async function runSalCalc() {
  const out = $("salCalcOut"), c = salCalc, amount = salAmount(c.amount);
  if (!out) return;
  if (!c.amount.trim()) { out.innerHTML = SAL_CALC_HINT; return; }
  if (amount == null || amount <= 0) { out.innerHTML = `<p class="cwarn">Не понял сумму: напишите число, например 400000, 400 тыс. или 1,2 млн.</p>`; return; }
  const q = new URLSearchParams({profile: state.profile, amount, net: c.net, period: c.period, currency: c.currency});
  let r;
  try { r = await api(`/api/salaries/calc?${q}`); }
  catch (e) { out.innerHTML = `<p class="cwarn">${esc(e.message || String(e))}</p>`; return; }
  if (salCalc !== c) return;                            // пока считали, поля поменялись
  out.innerHTML = salCalcResult(r);
}
function salCalcResult(r) {
  const b = salBasis, value = r[b], st = salData && salData[b], word = b === "net" ? "на руки" : "до вычета";
  const diff = (label, x) => {
    const d = value - x, pct = Math.round(Math.abs(d) / x * 100);
    return `<li>${label} ${thous(x)}: ${Math.abs(d) < 500 ? "столько же" : `${d > 0 ? "выше" : "ниже"} на ${thous(Math.abs(d))} (${pct}%)`}</li>`;
  };
  const range = m => m.from === m.to ? SAL_MONTHS[m.from - 1] : `${SAL_MONTHS[m.from - 1]} – ${SAL_MONTHS[m.to - 1]}`;
  const compare = [salData && salData.planka ? diff("Ваша планка", salData.planka) : "", st ? diff("Типичная зарплата по вакансиям", st.median) : ""].filter(Boolean);
  return `<div class="stcards salcards calcards">
      <div class="stcard"><div class="muted">До вычета</div><div class="stnum">${rub(r.gross)}</div><div class="small">в месяц · ${rub(r.gross_year)} за год</div></div>
      <div class="stcard"><div class="muted">На руки</div><div class="stnum">${rub(r.net)}</div><div class="small">в месяц в среднем · ${rub(r.net_year)} за год</div></div>
      <div class="stcard"><div class="muted">НДФЛ за год</div><div class="stnum">${rub(r.tax_year)}</div><div class="small">${(r.gross_year ? Math.round(r.tax_year / r.gross_year * 1000) / 10 : 0).toLocaleString("ru-RU")}% от дохода</div></div>
    </div>
    ${r.rate ? `<p class="hint">Курс ЦБ на ${ddmmyyyy(r.rate_date)}: 1 ${esc(salCalc.currency)} = ${r.rate.toLocaleString("ru-RU")} ₽.${r.note ? " " + esc(r.note) + "." : ""}</p>` : ""}
    ${r.months.length > 1 ? `<table class="stat saltab calcmonths"><thead><tr><th>Месяцы</th><th>На руки в месяц</th><th>Ставка НДФЛ</th></tr></thead>
      ${r.months.map(m => `<tr><td>${range(m)}</td><td>${rub(m.net)}</td><td class="muted">${m.rates.join(" и ")}%</td></tr>`).join("")}</table>
      <p class="hint">Ставка растёт, когда доход с начала года переходит ступень: до 2,4 млн — 13%, до 5 млн — 15%, до 20 млн — 18%, до 50 млн — 20%, выше — 22%.
        Здесь — если работать весь год с января; доход у прежнего работодателя в этом году тоже считается.</p>` : ""}
    ${compare.length ? `<p class="small calcmp">Сравнение ${word}, как выбрано вверху окна:</p><ul class="small calcmp">${compare.join("")}</ul>` : ""}`;
}

// Группа (уровень, город, формат) — строка: название, число вакансий, полоса от нижнего до верхнего квартиля,
// черта — медиана. Шкала общая у трёх графиков групп (all — все группы) и начинается после колонок.
// Строки — по убыванию медианы; мало данных (нет квартилей) — только бледная точка медианы
function salGroupChart(s, title, key, list, all) {
  const b = salBasis;
  const rows = list.filter(g => g[b].median != null).sort((p, q) => q[b].median - p[b].median);
  if (!rows.length) return `<p class="muted"><b>${esc(title)}</b>: нет данных.</p>`;
  const phone = matchMedia("(max-width: 600px)").matches;           // там текст графиков крупнее (style.css)
  const row = phone ? 30 : 17, top = phone ? 26 : 15;          // сверху — заголовки колонок
  // колонки «название», «вакансий», «медиана» и шкала — одни у всех трёх графиков: группы разных разрезов сравнимы на глаз
  const charW = phone ? 10.5 : 5.8, MAXL = 24;
  const short = t => t.length > MAXL ? t.slice(0, MAXL - 1).trimEnd() + "…" : t;   // целиком — в подсказке
  const nameW = Math.min(SAL_W * .35, Math.max("Уровень должности".length * 1.1, ...all.map(g => short(g.label).length)) * charW + 12);
  const medText = v => Math.round(v / 1000).toLocaleString("ru-RU");
  const colW = (head, texts) => Math.max(head.length * 1.12, ...texts.map(t => t.length)) * charW;   // заголовки — жирные, шире
  const countEnd = nameW + colW("вакансий", all.map(g => String(g[b].count)));          // числа — по правому краю
  const medEnd = countEnd + (phone ? 22 : 14) + colW("медиана", all.map(g => medText(g[b].median)));
  const left = medEnd + 18;
  const vals = all.flatMap(g => [g[b].q1, g[b].q3, g[b].median]).filter(v => v != null).concat(s.planka ? [s.planka] : []);
  let min = Math.min(...vals), max = Math.max(...vals);
  const padV = (max - min) * .08 || max * .1;
  min -= padV; max += padV;
  const step = [50, 100, 200, 250, 500, 1000].find(k => (max - min) / 1000 / k <= (phone ? 4 : 6)) || 2000;
  const ticks = [];
  for (let t = Math.ceil(min / 1000 / step) * step; t * 1000 <= max; t += step) ticks.push(t);
  const x = v => left + (v - min) / (max - min || 1) * (SAL_W - SAL_PAD - left);
  const base = top + rows.length * row + 1, H = base + (phone ? 22 : 13);
  const tip = (g, v) => `${g.label} — ${v.count} ${plural(v.count, "вакансия", "вакансии", "вакансий")}, медиана ${thous(v.median)}${
    v.q1 == null ? ", мало данных для вилки" : `, у половины ${thous(v.q1)} – ${thous(v.q3)}`}`;
  return `<svg class="stchart salchart salgroups" viewBox="0 0 ${SAL_W} ${H}" role="img" aria-label="Зарплаты по группам">
    <text class="colh" x="0" y="${top - (phone ? 9 : 5)}">${esc(title)}</text>
    <text class="colh" x="${countEnd}" y="${top - (phone ? 9 : 5)}" text-anchor="end">вакансий</text>
    <text class="colh" x="${medEnd}" y="${top - (phone ? 9 : 5)}" text-anchor="end">медиана</text>
    <text class="colh" x="${left}" y="${top - (phone ? 9 : 5)}">вилка</text>
    <line class="colline" x1="0" x2="${SAL_W - SAL_PAD}" y1="${top - 1}" y2="${top - 1}"/>
    ${rows.map((g, i) => { const v = g[b], y = top + i * row, mid = y + row / 2;
      return `<g class="grow"><title>${esc(tip(g, v))}</title>
        <rect class="hit" x="0" y="${y}" width="${SAL_W}" height="${row}"/>
        <text class="glink" data-gkey="${key}" data-glabel="${esc(g.label)}" x="0" y="${mid + (phone ? 6 : 3.5)}">${esc(short(g.label))}</text>
        <text class="cnt" x="${countEnd}" y="${mid + (phone ? 6 : 3.5)}" text-anchor="end">${v.count}</text>
        <text x="${medEnd}" y="${mid + (phone ? 6 : 3.5)}" text-anchor="end">${medText(v.median)}</text>
        ${v.q1 == null ? `<circle class="few" cx="${x(v.median)}" cy="${mid}" r="4"/>`
          : `<rect class="box" x="${x(v.q1)}" y="${mid - 4}" width="${Math.max(x(v.q3) - x(v.q1), 2)}" height="8" rx="2"/>
             <line class="med" x1="${x(v.median)}" x2="${x(v.median)}" y1="${mid - 6.5}" y2="${mid + 6.5}"/>`}</g>`; }).join("")}
    ${s.planka ? `<line class="planka" x1="${x(s.planka)}" x2="${x(s.planka)}" y1="${top - 2}" y2="${base}"/>` : ""}
    <line x1="${left}" x2="${SAL_W - SAL_PAD}" y1="${base}" y2="${base}"/>
    ${ticks.map(t => `<text class="axis" x="${x(t * 1000)}" y="${base + (phone ? 19 : 11)}" text-anchor="middle">${t}</text>`).join("")}
  </svg>`;
}

// Полоса с точками вакансий, квартилями и планкой
// Шкала, общая у графика вакансий и графиков групп: одна и та же сумма — в одном и том же месте
const SAL_W = 720, SAL_PAD = 20;
function salScale(s) {
  const st = s[salBasis];
  const max = Math.max(st.max, s.planka || 0) * 1.05, min = Math.min(st.min, s.planka || st.min) * .9;
  const step = [50, 100, 200, 250, 500, 1000].find(k => (max - min) / 1000 / k <= 8) || 2000;
  const ticks = [];
  for (let t = Math.ceil(min / 1000 / step) * step; t * 1000 <= max; t += step) ticks.push(t);
  return {min, max, ticks, x: v => SAL_PAD + (v - min) / (max - min || 1) * (SAL_W - SAL_PAD * 2)};
}

function salChart(s) {
  const b = salBasis, st = s[b], W = SAL_W, H = 120, pad = SAL_PAD, mid = 52;
  const {x, ticks} = salScale(s);
  return `<svg class="stchart salchart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Зарплаты по вакансиям">
    ${st.q1 != null ? `<rect class="box" x="${x(st.q1)}" y="${mid - 22}" width="${x(st.q3) - x(st.q1)}" height="44" rx="4"/>` : ""}
    <line class="med" x1="${x(st.median)}" x2="${x(st.median)}" y1="${mid - 26}" y2="${mid + 26}"/>
    ${s.points.map((p, i) => `<circle class="pt" data-vac="${p.n}" cx="${x(p[b])}" cy="${mid + ((i * 37) % 9 - 4) * 4}" r="5">
      <title>${esc(p.title)} — ${esc(p.company)}\n${thous(p[b])} ${b === "net" ? "на руки" : "до вычета"}\nВ вакансии: ${esc(p.salary)}</title></circle>`).join("")}
    ${s.planka ? `<line class="planka" x1="${x(s.planka)}" x2="${x(s.planka)}" y1="8" y2="${H - 26}"/>
      <text class="planka" x="${x(s.planka) + 4}" y="16">планка ${Math.round(s.planka / 1000)}</text>` : ""}
    <line x1="${pad}" x2="${W - pad}" y1="${H - 24}" y2="${H - 24}"/>
    ${ticks.map(t => `<text class="axis" x="${x(t * 1000)}" y="${H - 8}" text-anchor="middle">${t}</text>`).join("")}
  </svg>`;
}

function bindSalaries() {
  document.querySelectorAll("#salBody [data-basis]").forEach(btn => btn.onclick = () => {
    salBasis = btn.dataset.basis;
    $("salBody").innerHTML = salariesHtml(salData);
    bindSalaries();
  });
  document.querySelectorAll("#salBody [data-pick]").forEach(c => c.onclick = () => salPick(c.dataset.pick));
  document.querySelectorAll("#salBody [data-gkey]").forEach(c => c.onclick = () => salPickGroup(c.dataset.gkey, c.dataset.glabel));
  bindSalCalc();
  document.querySelectorAll("#salBody [data-vac]").forEach(c => c.onclick = () => {
    closeWizard();
    goToVacancy(+c.dataset.vac);
  });
}

// Карточка или группа → вкладка «Фильтр» ровно с теми вакансиями, по которым она посчитана (по номерам: города,
// формата и уровня в таблице нет, а суммы — с пересчётом «на руки» и валюты, как в окне)
const SAL_GROUP = {level: ["Уровень", "другое"], city: ["Город", "не указан"], format: ["Формат", "не указан"]};
function salFilter(nums, label) {
  closeWizard();
  openTabFilter({n: {nums: nums.map(Number), label}}, label);
}
function salPick(kind) {
  const s = salData, b = salBasis, st = s[b], basis = b === "net" ? "на руки" : "до вычета";
  const pts = (test, label) => salFilter(s.points.filter(p => test(p[b])).map(p => p.n), `Зарплата ${label}`);
  if (kind === "median") pts(v => v >= st.median, `не ниже типичной — от ${thous(st.median)} ${basis}`);
  else if (kind === "half") pts(v => v >= st.q1 && v <= st.q3, `у средней половины — ${thous(st.q1)} – ${thous(st.q3)} ${basis}`);
  else if (kind === "all") pts(() => true, "указана");
  else if (kind === "planka") pts(v => v >= s.planka, `не ниже планки — от ${thous(s.planka)} ${basis}`);
  else if (kind === "none") salFilter(s.without_n || [], "Зарплата не указана");
}
function salPickGroup(key, label) {
  const [name, empty] = SAL_GROUP[key];
  salFilter(salData.points.filter(p => (p[key] || empty) === label).map(p => p.n), `${name}: ${label}, зарплата указана`);
}

$("mSalaries").onclick = openSalaries;
