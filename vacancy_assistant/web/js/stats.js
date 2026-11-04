// Раздел «Статистика» (#55): вакансии, разборы и отклики по дням, неделям и месяцам — из файлов профиля, без модели
let statStep = "week", statMetric = "applied", statData = null;
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
}

function statsHtml(s) {
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
    <div class="stcols">
      <div><h3>Воронка</h3><p class="hint">Вакансии, добавленные за эти ${range}: докуда каждая дошла. Процент — от предыдущего шага.</p>
        <table class="stat funnel">${s.funnel.map((f, i) => `<tr><td>${f.label}</td><td><b>${f.count}</b></td>
          <td class="bar"><span style="width:${s.funnel[0].count ? f.count / s.funnel[0].count * 100 : 0}%"></span></td>
          <td class="muted">${i ? pct(f.count, s.funnel[i - 1].count) : ""}</td></tr>`).join("")}</table>
        <p class="small">${s.score.avg == null ? "" : `Средняя оценка этих вакансий — <b>${s.score.avg}</b>, оценка 7+ у ${pct(s.score.good, s.score.count)}.`}</p></div>
      <div><h3>Скорость</h3><p class="hint">По всем откликам профиля.</p>
        <table class="stat"><tr><td>От добавления до отклика</td><td>${sp(s.speed.to_apply, "откл.")}</td></tr>
          <tr><td>От отклика до ответа</td><td>${sp(s.speed.to_answer, "отв.")}</td></tr>
          <tr><td>От отклика до интервью</td><td>${sp(s.speed.to_interview, "инт.")}</td></tr></table>
        <h3>Ждут ответа дольше ${s.wait_days} дней</h3>
        ${s.waiting.length ? `<table class="stat">${s.waiting.map(w => `<tr class="link" data-vac="${w.n}" title="Открыть карточку вакансии"><td>${esc(w.title)}<div class="muted small">${esc(w.company)}</div></td>
            <td class="muted">отклик ${ddmm(w.applied)}</td><td><b>${w.days}</b> дн.</td></tr>`).join("")}</table>
            <p class="hint">Можно напомнить о себе или отметить этап «Не ответили».</p>` : `<p class="muted">Таких нет.</p>`}</div>
    </div>
    <h3>Отклики с сопроводительным письмом и без</h3>
    <p class="hint">Отклики за эти ${range}. Письмо считается отправленным, если во вкладке «Письма» у него стоит отметка «Отправлено»; у старых откликов её можно поставить с прошлой датой.</p>
    <table class="stat letters"><thead><tr><th></th><th>Откликов</th><th>Ответов</th><th>Отказов</th><th>Интервью</th></tr></thead>
      ${s.letters.map(x => `<tr><td>${x.letter ? "С письмом" : "Без письма"}</td><td>${x.applied}</td>
        <td>${x.answered} <span class="muted">${pct(x.answered, x.applied)}</span></td>
        <td>${x.rejected} <span class="muted">${pct(x.rejected, x.applied)}</span></td>
        <td>${x.interview} <span class="muted">${pct(x.interview, x.applied)}</span></td></tr>`).join("")}</table>
    ${s.letters[0].applied ? "" : `<p class="hint">Пока ни у одного отклика нет отметки «Отправлено» у письма — все отклики попали в «Без письма».</p>`}
    <div class="stcols">
      <div><h3>Источники</h3><p class="hint">Вакансии, добавленные за эти ${range}.</p>
        ${s.sources.length ? `<table class="stat"><thead><tr><th></th><th>Добавлено</th><th>Отклики</th><th>Ответы</th><th>Интервью</th></tr></thead>
          ${s.sources.map(x => `<tr><td>${esc(x.source)}</td><td>${x.added}</td><td>${x.applied}</td><td>${x.answered}</td><td>${x.interview}</td></tr>`).join("")}</table>`
          : `<p class="muted">Вакансий за эти ${range} нет.</p>`}</div>
      <div><h3>Статусы сейчас</h3>
        <table class="stat">${s.statuses.map(x => `<tr><td>${esc(x.label)}</td><td>${x.count}</td></tr>`).join("")}
          ${s.flags ? `<tr><td>С флагом</td><td>${s.flags}</td></tr>` : ""}
          <tr><td class="muted">Всего вакансий</td><td class="muted">${s.total_vacancies}</td></tr></table></div>
    </div>`;
}

// Кто разместил вакансию — части столбика снизу вверх (#2): работодатель, кадровое агентство, работодатель скрыт
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
    <div class="stlegend">${STAT_KINDS.map(([k, l]) => `<span><i style="background:var(--s-${k})"></i>${l} <b>${sum[k]}</b></span>`).join("")}</div>`;
}

function bindStats() {
  document.querySelectorAll("#wbody [data-step]").forEach(b => b.onclick = () => { statStep = b.dataset.step; openStats(); });
  document.querySelectorAll("#wbody [data-metric]").forEach(b => b.onclick = () => {
    statMetric = b.dataset.metric;
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
