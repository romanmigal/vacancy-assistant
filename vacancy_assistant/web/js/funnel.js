// Воронка отклика: этап вакансии с датой (в панели полей карточки) и вкладка «История»:
// когда добавлена, как менялись статусы и этапы.
// Обычные скрипты (не модули): подключаются по порядку в index.html и видят функции друг друга.

const STAGE_TONE = {offer: "good", rejected: "bad", silent: "muted"};

// Поле «Этап» в панели карточки; дата ставится сегодняшняя
function stageSection(r) {
  if (!r.analyzed)
    return `<div class="cfield inl off" title="Этап можно отметить после разбора вакансии"><span class="tlab">Этап</span><span class="muted tnone">после разбора</span></div>`;
  const f = r.funnel || {};
  return `<div class="cfield inl"><label class="tlab" for="fStage">Этап</label>
      <select id="fStage" class="${STAGE_TONE[f.stage] || ""}" title="Где вы с этой вакансией: отклик, ответ, интервью, итог. Дата — сегодняшняя, история — во вкладке «История»">
          <option value="">— не отмечен —</option>
          ${state.stages.map(([k, name]) => `<option value="${k}" ${k === f.stage ? "selected" : ""}>${esc(name)}</option>`).join("")}</select></div>`;
}

// Строка дат в панели карточки: когда вакансию сохранили, когда последний раз меняли этап или комментарий
// и открыта ли вакансия на сайте (проверяет «Разобрать заново»; в таблице закрытая — зачёркнута)
function datesLine(r) {
  return `<div class="crow cdates">
      <div class="cfield inl" title="Когда вакансия попала в программу"><span class="tlab">Сохранено</span><span>${esc(r.added || "—")}</span></div>
      <div class="cfield inl" title="Последняя смена этапа или правка комментария — в окне программы; правку в Obsidian программа не видит"><span class="tlab">Обновлено</span><span id="cUpdated">${r.updated ? ddmmyyyy(r.updated) : "—"}</span></div>
      ${actualField(r)}</div>`;
}
function actualField(r) {
  const a = r.actual || {}, again = "Чтобы проверить снова, нажмите «Разобрать заново»";
  if (a.checked) return `<div class="cfield actualbox"><span class="${a.closed ? "closedtag" : "opentag"}" title="${a.closed
      ? "Вакансию сняли с сайта. " + again : "Вакансия открыта на сайте. " + again}">${a.closed ? "Вакансия закрыта" : "Вакансия актуальна"}</span><span class="checkdate muted">проверено ${ddmm(a.checked)}</span></div>`;
  // Не проверяли — значит, вакансия была открыта, когда её загрузили
  const why = !/^https?:\/\//.test(r.link || "") ? "Вакансия добавлена текстом — проверять на сайте нечего"
    : /hh\.ru\//.test(r.link) && !hhOn() ? "Проверка открывает hh.ru, а поиск на hh выключен в настройках"
    : again;
  return `<div class="cfield actualbox"><span class="opentag" title="Вакансия была открыта, когда её загрузили. ${why}">Вакансия актуальна</span>${r.added
    ? `<span class="checkdate muted">загружена ${esc(r.added.slice(0, 5))}</span>` : ""}</div>`;
}

// Вкладка «История»: добавление, смены статуса и этапа, правки комментария и референсера — в том порядке,
// в каком были: по дате и времени (у старых записей времени нет — они идут первыми в своём дне).
// d — данные карточки (/api/vacancy), в них правки и время добавления
const EDIT_KIND = {comment: "Комментарий", referrer: "Референсер"};
// Правки писем и резюме под вакансию, свои тексты
const TEXT_KIND = {cover: "Письмо", referrer: "Референсеру", resume: "Резюме"};
const TEXT_EDITED = {cover: "Письмо отредактировано", referrer: "Сообщение отредактировано", resume: "Резюме под вакансию отредактировано"};
const TEXT_OWN = {cover: "Своё письмо сохранено", referrer: "Своё сообщение сохранено", resume: "Свой текст резюме сохранён"};
const TEXT_SENT = {cover: "Сопроводительное письмо отправлено", referrer: "Сообщение референсеру отправлено",
                   resume: "Резюме под вакансию отправлено"};
