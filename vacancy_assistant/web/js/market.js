// Окно «Резюме против рынка»: чего не хватает резюме и что прокачать. Два источника: вакансии с откликом
// и расхождения со своей оценкой с выбранной даты — вы считаете вакансию подходящей, а модель отвергла.
// Без модели — расхождения, требования с ❌, слова из вакансий, проверка на роботов-фильтры; с моделью — что дописать
// и что нарастить; правка резюме и «о себе» тут же — с пересчётом отмеченных вакансий и «Вернуть как было»
const MK = {since: null, data: null, picked: null, resume: null, facts: null};

async function openMarket(keep = false) {
  closeMenus();
  if (!keep || !MK.since) MK.since = todayIso(-30);
  const res = await api("/api/market", {profile: state.profile, since: MK.since}).catch(fail);
  if (!res) return;
  MK.data = res;
  const own = res.own, known = n => own.under.some(v => v.n === n);
  MK.picked = keep && MK.picked ? new Set([...MK.picked].filter(known)) : new Set(own.under.map(v => v.n));   // по умолчанию — все расхождения
  MK.resume = res.resume; MK.facts = res.facts;
  dialog("Резюме против рынка", `<div id="mkBody">${marketHtml(res)}</div>`, [{label: "Закрыть"}]);
  $("wiz").classList.add("wide");
  bindMarket();
}

const mkTask = action => myTasks().some(t => isActive(t) && t.action === action);
const nvac = n => `${n} ${plural(n, "вакансия", "вакансии", "вакансий")}`;
const nin = n => `${n} ${plural(n, "вакансии", "вакансиях", "вакансиях")}`;

function mkScore(o) {
  return `<b class="${scoreClass(o.score)}">${o.score ?? "?"}</b> <span class="muted">(${o.can ?? "?"}/${o.want ?? "?"})</span>`;
}

// Вакансия, где ваше решение и решение модели разошлись: обе оценки, ваша причина, что модель не нашла в резюме;
// check — галка «пересчитать после правки» (только у «модель — нет, вы — да»: остальное — к критериям, не к резюме)
function mkCard(v, check = true) {
  const reqs = v.failed.map(q => `<li>❌ ${esc(q)}</li>`).join("") + v.criteria.map(c => `<li>❌ <b>К${esc(c.k)}</b> ${esc(c.text)}</li>`).join("");
  return `<div class="gpcard">
    <label class="gphead">${check ? `<input type="checkbox" data-mkpick="${v.n}" ${MK.picked.has(v.n) ? "checked" : ""} title="Пересчитать после правки">` : ""}
      <span><button type="button" class="linkbtn" data-mkvac="${v.n}">${esc(v.title)}</button> <span class="t-meta">· ${esc(v.company)}</span></span></label>
    <div class="gpscores"><span class="gpme">Вы: ${mkScore(v.mine)} <span class="${MY_TONE[v.mine.decision] || ""}">${esc(v.mine.decision)}</span>${v.mine.date ? ` <span class="muted">${ddmm(v.mine.date)}</span>` : ""}</span>
      <span>ИИ: ${mkScore(v.model)} ${decisionHtml(v.model.decision)}${v.model.stage === "short" ? ' <span class="muted">короткая оценка</span>' : ""}</span></div>
    ${v.mine.reason ? `<div class="gpwhy">«${esc(v.mine.reason)}»</div>` : ""}
    ${reqs ? `<ul class="gpfail">${reqs}</ul>` : `<p class="muted small gpwhy">Требований с ❌ в разборе нет${v.model.stage === "short" ? " — это короткая оценка: сделайте «Разобрать заново»" : ""}.</p>`}</div>`;
}

