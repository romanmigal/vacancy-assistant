// Калибровка критериев: набор из своих недавних оценок → оценить ещё (необязательно) → автонастройка.
// Обычные скрипты (не модули): подключаются по порядку в index.html и видят функции друг друга.

// Набор вакансий программа подбирает сама (calibration.py): расхождения с моделью — первыми, разные решения.
// Флажок убирает вакансию из набора или добавляет другую из оценённых. «Оценить ещё» — прежний ввод оценки
// по разобранным, но ещё не оценённым вакансиям: набрать свои оценки, если их мало.
const C = {tab: 0, st: null, more: false, q: "", queue: [], idx: 0, d: null, my: {}};
const CTABS = ["Набор вакансий", "Оценить ещё", "Автонастройка"];
const cRated = n => C.st.rated.find(v => v.n === n);
const cPicked = () => C.st.picked.map(cRated).filter(Boolean);

async function openCalibration(tab = 0) {
  C.tab = tab === 1 ? 0 : tab; C.more = false; C.q = "";      // «Оценить ещё» открывается после загрузки
  await calLoad();
  $("wiz").classList.add("open");
  if (tab === 1) calStartRating();
}
async function calLoad() {
  try { C.st = await api(`/api/calibration?profile=${encodeURIComponent(state.profile)}`); }
  catch (e) { return fail(e); }
  calRender();
}
// Примерное время автонастройки: до 4 прогонов набора (3 правки) и 3 правки критериев по 1–2 минуты
function calMinutes(n) {
  return state.cloud ? Math.ceil(n * 4 / 6) + 6 : state.two_stage ? n + 6 : n * 4 + 6;
}
function calStartRating(idx = 0) {
  C.queue = C.st.unrated.map(v => ({...v}));     // очередь не меняется, пока окно открыто: оценённые остаются в списке с ✓
  C.tab = 1;
  calOpenRating(idx);
}
async function calOpenRating(idx) {
  const list = C.queue;
  C.idx = Math.max(0, Math.min(idx, list.length - 1));
  C.d = list.length ? await api(`/api/vacancy?profile=${encodeURIComponent(state.profile)}&n=${list[C.idx].n}`).catch(() => null) : null;
  const v = list[C.idx] || {};
  C.my = {can: v.can || null, want: v.want || null, decision: v.decision || null};
  calRender();
}
const yn = v => v === true ? "да" : v === false ? "нет" : "—";

function calCard(v, on) {
  return `<div class="gpcard ${v.diverge ? "diverge" : ""}" data-peek="${v.n}">
    <label class="gphead"><input type="checkbox" data-cpick="${v.n}" ${on ? "checked" : ""} title="${on ? "Убрать из калибровки" : "Добавить в калибровку"}">
      <span><button type="button" class="linkbtn" data-cvac="${v.n}">${esc(v.title)}</button> <span class="t-meta">· ${esc(v.company)}</span>
      ${v.diverge ? '<span class="chip calgap" title="Ваше решение не совпало с решением модели или оценки различаются на 2 и больше">расходится</span>' : ""}</span></label>
    <div class="gpscores"><span class="gpme">Вы: ${mkScore(v)} <span class="${MY_TONE[v.decision] || ""}">${esc(v.decision)}</span>${v.date ? ` <span class="muted">${ddmm(v.date)}</span>` : ' <span class="muted">без даты</span>'}</span>
      <span>ИИ: <b class="${scoreClass(v.model_score)}">${v.model_score ?? "?"}</b> ${decisionHtml(v.model_decision)}</span></div>
    ${v.reason ? `<div class="gpwhy">«${esc(v.reason)}»</div>` : ""}</div>`;
}
function calRestHtml() {
  const picked = new Set(C.st.picked), q = C.q.trim().toLowerCase();
  const rest = C.st.rated.filter(v => !picked.has(v.n) && (!q || `${v.title} ${v.company}`.toLowerCase().includes(q)));
  return rest.length ? rest.map(v => calCard(v, false)).join("") : `<p class="hint">${q ? "Ничего не нашлось." : "Других оценённых вакансий нет."}</p>`;
}

