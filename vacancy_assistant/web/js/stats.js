// Раздел «Статистика»: вакансии, разборы и отклики по дням, неделям и месяцам — из файлов профиля, без модели
// Шаг и показатель графика — как в прошлый раз (в этом браузере); впервые — по дням, «Добавлено»
let statStep = ["day", "week", "month"].includes(recall("statStep")) ? recall("statStep") : "day",
    statMetric = recall("statMetric") || "added", statData = null;
// шаг → [кнопка, «за …», диапазон, «с предыдущими …», «текущий … не закончился»]
const STAT_STEPS = {day: ["Дни", "день", "30 дней", "30 днями", "сегодняшний день ещё не закончился"],
  week: ["Недели", "неделю", "12 недель", "12 неделями", "текущая неделя ещё не закончилась"],
  month: ["Месяцы", "месяц", "12 месяцев", "12 месяцами", "текущий месяц ещё не закончился"]};
const MONTHS = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"];
const statPeriod = (s, step) => step === "day" ? ddmm(s.start)
  : step === "week" ? `${ddmm(s.start)}–${ddmm(s.end)}` : `${MONTHS[+s.start.slice(5, 7) - 1]} ${s.start.slice(0, 4)}`;
const pct = (a, b) => b ? `${Math.round(a / b * 100)}%` : "—";

async function openStats() {
  closeMenus();
  const res = await api(`/api/stats?profile=${encodeURIComponent(state.profile)}&step=${statStep}`).catch(fail);
  if (!res) return;
  statData = res;
  dialog("Статистика", statsHtml(res), [
    {label: "Скопировать как Markdown", left: true, title: "Итоги, воронка и таблица по периодам — например, чтобы обсудить с карьерным консультантом",
     onClick: () => navigator.clipboard.writeText(statsMarkdown(res)).then(() => toast("Скопировано"), fail)},
    {label: "Закрыть"}]);
  $("wiz").classList.add("wide");
  bindStats();
  fitStatusPie();
}

