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
      <div><h3>Оценки вакансий</h3><p class="hint">Все вакансии профиля. Какие оценки и ответы «откликаться» дала модель и какие — вы в «Моих оценках»; в ваших кольцах — и вакансии, которые вы ещё не оценили.</p>
        ${scoreRings(s.scores, s.total_vacancies)}</div>
      <div><h3>Оценки: модель и вы</h3><p class="hint">Процент от всех оценок модели и от всех ваших — так распределения сравнимы, хотя оценок у вас меньше.</p>
        <div class="stpair"><div><h4 class="stsub">Оценки</h4>${scoresChart(s.scores)}</div><div><h4 class="stsub">Ответ «откликаться»</h4>${answersChart(s.scores)}</div></div></div>
      <div><h3>Общая оценка: модель и вы</h3><p class="hint">Только вакансии, где есть и оценка модели, и ваша: насколько модель ставит выше или ниже вас. Чем больше столбик в центре, тем точнее модель настроена под вас; если вакансий по краям много — пора откалибровать критерии.</p>
        <div class="stpair"><div><h4 class="stsub">Оценки</h4>${diffChart(s.scores)}</div><div><h4 class="stsub">Ответ «откликаться»</h4>${answersMatrix(s.scores)}</div></div></div>
      <div><h3>Оценки и результат откликов</h3><p class="hint">Все отклики профиля: как часто отвечают и зовут на интервью в зависимости от оценки. Если у вакансий с высокой оценкой ответов не больше, чем у остальных, — оценка отражает критерии, а не шансы.</p>
        ${outcomesTable(s.outcomes)}</div>
      <div><h3>Модель и вы по неделям</h3><p class="hint">Вакансии с вашей оценкой — по неделе последнего разбора моделью: сколько оценок совпало с вашими (±1 балл) и сколько ответов «откликаться». ✎ — неделя, когда меняли критерии: видно, стала ли модель после этого точнее.</p>
        ${agreementChart(s.agreement)}</div>
      <div><h3>Модели</h3><p class="hint">Все вакансии профиля: какая модель их оценила. «Совпало с вами» — по вакансиям, где есть и ваша оценка: точно и с разницей не больше балла.</p>
        ${enginesTable(s.engines, s.total_vacancies)}</div>
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

// Оценки 1…10 в долях: у каждой пара столбиков — модель и вы, процент от всех своих оценок
function scoresChart(sc) {
  if (!sc || (!sc.model.some(Boolean) && !sc.mine.some(Boolean))) return '<p class="muted">Оценок пока нет.</p>';
  const tot = {model: sc.model.reduce((a, b) => a + b, 0), mine: sc.mine.reduce((a, b) => a + b, 0)};
  const val = (v, who) => tot[who] ? v / tot[who] * 100 : 0;
  const W = 460, H = 150, pad = 18, w = W / 10, bw = w * .38;
  const max = Math.max(1, ...sc.model.map(v => val(v, "model")), ...sc.mine.map(v => val(v, "mine")));
  const bar = (v, x, cls, who, i) => { if (!v) return ""; const h = val(v, cls) / max * (H - pad), p = Math.round(val(v, cls));
    return `<rect x="${x}" y="${H - h}" width="${bw}" height="${h}" rx="2" class="${cls}"><title>${who}: оценка ${i + 1} — ${v} ${plural(v, "вакансия", "вакансии", "вакансий")} (${p}% оценок)</title></rect>
      <text x="${x + bw / 2}" y="${H - h - 4}" text-anchor="middle" class="small">${p}%</text>`; };
  return `<svg class="stchart stscores" viewBox="0 0 ${W} ${H + 24}" role="img" aria-label="Распределение оценок в долях: модель и вы">
    ${sc.model.map((v, i) => `<g>${bar(v, i * w + w / 2 - bw - 1, "model", "Модель", i)}${bar(sc.mine[i], i * w + w / 2 + 1, "mine", "Вы", i)}
      <text x="${i * w + w / 2}" y="${H + 16}" text-anchor="middle" class="axis">${i + 1}</text></g>`).join("")}
    <line x1="0" x2="${W}" y1="${H}" y2="${H}"/></svg>
    <div class="stlegend"><span><i style="background:var(--s-model)"></i>Модель</span><span><i style="background:var(--s-mine)"></i>Вы</span></div>
    ${sc.both ? `<p class="small">Оценены и вами, и моделью — ${sc.both}: модель выше вас у ${sc.higher}, ниже — у ${sc.lower}.</p>`
      : `<p class="hint">Своих оценок пока нет — поставьте их в карточке вакансии («Поставить свои оценки») или в калибровке.</p>`}`;
}

