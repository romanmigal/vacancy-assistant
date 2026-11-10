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
  const card = (label, value, sub) => `<div class="stcard"><div class="muted">${label}</div><div class="stnum">${value}</div>${sub ? `<div class="small">${sub}</div>` : ""}</div>`;
  const rates = Object.entries(s.rates || {}).map(([c, r]) => `${c} — ${r.toLocaleString("ru-RU")} ₽`).join(", ");
  const groups = (title, list) => `<div><h3>${title}</h3><table class="stat"><thead><tr><th></th><th>Вакансий</th><th>Медиана</th><th>Квартили</th></tr></thead>
    ${list.map(g => { const x = g[b]; return `<tr><td>${esc(g.label)}</td><td>${x.count}</td><td>${thous(x.median)}</td>
      <td class="muted">${x.q1 == null ? "мало данных" : `${thous(x.q1)} – ${thous(x.q3)}`}</td></tr>`; }).join("")}</table></div>`;
  return `
    <div class="lkinds">${Object.entries(SAL_BASIS).map(([k, v]) => `<button type="button" class="lkind ${k === b ? "on" : ""}" data-basis="${k}">${v}</button>`).join("")}</div>
    <p class="hint">Это не весь рынок — только ${s.total} ${plural(s.total, "вакансия", "вакансии", "вакансий")}, которые видел профиль.
      Вилка «от–до» считается по середине, «от» и «до» — как есть, всё за месяц. Суммы ${other} пересчитаны по прогрессивному НДФЛ
      (13–22 % от годового дохода)${rates ? `, валюта — по курсу ЦБ на ${ddmmyyyy(s.rate_date)}: ${rates}` : ""}.</p>
    ${s.note ? `<p class="hint">${esc(s.note)}${s.skipped.length ? ` (${s.skipped.length} ${plural(s.skipped.length, "вакансия", "вакансии", "вакансий")})` : ""}.</p>` : ""}
    ${st ? `<div class="stcards">
      ${card("Медиана", thous(st.median), `по ${st.count} ${plural(st.count, "вакансии", "вакансиям", "вакансиям")}`)}
      ${card("Нижний квартиль", thous(st.q1), "четверть вакансий ниже")}
      ${card("Верхний квартиль", thous(st.q3), "четверть вакансий выше")}
      ${card("Разброс", `${Math.round(st.min / 1000)}–${Math.round(st.max / 1000)}`, "тыс., от мин. до макс.")}
      ${card("Без зарплаты", share(s.without, s.total), `${s.without} из ${s.total}`)}
      ${s.planka ? card("Не ниже планки", share(s.above[b], st.count), `${s.above[b]} из ${st.count}, планка ${thous(s.planka)}`) : ""}
    </div>
    <div id="salChart">${salChart(s)}</div>
    <p class="hint">Точка — вакансия, нажмите, чтобы открыть карточку. Прямоугольник — средняя половина вакансий (от нижнего до верхнего квартиля), черта в нём — медиана.
      ${s.planka ? "Красная линия — ваша планка из анкеты профиля (шаг «Критерии»)." : "Планка не задана: её можно указать в анкете профиля."}</p>
    <div class="stcols">${groups("По уровню должности", s.groups.level)}${groups("По городу", s.groups.city)}</div>
    <div class="stcols">${groups("По формату работы", s.groups.format)}<div></div></div>
    <p class="hint">Уровень — слово из фильтра по названию должности («Редактировать профиль → Поиск»). Формат — из шапки вакансии; у многих вакансий он не указан.</p>`
    : `<p class="muted">Ни в одной вакансии зарплата не указана.</p>`}`;
}

// Полоса с точками вакансий, квартилями и планкой
function salChart(s) {
  const b = salBasis, st = s[b], W = 720, H = 120, pad = 20, mid = 52;
  const max = Math.max(st.max, s.planka || 0) * 1.05, min = Math.min(st.min, s.planka || st.min) * .9;
  const x = v => pad + (v - min) / (max - min || 1) * (W - pad * 2);
  const step = [50, 100, 200, 250, 500, 1000].find(k => (max - min) / 1000 / k <= 8) || 2000;
  const ticks = [];
  for (let t = Math.ceil(min / 1000 / step) * step; t * 1000 <= max; t += step) ticks.push(t);
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
  document.querySelectorAll("#salBody [data-vac]").forEach(c => c.onclick = () => {
    closeWizard();
    goToVacancy(+c.dataset.vac);
  });
}

$("mSalaries").onclick = openSalaries;