const ARTIFACT_ADDED = {file: "Приложен файл", note: "Заметка о переписке"};
const KIND_RANK = {added: 0, analysis: 1, rating: 2, stage: 3, status: 4, edit: 5, text: 6};   // одна секунда: этап сам меняет статус — этап первым
function historyTab(r, d) {
  return `<div id="histBody">${historyHtml(r, d)}</div>`;
}
// Свои действия — метка синим (style.css, li.me): этап, статус, правки, своя оценка, свои тексты и артефакты;
// серые — что сделала программа (оценка ИИ) или неизвестно кто (вакансия добавлена: поиском или вами)
const MINE = new Set(["status", "stage", "edit", "rating", "text"]);
// Без времени — в начало дня; только «Отправлено» с прошлой датой — в конец: его отмечают уже после письма
const sortTime = e => e.time || (e.type === "text" ? "~" : "");
function historyHtml(r, d) {
  const f = r.funnel || {};
  const iso = x => /^\d{2}\.\d{2}\.\d{4}$/.test(x) ? `${x.slice(6)}-${x.slice(3, 5)}-${x.slice(0, 2)}` : x;
  const events = [
    ...(r.added ? [{date: iso(r.added), time: d.added_time || "", type: "added", kind: "Вакансия", name: "Добавлена"}] : []),
    ...(f.statuses || []).map(x => ({...x, type: "status", kind: "Статус", name: (state.statuses.find(s => s[0] === x.status) || [, x.status])[1], tone: "status"})),
    ...(f.history || []).map(x => ({...x, type: "stage", kind: "Этап", name: stageName(x.stage), tone: STAGE_TONE[x.stage] || ""})),
    ...(d.edits || []).map(x => ({...x, type: "edit", kind: EDIT_KIND[x.field], name: x.text, tone: "edit", empty: !x.text})),
    ...(d.analyses || []).map((x, i, all) => ({...x, type: "analysis", kind: "Оценка ИИ", tone: "analysis", prev: all[i - 1]})),
    ...(d.ratings || []).map((x, i, all) => ({...x, type: "rating", kind: "Моя оценка", tone: "rating", prev: all[i - 1]})),
    ...(d.texts || []).map(x => ({...x, type: "text", kind: x.source === "artifact" ? "Артефакт" : TEXT_KIND[x.kind], tone: "edit",
                                  name: x.source === "artifact" ? `${ARTIFACT_ADDED[x.kind]}: ${x.title}`
                                    : (x.source === "edit" ? TEXT_EDITED : x.source === "sent" ? TEXT_SENT : TEXT_OWN)[x.kind]})),
  ].map((e, i) => ({...e, i}))
   .sort((a, b) => (a.date + sortTime(a)).localeCompare(b.date + sortTime(b)) || KIND_RANK[a.type] - KIND_RANK[b.type] || a.i - b.i);
  const list = `<ol class="stagehist">${events.map((e, i) => `<li class="${e.tone || ""} ${MINE.has(e.type) ? "me" : ""} ${i === events.length - 1 ? "now" : ""}">
      <span class="hdate">${ddmm(e.date)}.${e.date.slice(0, 4)}${e.time ? ` <span class="htime">${e.time.slice(0, 5)}</span>` : ""}</span><span class="hkind">${e.kind}</span>${e.type === "analysis" ? analysisEvent(e) : e.type === "rating" ? ratingEvent(e) : e.type === "edit" ? (e.empty ? '<span class="muted">очищен</span>' : `<span class="htext">${esc(e.name)}</span>`) : `<b>${esc(e.name)}</b>`}</li>`).join("")}</ol>`;
  return list + `<p class="hint">${events.length > 1 ? '<span class="hme">Синие метки</span> — что сделали вы, серые — программа. ' : ""}${events.length > 1 ? ""
      : "Изменений пока не было. Отметьте этап вверху карточки — «Откликнулся», «Ответили», «Интервью с HR»… "}Изменения записываются, когда их делают в окне программы: правку в Obsidian программа не видит. Правка комментария — одной записью, пока вы его дописываете.</p>`;
}