// Ответы «да / возможно / нет» в долях: у каждого пара столбиков — модель и вы, процент от всех своих ответов
const ANSWERS = ["Да", "Возможно", "Нет"];
function answersChart(sc) {
  const m = sc?.ans_model || [0, 0, 0], y = sc?.ans_mine || [0, 0, 0];
  const tot = {model: m.reduce((a, b) => a + b, 0), mine: y.reduce((a, b) => a + b, 0)};
  if (!tot.model && !tot.mine) return '<p class="muted">Ответов пока нет.</p>';
  const val = (v, who) => tot[who] ? v / tot[who] * 100 : 0;
  const W = 300, H = 150, pad = 18, w = W / 3, bw = 34, max = Math.max(1, ...m.map(v => val(v, "model")), ...y.map(v => val(v, "mine")));
  const bar = (v, x, cls, who, i) => { if (!v) return ""; const h = val(v, cls) / max * (H - pad), p = Math.round(val(v, cls));
    return `<rect x="${x}" y="${H - h}" width="${bw}" height="${h}" rx="2" class="${cls}2"><title>${who}: «${ANSWERS[i].toLowerCase()}» — ${v} ${plural(v, "вакансия", "вакансии", "вакансий")} (${p}% ответов)</title></rect>
      <text x="${x + bw / 2}" y="${H - h - 4}" text-anchor="middle" class="small">${p}%</text>`; };
  return `<svg class="stchart stscores" viewBox="0 0 ${W} ${H + 24}" role="img" aria-label="Ответы «откликаться» в долях: модель и вы">
    ${ANSWERS.map((l, i) => `<g>${bar(m[i], i * w + w / 2 - bw - 2, "model", "Модель", i)}${bar(y[i], i * w + w / 2 + 2, "mine", "Вы", i)}
      <text x="${i * w + w / 2}" y="${H + 16}" text-anchor="middle" class="axis">${l}</text></g>`).join("")}
    <line x1="0" x2="${W}" y1="${H}" y2="${H}"/></svg>
    <div class="stlegend"><span><i style="background:var(--s-model2)"></i>Модель</span><span><i style="background:var(--s-mine2)"></i>Вы</span></div>
    <p class="small">Ответов модели — ${tot.model}, ваших — ${tot.mine}.</p>`;
}

// Кто что ответил, где есть оба ответа: строка — модель, столбец — вы; совпадения — по диагонали
function answersMatrix(sc) {
  if (!sc?.ans_both) return '<p class="hint">Пока нет вакансий, где ответили и модель, и вы.</p>';
  const mx = sc.ans_matrix, max = Math.max(1, ...mx.flat()), same = mx[0][0] + mx[1][1] + mx[2][2];
  const soft = mx[0][1] + mx[1][0] + mx[1][2] + mx[2][1], hard = mx[0][2] + mx[2][0];
  return `<table class="stat stanswers"><thead><tr><th class="muted small" title="Строка — ответ модели, столбец — ваш">модель ↓ вы →</th>${ANSWERS.map(a => `<th>${a}</th>`).join("")}<th>Всего</th></tr></thead>
    ${mx.map((row, i) => `<tr><th>${ANSWERS[i]}</th>${row.map((n, j) => `<td class="${i === j ? "same" : Math.abs(i - j) === 2 ? "far" : ""}"
        style="--a:${n / max}" title="Модель — «${ANSWERS[i].toLowerCase()}», вы — «${ANSWERS[j].toLowerCase()}»: ${n} (${pct(n, sc.ans_both)})">${n || ""}</td>`).join("")}
      <td class="muted">${row.reduce((a, b) => a + b, 0)}</td></tr>`).join("")}</table>
    <p class="small">Из ${sc.ans_both}: совпали — ${same} (${pct(same, sc.ans_both)}), соседние ответы — ${soft}, противоположные («да» и «нет») — ${hard}.</p>`;
}