function statsHtml(s) {
  if (!s.metrics.some(m => m.key === statMetric)) statMetric = "added";
  const [, per, range, prevRange, partial] = STAT_STEPS[s.step];
  const arrow = t => t.total === t.prev ? `<span class="muted">как раньше</span>`
    : `<span class="${t.total > t.prev ? "up" : "down"}">${t.total > t.prev ? "▲" : "▼"} ${Math.abs(t.total - t.prev)}</span>`;
  const sp = (x, what) => x.days == null ? `<span class="muted">пока нет данных</span>` : `<b>${x.days}</b> дн. <span class="muted">(${x.count} ${what})</span>`;
  return `
    <div class="lkinds">${Object.entries(STAT_STEPS).map(([k, v]) => `<button type="button" class="lkind ${k === s.step ? "on" : ""}" data-step="${k}">${v[0]}</button>`).join("")}</div>
    <p class="hint">Последние ${range}: ${ddmmyyyy(s.start)} — ${ddmmyyyy(s.end)}. Среднее — за ${per}; ${partial}, и среднее считается по прошедшим дням. Стрелка — сравнение с предыдущими ${prevRange}. Всё считается по файлам профиля, без модели.</p>
    <div class="stcards">${s.metrics.map(m => { const t = s.totals[m.key]; return `
      <div class="stcard"><div class="muted">${m.label}</div><div class="stnum">${t.total}</div>
        <div class="small">≈ ${t.avg} за ${per}</div><div class="small">${arrow(t)}</div></div>`; }).join("")}</div>
    <h3>По периодам</h3>
    <div class="lkinds">${s.metrics.map(m => `<button type="button" class="lkind ${m.key === statMetric ? "on" : ""}" data-metric="${m.key}">${m.label}</button>`).join("")}</div>
    <div id="stChart">${statChart(s)}</div>
    <details class="sttable"><summary>Таблица по периодам</summary>
      <table class="stat"><thead><tr><th>Период</th>${s.metrics.map(m => `<th>${m.label}</th>`).join("")}</tr></thead>
      <tbody>${[...s.series].reverse().map(p => `<tr><td>${statPeriod(p, s.step)}${p.partial ? ' <span class="muted">(идёт)</span>' : ""}</td>
        ${s.metrics.map(m => `<td>${p[m.key] || '<span class="muted">0</span>'}</td>`).join("")}</tr>`).join("")}</tbody></table></details>
    <div class="stcol1">
      <div><h3>Воронка</h3><p class="hint">Вакансии, добавленные за эти ${range}: докуда каждая дошла. Процент — от предыдущего шага.</p>
        <table class="stat funnel">${s.funnel.map((f, i) => `<tr><td>${f.label}</td><td><b>${f.count}</b></td>
          <td class="bar" title="${f.label}: ${f.count}${f.count ? "\n" + STAT_KINDS.filter(([k]) => f.by_kind?.[k]).map(([k, l]) => `${l} — ${f.by_kind[k]}`).join("\n") : ""}">${funnelBar(f, s.funnel[0].count)}</td>
          <td class="muted">${i ? pct(f.count, s.funnel[i - 1].count) : ""}</td></tr>`).join("")}</table>
        ${statLegend(Object.fromEntries(STAT_KINDS.map(([k]) => [k, s.funnel[0].by_kind?.[k] || 0])))}
        <p class="small">${s.score.avg == null ? "" : `Средняя оценка этих вакансий — <b>${s.score.avg}</b>, оценка 7+ у ${pct(s.score.good, s.score.count)}.`}</p></div>
      <div><h3>Источники</h3><p class="hint">Вакансии, добавленные за эти ${range}: докуда дошли. Полоска — от добавленных из этого источника, справа — сколько откликов получили ответ.</p>
        ${s.sources.length ? sourcesChart(s.sources) : `<p class="muted">Вакансий за эти ${range} нет.</p>`}</div>
      <div><h3>Статусы сейчас</h3>
        ${statusPie(s.statuses)}
</div>
      <div><h3>Отклики с сопроводительным письмом и без</h3>
        <p class="hint">Отклики за эти ${range}. Письмо считается отправленным, если во вкладке «Письма» у него стоит отметка «Отправлено»; у старых откликов её можно поставить с прошлой датой. Процент в подсказке у столбика — от откликов той же группы.</p>
        ${lettersChart(s.letters)}
        ${s.letters[0].applied ? "" : `<p class="hint">Пока ни у одного отклика нет отметки «Отправлено» у письма — все отклики попали в «Без письма».</p>`}</div>
      <div><h3>Скорость</h3><p class="hint">Сколько в среднем проходит между этапами — по всем откликам профиля. Длина отрезка — сколько дней.</p>
        ${speedTimeline(s.speed)}
        ${s.waiting.length ? `<details class="sttable"><summary>Ждут ответа дольше ${s.wait_days} дней — ${s.waiting.length}</summary>
          <table class="stat">${s.waiting.map(w => `<tr class="link" data-vac="${w.n}" title="Открыть карточку вакансии"><td>${esc(w.title)}<div class="muted small">${esc(w.company)}</div></td>
            <td class="muted">отклик ${ddmm(w.applied)}</td><td><b>${w.days}</b> дн.</td></tr>`).join("")}</table>
          <p class="hint">Можно напомнить о себе или отметить этап «Не ответили».</p></details>` : ""}</div>
    </div>`;
}

// Кто разместил вакансию — части столбика снизу вверх: работодатель, кадровое агентство, работодатель скрыт
const STAT_KINDS = [["employer", "Работодатель"], ["agency", "Кадровое агентство"], ["hidden", "Работодатель скрыт"]];