// Разбор в «Истории»: решение, оценка (Могу / Хочу), модель; стрелка — как изменилось с прошлого разбора
const decisionWord = d => ({3: "да", 2: "возможно", 1: "нет"})[DECISION_RANK(d)] || d || "?";
function scoreDelta(v, before) {
  if (v == null || before == null || v === before) return esc(v ?? "?");
  return `${esc(v)}<span class="hdelta ${v > before ? "up" : "down"}" title="было ${before}">${v > before ? "↑" : "↓"}${before}</span>`;
}
function changedText(e) {
  if (!e.prev) return "";
  if (e.changed == null) return "";                                   // у прошлого разбора отпечатков нет
  return e.changed.length ? `после правки: ${e.changed.join(", ")}` : "без изменений в критериях и резюме";
}
function analysisEvent(e) {
  const p = e.prev || {};
  const model = /^gigachat/i.test(e.model || "") ? "GigaChat" : (e.model || "").split(":")[0].replace(/^gemma\d*/i, "Gemma");
  return `<b class="d-${({3: "yes", 2: "maybe", 1: "no"})[DECISION_RANK(e.decision)] || ""}">${esc(decisionWord(e.decision))}</b>
    <span>${scoreDelta(e.score, p.score)} <span class="muted">(Могу ${scoreDelta(e.can, p.can)} / Хочу ${scoreDelta(e.want, p.want)})</span></span>
    <span class="muted">${[e.stage === "short" ? "короткая оценка" : "", model, changedText(e)].filter(Boolean).map(esc).join(" · ")}</span>`;
}

// Своя оценка в «Истории»: решение, общая (Могу / Хочу), причина; стрелка — как изменилось с прошлой своей оценки.
// Чтобы не спутать с «Оценкой ИИ», строка выделена ещё и маркером и подложкой (style.css, li.rating)
function ratingEvent(e) {
  const p = e.prev || {};
  return `<b class="${MY_TONE[e.decision] || ""}">${esc(e.decision)}</b>
    <span>${scoreDelta(e.score, p.score)} <span class="muted">(Могу ${scoreDelta(e.can, p.can)} / Хочу ${scoreDelta(e.want, p.want)})</span></span>
    ${e.reason ? `<span class="htext">${esc(e.reason)}</span>` : ""}`;
}

function bindFunnel(r, n) {
  if (!$("fStage")) return;
  const stage = async () => {
    const res = await api("/api/funnel/stage", {profile: state.profile, n, stage: $("fStage").value}).catch(fail);
    if (!res) return;
    const moved = res.status && res.status !== r.status;
    await refreshRows();
    if (moved) tab = res.status;
    if (selected === n) openVacancy(n);
    if (res.archive)                                    // отказ или тишина — предложить Архив, сами не переносим
      return toast("Этап сохранён. Перенести вакансию в Архив?", {label: "Перенести в Архив", onClick: async () => {
        await api("/api/status", {profile: state.profile, n, value: "no"}).catch(fail);
        await refreshRows(); tab = "no"; openVacancy(n); toast("Вакансия в Архиве");
      }});
    toast(moved ? `Этап сохранён — вакансия в разделе «${(state.statuses.find(s => s[0] === res.status) || [, ""])[1]}»` : "Этап сохранён");
  };
  $("fStage").onchange = stage;                        // дата этапа — сегодняшняя
}