// Расхождение «модель − вы»: столбик на каждую разницу; слева — модель ниже вас, в центре — совпали, справа — модель выше
function diffChart(sc) {
  if (!sc?.both) return '<p class="hint">Пока нет вакансий с обеими оценками — поставьте свои в карточке вакансии («Поставить свои оценки») или в калибровке.</p>';
  const ds = sc.diffs.map((n, i) => [i - 9, n]), used = ds.filter(([, n]) => n).map(([d]) => Math.abs(d));
  const k = Math.max(2, ...used), cols = ds.filter(([d]) => Math.abs(d) <= k);
  const W = 460, H = 130, pad = 18, w = W / cols.length, bw = Math.min(w * .6, 40), max = Math.max(1, ...cols.map(([, n]) => n));
  const what = d => d === 0 ? "совпали" : d > 0 ? `модель выше на ${d}` : `модель ниже на ${-d}`;
  const same = ds.find(([d]) => d === 0)[1];
  return `<svg class="stchart stdiff" viewBox="0 0 ${W} ${H + 40}" role="img" aria-label="Расхождение оценок модели и ваших">
    ${cols.map(([d, n], i) => { const h = n / max * (H - pad), x = i * w + (w - bw) / 2;
      return `<g>${n ? `<rect x="${x}" y="${H - h}" width="${bw}" height="${h}" rx="2" class="${d === 0 ? "same" : d > 0 ? "model" : "mine"}"><title>${what(d)}: ${n} ${plural(n, "вакансия", "вакансии", "вакансий")} (${pct(n, sc.both)})</title></rect>
        <text x="${x + bw / 2}" y="${H - h - 4}" text-anchor="middle" class="small">${n}</text>` : ""}
        <text x="${i * w + w / 2}" y="${H + 16}" text-anchor="middle" class="axis">${d > 0 ? "+" + d : d}</text></g>`; }).join("")}
    <line x1="0" x2="${W}" y1="${H}" y2="${H}"/>
    <text x="4" y="${H + 34}" class="axis">← модель ниже вас</text><text x="${W / 2}" y="${H + 34}" text-anchor="middle" class="axis">совпали</text>
    <text x="${W - 4}" y="${H + 34}" text-anchor="end" class="axis">модель выше вас →</text></svg>
    <p class="small">Из ${sc.both}: совпали — ${same} (${pct(same, sc.both)}), модель выше вас — ${sc.higher}, ниже — ${sc.lower}.</p>`;
}

// Чем кончились отклики: группы по оценке модели, вашей оценке и вашему ответу; полоска — ответили, внутри — интервью
function outcomesTable(o) {
  if (!o) return "";
  const total = o.model.reduce((a, g) => a + g.applied, 0);
  if (!total) return '<p class="muted">Откликов пока нет.</p>';
  const row = g => `<tr class="${g.applied ? "" : "zero"}"><td>${esc(g.label)}</td><td><b>${g.applied}</b></td>
    <td class="obar" title="Ответили ${g.answered} из ${g.applied}, интервью — ${g.interview}"><span><i class="ans" style="width:${g.applied ? g.answered / g.applied * 100 : 0}%"></i><i class="int" style="width:${g.applied ? g.interview / g.applied * 100 : 0}%"></i></span></td>
    <td>${g.applied ? pct(g.answered, g.applied) : "—"}</td><td>${g.applied ? pct(g.interview, g.applied) : "—"}</td><td>${g.applied ? pct(g.rejected, g.applied) : "—"}</td></tr>`;
  const block = (title, list) => `<tr class="ohead"><th colspan="6">${title}</th></tr>${list.map(row).join("")}`;
  return `<table class="stat stoutcomes"><thead><tr><th></th><th>Откликов</th><th></th><th>Ответили</th><th>Интервью</th><th>Отказ</th></tr></thead>
    ${block("Оценка модели", o.model)}${block("Ваша оценка", o.mine)}${block("Ваш ответ «откликаться»", o.answer)}</table>
    <div class="stlegend"><span><i style="background:var(--s-src1)"></i>ответили</span><span><i style="background:var(--s-src3)"></i>из них интервью</span></div>`;
}