// Столбики по периодам, разложенные по STAT_KINDS; текущий неполный период — бледнее
function statChart(s) {
  const W = 720, H = 150, pad = 18, gap = 2, n = s.series.length, w = W / n;
  const max = Math.max(1, ...s.series.map(p => p[statMetric]));
  const every = Math.ceil(n / 12);                   // подписи периодов — не чаще 12 на график
  const sum = Object.fromEntries(STAT_KINDS.map(([k]) => [k, s.series.reduce((a, p) => a + (p.by_kind?.[statMetric]?.[k] || 0), 0)]));
  return `<svg class="stchart" viewBox="0 0 ${W} ${H + 30}" role="img" aria-label="График по периодам: работодатели, кадровые агентства, скрытые работодатели">
    ${s.series.map((p, i) => { const v = p[statMetric], h = v / max * (H - pad), parts = p.by_kind?.[statMetric] || {employer: v};
      let y = H;
      const segs = STAT_KINDS.filter(([k]) => parts[k]).map(([k]) => {
        const sh = parts[k] / max * (H - pad); y -= sh;
        return `<rect x="${i * w + w * .15}" y="${y}" width="${w * .7}" height="${Math.max(sh - gap, 1)}" rx="2" class="${k} ${p.partial ? "partial" : ""}"/>`;
      }).join("");
      return `<g><title>${statPeriod(p, s.step)}: ${v}${v ? "\n" + STAT_KINDS.filter(([k]) => parts[k]).map(([k, l]) => `${l} — ${parts[k]}`).join("\n") : ""}</title>
        <rect class="hit" x="${i * w}" y="0" width="${w}" height="${H}"/>${segs}
        ${v ? `<text x="${i * w + w / 2}" y="${H - h - 4}" text-anchor="middle">${v}</text>` : ""}
        ${(n - 1 - i) % every === 0 ? `<text x="${i * w + w / 2}" y="${H + 16}" text-anchor="middle" class="axis">${statPeriod(p, s.step).split("–")[0]}</text>` : ""}</g>`; }).join("")}
    <line x1="0" x2="${W}" y1="${H}" y2="${H}"/></svg>
    ${statLegend(sum)}`;
}
// Отклики, ответы, отказы, интервью — столбик из двух частей: с письмом (снизу) и без
const LETTER_PARTS = [[true, "С письмом", "letter"], [false, "Без письма", "noletter"]];
function lettersChart(letters) {
  const by = Object.fromEntries(letters.map(x => [x.letter, x]));
  const cols = [["applied", "Откликов"], ["answered", "Ответов"], ["rejected", "Отказов"], ["interview", "Интервью"]];
  const W = 720, H = 150, pad = 18, gap = 2, w = W / cols.length;
  const total = k => LETTER_PARTS.reduce((a, [f]) => a + (by[f]?.[k] || 0), 0);
  const max = Math.max(1, ...cols.map(([k]) => total(k)));
  return `<svg class="stchart" viewBox="0 0 ${W} ${H + 30}" role="img" aria-label="Отклики, ответы, отказы и интервью: с письмом и без">
    ${cols.map(([k, label], i) => { let y = H; const v = total(k);
      const segs = LETTER_PARTS.filter(([f]) => by[f]?.[k]).map(([f, , cls]) => {
        const sh = by[f][k] / max * (H - pad); y -= sh;
        return `<rect x="${i * w + w * .3}" y="${y}" width="${w * .4}" height="${Math.max(sh - gap, 1)}" rx="2" class="${cls}"/>`;
      }).join("");
      const tip = LETTER_PARTS.map(([f, l]) => { const x = by[f] || {}; return `${l} — ${x[k] || 0}${k === "applied" ? "" : ` (${pct(x[k] || 0, x.applied || 0)})`}`; }).join("\n");
      return `<g><title>${label}: ${v}\n${tip}</title><rect class="hit" x="${i * w}" y="0" width="${w}" height="${H}"/>${segs}
        ${v ? `<text x="${i * w + w / 2}" y="${y - 4}" text-anchor="middle">${v}</text>` : ""}
        <text x="${i * w + w / 2}" y="${H + 16}" text-anchor="middle" class="axis">${label}</text></g>`; }).join("")}
    <line x1="0" x2="${W}" y1="${H}" y2="${H}"/></svg>
    <div class="stlegend">${LETTER_PARTS.map(([f, l, cls]) => `<span><i style="background:var(--s-${cls})"></i>${l} <b>${by[f]?.applied || 0}</b></span>`).join("")}</div>`;
}

// Источники: у каждого — вложенные полоски от его же «Добавлено»: отклики, ответы, интервью. Больше 6 — хвост в «Остальные»
const SRC_STEPS = [["added", "Добавлено"], ["applied", "Отклики"], ["answered", "Ответы"], ["interview", "Интервью"]];
function sourcesChart(sources) {
  let rows = [...sources].sort((a, b) => b.added - a.added);
  if (rows.length > 6) {
    const rest = rows.slice(5);
    rows = [...rows.slice(0, 5), Object.fromEntries([["source", `Остальные (${rest.length})`],
      ...SRC_STEPS.map(([k]) => [k, rest.reduce((a, x) => a + x[k], 0)])])];
  }
  const tip = x => `${x.source}\n` + SRC_STEPS.map(([k, l]) => `${l} — ${x[k]}`).join("\n");
  return `<div class="srcrows">${rows.map(x => `<div class="srcrow" title="${esc(tip(x))}">
      <span class="srcname">${esc(x.source)}</span><b class="srcadded">${x.added}</b>
      <span class="srcbar">${SRC_STEPS.slice(1).map(([k], i) => `<i class="s${i + 1}" style="width:${x.added ? x[k] / x.added * 100 : 0}%"></i>`).join("")}</span>
      <span class="srcresp">${x.applied ? `${x.answered} из ${x.applied} <span class="muted">${pct(x.answered, x.applied)}</span>` : '<span class="muted">откликов нет</span>'}</span>
    </div>`).join("")}</div>
    <div class="stlegend"><span><i class="s0"></i>Добавлено</span>${SRC_STEPS.slice(1).map(([, l], i) => `<span><i class="s${i + 1}"></i>${l}</span>`).join("")}</div>`;
}