function calRender() {
  calPeekHide();
  const st = C.st, chosen = cPicked();
  $("wtitle").textContent = "Калибровка критериев";
  $("wiz").classList.toggle("wide", C.tab === 1);           // список вакансий слева от текста — нужно широкое окно
  $("wsteps").innerHTML = CTABS.map((t, i) => `<span class="${i === C.tab ? "on" : ""}" data-ctab="${i}" style="cursor:pointer">${t}</span>`).join("");
  let body = "", foot = `<button class="left" id="cClose">Закрыть</button>`;
  const enough = chosen.length >= st.minimum, gaps = chosen.filter(v => v.diverge).length;
  const runBtn = label => `<button class="primary" id="cRun" ${enough && !busyMine() && !state.no_model ? "" : "disabled"}
    title="${state.no_model ? NO_MODEL_HINT : enough ? "" : `Нужно хотя бы ${st.minimum} вакансий в наборе`}">${label}</button>`;
  if (C.tab === 0) {
    const rest = st.rated.length - chosen.length;
    const rateMore = `<button type="button" class="linkbtn" id="cRateMore">оценить ещё</button>`;
    let warn = "";
    if (st.rated.length < st.minimum)
      warn = `Своих оценок у разобранных вакансий пока ${st.rated.length}, а нужно хотя бы ${st.minimum}. Оцените ещё несколько — прямо здесь (${rateMore}) или в карточке вакансии кнопкой «✎ Поставить свои оценки» — и возвращайтесь.`;
    else if (!st.rated.some(v => v.diverge))
      warn = `Модель везде согласна с вами — настраивать пока нечего. Если видите вакансии, где она ошибается, оцените их (${rateMore} или в карточке) — они попадут в набор первыми.`;
    else if (!enough)
      warn = `В наборе ${chosen.length} — нужно хотя бы ${st.minimum}. Добавьте вакансии из оценённых ниже или ${rateMore}.`;
    body = `<h3>Набор вакансий для калибровки</h3>
      <p class="hint">Программа взяла ваши недавние оценки: сначала те, где модель с вами не согласна, и хотя бы по две на каждое ваше решение — «да», «возможно» и «нет»; затем совпадающие, чтобы правка не сломала то, что уже работает. Автонастройка проверит правку критериев на этих вакансиях. Снимите флажок, чтобы убрать вакансию из набора, или добавьте другую из оценённых.</p>
      ${warn ? `<p class="cwarn">${warn}</p>` : ""}
      ${chosen.length ? `<p class="calcount">Расходятся с моделью: <b>${gaps}</b> из ${chosen.length}</p>
        <div class="gplist" id="cSet">${chosen.map(v => calCard(v, true)).join("")}</div>` : ""}
      ${rest > 0 ? `<button type="button" id="cMore" aria-expanded="${C.more}">${C.more ? "Скрыть остальные оценённые" : `Показать ещё оценённые (${rest})`}</button>
        ${C.more ? `<div class="calsearch"><input type="search" id="cQ" placeholder="Поиск по названию или компании" value="${esc(C.q)}" aria-label="Поиск по оценённым вакансиям"></div>
          <div class="gplist" id="cRest">${calRestHtml()}</div>` : ""}` : ""}
      <p class="calcount calsum">В наборе: <b>${chosen.length}</b> ${plural(chosen.length, "вакансия", "вакансии", "вакансий")}${chosen.length ? ` · автонастройка — около ${calMinutes(chosen.length)} мин работы модели` : ""}. Программа подбирает до ${st.limit} — с этой моделью один круг правки займёт не больше 5 минут.</p>`;
    foot += `${st.edited ? '<button id="cReset" title="Забыть, какие вакансии вы убрали и добавили">Подобрать заново</button>' : ""}
      <button id="cRateBtn" ${st.unrated.length ? "" : 'disabled title="Все разобранные вакансии уже оценены"'}>Оценить ещё</button>${runBtn("Запустить автонастройку")}`;
  }
  if (C.tab === 1) {
    const list = C.queue, v = list[C.idx], done = list.filter(x => x.decision).length;
    if (!list.length) body = `<h3>Оценить ещё</h3><p>Все разобранные вакансии уже оценены вами. Новые появятся после поиска и разбора.</p>`;
    else if (!C.d) body = `<h3>Оценить ещё</h3><p class="hint">Загружаю вакансию…</p>`;
    else {
      // Слева — список с названиями (на узком экране — выпадающий список): «✓ 7 · да» — оценили, «•» — ещё нет
      const mark = x => x.decision ? `✓ ${x.score ?? "?"} · ${x.decision}` : x.flag ? "⚑" : "•";
      const nav = `<nav class="callist" aria-label="Вакансии без вашей оценки">${list.map((x, i) => `
          <button type="button" data-goto="${i}" class="${i === C.idx ? "cur" : ""} ${x.decision ? "done" : ""}" ${i === C.idx ? 'aria-current="true"' : ""}>
            <span class="cname">${esc(x.title)}</span><span class="t-meta">${esc(x.company || "")}</span>
            <span class="cmark">${esc(mark(x))}</span></button>`).join("")}</nav>
        <select class="calpick" id="cPick" aria-label="Вакансия">${list.map((x, i) =>
          `<option value="${i}" ${i === C.idx ? "selected" : ""}>${i + 1}. ${esc(x.title)}${x.company ? " — " + esc(x.company) : ""} · ${esc(mark(x))}</option>`).join("")}</select>`;
      body = `<div class="calrate">${nav}<div class="calmain">
        <div class="calprog">
          <button type="button" id="cPrev" ${C.idx > 0 ? "" : "disabled"} aria-label="Предыдущая">←<span class="wide-only"> Предыдущая</span></button>
          <div class="calprogtext">Вакансия ${C.idx + 1} из ${list.length} · оценено ${done}
            <div class="progbar" role="progressbar" aria-valuemin="0" aria-valuemax="${list.length}" aria-valuenow="${done}"><span style="width:${done / list.length * 100}%"></span></div></div>
          <button type="button" id="cNextNo" ${C.idx < list.length - 1 ? "" : "disabled"} title="Перейти к следующей, ничего не меняя" aria-label="Следующая"><span class="wide-only">Следующая </span>→</button>
        </div>
        <h3>${esc(v.title)}${v.company ? ` <span class="t-meta">· ${esc(v.company)}</span>` : ""}</h3>
        <p class="hint">Разобранные вакансии, которые вы ещё не оценивали: с флагом ⚑ — первыми, дальше новые. Оцените, сколько успеете, — оценки сразу попадут в набор. Оценку модели здесь не показываем, чтобы она не подсказывала.</p>
        <div class="calvac"><div class="md">${md(C.d.vacancy)}</div></div>
        ${myScoreHtml(C.my, "c")}
        ${field(`Почему <button type="button" class="info" id="cWhyInfo" title="Что писать в «Почему»" aria-label="Что писать в «Почему»">i</button>`,
          `<div class="expop" id="ex-why"></div><textarea id="cReason" rows="2" class="reason" placeholder="1–2 фразы: например, «переезд в другой город» или «нет разработки, только инфраструктура»">${esc(v.reason || v.note || "")}</textarea>`,
          "Причина — главное для автонастройки: по ней модель поймёт, какое правило дописать в критерии.")}</div></div>`;
      foot += `<button id="cBack">К набору</button><button class="primary" id="cSave">${C.idx < list.length - 1 ? "Сохранить и дальше" : "Сохранить и к набору"}</button>`;
    }
  }
  if (C.tab === 2) {
    const t = st.tune;
    body = `<h3>Автонастройка критериев</h3>
      <p>Модель смотрит, где её решения разошлись с вашими, и предлагает правку критериев. Каждая версия проверяется на вакансиях из набора; остаётся только та, что лучше: меньше пропущенных подходящих, больше совпавших решений. Ваши критерии не меняются, пока вы не нажмёте «Применить», а прежние версии сохраняются в истории критериев.</p>
      ${enough ? `<p class="cwarn">В наборе ${chosen.length} ${plural(chosen.length, "вакансия", "вакансии", "вакансий")} — около ${calMinutes(chosen.length)} мин работы модели. Окно можно закрыть; остановить — «Остановить» в ходе задачи.</p>`
               : `<p class="cwarn">Нужно хотя бы ${st.minimum} вакансий в наборе (сейчас ${chosen.length}) — добавьте их на шаге «Набор вакансий».</p>`}
      ${t ? calTuneResult(t) : '<p class="hint">Автонастройку ещё не запускали.</p>'}`;
    foot += `${t && t.best ? '<button id="cApply">Применить лучшую версию</button>' : ""}${runBtn(t ? "Запустить ещё раз" : "Запустить автонастройку")}`;
  }
  $("wbody").innerHTML = body;
  $("wfoot").innerHTML = foot;
  calBind();
}