function marketHtml(m) {
  const own = m.own, noModel = state.no_model, busyA = mkTask("market_advice"), busyR = mkTask("market_recheck");
  const vacs = ns => `<ul class="covacs">${ns.map(n => state.rows.find(r => r.n === n)).filter(Boolean).map(r =>
    `<li><button type="button" class="linkbtn" data-mkvac="${r.n}">${esc(r.title)}</button><div class="covmeta">${esc(r.company)}</div></li>`).join("")}</ul>`;
  const missing = m.words.filter(w => !w.in_resume), have = m.words.filter(w => w.in_resume);
  const prev = [...m.history].reverse().find(h => h.date < todayIso());
  const advice = m.advice;
  const wordRow = w => `<tr><td><b>${esc(w.term)}</b></td><td>${nin(w.count)}</td>
    <td><details><summary class="muted">какие</summary>${vacs(w.vacancies)}</details></td></tr>`;
  const gapRow = g => `<tr><td>${esc(g.text)}${g.variants > 1 ? ` <span class="muted small">и ещё ${g.variants - 1} похож${g.variants - 1 === 1 ? "ее" : "их"}</span>` : ""}</td>
    <td>${nin(g.count)}</td><td><details><summary class="muted">какие</summary>${vacs(g.vacancies)}</details></td></tr>`;
  return `
    <p class="hint">Чего не хватает резюме и что прокачать, чтобы чаще проходить отбор. Программа смотрит на два сигнала:
      вакансии, на которые вы откликались (проставлен этап), — это <b>${m.vacancies}</b> из ${m.total}; и вакансии, которые вы сами
      оценили как подходящие, а модель по резюме отвергла.</p>
    <p class="hint">Списки ниже программа собирает сама, без модели. Модель понадобится только для двух кнопок:
      «Подсказать, что прокачать» и «Сохранить и пересчитать отмеченные».</p>
    ${prev ? `<p class="hint">${marketProgress(prev, m)}</p>` : ""}
    ${m.vacancies < 3 && !own.under.length ? `<p class="cwarn">Откликов пока мало — выводы будут случайными. Отметьте этап «Откликнулся» у вакансий, на которые уже откликались, и ставьте свои оценки кнопкой «Поставить свои оценки» в карточке.</p>` : ""}

    <h3>Подходят вам, а модель сказала «нет»</h3>
    <div class="gpdate"><label>С какой даты своей оценки <input type="date" id="mkSince" value="${MK.since}" max="${todayIso()}"></label>
      <button type="button" id="mkShow">Показать</button></div>
    <p class="hint">${own.rated ? `С ${ddmm(own.since)}.${own.since.slice(0, 4)} вы сами оценили <b>${nvac(own.rated)}</b>: решение совпало с моделью у ${own.same},
      модель сказала «нет», а вы «да» или «возможно» — <b>${own.under.length}</b>, наоборот — ${own.over.length}${own.waiting ? `, ждут разбора — ${own.waiting}` : ""}.`
      : "С этой даты своих оценок нет. Ставьте их кнопкой «Поставить свои оценки» в карточке вакансии или в калибровке."}
      Самый честный сигнал: по резюме и «Дополнительно о себе» модель не видит того, что нужно работодателю — либо опыт есть, но не описан, либо его стоит нарастить.
      Отмеченные галкой пересчитаются после правки ниже.</p>
    ${own.under.length ? `<div class="gplist">${own.under.map(v => mkCard(v)).join("")}</div>` : own.rated ? `<p class="muted">Таких нет: вакансии, которые вам подходят, модель не отвергала.</p>` : ""}

    <h3>Требования, которых модель не нашла в резюме</h3>
    <p class="hint">Требования с ❌ из разборов вакансий с откликом и тех, что выше; похожие склеены.</p>
    ${m.gaps.length ? `<table class="stat mktable">${m.gaps.map(gapRow).join("")}</table>` : `<p class="muted">Повторяющихся нет.</p>`}
    ${m.rare.length ? `<details class="mkmore"><summary>Встречались по разу — ${m.rare.length}</summary><table class="stat mktable">${m.rare.map(gapRow).join("")}</table></details>` : ""}

    <h3>Слова из вакансий, которых нет в резюме</h3>
    <p class="hint">Технологии, методологии, стандарты — встречаются хотя бы в ${nin(m.need)} с откликом. Рекрутер и робот-фильтр ищут в резюме именно эти слова.
      Добавляйте только то, что правда было: в «Дополнительно о себе» или в само резюме.</p>
    ${missing.length ? `<table class="stat mktable">${missing.map(wordRow).join("")}</table>` : `<p class="muted">Таких нет — все частые слова вакансий в резюме есть.</p>`}
    ${have.length ? `<details class="mkmore"><summary>Уже есть в резюме — ${have.length}</summary><p>${have.map(w => `${esc(w.term)} <span class="muted">${w.count}</span>`).join(" · ")}</p></details>` : ""}

    <h3>Что прокачать</h3>
    <p class="hint">Модель сгруппирует недостающее и для каждой компетенции скажет: есть ли опора в резюме или «о себе» — тогда «было → стало» и куда дописать;
      или опыта нет — тогда что нарастить и как быстро (проект, курс, сертификат). Ничего не придумывает.</p>
    <p class="calbar"><button type="button" class="primary" id="mkAdvice" ${busyA || noModel ? "disabled" : ""}>${busyA ? "Модель думает…" : advice ? "Подсказать заново" : "Подсказать, что прокачать"}</button>
      ${noModel ? `<span class="hint">Нужна модель — включите в «Настройках».</span>` : ""}</p>
    ${advice ? `<div class="mkadvice"><p class="muted small">${ddmm(advice.date)} · ${esc(advice.model)} · по ${nin(advice.vacancies)} с откликом${
      advice.under != null ? ` и ${advice.under} расхождени${plural(advice.under, "ю", "ям", "ям")} с ${ddmm(advice.since)}` : ""}${
      advice.resume && advice.resume !== m.resume_hash ? ` · <span class="s-mid">резюме с тех пор изменилось — подскажите заново</span>` : ""}</p>${md(advice.text)}</div>` : ""}

    <h3>Поправить и пересчитать</h3>
    ${m.recheck ? mkRecheckHtml(m.recheck) : ""}
    ${busyR ? `<p class="cwarn">Сохраняю правки и пересчитываю вакансии. Ход — на песочных часах в шапке; окно можно закрыть — итог откроется сам.</p>` : `
    <p class="hint">Допишите опыт в резюме или «Дополнительно о себе» и пересчитайте отмеченные вакансии — увидите «было → стало».
      Прежние тексты и разборы запоминаются: не понравится — «Вернуть как было».</p>
    <details class="fixedit" open><summary><b>Дополнительно о себе</b> <span class="t-meta">факты, которых нет в резюме; каждый — с «- »</span></summary>
      <textarea id="mkFacts" rows="5" class="facts" placeholder="- Руководил внедрением 1С:ERP на 3 тыс. пользователей">${esc(MK.facts)}</textarea></details>
    <details class="fixedit"><summary><b>Резюме</b> <span class="t-meta">опыт, который видит модель</span></summary>
      ${m.resume_editable ? `<textarea id="mkResume" rows="14" class="mono">${esc(MK.resume)}</textarea>`
        : `<p class="hint">Резюме лежит во внешнем файле — здесь его не поправить. Поправьте файл или перенесите резюме в папку профиля в «Параметры → Резюме».</p>`}</details>
    <p class="calbar"><button type="button" class="primary" id="mkRecheck" ${noModel || !MK.picked.size ? "disabled" : ""}>Сохранить и пересчитать отмеченные (<span id="mkCount">${MK.picked.size}</span>)</button>
      ${own.under.length ? `<button type="button" id="mkAll">Отметить все</button><button type="button" id="mkNone">Снять все</button>` : ""}
      ${!own.under.length ? `<span class="hint">Пересчитать можно вакансии из раздела «Подходят вам, а модель сказала «нет»» — сейчас их нет.</span>` : ""}</p>`}

    <h3>Проверка на роботов-фильтры (ATS)</h3>
    <ul class="mkats">${m.ats.map(a => `<li class="${a.ok ? "s-good" : "s-bad"}">${a.ok ? "✓" : "✗"} <span>${esc(a.text)}</span></li>`).join("")}</ul>

    ${own.over.length ? `<details class="mkmore"><summary>Модель сказала «да», вы — «нет»: ${own.over.length}</summary>
      <p class="hint">Модель переоценивает — это скорее к критериям, чем к резюме: откройте вакансию и нажмите «Поставить свои оценки» → «Поправлю сам»
        или «Подобрать правку критериев». Если вакансий много — калибровка.</p>
      <div class="gplist">${own.over.map(v => mkCard(v, false)).join("")}</div></details>` : ""}`;
}