// Статусы сейчас — кольцо слева, справа таблица всех статусов в порядке вкладок: цвет и доля, значок и название, вакансий.
// Встроенные статусы — своими цветами, свои — цветом своего значка.
function statusPie(statuses) {
  const sum = statuses.reduce((a, x) => a + x.count, 0);
  if (!sum) return '<p class="muted">Вакансий пока нет.</p>';
  const R = 60, C = 2 * Math.PI * R, BUILT = ["new", "yes", "interview", "no"];
  const parts = statuses.map(x => ({...x, color: BUILT.includes(x.key) ? `var(--pie-${x.key})` : `var(--pie-${state.status_colors?.[x.key] || "blue"})`}));
  const shown = parts.filter(x => x.count);
  let at = 0;
  const arcs = shown.map(x => { const len = x.count / sum * C, gap = shown.length > 1 ? Math.min(2, len / 2) : 0;
    const arc = `<circle r="${R}" cx="80" cy="80" fill="none" stroke="${x.color}" stroke-width="26"
      stroke-dasharray="${len - gap} ${C - len + gap}" stroke-dashoffset="${-at}" transform="rotate(-90 80 80)"><title>${esc(x.label)}: ${x.count} (${pct(x.count, sum)})</title></circle>`;
    at += len; return arc; }).join("");
  return `<div class="stpie"><svg viewBox="0 0 160 160" role="img" aria-label="Статусы вакансий">${arcs}
      <text x="80" y="78" text-anchor="middle" class="pienum">${sum}</text><text x="80" y="96" text-anchor="middle" class="pielbl">вакансий</text></svg>
    <table class="stat stpietab"><thead><tr><th></th><th>Статус</th><th class="fl" title="С флагом — отдельно, в «Всего» уже входят"><span class="flag">⚑</span></th>
      <th title="Вакансия ещё открыта на сайте">Открытых</th><th title="Вакансия закрыта или в архиве на сайте">Закрытых</th><th>Всего</th></tr></thead>
      ${parts.map(x => `<tr class="${x.count ? "" : "zero"}"><td class="pct"><i style="background:${x.color}"></i>${pct(x.count, sum)}</td>
        <td>${statusIcon(x.key)} ${esc(x.label)}</td><td class="fl">${x.flagged || ""}</td><td>${x.count - x.closed}</td><td>${x.closed}</td><td><b>${x.count}</b></td></tr>`).join("")}
      <tr class="total"><td></td><td>Всего</td>${["flagged", "open", "closed", "count"].map(k =>
        `<td class="${k === "flagged" ? "fl" : ""}"><b>${parts.reduce((a, x) => a + (k === "open" ? x.count - x.closed : x[k]), 0)}</b></td>`).join("")}</tr></table></div>`;
}

// Кольцо «Статусы сейчас» — квадрат высотой с таблицу справа; на узком экране, под таблицей, — как задано в CSS
function fitStatusPie() {
  const svg = document.querySelector(".stpie > svg"), tab = document.querySelector(".stpietab");
  if (!svg || !tab) return;
  const side = svg.getBoundingClientRect().top === tab.getBoundingClientRect().top;
  svg.style.width = side ? `${Math.round(tab.getBoundingClientRect().height)}px` : "";
}
addEventListener("resize", () => fitStatusPie());