function calBindList() {
  document.querySelectorAll("#wbody [data-cpick]").forEach(c => c.onchange = async () => {
    try {
      const r = await api("/api/calibration/select", {profile: state.profile, n: +c.dataset.cpick, on: c.checked});
      C.st.picked = r.picked; C.st.edited = true;
      calRender();
    } catch (e) { fail(e); }
  });
  document.querySelectorAll("#wbody [data-cvac]").forEach(b => b.onclick = e => {
    e.preventDefault();
    closeWizard();
    goToVacancy(+b.dataset.cvac);
  });
  document.querySelectorAll("#wbody [data-peek]").forEach(el => {
    el.onmouseenter = () => calPeek(el, +el.dataset.peek);
    el.onmouseleave = calPeekHide;
  });
}
function calBind() {
  document.querySelectorAll("[data-ctab]").forEach(s => s.onclick = async () => {
    const to = +s.dataset.ctab;
    if (to === 1) return calStartRating();
    C.tab = to;
    await calLoad();
  });
  $("cClose").onclick = closeWizard;
  calBindList();
  if ($("cMore")) $("cMore").onclick = () => { C.more = !C.more; calRender(); if (C.more) $("cQ").focus(); };
  if ($("cQ")) $("cQ").oninput = e => { C.q = e.target.value; $("cRest").innerHTML = calRestHtml(); calBindList(); };
  if ($("cReset")) $("cReset").onclick = async () => {
    try { await api("/api/calibration/select", {profile: state.profile, reset: true}); await calLoad(); } catch (e) { fail(e); }
  };
  ["cRateBtn", "cRateMore"].forEach(id => { if ($(id)) $(id).onclick = () => calStartRating(); });
  if ($("cBack")) $("cBack").onclick = () => { C.tab = 0; calLoad(); };
  if (C.tab === 1 && C.d) myScoreBind(C.my, "c");
  if ($("cReason")) {                     // две строки, длиннее — поле растёт по тексту
    const r = $("cReason"), grow = () => { r.style.height = "auto"; r.style.height = Math.max(r.scrollHeight + 2, 0) + "px"; };
    r.oninput = grow; grow();
  }
  if ($("cPrev")) $("cPrev").onclick = () => calOpenRating(C.idx - 1);
  if ($("cNextNo")) $("cNextNo").onclick = () => calOpenRating(C.idx + 1);
  document.querySelectorAll("[data-goto]").forEach(b => b.onclick = () => calOpenRating(+b.dataset.goto));
  if ($("cPick")) $("cPick").onchange = e => calOpenRating(+e.target.value);
  const cur = document.querySelector(".callist .cur");
  if (cur) cur.scrollIntoView({block: "nearest"});           // текущая вакансия видна в длинном списке
  if ($("cWhyInfo")) $("cWhyInfo").onclick = e => { e.stopPropagation(); toggleWhyHelp(); };
  if ($("cSave")) $("cSave").onclick = async () => {
    let bad = false;
    for (const [key, label] of MY_AXES) if (!C.my[key]) { bad = true; calInvalid(`.scorepick[data-axis="${key}"]`, `Выберите «${label}» от 1 до 10.`); }
    if (!C.my.decision) { bad = true; calInvalid('input[name="cdec"]', "Выберите решение."); }
    if (bad) return toast("Заполните обязательные поля — они отмечены красным");
    const v = C.queue[C.idx], last = C.idx >= C.queue.length - 1, reason = $("cReason").value;
    try {
      const r = await api("/api/calibration/rate", {profile: state.profile, n: v.n, can: C.my.can, want: C.my.want,
                                                  decision: C.my.decision, reason});
      toast(`Сохранено: ${r.score} (могу ${C.my.can}, хочу ${C.my.want}), ${C.my.decision}`);
      Object.assign(v, {score: r.score, can: C.my.can, want: C.my.want, decision: C.my.decision, reason});
      C.st = await api(`/api/calibration?profile=${encodeURIComponent(state.profile)}`);
      if (last) { C.tab = 0; calRender(); } else calOpenRating(C.idx + 1);
    } catch (e) { fail(e); }
  };
  if ($("cRun")) $("cRun").onclick = () => { closeWizard(); run("tune", {rounds: 3}); };
  if ($("cApply")) $("cApply").onclick = async () => {
    if (!confirm("Заменить критерии лучшей версией? Прежние сохранятся в истории критериев.")) return;
    try {
      await api("/api/calibration/apply", {profile: state.profile});
      toast("Критерии обновлены");
      await load(state.profile);
      openAfterEdit(true, false);                       // предложить переоценить вакансии
    } catch (e) { fail(e); }
  };
}