// Совпадение модели с вами по неделям: пара столбиков — оценка ±1 и ответ; ✎ — правка критериев
function agreementChart(weeks) {
  if (!weeks?.some(w => w.both)) return '<p class="hint">Пока нет вакансий, где есть и оценка модели, и ваша.</p>';
  weeks = weeks.slice(Math.max(0, Math.min(weeks.findIndex(w => w.both || w.edits.length), weeks.length - 4)));   // без пустых недель в начале
  const W = 720, H = 120, pad = 20, w = W / weeks.length, bw = Math.min(w * .3, 28);
  const bar = (n, of, x, cls, what, wk) => { if (!of) return ""; const v = n / of, h = Math.max(v * (H - pad), 1);
    return `<rect x="${x}" y="${H - h}" width="${bw}" height="${h}" rx="2" class="${cls}"><title>${statPeriod(wk, "week")}: ${what} — ${n} из ${of} (${pct(n, of)})</title></rect>
      <text x="${x + bw / 2}" y="${H - h - 4}" text-anchor="middle" class="small">${Math.round(v * 100)}%</text>`; };
  return `<svg class="stchart stagree" viewBox="0 0 ${W} ${H + 44}" role="img" aria-label="Совпадение оценок модели с вашими по неделям">
    ${weeks.map((wk, i) => { const cx = i * w + w / 2;
      return `<g>${wk.edits.length ? `<line class="edit" x1="${i * w + 2}" x2="${i * w + 2}" y1="4" y2="${H}"/><text x="${i * w + 5}" y="12" class="edit"><title>Правка критериев: ${wk.edits.map(d => d.split("-").reverse().join(".")).join(", ")}</title>✎</text>` : ""}
        ${bar(wk.near, wk.both, cx - bw - 3, "near", "оценка ±1 балл", wk)}${bar(wk.ans_same, wk.ans_both, cx + 3, "ans", "ответ совпал", wk)}
        <text x="${cx}" y="${H + 16}" text-anchor="middle" class="axis">${statPeriod(wk, "week").split("–")[0]}</text>
        <text x="${cx}" y="${H + 30}" text-anchor="middle" class="small">${wk.both ? `из ${wk.both} ${plural(wk.both, "вакансии", "вакансий", "вакансий")}` : "—"}</text></g>`; }).join("")}
    <line x1="0" x2="${W}" y1="${H}" y2="${H}"/></svg>
    <div class="stlegend"><span><i style="background:var(--s-model)"></i>оценка совпала ±1 балл</span><span><i style="background:var(--s-model2)"></i>ответ совпал</span><span>✎ правка критериев</span></div>`;
}

// Модели: локальная, GigaChat, без оценки — вакансий и доля, быстрая оценка или полный разбор, решения, совпадение с вами
function enginesTable(list, total) {
  if (!list) return "";
  const NAMES = {local: "Локальная", cloud: "GigaChat", none: "Без оценки"};
  const HINT = {local: "на этом компьютере", cloud: "облако Сбера", none: "не разобраны"};
  const dec = e => e.key === "none" ? '<span class="muted">—</span>'
    : `<span class="good">${e.yes}</span> / <span class="mid">${e.maybe}</span> / <span class="bad">${e.no}</span>`;
  const agree = e => e.key === "none" ? '<span class="muted">—</span>' : !e.both ? '<span class="muted">нет ваших оценок</span>'
    : `<b>${pct(e.same, e.both)}</b> <span class="muted">из ${e.both}</span><div class="muted small">±1 балл — ${pct(e.near, e.both)}</div>`;
  return `<table class="stat stengines"><thead><tr><th>Модель</th><th></th><th>Вакансий</th><th title="Полный разбор / быстрая оценка (первая ступень из двух)">Полный / быстрый</th>
      <th title="Решение «откликаться»: да / возможно / нет">Да / возм. / нет</th><th>Совпало с вами</th></tr></thead>
    ${list.map(e => `<tr class="${e.count ? "" : "zero"}"><td class="ename"><span class="eicon ${e.key}">${MODEL_ICON[e.key]}</span><b>${NAMES[e.key]}</b><div class="muted small">${e.names?.length ? esc(e.names.join(", ")) : HINT[e.key]}</div></td>
      <td class="ebar"><span><i class="${e.key}" style="width:${total ? e.count / total * 100 : 0}%"></i></span></td>
      <td><b>${e.count}</b> <span class="muted">${pct(e.count, total)}</span></td>
      <td>${e.key === "none" ? '<span class="muted">—</span>' : `${e.full} / ${e.short}`}</td><td>${dec(e)}</td><td>${agree(e)}</td></tr>`).join("")}</table>`;
}