// Прогресс с прошлой проверки: сколько частых слов вакансий не хватает резюме — и почему число изменилось
function marketProgress(prev, m) {
  const words = n => `${n} ${plural(n, "слова", "слов", "слов")}`;
  const delta = m.missing - prev.missing, more = m.vacancies - (prev.vacancies ?? m.vacancies);
  const head = `<b>Прогресс с ${ddmm(prev.date)}.</b> Тогда в резюме не хватало ${words(prev.missing)} из вакансий с откликом, сейчас не хватает <b>${words(m.missing)}</b>`;
  if (!delta) return `${head}: без изменений.`;
  if (delta < 0) return `${head} <span class="s-good">▼ ${-delta}</span>: резюме стало ближе к вакансиям.`;
  return `${head} <span class="s-mid">▲ ${delta}</span>: ${more > 0
    ? `с тех пор вы откликнулись ещё на ${more} ${plural(more, "вакансию", "вакансии", "вакансий")} (было ${prev.vacancies}, стало ${m.vacancies}), и в них встретились новые слова — это не значит, что резюме стало хуже`
    : "в вакансиях с откликом стали чаще встречаться слова, которых нет в резюме, — или из резюме убрали что-то нужное"}.`;
}

// Итог пересчёта: по каждой вакансии — было → стало (оценка, решение, требования с ❌)
function mkRecheckHtml(rc) {
  const names = {resume: "резюме", facts: "«Дополнительно о себе»"};
  const title = n => (state.rows.find(r => r.n === n) || {}).title || `№${n}`;
  const yes = d => d && !d.startsWith("нет");
  const better = rc.items.filter(it => yes(it.after.decision) && !yes(it.before.decision)).length;
  const row = it => {
    const b = it.before, a = it.after;
    const fail = b.failed === a.failed ? `${a.failed}` : `${b.failed} → <b class="${a.failed < b.failed ? "s-good" : "s-bad"}">${a.failed}</b>`;
    return `<li><div>${esc(title(it.n))}</div><div class="gpmeta">оценка ${scoreDelta(a.score, b.score)} · ${decisionHtml(b.decision || "")} → ${decisionHtml(a.decision || "")}
      · требований с ❌: ${fail}</div></li>`;
  };
  return `<div class="gpresult"><p><b>Пересчёт ${esc(rc.date.slice(8, 10))}.${esc(rc.date.slice(5, 7))} ${esc(rc.date.slice(11))}:</b>
      ${rc.changed.length ? `сохранено — ${rc.changed.map(k => names[k]).join(", ")}` : "тексты не менялись"}; решение стало «да» у ${better} из ${rc.items.length}.</p>
    <ul class="gpitems">${rc.items.map(row).join("")}</ul>
    <p class="calbar"><button type="button" id="mkUndo">Вернуть как было</button>
      ${rc.changed.length ? `<span class="hint">Оценки остальных вакансий посчитаны по прежним текстам — в таблице они помечены ↻.</span>` : ""}</p></div>`;
}