// Подсказка к полю «Почему»: какие причины помогают автонастройке
function toggleWhyHelp() {
  const pop = $("ex-why");
  if (pop.classList.contains("open")) { pop.classList.remove("open"); pop.innerHTML = ""; return; }
  pop.innerHTML = `<div class="cpop">
    <div class="cpop-head"><b>Что писать в «Почему»</b><button type="button" class="x" aria-label="Закрыть">×</button></div>
    <div class="cbody">
      <p>Главную причину вашего решения — одной-двумя фразами. По ней автонастройка поймёт, какое правило дописать в критерии, поэтому причина должна быть такой, чтобы её можно было проверить по тексту любой вакансии.</p>
      <div class="chead">Хорошо — конкретно и проверяемо</div>
      <ul class="exnotes">
        <li>«Переезд в другой город» · «Только офис, без удалёнки»</li>
        <li>«Зарплата до 300 тыс., мне нужно от 400»</li>
        <li>«Роль про эксплуатацию инфраструктуры, нет разработки»</li>
        <li>«Уровень руководителя отдела, а я ищу руководителя всего направления»</li>
        <li>«Главное в роли — 1С, это не мой профиль»</li>
        <li>Для «да» тоже: «Банк, строить ИТ с нуля — то, что ищу»</li>
      </ul>
      <div class="chead">Хуже — модели не на что опереться</div>
      <ul class="exnotes">
        <li>«Не нравится» · «Интересно» · «Так себе»</li>
        <li>Название компании: «это Сбер» — критерии не должны зависеть от конкретных компаний</li>
      </ul>
      <p class="hint">Если причин несколько — напишите главную первой. Поле необязательное, но без причин автонастройке сложнее понять, что исправлять.</p>
    </div></div>`;
  pop.classList.add("open");
  pop.onclick = e => e.stopPropagation();
  pop.querySelector(".x").onclick = () => { pop.classList.remove("open"); pop.innerHTML = ""; };
}

