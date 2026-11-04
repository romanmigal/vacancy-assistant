// Окно «Мои оценки» в карточке вакансии, бывшее «Не согласен с оценкой»: своя оценка («Могу», «Хочу», решение), дальше — на выбор:
// просто сохранить её; правка критериев моделью (что повлияло → правка и проверка на этой вакансии →
// проверка на оценённых → применить); или правка своими руками — критерии, резюме, «о себе» — и пересчёт вакансии.
// Обычные скрипты (не модули): подключаются по порядку в index.html и видят функции друг друга.

const F = {n: null, step: 0, mode: "model", v: null, can: null, want: null, decision: "", reason: "", marks: new Set(), manual: null, editing: false};
const FSTEPS = ["Ваша оценка", "Что повлияло", "Правка критериев", "Проверка на оценённых", "Применить"];
const FSTEPS_HAND = ["Ваша оценка", "Правка и пересчёт"];
const fixTask = action => myTasks().find(t => isActive(t) && t.action === action && (action === "fix_check" || t.n === F.n));
const yesOf = d => !d ? null : !d.startsWith("нет");

// Выше или ниже должна быть оценка: решение важнее числа; оценки рядом и решение то же — править нечего
const fixScore = () => myTotal(F.can, F.want, F.decision);
function fixDirection() {
  const m = F.v.model, yes = F.decision ? F.decision !== "нет" : null, myes = yesOf(m.decision), score = fixScore();
  if (yes !== null && myes !== null && yes !== myes) return yes ? "up" : "down";
  if (score && m.score != null && Math.abs(score - m.score) >= 2) return score > m.score ? "up" : "down";
  return null;
}
const fixRated = () => F.can && F.want && F.decision;

async function openFix(n) {
  try { F.v = await api(`/api/fix?profile=${encodeURIComponent(state.profile)}&n=${n}`); }
  catch (e) { return fail(e); }
  const st = F.v.state, mine = F.v.mine, row = state.rows.find(r => r.n === n);
  if (F.n !== n) {                                    // другая вакансия — с начала, с прежней своей оценкой, если была
    Object.assign(F, {n, step: 0, mode: F.v.recheck ? "hand" : "model", can: mine.can, want: mine.want, decision: decWord(mine.decision),
                      reason: mine.reason || (row && row.note) || "", marks: new Set(st ? st.marks : []), manual: null, editing: false});
    if (F.v.recheck) F.step = 1;                      // пересчёт после своей правки — к его итогу
  }
  if (F.mode === "hand") F.editing = F.editing && !F.v.recheck;
  else if (st) F.step = Math.max(F.step, st.reference ? 3 : 2);          // правка уже есть — к ней
  else if (!fixTask("fix_suggest")) F.step = Math.min(F.step, 1);
  $("wiz").classList.add("open");
  fixRender();
}