function bindMarket() {
  const reopen = () => openMarket(true);
  $("mkShow").onclick = () => { MK.since = $("mkSince").value || todayIso(-30); MK.picked = null; reopen(); };
  $("mkSince").onkeydown = e => { if (e.key === "Enter") $("mkShow").click(); };
  document.querySelectorAll("#mkBody [data-mkvac]").forEach(b => b.onclick = e => {
    e.preventDefault();
    closeWizard();
    goToVacancy(+b.dataset.mkvac);
  });
  const count = () => { if ($("mkCount")) { $("mkCount").textContent = MK.picked.size; $("mkRecheck").disabled = state.no_model || !MK.picked.size; } };
  document.querySelectorAll("#mkBody [data-mkpick]").forEach(c => c.onchange = () => {
    c.checked ? MK.picked.add(+c.dataset.mkpick) : MK.picked.delete(+c.dataset.mkpick);
    count();
  });
  const all = on => {
    MK.picked = new Set(on ? MK.data.own.under.map(v => v.n) : []);
    document.querySelectorAll("#mkBody [data-mkpick]").forEach(c => { c.checked = MK.picked.has(+c.dataset.mkpick); });
    count();
  };
  if ($("mkAll")) $("mkAll").onclick = () => all(true);
  if ($("mkNone")) $("mkNone").onclick = () => all(false);
  if ($("mkFacts")) { bulletArea($("mkFacts")); $("mkFacts").oninput = e => { MK.facts = e.target.value; }; }
  if ($("mkResume")) $("mkResume").oninput = e => { MK.resume = e.target.value; };
  $("mkAdvice").onclick = async () => { await run("market_advice", {since: MK.since}); reopen(); };
  if ($("mkRecheck")) $("mkRecheck").onclick = async () => {
    const m = MK.data, edits = {};
    if ($("mkFacts") && $("mkFacts").value.trim() !== (m.facts || "").trim()) edits.facts = $("mkFacts").value;
    if ($("mkResume") && $("mkResume").value.trim() !== (m.resume || "").trim()) edits.resume = $("mkResume").value;
    if (edits.resume !== undefined && !edits.resume.trim()) return toast("Резюме не может быть пустым");
    if (!Object.keys(edits).length && !confirm("Резюме и «о себе» не менялись. Просто пересчитать отмеченные вакансии?")) return;
    await run("market_recheck", {since: MK.since, ns: [...MK.picked], ...edits});
    reopen();
  };
  if ($("mkUndo")) $("mkUndo").onclick = async () => {
    if (!confirm("Вернуть прежние резюме, «о себе» и прежние разборы пересчитанных вакансий?")) return;
    try { await api("/api/market/undo", {profile: state.profile}); }
    catch (e) { return fail(e); }
    toast("Вернул как было");
    await load(state.profile);
    openMarket(true);
  };
}

$("mMarket").onclick = () => openMarket();