// Скорость — шкала пути вакансии: Добавлена → Отклик → Ответ → Интервью; длина отрезка — среднее число дней
function speedTimeline(sp) {
  const ans = sp.to_answer.days, intv = sp.to_interview.days;
  const segs = [
    [sp.to_apply.days, sp.to_apply.count, "откл."],
    [ans, sp.to_answer.count, "отв."],
    [intv != null && ans != null ? Math.max(Math.round((intv - ans) * 10) / 10, 0) : intv, sp.to_interview.count, "инт."]];
  const nodes = ["Добавлена", "Отклик", "Ответ", "Интервью"];
  const seg = ([d, n, what]) => `<div class="tlseg ${d == null ? "none" : ""}" style="flex-grow:${d == null ? 1 : Math.max(d, .6)}">
      <span class="tld">${d == null ? "нет данных" : `${String(d).replace(".", ",")} дн.`}</span><i></i>
      <span class="tln muted">${n ? `по ${n} ${what}` : ""}</span></div>`;
  return `<div class="sttl">${nodes.map((l, i) => `<div class="tlnode"><b></b><span>${l}</span></div>${i < segs.length ? seg(segs[i]) : ""}`).join("")}</div>`;
}

const statLegend = sum => `<div class="stlegend">${STAT_KINDS.map(([k, l]) => `<span><i style="background:var(--s-${k})"></i>${l} <b>${sum[k]}</b></span>`).join("")}</div>`;

// Полоска шага воронки — по частям STAT_KINDS, длина от числа на первом шаге
function funnelBar(f, top) {
  const parts = f.by_kind || {employer: f.count};
  return `<span class="fbar">${STAT_KINDS.filter(([k]) => parts[k]).map(([k]) =>
    `<i class="${k}" style="width:${top ? parts[k] / top * 100 : 0}%"></i>`).join("")}</span>`;
}

function bindStats() {
  document.querySelectorAll("#wbody [data-step]").forEach(b => b.onclick = () => { statStep = b.dataset.step; remember("statStep", statStep); openStats(); });
  document.querySelectorAll("#wbody [data-metric]").forEach(b => b.onclick = () => {
    statMetric = b.dataset.metric; remember("statMetric", statMetric);
    document.querySelectorAll("#wbody [data-metric]").forEach(x => x.classList.toggle("on", x === b));
    $("stChart").innerHTML = statChart(statData);
  });
  document.querySelectorAll("#wbody [data-vac]").forEach(b => b.onclick = () => {
    const n = +b.dataset.vac, row = state.rows.find(r => r.n === n);
    closeWizard();
    if (row) { tab = row.status; openVacancy(n); }
  });
}

function statsMarkdown(s) {
  const [, per, range] = STAT_STEPS[s.step];
  const line = cells => `| ${cells.join(" | ")} |`;
  return [`# Статистика поиска: последние ${range} (${ddmmyyyy(s.start)} — ${ddmmyyyy(s.end)})`, "",
    line(["Метрика", "Всего", `В среднем за ${per}`, `Предыдущие ${range}`]), line(["---", "---:", "---:", "---:"]),
    ...s.metrics.map(m => line([m.label, s.totals[m.key].total, s.totals[m.key].avg, s.totals[m.key].prev])), "",
    "## Воронка", "", ...s.funnel.map((f, i) => `- ${f.label}: ${f.count}${i ? ` (${pct(f.count, s.funnel[i - 1].count)})` : ""}`), "",
    "## Скорость", "",
    `- От добавления до отклика: ${s.speed.to_apply.days ?? "—"} дн.`,
    `- От отклика до ответа: ${s.speed.to_answer.days ?? "—"} дн.`,
    `- От отклика до интервью: ${s.speed.to_interview.days ?? "—"} дн.`,
    `- Ждут ответа дольше ${s.wait_days} дней: ${s.waiting.length}`, "",
    "## Отклики с письмом и без", "", line(["", "Откликов", "Ответов", "Отказов", "Интервью"]), line(["---", "---:", "---:", "---:", "---:"]),
    ...s.letters.map(x => line([x.letter ? "С письмом" : "Без письма", x.applied, `${x.answered} (${pct(x.answered, x.applied)})`,
      `${x.rejected} (${pct(x.rejected, x.applied)})`, `${x.interview} (${pct(x.interview, x.applied)})`])), "",
    "## По периодам", "", line(["Период", ...s.metrics.map(m => m.label)]), line(["---", ...s.metrics.map(() => "---:")]),
    ...[...s.series].reverse().map(p => line([statPeriod(p, s.step) + (p.partial ? " (идёт)" : ""), ...s.metrics.map(m => p[m.key])]))].join("\n");
}

$("mStats").onclick = openStats;