// Текст вакансии рядом со строкой списка — при наведении (без оценки модели)
const peekCache = {};
let peekTimer = null;
function calPeek(el, n) {
  clearTimeout(peekTimer);
  peekTimer = setTimeout(async () => {
    const d = peekCache[n] || (peekCache[n] = await api(`/api/vacancy?profile=${encodeURIComponent(state.profile)}&n=${n}`).catch(() => null));
    if (!d || !el.matches(":hover")) return;
    const box = $("calPeek"), r = el.getBoundingClientRect(), modal = document.querySelector(".wbox").getBoundingClientRect();
    box.innerHTML = `<div class="md">${md(d.vacancy)}</div>`;
    box.hidden = false;
    const w = Math.min(440, innerWidth - 32);
    const right = modal.right + 12;                       // справа от окна калибровки, если есть место
    box.style.width = w + "px";
    box.style.left = (right + w <= innerWidth - 8 ? right : Math.max(16, innerWidth - w - 16)) + "px";
    const h = box.offsetHeight;
    box.style.top = Math.max(16, Math.min(r.top, innerHeight - h - 16)) + "px";
  }, 250);
}
function calPeekHide() { clearTimeout(peekTimer); $("calPeek").hidden = true; }

function calInvalid(selector, msg) {
  const el = document.querySelector("#wbody " + selector);
  const box = el && el.closest(".field");
  if (box) { box.classList.add("invalid"); if (!box.querySelector(".ferr")) box.insertAdjacentHTML("beforeend", `<div class="ferr">${esc(msg)}</div>`); }
}
function calTuneResult(t) {
  const ver = t.versions.map(v => `<tr class="${v.verdict === "принята" ? "best" : ""}"><td>${esc(v.version)}</td><td>${esc(v.what)}</td>
    <td class="num">${v.metrics ? `${v.metrics["решение совпало"]} из ${v.metrics["всего"]}` : "—"}</td>
    <td class="num">${v.metrics ? v.metrics["пропущено подходящих"] : "—"}</td><td>${esc(v.verdict)}</td></tr>`).join("");
  const diff = (t.diff || []).filter(l => !l.startsWith("@@")).map(l =>
    `<div class="${l[0] === "+" ? "add" : l[0] === "-" ? "del" : ""}">${esc(l)}</div>`).join("");
  // По каждой вакансии: решение модели с текущими критериями и с лучшей версией — что исправилось, что сломалось
  const model = o => `<b class="${scoreClass(o.score)}">${o.score ?? "?"}</b> · ${esc(yn(o.yes))}`;
  const per = (t.rows || []).map(r => {
    const was = r.before.yes === r.yes, now = r.after.yes === r.yes;
    const verdict = !was && now ? '<span class="s-good">исправилось</span>' : was && !now ? '<span class="s-bad">сломалось</span>'
      : now ? '<span class="muted">совпадает</span>' : '<span class="s-mid">расходится</span>';
    return `<tr class="${was && !now ? "miss" : ""}"><td>${esc(r.title)}<div class="t-meta">${esc(r.company || "")}</div></td>
      <td class="num">${r.score ?? "?"} · ${esc(yn(r.yes))}</td><td class="num">${model(r.before)}</td><td class="num">${model(r.after)}</td><td>${verdict}</td></tr>`;
  }).join("");
  return `<h3 class="sec" style="font-size:15px">Последняя автонастройка — ${esc(new Date(t.date).toLocaleDateString("ru"))}, вакансий: ${t.reference}</h3>
    <table class="vac caltable"><thead><tr><th>Версия</th><th>Что изменено</th><th class="num">Совпало</th><th class="num">Пропущено</th><th>Итог</th></tr></thead><tbody>${ver}</tbody></table>
    ${per ? `<h3 class="sec" style="font-size:15px">Было → стало по каждой вакансии</h3>
      <div class="tablewrap"><table class="vac caltable"><thead><tr><th>Вакансия</th><th class="num">Вы</th><th class="num">ИИ было</th><th class="num">ИИ ${t.best ? `стало (v${t.best})` : "стало"}</th><th></th></tr></thead><tbody>${per}</tbody></table></div>` : ""}
    ${t.best ? `<p><b>Лучшая — v${t.best}.</b> Что изменится в критериях:</p><div class="diff">${diff}</div>
      <p class="hint">Прочитайте изменения: формулировки должны быть вашими. Вакансий в наборе немного — модель могла подогнать критерии под них. Прежние критерии останутся в истории, к ним можно вернуться.</p>`
      : `<p><b>Улучшить не удалось</b> — текущие критерии остаются. Если ошибки остались, допишите причины в своих оценках («Почему») и запустите снова.</p>`}`;
}