function fixRender() {
  const v = F.v, m = v.model, st = v.state, dir = (st && st.direction) || fixDirection(), up = dir === "up";
  $("wtitle").textContent = "Мои оценки";
  $("wiz").classList.remove("wide");
  $("wsteps").innerHTML = (F.mode === "hand" ? FSTEPS_HAND : FSTEPS).map((t, i) => `<span class="${i === F.step ? "on" : i < F.step ? "done" : "off"}">${i + 1}. ${t}</span>`).join("");
  const head = `<p class="fixvac"><b>${esc(v.title)}</b>${v.company ? ` <span class="t-meta">· ${esc(v.company)}</span>` : ""}<br>
    Модель: <b class="${scoreClass(m.score)}">${m.score ?? "?"}</b>/10 · ${decisionHtml(m.decision)}${m.want != null ? ` <span class="t-meta">(Могу ${m.can ?? "?"}, Хочу ${m.want})</span>` : ""}</p>`;
  let body = head, foot = `<button class="left" id="fClose">Закрыть</button>`;

  if (F.step === 0) {
    const d = fixDirection();
    body += `<h3>Как вам эта вакансия?</h3>
      ${myScoreHtml(F, "f")}
      ${field("Почему", `<textarea id="fReason" rows="2" class="reason" placeholder="1–2 фразы: например, «вакансии с ИИ мне интересны, даже если в резюме нет опыта в ИИ»">${esc(F.reason)}</textarea>`,
        "Главное для правки: по причине модель поймёт, какое общее правило поменять в критериях.")}
      <p class="${d ? "hint" : "cwarn"}" id="fDir">${fixDirText(d)}</p>
      <p class="hint">Что дальше — на выбор: <b>«Сохранить оценку»</b> — только запомнить её, следующая автонастройка в «Калибровке» её учтёт;
        <b>«Поправлю сам»</b> — здесь же поправить критерии, резюме или «Дополнительно о себе» и пересчитать эту вакансию;
        <b>«Подобрать правку критериев»</b> — модель предложит правку и проверит её. Оценка сохраняется в любом случае.
        Что выбрать — в гиде <a href="/help/docs/${encodeURIComponent("Оценка не совпадает с вашей.md")}" target="_blank" rel="noopener">«Оценка не совпадает с вашей»</a>.</p>`;
    foot += `<button id="fSave">Сохранить оценку</button><button id="fHand">Поправлю сам</button>
      <button class="primary" id="fNext" ${d ? "" : "disabled"} title="${d ? "" : "Доступно, когда ваша оценка расходится с оценкой модели"}">Подобрать правку критериев</button>`;
  }

  if (F.mode === "hand" && F.step === 1) {
    const t = fixTask("fix_recheck"), rc = v.recheck;
    if (t) body += `<h3>Пересчёт вакансии</h3><p class="cwarn">Сохраняю правки и заново разбираю вакансию. ${fixTime(1)} Ход — на песочных часах в шапке; окно можно закрыть — итог откроется сам.</p>`;
    else if (rc && !F.editing) body += fixRecheckHtml(rc);
    else body += fixHandHtml();
    foot += `<button id="fBack">Назад</button>`;
    if (!t && rc && !F.editing) foot += `<button id="fUndo">Вернуть как было</button><button id="fMore">Поправить ещё</button><button class="primary" id="fDone">Готово</button>`;
    else if (!t) foot += `<button class="primary" id="fRecheck">Сохранить и пересчитать вакансию</button>`;
  }

  if (F.mode === "model" && F.step === 1) {
    const f = v.factors, kmap = criteriaMap(v.criteria);
    const item = (key, text, extra = "") => `<label class="fixitem"><input type="checkbox" data-mark="${esc(key)}" ${F.marks.has(key) ? "checked" : ""}> <span>${text}${extra}</span></label>`;
    const crit = f.criteria.filter(c => up ? c.mark !== "✅" : c.mark === "✅").map(c => {
      const key = `К${c.k}${kmap[c.k] ? ` (${kmap[c.k].split(/[:.(—]/)[0].trim()})` : ""}: ${c.mark} ${c.text}`;
      return item(key, `<b>К${c.k}</b> ${c.mark} ${esc(c.text)}`, kmap[c.k] ? `<div class="t-meta">${esc(kmap[c.k])}</div>` : "");
    }).join("");
    const reqs = f.requirements.filter(r => up ? !r.ok : r.ok).map(r => item(`Требование: ${r.text}`, esc(r.text))).join("");
    const more = (up ? f.gaps : f.strengths).map(g => item(`${up ? "Пробел" : "Сильная сторона"}: ${g}`, esc(g))).join("");
    const block = (title, html) => html ? `<div class="chead">${title}</div>${html}` : "";
    body += `<h3>Что повлияло на оценку</h3>
      <p class="hint">Отметьте, что модель учла неверно${up ? " — из-за чего оценка, по-вашему, занижена" : " — из-за чего оценка, по-вашему, завышена"}. Можно ничего не отмечать: тогда модель опирается только на причину «${esc(F.reason || "не указана")}».</p>
      ${f.want ? `<p class="why"><b>Хочу:</b> ${esc(f.want)}</p>` : ""}${f.can ? `<p class="why"><b>Могу:</b> ${esc(f.can)}</p>` : ""}
      <div class="fixlist">${block(up ? "Критерии — нарушены или под вопросом" : "Критерии — выполнены", crit)}
        ${block(up ? "Требования, которых нет в резюме" : "Требования, которые вы закрываете", reqs)}
        ${block(up ? "Пробелы" : "Сильные стороны", more)}</div>
      ${!crit && !reqs && !more ? `<p class="hint">В разборе нечего отметить${m.stage === "short" ? " — это короткая оценка, в ней нет требований и пробелов" : ""}.</p>` : ""}
      <p class="cwarn" id="fGap" ${up && [...F.marks].some(k => /^(Требование|Пробел)/.test(k)) ? "" : "hidden"}>Отмеченное — пробел в резюме, а не в критериях. Правка критериев может лишь сказать модели не отказывать из-за него, если есть смежный опыт; «Могу» от этого не вырастет. Если такой опыт у вас есть — допишите его в «Дополнительно о себе» («Параметры → Резюме»): тогда модель его увидит. Пометка о пробеле в разборе останется — она нужна для письма и подготовки к интервью.</p>`;
    foot += `<button id="fBack">Назад</button><button class="primary" id="fPropose" ${fixTask("fix_suggest") ? "disabled" : ""}>Предложить правку</button>`;
  }

  if (F.mode === "model" && F.step === 2) {
    const t = fixTask("fix_suggest");
    body += `<h3>Правка критериев</h3>`;
    if (t) body += `<p class="cwarn">Модель предлагает правку и проверяет её на этой вакансии. ${fixTime(2)} Ход — на песочных часах в шапке; окно можно закрыть — итог откроется сам.</p>`;
    else if (!st) body += `<p class="hint">Правки пока нет — вернитесь на шаг «Что повлияло» и нажмите «Предложить правку».</p>`;
    else {
      const b = st.before, a = st.after;
      body += st.problem ? `<p class="cwarn">Правка отброшена: ${esc(st.problem)}. Попробуйте другой вариант или поправьте вручную.</p>`
        : `<p><b>Что меняю:</b> ${esc(st.what)}</p>
          <div class="diff">${st.diff.filter(l => !l.startsWith("@@")).map(l => `<div class="${l[0] === "+" ? "add" : l[0] === "-" ? "del" : ""}">${esc(l)}</div>`).join("")}</div>
          <h3>Проверка на этой вакансии</h3>
          <div class="scores">
            <div class="scorebox"><div class="lbl">Было</div><div class="val ${scoreClass(b.score)}">${b.score ?? "?"}<small>/10</small></div><div class="lbl">${decisionHtml(b.decision)}</div></div>
            <div class="scorebox total"><div class="lbl">Стало</div><div class="val ${scoreClass(a.score)}">${a.score ?? "?"}<small>/10</small></div><div class="lbl">${decisionHtml(a.decision)}</div></div>
            ${a.want != null ? `<div class="scorebox"><div class="lbl">Могу · Хочу</div><div class="val">${a.can ?? "?"} · ${a.want}</div></div>` : ""}
          </div>
          <p class="${st.achieved ? "hint" : "cwarn"}">${st.achieved ? "Оценка сдвинулась в нужную сторону. Разбор этой вакансии не сохранён — это только проверка."
            : `Оценка не сдвинулась ${st.direction === "up" ? "вверх" : "вниз"}. Попробуйте другой вариант или поправьте вручную.`}
            ${st.achieved && st.direction === "up" && a.can != null && a.can < a.score + 2 && a.can <= 6 ? " Оценку сдерживает «Могу» — пробелы в резюме: критерии их не закроют, а «Дополнительно о себе» — может." : ""}</p>`;
      body += F.manual !== null ? field("Свой вариант критериев", `<textarea id="fManual" rows="12" class="mono">${esc(F.manual)}</textarea>`,
        "Поправьте текст и нажмите «Проверить мой вариант» — модель разберёт эту вакансию по нему.") : "";
    }
    if (!t && st) {
      foot += F.manual !== null ? `<button id="fManualRun">Проверить мой вариант</button>` : `<button id="fManualOpen">Поправить вручную</button>`;
      foot += `<button id="fAgain">ИИ предложит другой вариант</button>`;
      if (!st.problem) foot += `<button class="primary" id="fNext">Дальше</button>`;
    }
  }

  if (F.mode === "model" && F.step === 3) {
    const t = fixTask("fix_check"), r = st && st.reference, nref = v.reference;
    body += `<h3>Не сломали ли остальное</h3>`;
    if (!nref) body += `<p class="cwarn">Оценённых вакансий пока нет — проверить правку не на чем. Одна вакансия — слабый сигнал: правка может задеть другие. Лучше сначала оценить ещё несколько вакансий — в их карточках или в «Калибровке» на шаге «Оценить ещё», — но применить можно и так.</p>`;
    else if (t) body += `<p class="cwarn">Идёт проверка: прежние и новые критерии на ${nref} оценённых вакансиях. ${fixTime(nref * 2)} Ход — на песочных часах в шапке; окно можно закрыть — итог откроется сам.</p>`;
    else if (!r) body += `<p>Кнопка <b>«Проверить на ${nref} оценённых»</b> прогонит прежние и новые критерии на вакансиях, которые вы уже оценили, и сравнит решения модели с вашими. ${fixTime(nref * 2)}</p>
      <p class="hint">«Дальше без проверки» — сразу к применению правки, ничего не прогоняя. Одна вакансия — слабый сигнал, поэтому лучше проверить.</p>`;
    if (r) {
      const row = (label, k, good) => { const b = r.before[k], a = r.after[k], cls = a === b ? "" : (a > b) === good ? "s-good" : "s-bad";
        return `<tr><td>${label}</td><td class="num">${b}</td><td class="num"><b class="${cls}">${a}</b></td></tr>`; };
      const worse = r.after["пропущено подходящих"] > r.before["пропущено подходящих"] || r.after["решение совпало"] < r.before["решение совпало"];
      body += `<table class="vac caltable"><thead><tr><th>На ${r.before["всего"]} оценённых</th><th class="num">Было</th><th class="num">Стало</th></tr></thead><tbody>
          ${row("Решения совпали с вашими", "решение совпало", true)}${row("Пропущено подходящих", "пропущено подходящих", false)}${row("Лишних «да»", "лишних да", false)}</tbody></table>
        ${r.changed.length ? `<p><b>Где решение модели поменялось:</b></p><ul class="fixchanged">${r.changed.map(c =>
          `<li>${esc(c.title)}: ${c.before ? "да" : "нет"} → <b>${c.after ? "да" : "нет"}</b> <span class="${c.after === c.yes ? "s-good" : "s-bad"}">(вы — ${c.yes ? "да" : "нет"})</span></li>`).join("")}</ul>` : "<p class=\"hint\">Решения по остальным вакансиям не поменялись.</p>"}
        <p class="${worse ? "cwarn" : "hint"}">${worse ? "Новая версия хуже на ваших оценках — лучше попробовать другой вариант правки." : "Новая версия не хуже прежней на ваших оценках."}</p>`;
    }
    // Главная кнопка — справа: до проверки это «Проверить», после — «Дальше»
    const check = `<button ${r ? "" : 'class="primary"'} id="fCheck">${r ? "Проверить ещё раз" : `Проверить на ${nref} оценённых`}</button>`;
    const next = `<button ${r ? 'class="primary"' : ""} id="fNext">${r ? "Дальше" : "Дальше без проверки"}</button>`;
    foot += `<button id="fBack">Назад</button>`;
    if (!nref) foot += `<button id="fCalib">Открыть калибровку</button>${next}`;
    else if (!t) foot += r ? check + next : next + check;
  }

  if (F.mode === "model" && F.step === 4) {
    body += `<h3>Сделать новые критерии общими?</h3>
      <p>«Да» — критерии профиля заменятся новой версией; прежняя останется в истории версий («Критерии модели → Выбрать из прежних версий»). Потом программа предложит переоценить вакансии по новым критериям.</p>
      <p>«Нет» — критерии не меняются. Ваша оценка этой вакансии уже сохранена в «Калибровке» и пригодится следующей автонастройке.</p>
      <div class="diff">${st.diff.filter(l => !l.startsWith("@@")).map(l => `<div class="${l[0] === "+" ? "add" : l[0] === "-" ? "del" : ""}">${esc(l)}</div>`).join("")}</div>`;
    foot += `<button id="fBack">Назад</button><button id="fNo">Нет, оставить как есть</button><button class="primary" id="fApply">Да, применить</button>`;
  }
  $("wbody").innerHTML = body;
  $("wfoot").innerHTML = foot;
  fixBind();
}

function fixDirText(d) {
  return d === "up" ? "Модель недооценила вакансию — правка критериев может сделать так, чтобы такие вакансии оценивались <b>выше</b>."
    : d === "down" ? "Модель переоценила вакансию — правка критериев может сделать так, чтобы такие вакансии оценивались <b>ниже</b>."
    : fixRated() ? "Ваша оценка близка к оценке модели и решение то же — править критерии незачем, достаточно сохранить оценку."
    : "Поставьте «Могу», «Хочу» и решение.";
}

// Правка своими руками: критерии (с отметками модели по этой вакансии), резюме, «Дополнительно о себе»
function fixHandHtml() {
  const v = F.v, marks = v.factors.criteria.filter(c => c.mark !== "✅");
  const box = (id, title, sub, inner, open) => `<details class="fixedit" ${open ? "open" : ""}><summary><b>${title}</b> <span class="t-meta">${sub}</span></summary>${inner}</details>`;
  return `<h3>Поправить и пересчитать</h3>
    <p class="hint">Поправьте, что нужно, и нажмите «Сохранить и пересчитать вакансию»: правки сохранятся в профиль, модель заново разберёт эту вакансию.
      Не понравится итог — «Вернуть как было».</p>
    ${box("c", "Критерии", "что важно вам: город, деньги, роль, отрасль",
      `${marks.length ? `<p class="hint">По этой вакансии модель отметила: ${marks.map(c => `<b>К${c.k}</b> ${c.mark} ${esc(c.text)}`).join("; ")}</p>` : ""}
       <textarea id="fCrit" rows="12" class="mono">${esc(v.criteria)}</textarea>`, true)}
    ${box("r", "Резюме", "опыт, который видит модель", v.resume_editable
      ? `<textarea id="fResume" rows="12" class="mono">${esc(v.resume)}</textarea>`
      : `<p class="hint">Резюме лежит во внешнем файле — здесь его не поправить. Поправьте файл или перенесите резюме в папку профиля в «Параметры → Резюме».</p>`)}
    ${box("f", "Дополнительно о себе", "факты, которых нет в резюме; каждый — с «- », Enter начнёт следующий",
      `<textarea id="fFacts" rows="5" class="facts" placeholder="- Руководил внедрением 1С:ERP на 3 тыс. пользователей">${esc(v.facts)}</textarea>`)}`;
}

// Итог пересчёта: было → стало, и какие отметки критериев поменялись
function fixRecheckHtml(rc) {
  const b = rc.before, a = rc.after, names = {criteria: "критерии", resume: "резюме", facts: "«Дополнительно о себе»"};
  const box = (label, r, cls) => `<div class="scorebox ${cls}"><div class="lbl">${label}</div><div class="val ${scoreClass(r.score)}">${r.score ?? "?"}<small>/10</small></div>
    <div class="lbl">${decisionHtml(r.decision || "")}</div>${r.want != null ? `<div class="lbl">могу ${r.can ?? "?"} · хочу ${r.want}</div>` : ""}</div>`;
  const was = Object.fromEntries((b.criteria || []).map(c => [c.k, c.mark]));
  const moved = (a.criteria || []).filter(c => was[c.k] && was[c.k] !== c.mark).map(c => `<b>К${c.k}</b> ${was[c.k]} → ${c.mark}`);
  return `<h3>Пересчёт вакансии</h3>
    <p class="hint">${rc.changed.length ? `Сохранено: ${rc.changed.map(k => names[k]).join(", ")}.` : "Тексты не менялись — вакансия просто разобрана заново."}</p>
    <div class="scores">${box("Было", b, "")}${box("Стало", a, "total")}</div>
    ${moved.length ? `<p>Поменялись отметки критериев: ${moved.join("; ")}.</p>` : ""}
    ${rc.changed.length ? `<p class="hint">Оценки остальных вакансий посчитаны по прежним текстам — в таблице они помечены ↻. Пересчитать их можно кнопкой «Пересчитать» в шапке.</p>` : ""}`;
}

// Сколько ждать: число разборов модели — облако секунды, локальная — 15 секунд на оценку или минута на разбор
function fixTime(runs) {
  const min = state.cloud ? Math.ceil(runs / 6) : state.two_stage ? Math.ceil(runs / 4) : runs;
  return `Примерно ${min <= 1 ? "минута" : `${min} мин`} работы модели.`;
}

function fixBind() {
  const go = step => { F.step = step; fixRender(); };
  $("fClose").onclick = closeWizard;
  if ($("fBack")) $("fBack").onclick = () => go(F.step - 1);
  if (F.step === 0) myScoreBind(F, "f", () => {
    const d = fixDirection();
    $("fDir").innerHTML = fixDirText(d);
    $("fDir").className = d ? "hint" : "cwarn";
    $("fNext").disabled = !d;
    $("fNext").title = d ? "" : "Доступно, когда ваша оценка расходится с оценкой модели";
  });
  if ($("fReason")) $("fReason").oninput = e => { F.reason = e.target.value; };
  document.querySelectorAll("#wbody [data-mark]").forEach(c => c.onchange = () => {
    c.checked ? F.marks.add(c.dataset.mark) : F.marks.delete(c.dataset.mark);
    $("fGap").hidden = !(fixDirection() === "up" && [...F.marks].some(k => /^(Требование|Пробел)/.test(k)));
  });
  const rate = async () => {
    try {
      await api("/api/calibration/rate", {profile: state.profile, n: F.n, can: F.can, want: F.want, decision: F.decision, reason: F.reason});
      return true;
    } catch (e) { fail(e); return false; }
  };
  const need = () => {                                 // все три — обязательные
    let bad = false;
    for (const [key, label] of MY_AXES) if (!F[key]) { bad = true; calInvalid(`.scorepick[data-axis="${key}"]`, `Выберите «${label}» от 1 до 10.`); }
    if (!F.decision) { bad = true; calInvalid('input[name="fdec"]', "Выберите решение."); }
    if (bad) toast("Заполните обязательные поля — они отмечены красным");
    return !bad;
  };
  if ($("fSave")) $("fSave").onclick = async () => {
    if (!need() || !await rate()) return;
    toast(`Сохранено: ${fixScore()} (могу ${F.can}, хочу ${F.want}), ${F.decision}`);
    F.n = null;
    closeWizard();
    load(state.profile);
  };
  if ($("fHand")) $("fHand").onclick = async () => {    // оценка не обязательна: можно просто поправить тексты
    if (fixRated() && !await rate()) return;
    Object.assign(F, {mode: "hand", editing: true});
    go(1);
  };
  if ($("fNext")) $("fNext").onclick = async () => {
    if (F.step === 0) {
      if (!need() || !await rate()) return;
      F.mode = "model";
    }
    go(F.step + 1);
  };
  if ($("fBack") && F.mode === "hand") $("fBack").onclick = () => { F.mode = "model"; go(0); };
  if ($("fRecheck")) $("fRecheck").onclick = async () => {
    const v = F.v, edits = {};
    const take = (id, key) => { if ($(id) && $(id).value.trim() !== (v[key] || "").trim()) edits[key] = $(id).value; };
    take("fCrit", "criteria"); take("fResume", "resume"); take("fFacts", "facts");
    if (edits.criteria !== undefined && !edits.criteria.trim()) return toast("Критерии не могут быть пустыми");
    Object.assign(v, edits);                          // пока идёт задача — тексты в окне те, что сохраняем
    F.editing = false;
    await run("fix_recheck", {n: F.n, ...edits});
    fixRender();
  };
  bulletArea($("fFacts"));
  if ($("fMore")) $("fMore").onclick = () => { F.editing = true; fixRender(); };
  if ($("fUndo")) $("fUndo").onclick = async () => {
    if (!confirm("Вернуть прежние тексты и прежний разбор этой вакансии?")) return;
    try { await api("/api/fix/undo", {profile: state.profile, n: F.n}); }
    catch (e) { return fail(e); }
    toast("Вернул как было");
    await load(state.profile);
    F.editing = true;
    openFix(F.n);
  };
  if ($("fDone")) $("fDone").onclick = () => { F.n = null; closeWizard(); load(state.profile); };
  const suggest = async extra => {
    await run("fix_suggest", {n: F.n, direction: fixDirection() || F.v.state?.direction, reason: F.reason, marks: [...F.marks],
                        score: fixScore(), can: F.can, want: F.want, decision: F.decision, ...extra});
    F.v.state = null;
    go(2);
  };
  if ($("fPropose")) $("fPropose").onclick = () => suggest({});
  if ($("fAgain")) $("fAgain").onclick = () => suggest({history: F.v.state.history});
  if ($("fManualOpen")) $("fManualOpen").onclick = () => { F.manual = F.v.state.problem ? F.v.criteria : F.v.state.criteria; fixRender(); };
  if ($("fManualRun")) $("fManualRun").onclick = () => { const text = $("fManual").value; F.manual = null; suggest({manual: text, history: F.v.state.history}); };
  if ($("fCheck")) $("fCheck").onclick = async () => { await run("fix_check", {n: F.n}); fixRender(); };
  if ($("fCalib")) $("fCalib").onclick = () => openCalibration(1);
  if ($("fNo")) $("fNo").onclick = () => { closeWizard(); toast("Критерии не изменились, ваша оценка сохранена в «Калибровке»"); };
  if ($("fApply")) $("fApply").onclick = async () => {
    try {
      await api("/api/fix/apply", {profile: state.profile, n: F.n});
      toast("Критерии обновлены");
      F.n = null;
      await load(state.profile);
      openAfterEdit(true, false);                       // предложить переоценить вакансии
    } catch (e) { fail(e); }
  };
}
