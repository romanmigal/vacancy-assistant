// «Итоги недели»: неделя рядом с предыдущей и всем временем, переходы воронки, что не подходило, вывод.
// Без модели. В начале новой недели — плашка с итогами прошлой, пока её не открыли или не скрыли
let weekWhich = "last";
const weekSeenKey = () => `weeklySeen:${state.profile}`;

async function openWeekly(which) {
  closeMenus();
  if (which) weekWhich = which;
  const res = await api(`/api/weekly?profile=${encodeURIComponent(state.profile)}&week=${weekWhich}`).catch(fail);
  if (!res) return;
  if (res.which === "last") { remember(weekSeenKey(), res.start); $("weekBar").hidden = true; }
  dialog("Итоги недели", weeklyHtml(res), [
    {label: "Скопировать как Markdown", left: true, title: "Итоги недели текстом — например, чтобы обсудить с карьерным консультантом",
     onClick: () => navigator.clipboard.writeText(res.markdown).then(() => toast("Скопировано"), fail)},
    {label: "Статистика…", left: true, title: "Подробно по дням, неделям и месяцам", onClick: () => { closeWizard(); openStats(); }},
    {label: "Закрыть"}]);
  $("wiz").classList.add("wide");
  document.querySelectorAll("#wbody [data-week]").forEach(b => b.onclick = () => openWeekly(b.dataset.week));
}

function weeklyHtml(w) {
  const arrow = (a, b) => a === b || w.partial ? "" : `<span class="${a > b ? "up" : "down"}">${a > b ? "▲" : "▼"} ${Math.abs(a - b)}</span>`;
  return `
    <div class="lkinds">${[["last", "Прошлая неделя"], ["this", "Эта неделя"]].map(([k, l]) =>
      `<button type="button" class="lkind ${k === w.which ? "on" : ""}" data-week="${k}">${l}</button>`).join("")}</div>
    <p class="hint">${ddmmyyyy(w.start)} — ${ddmmyyyy(w.end)}${w.partial ? ", неделя ещё идёт" : ""}. Всё считается по файлам профиля, без модели.</p>
    ${w.advice.length ? `<ul class="wkadvice">${w.advice.map(a => `<li class="${a.kind}">${esc(a.text)}</li>`).join("")}</ul>` : ""}
    <table class="stat wktable"><thead><tr><th></th><th>Неделя</th><th>Неделей раньше</th><th>Всё время</th></tr></thead>
      ${w.metrics.map(m => `<tr><td>${m.label}</td><td class="nowrap"><b>${w.week[m.key]}</b> ${arrow(w.week[m.key], w.prev[m.key])}</td>
        <td class="muted">${w.prev[m.key]}</td><td>${w.total[m.key]}</td></tr>`).join("")}</table>
    <div class="stcols">
      <div><h3>Переходы</h3><p class="hint">Какая доля дошла до следующего шага. Где процент ниже всего — там затык. Неделя — вакансии, разобранные за ${w.partial ? "эту" : "прошлую"} неделю: докуда успели дойти; ответы и интервью приходят позже, поэтому дальше отклика по неделе судить рано. «Оценка 7+ → Отклик» — только отклики на вакансии с оценкой 7+.</p>
        <table class="stat"><thead><tr><th></th><th>${w.partial ? "Эта неделя" : "Неделя"}</th><th>За всё время</th></tr></thead>
        ${w.conversions.map(c => `<tr><td>${c.label}</td>
          <td>${!c.week ? '<span class="muted small">рано судить</span>' : c.week.pct == null ? '<span class="muted">—</span>'
            : `<b>${c.week.pct}%</b> <span class="muted small">${c.week.n} из ${c.week.of}</span>`}</td>
          <td>${c.pct == null ? '<span class="muted">—</span>' : `<b>${c.pct}%</b>`}</td></tr>`).join("")}</table></div>
      <div><h3>Что чаще всего не подходило</h3><p class="hint">Критерии с ❌ в разборах ${w.partial ? "этой" : "прошлой"} недели.</p>
        ${w.reasons.length ? `<table class="stat">${w.reasons.map(r => `<tr><td>${esc(r.name)}</td><td>${r.count}</td></tr>`).join("")}</table>`
          : `<p class="muted">Разборов с ❌ за неделю нет.</p>`}
        ${w.reasons_total.length ? `<details class="mkmore"><summary>За всё время</summary><table class="stat">${
          w.reasons_total.map(r => `<tr><td>${esc(r.name)}</td><td>${r.count}</td></tr>`).join("")}</table></details>` : ""}</div>
    </div>
    ${w.title_drops.length || w.salary_filter ? `<h3>Отсеяно при поиске</h3>
      <p class="hint">Найденные поиском hh, которые модель не разбирала: в названии стоп-слово или нет слов про уровень и сферу — причина по нынешним правилам отбора${w.salary_filter ? "; вакансии с низкой зарплатой отсекает сам hh.ru, поэтому их число неизвестно" : ""}. Настроить — «Параметры → Отбор при поиске».</p>
      <table class="stat">${w.title_drops.map(d => `<tr><td>${esc(d.reason)}</td><td>${d.count}</td>
        <td class="muted small">${d.examples.map(esc).join("; ")}</td></tr>`).join("")}
        ${w.salary_filter ? `<tr><td>${esc(w.salary_filter.text)}</td><td class="muted">—</td><td class="muted small">отсекает hh.ru: такие вакансии программа не скачивает</td></tr>` : ""}</table>` : ""}`;
}

// Плашка в начале новой недели: итоги прошлой, если на ней что-то было
async function checkWeekly() {
  if (!state.profile || !state.rows.length) return;
  const w = await api(`/api/weekly?profile=${encodeURIComponent(state.profile)}&week=last`).catch(() => null);
  if (!w || recall(weekSeenKey()) === w.start) return;
  const k = w.week;
  if (!k.added && !k.applied && !k.answered && !k.interview) return;
  const parts = [`${k.added} ${plural(k.added, "вакансия добавлена", "вакансии добавлено", "вакансий добавлено")}`,
    `${k.applied} ${plural(k.applied, "отклик", "отклика", "откликов")}`, `${k.answered} ${plural(k.answered, "ответ", "ответа", "ответов")}`,
    k.interview ? `${k.interview} интервью` : ""].filter(Boolean);
  $("weekBar").innerHTML = `<b>Итоги прошлой недели</b> <span>${ddmm(w.start)}–${ddmm(w.end)}: ${parts.join(", ")}</span>
    <button type="button" class="small primary" id="weekOpen">Открыть</button>
    <button type="button" class="small" id="weekHide" title="Не показывать до следующей недели">Скрыть</button>`;
  $("weekBar").hidden = false;
  $("weekOpen").onclick = () => openWeekly("last");
  $("weekHide").onclick = () => { remember(weekSeenKey(), w.start); $("weekBar").hidden = true; };
}

$("mWeekly").onclick = () => openWeekly("last");