// Два кольца: оценки модели и ваши, ваши — вместе с неоценёнными вакансиями. Оценки 1…10 — от светлого к тёмному
// Оценки 1–10: от красного через жёлтый к зелёному — соседние оценки различимы, низкие и высокие видны сразу
const SCORE_COLORS = ["#a50026", "#d73027", "#f46d43", "#fdae61", "#fee08b", "#d9ef8b", "#a6d96a", "#66bd63", "#1a9850", "#006837"];
const scoreColor = i => SCORE_COLORS[i];
function scoreRings(sc, total) {
  if (!sc) return "";
  const sum = a => a.reduce((x, y) => x + y, 0), rest = (n, label) => n > 0 ? [{label, count: n, color: "var(--s-src0)"}] : [];
  const scores = bins => bins.map((v, i) => ({label: `Оценка ${i + 1}`, count: v, color: scoreColor(i)}));
  const answers = list => list.map((v, i) => ({label: `«${ANSWERS[i].toLowerCase()}»`, count: v, color: ANSWER_COLORS[i]}));
  const am = sc.ans_model || [0, 0, 0], ay = sc.ans_mine || [0, 0, 0];
  return `<div class="scrings">${donut("Модель", scores(sc.model), "оценено")}${donut("Вы", [...scores(sc.mine), ...rest(total - sum(sc.mine), "Не оценено вами")], "оценено")}</div>
    <div class="stlegend scscale"><span>Оценка</span>${sc.model.map((_, i) => `<span><i style="background:${scoreColor(i)}"></i>${i + 1}</span>`).join("")}
      <span><i style="background:var(--s-src0)"></i>не оценено</span></div>
    <h4 class="stsub">Ответ «откликаться»</h4>
    <div class="scrings">${donut("Модель", [...answers(am), ...rest(sum(sc.model) - sum(am), "Без ответа")], "с ответом")}${donut("Вы", [...answers(ay), ...rest(total - sum(ay), "Нет вашего ответа")], "с ответом")}</div>
    <div class="stlegend scscale">${ANSWERS.map((l, i) => `<span><i style="background:${ANSWER_COLORS[i]}"></i>${l}</span>`).join("")}
      <span><i style="background:var(--s-src0)"></i>нет ответа</span></div>`;
}

// Кольцо: части по порядку; в центре — сколько не серых (оценено / с ответом) из всех
const ANSWER_COLORS = ["var(--good)", "var(--mid)", "var(--bad)"];
function donut(title, all, what) {
  const parts = all.filter(x => x.count), sum = parts.reduce((a, x) => a + x.count, 0);
  if (!sum) return `<div class="scring"><b>${title}</b><p class="muted">Пока пусто.</p></div>`;
  const R = 60, C = 2 * Math.PI * R; let at = 0;
  const arcs = parts.map(x => { const len = x.count / sum * C, gap = parts.length > 1 ? Math.min(1.5, len / 2) : 0;
    const a = `<circle r="${R}" cx="80" cy="80" fill="none" stroke="${x.color}" stroke-width="26" stroke-dasharray="${len - gap} ${C - len + gap}"
      stroke-dashoffset="${-at}" transform="rotate(-90 80 80)"><title>${x.label}: ${x.count} (${pct(x.count, sum)})</title></circle>`;
    at += len; return a; }).join("");
  const done = parts.filter(x => x.color !== "var(--s-src0)").reduce((a, x) => a + x.count, 0);
  return `<div class="scring"><b>${title}</b><svg viewBox="0 0 160 160" role="img" aria-label="${title}">${arcs}
    <text x="80" y="78" text-anchor="middle" class="pienum">${done}</text><text x="80" y="96" text-anchor="middle" class="pielbl">из ${sum} ${what}</text></svg></div>`;
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
