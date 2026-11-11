// Главное окно: таблица вакансий, карточка, первый поиск, тема, ширина панелей. Задачи — в tasks.js.
// Обычные скрипты (не модули): подключаются по порядку в index.html и видят функции друг друга.

async function load(profile) {
  state = await api("/api/state" + (profile ? "?profile=" + encodeURIComponent(profile) : ""));
  if (state.profile) { remember("profile", state.profile); try { sessionStorage.setItem("profile", state.profile); } catch (e) {} }
  const mdl = state.no_model ? "без модели" : `модель ${state.model}`;
  $("who").textContent = state.name ? `${state.name} · ` : "";
  if (state.no_model && !REMOTE) {                        // включить модель — в настройках; ссылка прямо из шапки
    const b = document.createElement("button");
    b.className = "linkbtn"; b.textContent = mdl; b.title = "Включить модель: «Параметры → Настройки → Модель профиля»";
    b.onclick = openSettings;
    $("who").append(b);
  } else $("who").append(mdl);
  $("mCrit").hidden = $("mCalib").hidden = $("mLetter").hidden = !!state.no_model;   // «Без модели»: критерии, калибровка и шаблоны писем не нужны
  $("profile").innerHTML = state.profiles.map(p => `<option ${p === state.profile ? "selected" : ""}>${esc(p)}</option>`).join("")
    + '<option value="__new">+ Новый профиль…</option>';
  render();
  showHh();
  if (state.profile) offerRecheck();
  seedTasks();
  showTasks();
  if (state.tasks.some(isActive)) poll();
  if (state.hh?.state === "ask" && !hhAsked[state.profile] && !$("wiz").classList.contains("open")) askHh();
}

// Поиск на hh.ru: кнопка «hh» — только если он включён; иначе вакансии добавляются вручную.
// Включены только ленты Хабр Карьеры и GeekJob — кнопка «RSS»
function showHh() {
  const on = hhOn(), feeds = rssOn() ? state.rss.map(f => ({habr: "Хабр Карьеры", geekjob: "GeekJob"})[f]).join(" и ") : "";
  $("btnUpdate").hidden = !!state.profile && !on && !feeds && state.hh?.state !== "ask";
  const mark = $("btnUpdate").querySelector(".hh");
  mark.textContent = on || !feeds ? "hh" : "RSS";
  mark.classList.toggle("rss", !on && !!feeds);
  const what = on ? `на hh.ru${feeds ? ` и в лентах ${feeds}` : ""}` : feeds ? `в лентах ${feeds}` : "на hh.ru";
  // Подсказку без задач ставит showTasks (tasks.js): пока идут задачи, на кнопке — другая
  $("btnUpdate").dataset.idle = `Найти новые вакансии ${what} — поиск по запросам профиля и разбор${on ? " (на ваш риск: соглашение hh это запрещает)" : ""}`;
  $("btnUpdate").setAttribute("aria-label", `Найти новые вакансии ${what}`);
  $("links").placeholder = on || !state.profile ? "Ссылки на вакансии — hh.ru или любой другой сайт, одна или несколько"
    : "Ссылки на вакансии с других сайтов, одна или несколько (hh.ru — сохранённой страницей)";
  $("addHint").innerHTML = on || !state.profile ? "Страницу вакансии, сохранённую в браузере, можно загрузить файлом или перетащить в окно."
    : `Поиск на hh.ru выключен. ${HH_MANUAL}`;
}

// Профиль прежней версии: поиск на hh.ru ждёт решения человека — до него программа на hh.ru не ходит
const hhAsked = {};
function askHh() {
  hhAsked[state.profile] = true;                         // закрыли без выбора — спросим при следующем запуске
  const choose = on => async () => {
    try {
      await api("/api/profile/settings", {profile: state.profile, hh_auto: on, hh_risk: on});
      closeWizard();
      await load(state.profile);
      toast(on ? "Поиск на hh.ru оставлен включённым — на ваш риск" : "Поиск на hh.ru выключен. Вакансии с hh.ru добавляйте сохранённой страницей или текстом");
    } catch (e) { fail(e); }
  };
  dialog("Поиск на hh.ru", `
    <p>Раньше программа сама искала вакансии на hh.ru и скачивала их. Теперь это включается только с вашего согласия.</p>
    <p class="cwarn"><b>Соглашение hh.ru запрещает</b> программы для поиска и сбора данных с сайта (пп. 5.1.6, 5.1.7, 8.6 и 8.8 <a href="${HH_AGREEMENT}" target="_blank" rel="noopener">соглашения</a>). Отвечает за нарушение пользователь: hh может заблокировать аккаунт или доступ к сайту — в том числе по одному подозрению.</p>
    <p class="hint">Без поиска вакансии с hh.ru добавляются вручную. ${HH_MANUAL} Вакансии с других сайтов добавляются по ссылке, как обычно. Решение можно поменять в «Параметры → Настройки».</p>
    <p class="hint">Пока вы не выбрали, программа на hh.ru не ходит.</p>`, [
    {label: "Решу позже", left: true},
    {label: "Оставить включённым, понимаю риск", onClick: choose(true)},
    {label: "Выключить поиск на hh", primary: true, onClick: choose(false)},
  ]);
}

// Вакансии открытой вкладки: статуса или, во вкладке «Фильтр», все
const currentTabRows = () => tab === FILTER_TAB ? state.rows : state.rows.filter(r => r.status === tab);

function render() {
  restoreFilters();
  const cols = shownColumns();
  dropHiddenFilters(cols);
  const today = new Date(), on = filtering();
  // счётчики вкладок-статусов — по их общему фильтру, даже когда открыта вкладка «Фильтр»
  const statusSet = tab === FILTER_TAB ? loadFilters("status") : {f: filters, closed: hideClosed};
  const statusOn = Object.keys(statusSet.f).some(k => filterOn(k, statusSet.f[k])) || statusSet.closed;
  const counts = Object.fromEntries(state.statuses.map(([v]) => {   // с фильтром — «12 из 83»
    const all = state.rows.filter(r => r.status === v);
    return [v, statusOn ? `${filterRows(all, statusSet.f, statusSet.closed, today).length} из ${all.length}` : all.length];
  }));
  if (tab !== FILTER_TAB && !state.statuses.some(([v]) => v === tab)) tab = "new";         // свой статус удалили
  const filterSet = tab === FILTER_TAB ? {f: filters, closed: hideClosed} : loadFilters("filter");
  $("tabs").innerHTML = state.statuses.map(([v, name]) =>
    `<button class="tab ${v === tab ? "on" : ""}" data-tab="${v}" ${state.custom_statuses?.includes(v) ? 'title="Свой статус"' : ""}>${statusIcon(v)}${esc(name)} <span class="count">${counts[v]}</span></button>`).join("")
    + (state.profiles.length ? `<button class="tab addtab" id="addStatus" title="Свои статусы: добавить, переименовать, удалить">+</button>` : "")
    + (state.profiles.length ? `<button class="tab ftab ${tab === FILTER_TAB ? "on" : ""}" data-tab="${FILTER_TAB}" title="Не статус: вакансии всех статусов по фильтру — например, одной компании за последний месяц. Фильтры можно сохранять">${FUNNEL}Фильтр <span class="count">${filterRows(state.rows, filterSet.f, filterSet.closed, today).length}</span></button>` : "");
  const activeTab = PHONE.matches && $("tabs").querySelector(".tab.on");   // телефон: вкладки в строку — выбранную видно
  if (activeTab) $("tabs").scrollLeft = Math.max(0, activeTab.offsetLeft - $("tabs").offsetLeft - 40);
  const tabRows = currentTabRows();
  const rows = sorted(filterRows(tabRows, filters, hideClosed, today));
  renderSavedBar();
  renderFilterBar(tabRows);
  $("heads").innerHTML = cols.map(([key, name, , cls]) =>
    `<th class="${cls} ${PINNED.includes(key) ? `pin pin-${key}` : ""} ${key === sort.key ? "on" : ""} ${columnFiltered(key) ? "filtered" : ""}" data-sort="${key}" title="${{flag: "Флаг"}[key] || ""}">${name}${key === sort.key ? `<span class="arr">${sort.dir > 0 ? "▲" : "▼"}</span>` : ""}${filterButton(key)}</th>`).join("");
  $("rows").innerHTML = rows.map(r => PHONE.matches     // на телефоне — карточкой во всю ширину, без колонок
    ? `<tr class="row card ${r.n === selected ? "sel" : ""}" data-n="${r.n}"><td>${phoneCard(r)}</td></tr>`
    : `<tr class="row ${r.n === selected ? "sel" : ""}" data-n="${r.n}">${cols.map(([key]) => CELLS[key](r)).join("")}
    </tr>`).join("");
  renderPhoneSort(cols);
  pinWidth();
  // Кнопка ↻ в шапке — всегда, кроме «Без модели»; число — сколько вакансий оценено по прежним данным
  const stale = state.rows.filter(r => r.criteria_changed).length, raw = state.rows.filter(r => !r.analyzed || r.stage === "none").length;
  $("btnRescore").hidden = state.no_model;
  $("rescoreCount").textContent = stale + raw || "";        // и неразобранные: их тоже разбирают отсюда
  $("btnRescore").title = stale || raw ? "Пересчитать оценки — " + [raw && `${raw} ${plural(raw, "вакансия ждёт", "вакансии ждут", "вакансий ждут")} разбора`,
      stale && `${stale} ${plural(stale, "вакансия оценена", "вакансии оценены", "вакансий оценены")} по прежним резюме, критериям или фактам о себе`].filter(Boolean).join("; ")
    : "Пересчитать оценки заново — например, после смены модели";
  if (!state.profiles.length) {                          // мастер закрыли, не создав профиль
    $("empty").hidden = false;
    $("empty").innerHTML = `Профиля пока нет. Мастер задаст несколько вопросов и соберёт профиль — после этого программа начнёт искать и разбирать вакансии.
      <p><button class="primary" id="emptyWizard">Создать профиль</button></p>`;
    $("emptyWizard").onclick = openWizard;
    return;
  }
  const waiting = state.no_model ? 0 : state.rows.filter(r => !r.analyzed).length;   // без модели разбора не ждут
  const hint = !state.rows.length
    ? (hhOn() ? "Вакансий пока нет. Нажмите «Найти новые вакансии» — программа найдёт их на hh.ru по запросам профиля, — или добавьте по ссылке."
              : `Вакансий пока нет. Нажмите «Добавить вакансию» — по ссылке, сохранённой страницей или текстом. ${HH_MANUAL}`)
    : waiting && !busyMine() ? `Ждут разбора: ${waiting}.`
    : rows.length ? "" : tabRows.length ? (tab === FILTER_TAB ? "Под фильтр ничего не подходит — измените условия в заголовках колонок или выберите другой фильтр."
      : "Под фильтр в этой вкладке ничего не подходит — измените или сбросьте его.") : "В этом списке пусто.";
  $("empty").hidden = !hint;
  $("empty").textContent = hint;
  if (hint && waiting && state.rows.length && !busyMine()) {   // разобрать ждущих — без нового поиска (например, Ollama была не запущена)
    $("empty").insertAdjacentHTML("beforeend", ' <button class="primary" id="emptyAnalyze">Разобрать</button>');
    $("emptyAnalyze").onclick = () => run("analyze");
  } else if (!state.rows.length && !hhOn()) {
    $("empty").insertAdjacentHTML("beforeend", '<p><button class="primary" id="emptyAdd">Добавить вакансию</button></p>');
    $("emptyAdd").onclick = openAdd;
  }
}

// «Компания» закреплена сразу за «Вакансией»: её отступ слева — ширина колонки «Вакансия», а она зависит от текста
// и ширины панели — поэтому мерим после отрисовки и при изменении размера
// (отступ меняем на следующем кадре и только если изменился — иначе ResizeObserver жалуется на цикл)
const pinObserver = window.ResizeObserver ? new ResizeObserver(() => requestAnimationFrame(setPinLeft)) : null;
let pinWatched = null;
function setPinLeft() {
  const th = document.querySelector("#heads th.pin-title"), table = document.querySelector("table.vac");
  if (!th) return;
  const w = th.getBoundingClientRect().width + "px";
  if (table.style.getPropertyValue("--pin-left") !== w) table.style.setProperty("--pin-left", w);
}
function pinWidth() {
  setPinLeft();
  const th = document.querySelector("#heads th.pin-title");
  if (pinObserver && th && th !== pinWatched) { pinObserver.disconnect(); pinObserver.observe(th); pinWatched = th; }
}

// Ячейки таблицы по ключу колонки (COLUMNS в core.js): набор и порядок колонок пользователь выбирает сам
const CELLS = {
  flag: r => `<td class="num">${r.flag ? '<span class="flag" title="С флагом">⚑</span>' : ""}</td>`,
  score: r => r.stage === "none" ? `<td class="num muted" title="Сохранена без разбора — режим «Без модели»">—</td>`
    : `<td class="num big ${scoreClass(r.score)}" title="могу / хочу${esc(likeTip(r))}">${r.analyzed ? (r.score ?? "?") : "…"}${r.analyzed ? `<small>${r.can ?? "?"}/${wantText(r)}</small>` : ""}</td>`,
  decision: r => `<td class="nowrap" title="${esc(r.decision)}${(r.violations || []).map(v => `\nНарушен К${v.n}: ${esc(v.text)}`).join("")}">${r.stage === "none" ? '<span class="muted">без разбора</span>' : r.analyzed ? decisionHtml(r.decision) : '<span class="muted">ждёт разбора</span>'}</td>`,
  mine: r => r.my_decision ? `<td class="nowrap" title="${esc(myTip(r))}"><div class="mine"><span class="big ${scoreClass(r.my_score)}">${r.my_score ?? "?"}<small>${r.my_can ?? "?"}/${r.my_want ?? "?"}</small></span>`
    + `<span class="mydec"><span class="${MY_TONE[r.my_decision]}">${r.my_decision}</span>${r.my_date ? `<small class="muted">${ddmm(r.my_date)}</small>` : ""}</span></div></td>` : "<td></td>",
  status: r => `<td class="nowrap stcell">${statusIcon(r.status)}${esc((state.statuses.find(([v]) => v === r.status) || [, r.status])[1])}</td>`,
  title: r => `<td class="t-title pin pin-title">${r.actual?.closed ? `<span class="closedtitle">${esc(r.title)}</span> <span class="closedtag" title="Вакансия закрыта">закрыта</span>`
    : esc(r.title)}</td>`,
  company: r => `<td class="co pin pin-company">${esc(r.company)}${agencyChip(r)}${r.contacts ? ` <span class="people-mark" title="В контактах — ${r.contacts} ${plural(r.contacts, "человек", "человека", "человек")} из этой компании">👥${r.contacts > 1 ? r.contacts : ""}</span>` : ""}</td>`,
  source: r => `<td class="src">${esc([r.source, ...(r.more_links || []).map(l => l.source)].filter((x, i, all) => x && all.indexOf(x) === i).join(" · "))}</td>`,
  salary: r => `<td class="sal ${r.salary_value == null ? "muted" : ""}">${esc(r.salary)}</td>`,
  city: r => `<td class="city" title="${esc(r.city)}">${esc(r.city)}</td>`,
  format: r => `<td class="nowrap">${esc(r.format)}</td>`,
  posted: r => `<td class="nowrap">${esc(r.posted)}</td>`,
  added: r => `<td class="nowrap">${esc(r.added)}</td>`,
  updated: r => `<td class="nowrap">${r.updated ? ddmmyyyy(r.updated) : ""}</td>`,
  stage: r => funnelCells(r),
  referrer: r => `<td class="ref">${r.referrer ? `<button type="button" class="reflink" data-ref="${r.n}" title="${esc(r.referrer_contact ? r.referrer_contact.details : r.referrer)}\n\nЩёлкните — открыть карточку контакта">${esc(r.referrer_contact ? r.referrer_contact.short : r.referrer.split(",").slice(0, 2).join(",").trim())}</button>` : ""}</td>`,
  note: r => `<td class="note" title="${esc(r.note)}">${esc(r.note)}</td>`,
  artifacts: r => `<td class="num">${r.artifacts || ""}</td>`,
};

// Своя оценка: «7 · да · 03.11»; причина — при наведении
const MY_TONE = {"да": "s-good", "возможно": "s-mid", "нет": "s-bad"};
// Своя оценка — как «Оценка ИИ»: общая и под ней могу/хочу (у старых оценок «Могу» и «Хочу» нет — «?/?»)
const myTip = r => `Моя оценка${r.my_date ? " от " + ddmmyyyy(r.my_date) : ""}: могу / хочу${r.my_reason ? "\n" + r.my_reason : ""}`;
const myRating = r => r.my_decision ? `<span title="${esc(myTip(r))}">`
  + `<b>${r.my_score ?? "?"}</b> <span class="muted">(${r.my_can ?? "?"}/${r.my_want ?? "?"})</span> · <span class="${MY_TONE[r.my_decision]}">${r.my_decision}</span>${r.my_date ? ` · <span class="muted">${ddmm(r.my_date)}</span>` : ""}</span>` : "";

// Телефон: узкий экран — список карточками, карточка вакансии во весь экран с кнопкой «← К списку»
const PHONE = matchMedia("(max-width: 640px)");
PHONE.addEventListener("change", () => { if (!PHONE.matches) closePhoneDetail(); if (state) render(); });

// Пометка «Возможно, дубль»: та же компания и похожее название, а описание отличается — решает человек
function dupeBox(r) {
  const same = r.maybe_dupe && state.rows.find(x => x.n === r.maybe_dupe);
  if (!same) return "";
  return `<p class="cwarn dupebox">Возможно, это та же вакансия, что
    <button type="button" class="linkbtn" data-like="${same.n}" title="Открыть ту вакансию">№ ${same.n}</button> «${esc(same.title)}» (${esc(same.source || "")}, сохранена ${esc(same.added)}):
    та же компания и похожее название.
    <span class="dupebtns"><button type="button" class="primary small" data-dupe="merge" title="Ссылка этой вакансии допишется к той, а эта карточка с разбором и письмами уйдёт в Корзину">Склеить</button>
    <button type="button" class="small" data-dupe="apart" title="Пометка исчезнет, обе карточки останутся">Это разные</button></span></p>`;
}

// Надбавка к «Хочу» в разборе: на какие отклики похожа вакансия — со ссылками на них
function likeHtml(r) {
  if (!r.want_bonus) return "";
  const items = r.want_like.map(l => `<button type="button" class="linkbtn" data-like="${l.n}">${esc(l.title)}, ${esc(l.company)}</button> <span class="muted">(отклик ${ddmm(l.date)})</span>`);
  return `<p class="why wantlike"><b>Хочу +${r.want_bonus}:</b> похожа на ${items.length > 1 ? "вакансии, на которые вы откликались" : "вакансию, на которую вы откликались"} — ${items.join("; ")}.
    <span class="muted">Надбавку ставит программа, а не модель: «Хочу» модели — ${r.want}, с надбавкой — ${wantOf(r)}. Выключается в «Настройках».</span></p>`;
}

function phoneCard(r) {
  const f = r.funnel || {};
  const score = r.stage === "none" ? "" : `<span class="cscore ${scoreClass(r.score)}" title="могу / хочу">${r.analyzed ? (r.score ?? "?") : "…"}${r.analyzed ? `<small>${r.can ?? "?"}/${wantText(r)}</small>` : ""}</span>`;
  const meta = [r.stage === "none" ? "" : r.analyzed ? decisionHtml(r.decision) : '<span class="muted">ждёт разбора</span>',
    r.salary_value == null ? "" : esc(r.salary),
    f.stage ? `<span class="stagecell ${STAGE_TONE[f.stage] || ""}">${esc(stageName(f.stage))}</span>` : "",
    `<span class="muted">${esc(r.added)}</span>`,
    r.posted && shownColumns().some(c => c[0] === "posted") ? `<span class="muted">опубликована ${esc(r.posted)}</span>` : "",
    r.city && shownColumns().some(c => c[0] === "city") ? esc(r.city) : "",
    r.format && shownColumns().some(c => c[0] === "format") ? esc(r.format) : "",
    r.my_decision && shownColumns().some(c => c[0] === "mine") ? `<span>моя ${myRating(r)}</span>` : ""].filter(Boolean);   // колонка включена — и в карточке
  return `<div class="ctop"><div class="ctitle">${r.flag ? '<span class="flag" title="С флагом">⚑</span> ' : ""}${r.actual?.closed
      ? `<span class="closedtitle">${esc(r.title)}</span> <span class="closedtag">закрыта</span>` : esc(r.title)}</div>${score}</div>
    <div class="cco">${esc(r.company)}${agencyChip(r)}${r.contacts ? ` <span class="people-mark">👥${r.contacts > 1 ? r.contacts : ""}</span>` : ""}</div>
    <div class="cmeta">${meta.join('<span class="dot">·</span>')}</div>${r.note ? `<div class="cnote">${esc(r.note)}</div>` : ""}`;
}

// Сортировка по колонке: тексты — по алфавиту, остальное — сначала большие; dir — явное направление
function setSort(key, dir = ["title", "company", "note"].includes(key) ? 1 : -1) {
  sort = {key, dir};
  remember("sort", JSON.stringify(sort));
  render();
}

// Заголовков колонок на телефоне нет — сортировка и фильтр по полю из списка
function renderPhoneSort(cols) {
  if (!PHONE.matches || !state.rows.length) { $("psort").innerHTML = ""; return; }
  const key = cols.some(c => c[0] === sort.key) ? sort.key : "score";
  $("psort").innerHTML = `<label>Сортировка <select id="psKey">${cols.map(([k, name]) =>
      `<option value="${k}" ${k === key ? "selected" : ""}>${esc(COLUMN_NAMES[k] || name)}</option>`).join("")}</select></label>
    <button type="button" class="icon" id="psDir" title="Направление сортировки">${sort.dir > 0 ? "▲" : "▼"}</button>
    ${FILTER_KIND[key] ? `<button type="button" class="icon ${columnFiltered(key) ? "on" : ""}" id="psFilter" title="Фильтр по этому полю">${FUNNEL}</button>` : ""}`;
  $("psKey").onchange = e => setSort(e.target.value);
  $("psDir").onclick = () => setSort(key, -(key === sort.key ? sort.dir : -1));
  if ($("psFilter")) $("psFilter").onclick = e => { e.stopPropagation(); openFilter(key, $("psFilter")); };
}

let listScroll = 0;
function openPhoneDetail(push) {
  if (!PHONE.matches) return;
  if (!document.body.classList.contains("phone-detail")) listScroll = scrollY;
  document.body.classList.add("phone-detail");
  if (push) history.pushState({phoneDetail: true}, "", location.hash);
  scrollTo(0, 0);
}
function closePhoneDetail() {
  if (!document.body.classList.contains("phone-detail")) return;
  document.body.classList.remove("phone-detail");
  history.replaceState(null, "", location.pathname + location.search);
  requestAnimationFrame(() => scrollTo(0, listScroll));
}
addEventListener("popstate", () => closePhoneDetail());     // «Назад» в браузере телефона — к списку
$("detail").addEventListener("click", e => {
  if (!e.target.closest("#backToList")) return;
  if (history.state?.phoneDetail) history.back(); else closePhoneDetail();
});

// Колонка «Этап»: только название этапа (даты и история — во вкладке «История» карточки)
function funnelCells(r) {
  const f = r.funnel || {};
  return `<td class="nowrap stagecell ${STAGE_TONE[f.stage] || ""}">${f.stage ? esc(stageName(f.stage)) : ""}</td>`;
}

// Поиск людей в компании вакансии: [значение, название, что добавить к названию компании в запросе]
const PEOPLE_WHO = [["all", "все сотрудники", ""], ["hr", "HR и рекрутеры", "HR"], ["it", "ИТ-руководители", "IT директор"],
                    ["lead", "руководство", "директор"]];
let peopleWho = "all";
try { peopleWho = localStorage.getItem("peopleWho") || "all"; } catch (e) {}

// «О компании»: кадровое агентство или работодатель, сайт, рейтинг hh, отчётность, другие вакансии
let aboutOpen = false;
const AGENCY_WHY = {hh: "так у работодателя на hh", name: "по названию", text: "по тексту вакансии"};
function agencyChip(r) {
  if (!r.agency) return "";
  const tip = r.agency_why === "mark" ? "Вы отметили компанию как кадровое агентство"
    : `Похоже на кадровое агентство — ${AGENCY_WHY[r.agency_why]}${r.agency_what && r.agency_why === "text" ? `: «${r.agency_what}»` : ""}. Поправить — в карточке, «О компании»`;
  return ` <span class="chip agency" title="${esc(tip)}">Кадровое агентство</span>`;
}
// ИТ-аккредитация Минцифры — как её указывает hh у работодателя
function itText(it, onHh) {
  return it === true ? `<span class="s-good">есть</span> <span class="muted">— аккредитованная ИТ-компания, по данным hh</span>`
    : it === false ? `нет <span class="muted">— по данным hh</span>`
    : `<span class="muted">нет сведений${onHh ? (hhOn() ? " — появятся после «Разобрать заново»" : " — сохраните страницу вакансии на hh в браузере и перетащите файл в окно") : " — их даёт только hh"}</span>`;
}
function aboutBox(r, d) {
  const a = d.about, hh = a.hh || {};
  const num = x => String(x).replace(".", ",");
  const rating = hh.rating != null ? `★ ${num(hh.rating)}` + (hh.reviews != null ? ` · ${hh.reviews} ${plural(hh.reviews, "отзыв", "отзыва", "отзывов")}` : "")
    : hh.reviews != null ? `${hh.reviews} ${plural(hh.reviews, "отзыв", "отзыва", "отзывов")}` : "";
  const past = a.past.map(p => ({...p, r: state.rows.find(x => x.n === p.n)})).filter(p => p.r);
  // «ещё N вакансий» — ссылка: все вакансии компании (и с похожим названием) во вкладке «Фильтр»
  const more = past.length ? `<button type="button" class="linkbtn morevac" id="aboutMore" title="Все вакансии этой компании — во вкладке «Фильтр»">ещё ${past.length} ${plural(past.length, "вакансия", "вакансии", "вакансий")}</button>` : "";
  const facts = [rating, more].filter(Boolean);
  if (a.anonymous) return `<details class="coabout" id="about" ${aboutOpen ? "open" : ""}>
    <summary><b>О компании</b> <span class="chip">Работодатель скрыт</span></summary>
    <p class="muted">Компания не названа в вакансии — сайт, рейтинг, отчётность и другие вакансии найти не по чему.</p></details>`;
  const chip = a.agency ? `<span class="chip agency">Кадровое агентство</span>` : `<span class="chip employer">Работодатель</span>`;
  const mark = a.agency ? `<button type="button" class="markbtn" data-agency="0">отметить, что это не агентство</button>`
    : `<button type="button" class="markbtn" data-agency="1">отметить, что это кадровое агентство</button>`;
  const who = a.agency
    ? `<b>Кадровое агентство</b> — ${a.marked ? "отмечено вами" : `${AGENCY_WHY[a.agency_why]}${a.agency_what && a.agency_why === "text" ? ` («${esc(a.agency_what)}»)` : ""}`} (${mark}).
       <span class="muted">Настоящий работодатель не назван: референсеры, поиск людей и отчётность — по агентству.</span>`
    : `<b>Работодатель</b>${a.marked ? " — отмечено вами" : ""} (${mark})`;
  const site = hh.site || (/^Сайт /.test(r.source || "") && /^https?:\/\//.test(r.link || "") ? new URL(r.link).origin : "");
  const host = u => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return u; } };
  const noRating = hhOn() ? "рейтинг появится после «Разобрать заново»"
    : "рейтинг: поиск на hh выключен — сохраните страницу вакансии в браузере (⌘S или Ctrl+S) и перетащите файл в окно";
  const hhRow = a.hh ? `<a href="${esc(hh.url)}" target="_blank" rel="noopener" title="Страница работодателя на hh: отзывы, другие вакансии">${esc(hh.url.replace(/^https:\/\//, ""))}</a>
        ${rating ? `· <b>${rating}</b> <span class="muted">на ${ddmm(hh.rating_date)}</span>`
          : hh.rating_date ? `<span class="muted">· отзывов на hh нет</span>` : `<span class="muted">· ${noRating}</span>`}`
    : r.source === "HH" ? `<span class="muted">нет сведений — ${hhOn() ? "появятся после «Разобрать заново»" : "сохраните страницу вакансии на hh в браузере (⌘S или Ctrl+S) и перетащите файл в окно"}</span>` : "";
  return `<details class="coabout" id="about" ${aboutOpen ? "open" : ""}>
    <summary><b>О компании</b> ${chip}${facts.length ? ` <span class="muted">· ${facts.join(" · ")}</span>` : ""}</summary>
    <dl>
      <dt>Название</dt><dd>${r.company ? `<button type="button" class="linkbtn cofilter" id="aboutCoFilter" title="Все вакансии этой компании — во вкладке «Фильтр»">${esc(r.company)}</button>` : ""}</dd>
      <dt>Тип</dt><dd>${who}</dd>
      <dt>Сайт</dt><dd>${site ? `<a href="${esc(site)}" target="_blank" rel="noopener">${esc(host(site))}</a>`
        : `<span class="muted">${r.source === "HH" && !a.hh ? "нет сведений" : "не указан"}</span>`}</dd>
      ${hhRow ? `<dt>Страница на hh</dt><dd>${hhRow}</dd>` : ""}
      <dt>ИТ-аккредитация</dt><dd>${itText(hh.it, a.hh)}</dd>
      ${d.finance ? `<dt>Отчётность</dt><dd><a href="${esc(d.finance.url)}" target="_blank" rel="noopener" title="${d.finance.by_inn
          ? "Поиск по ИНН из текста вакансии"
          : `Поиск по названию «${esc(r.people_query)}» — выберите компанию в списке по адресу; не нашлась — попробуйте юридическое название`}">в ФНС (ГИР БО)</a>
          <span class="muted">выручка, прибыль, долги${a.agency ? " — это отчётность агентства, а не работодателя" : ""}</span></dd>` : ""}
    </dl></details>`;
}

async function openVacancy(n) {
  selected = n; render();
  history.replaceState(history.state, "", "#" + n);   // ссылку на вакансию можно сохранить
  const r = state.rows.find(x => x.n === n);
  const d = await api(`/api/vacancy?profile=${encodeURIComponent(state.profile)}&n=${n}`).catch(fail);
  if (!d || selected !== n) return;
  const {stories, questions} = interviewParts(d.interview);
  if ((detailTab === "history" || detailTab === "artifacts") && !r.analyzed) detailTab = "analysis";
  if (detailTab === "analysis" && !d.analysis) detailTab = "vacancy";
  const opts = state.statuses.map(([v, name]) => `<option value="${v}" ${v === r.status ? "selected" : ""}>${esc(name)}</option>`).join("");
  const dtab = (key, name, on) => on ? `<button class="tab ${detailTab === key ? "on" : ""}" data-dtab="${key}">${name}</button>` : "";
  const body = detailTab === "letter" ? lettersTab(r, d, n)
    : detailTab === "history" ? historyTab(r, d)
    : detailTab === "artifacts" ? artifactsTab(r, d, n)
    : detailTab === "resume" ? resumeFitTab(r, d, n)
    : detailTab === "interview" ? (!r.analyzed
      ? `<p class="hint">Подготовиться к интервью — истории STAR и вопросы работодателю — можно после разбора вакансии.</p>`
      : d.interview
      ? `<section class="isec"><h3>Истории STAR <button type="button" class="info tip" aria-label="Что такое STAR" data-tip="${STAR_TIP}">i</button></h3>
           <p class="lettertools"><button class="primary" id="copyInterview">Скопировать</button>
             <button id="newInterview" title="Подобрать истории заново — нынешние заменятся, вопросы работодателю останутся">Подготовить заново</button>
             <span class="hint">подготовлено ${esc(d.interview_when)} · проверьте факты и допишите то, что в [скобках]</span></p>
           <div class="md interview">${markAsk(storiesHtml(stories))}</div></section>
         <section class="isec"><h3>Вопросы работодателю</h3>
           ${questions ? `<p class="lettertools"><button class="primary" id="copyQuestions" title="Только вопросы — чтобы взять с собой на интервью">Скопировать</button>
               <button id="newQuestions" title="Подобрать вопросы заново — нынешние заменятся, истории останутся">Новые вопросы</button></p>
             <div class="md interview">${markAsk(md(questions))}</div>`
           : `<p class="hint">5–7 ваших вопросов к этой вакансии — про пробелы и неясности из разбора: кому подчиняется роль, почему она открыта, бюджет и команда, чего ждут через 3–6 месяцев. Истории останутся как есть.</p>
             <p class="lettertools"><button id="newQuestions">Подготовить вопросы</button></p>`}</section>`
      : `<div class="md"><p>Модель подберёт из резюме <b>4 истории по методу <span class="tip tipword" tabindex="0" data-tip="${STAR_TIP}">STAR</span></b> под главные требования этой вакансии — для вопросов вроде «Расскажите о случае, когда…»: ситуация, задача, ваши действия, результат с цифрами и вывод. А ещё подскажет, как честно отвечать на вопросы о пробелах из разбора, и предложит <b>5–7 ваших вопросов работодателю</b> — про то, что неясно именно в этой вакансии: кому подчиняется роль, почему она открыта, бюджет и команда, чего ждут через 3–6 месяцев.</p>
         <p class="hint">Факты — только из резюме; чего не хватает, модель отметит [в скобках], чтобы вы дописали. Занимает 1–3 минуты.</p>
         <p><button class="primary" id="newInterview">Подготовить истории</button></p></div>`)
    : detailTab === "analysis" ? `${r.stage === "short" ? `<p class="cwarn">Короткая оценка: модель проверила критерии и поставила оценку, а полный разбор — требования, сильные стороны, пробелы — делает только для «да» и «возможно». Нужны подробности — кнопка «Разобрать заново» вверху: она делает полный разбор.</p>` : ""}<div class="md analysis">${analysisHtml(d.parsed, d.criteria, d.criteria_changed, d.model, d.analysis_date, likeHtml(r))}</div>`
    : `<div class="md">${md(d.vacancy)}</div>`;
  const typing = document.activeElement && document.activeElement.id === "textEdit"   // перерисовка не сбивает набор
    ? [document.activeElement.selectionStart, document.activeElement.selectionEnd] : null;
  $("detail").innerHTML = `
    <button type="button" class="backlist" id="backToList">← К списку</button>
    <div class="dhead">
      <div class="dtitle"><h2><button type="button" class="titlefilter" id="titleFilter" title="Все вакансии с таким названием — во вкладке «Фильтр»">${esc(r.title)}</button></h2>
        <div class="t-meta">${r.company ? `<button type="button" class="linkbtn cofilter" id="coFilter" title="Все вакансии этой компании — во вкладке «Фильтр»">${esc(r.company)}</button>` : ""} · ${r.salary_value == null ? "зарплата не указана" : esc(r.salary)}${/^https?:\/\//.test(r.link || "") ? ` · <a href="${esc(r.link)}" target="_blank" rel="noopener">открыть на ${esc(new URL(r.link).hostname.replace(/^www\./, ""))}</a>` : ""}${
          r.posted ? ` · <span title="Дата публикации на сайте: ${esc(r.posted)}. Давно висящая вакансия — повод спросить, актуальна ли она">опубликована ${r.posted.endsWith(String(new Date().getFullYear())) ? r.posted.slice(0, 5) : esc(r.posted)}</span>` : ""}${
          (r.more_links || []).length ? ` · ещё на ${r.more_links.map(l => `<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(new URL(l.url).hostname.replace(/^www\./, ""))}</a>`).join(", ")}` : ""}</div></div>
      <div class="dactions">
        <button class="primary" id="refreshCard" title="Собрать карточку заново: текст вакансии (для других сайтов — со страницы) и полный разбор по текущим критериям и модели — требования, сильные стороны, пробелы. Статус, флаг, комментарий, референсер и письма сохранятся"><svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-2.6-6.4"/><path d="M21 3v6h-6"/></svg>Разобрать заново</button>
      </div>
    </div>
    ${dupeBox(r)}
    ${aboutBox(r, d)}
    <div class="controls">
      <section class="cardbox" aria-label="Поля карточки">
        <div class="crow">
          <label class="flagbox" title="Флаг — пометить вакансию, чтобы не потерять"><input type="checkbox" id="flag" ${r.flag ? "checked" : ""}><span class="flag">⚑</span></label>
          <div class="cfield inl"><label class="tlab" for="status">Статус</label><span class="statussel"><span id="statusIcon">${statusIcon(r.status)}</span><select id="status" title="Раздел таблицы">${opts}</select></span></div>
          ${stageSection(r)}</div>
        ${r.analyzed ? `<div class="cline"><div class="cfhead"><label class="tlab" for="note">Комментарий</label><span class="saved" id="savedNote"></span></div>
          <textarea id="note" rows="1" placeholder="что важно помнить: с кем говорили, о чём договорились, почему не подходит">${esc(r.note)}</textarea></div>
        ${datesLine(r)}
        <div class="cline"><div class="cfhead"><label class="tlab" for="referrer" title="Кто работает в компании и может передать резюме — отклик через знакомого">Референсер</label><span class="saved" id="savedReferrer"></span></div>
          <div class="cval"><div class="refline"><textarea id="referrer" rows="1" placeholder="кто в компании передаст резюме: имя, должность, контакт">${esc(r.referrer || "")}</textarea>${r.referrer ? `<button type="button" class="icon refopen" id="openReferrer" title="Карточка референсера: имя, должность, статус, заметка" aria-label="Карточка референсера"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="11" r="2.5"/><path d="M5.5 17a3.5 3.5 0 0 1 7 0"/><path d="M15 9h3M15 13h3"/></svg></button>` : ""}</div>
          ${referrerCandidates(r, d)}</div></div>` : datesLine(r)}
      </section>
      <section class="peoplebar" aria-label="Найти людей в компании">
        <div class="people"><span class="pbhead"><svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg><b>Найти людей</b></span>
          <select id="peopleWho" title="Кого искать в компании" ${r.people_query ? "" : "disabled"}>
            ${PEOPLE_WHO.map(([v, name]) => `<option value="${v}" ${v === peopleWho ? "selected" : ""}>${name}</option>`).join("")}</select>
          <a class="btnlink linkedin ${r.people_query ? "" : "off"}" id="findLinkedIn" target="_blank" rel="noopener" title="Поиск людей в LinkedIn — откроется в новой вкладке, нужен вход в ваш аккаунт"><span class="logo">in</span>LinkedIn</a>
          <a class="btnlink setka ${r.people_query ? "" : "off"}" id="findSetka" target="_blank" rel="noopener" title="Поиск людей в Сетке (соцсеть hh.ru) — откроется в новой вкладке, нужен вход в ваш аккаунт"><span class="logo">С</span>Сетка</a></div>
        <div class="hint">${r.people_query ? `в «${esc(r.people_query)}» — ${r.agency ? "это агентство: найдёте его сотрудников, а не работодателя" : "найдёте, кто передаст резюме, впишите в «Референсер»"}` : "компания в вакансии скрыта — искать некого"}</div>
      </section>
    </div>
    <div class="dtabs">${dtab("analysis", "Разбор", d.analysis)}${dtab("vacancy", "Вакансия", true)}${dtab("resume", "Резюме", true)}${dtab("letter", "Письма", true)}${dtab("interview", "Интервью", true)}${dtab("artifacts", `Артефакты${(d.artifacts || []).length ? ` <span class="ok">${d.artifacts.length}</span>` : ""}`, r.analyzed)}${dtab("history", "История", r.analyzed)}</div>
    ${body}`;
  $("about").ontoggle = e => { aboutOpen = e.target.open; };
  document.querySelectorAll("#about [data-agency]").forEach(b => b.onclick = async () => {
    const v = b.dataset.agency;
    await api("/api/company/agency", {profile: state.profile, n, agency: v === "1"}).catch(fail);
    toast(v === "1" ? "Отмечено: кадровое агентство — для всех вакансий компании" : "Отмечено: работодатель — для всех вакансий компании");
    await refreshRows(); if (selected === n) openVacancy(n);
  });
  if ($("aboutMore")) $("aboutMore").onclick = e => {            // в заголовке «О компании»: не сворачивать блок
    e.preventDefault(); e.stopPropagation();
    openCompanyFilter([r.company, ...d.about.past.map(p => state.rows.find(x => x.n === p.n)?.company).filter(Boolean)]);
  };
  if ($("aboutCoFilter")) $("aboutCoFilter").onclick = () => openCompanyFilter(r.company);
  $("status").onchange = async e => {
    $("statusIcon").innerHTML = statusIcon(e.target.value);       // значок — сразу, как и на вкладке
    await api("/api/status", {profile: state.profile, n, value: e.target.value}).catch(fail);
    r.status = e.target.value; render(); toast("Статус сохранён");
    if (r.status === "interview" && r.analyzed) detailTab = "interview";   // сразу к подготовке
    if (r.analyzed) { await refreshRows(); if (selected === n) openVacancy(n); }   // история статусов — во вкладке «История»
  };
  $("flag").onchange = async e => {
    const on = e.target.checked;
    await api("/api/flag", {profile: state.profile, n, on}).then(() => { r.flag = on; render(); },
      err => { e.target.checked = !on; fail(err); });
  };
  // Заметка и референсер: сохраняются сами через 0,7 с после ввода или по Enter
  const autosave = (id, url, key, savedId) => {
    const el = $(id);
    if (!el) return;
    let h;
    const save = async () => {
      const res = await api(url, {profile: state.profile, n, text: el.value}).catch(fail);
      r[key] = el.value.trim(); $(savedId).textContent = "сохранено";
      if (res && res.updated !== undefined && res.updated !== r.updated) {   // правка комментария — «Обновлено» сегодня
        r.updated = res.updated;
        if ($("cUpdated")) $("cUpdated").textContent = r.updated ? ddmmyyyy(r.updated) : "—";
      }
      render();
      if ($("histBody")) api(`/api/vacancy?profile=${encodeURIComponent(state.profile)}&n=${n}`)   // открыта «История» — дописать правку
        .then(d2 => { if ($("histBody") && selected === n) $("histBody").innerHTML = historyHtml(r, d2); }, () => {});
    };
    const grow = () => { el.style.height = "auto"; el.style.height = el.scrollHeight + 2 + "px"; };   // высота по тексту
    grow();
    el.oninput = () => { grow(); $(savedId).textContent = ""; clearTimeout(h); h = setTimeout(save, 700); };
    el.onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); clearTimeout(h); save(); } };
  };
  const people = () => {                                // ссылки поиска — по компании и выбранной роли
    if (!r.people_query) return;
    peopleWho = $("peopleWho").value;
    try { localStorage.setItem("peopleWho", peopleWho); } catch (e) {}
    const q = encodeURIComponent([r.people_query, (PEOPLE_WHO.find(w => w[0] === peopleWho) || [])[2]].filter(Boolean).join(" "));
    $("findLinkedIn").href = `https://www.linkedin.com/search/results/people/?keywords=${q}`;
    $("findSetka").href = `https://setka.ru/search?query=${q}&category=ACCOUNTS`;
  };
  if ($("peopleWho")) { $("peopleWho").onchange = people; people(); }
  bindReferrerCandidates(r, d, n);
  autosave("note", "/api/note", "note", "savedNote");
  autosave("referrer", "/api/referrer", "referrer", "savedReferrer");
  bindFunnel(r, n);
  $("refreshCard").onclick = () => { detailTab = "analysis"; run("refresh_card", {n}); };
  if ($("critInfo")) $("critInfo").onclick = e => { e.stopPropagation(); toggleCriteria(d); };
  // «Поставить свои оценки» → окно «Мои оценки» — после ссылки на гид у блока «Оценка»: правка критериев по этой вакансии
  const help = document.querySelector("#detail .analysis .helplink");
  if (help && !state.no_model && r.stage !== "none") {
    help.insertAdjacentHTML("afterend", `<button type="button" class="fixbtn" id="fixOpen" title="Поставить свою оценку и, если нужно, поправить критерии, резюме или «о себе» и пересчитать вакансию">✎ Поставить свои оценки</button>`);
    $("fixOpen").onclick = () => openFix(n);
  }
  if (detailTab === "letter") bindLetters(r, d, n);
  if (detailTab === "resume") bindResumeFit(d, n);
  if (detailTab === "artifacts") bindArtifacts(d, n);
  if (typing && $("textEdit")) { $("textEdit").focus(); $("textEdit").setSelectionRange(...typing); }
  if ($("copyInterview")) $("copyInterview").onclick = () => navigator.clipboard.writeText(stories).then(() => toast("Истории скопированы"), fail);
  if ($("newInterview")) {
    $("newInterview").onclick = () => { detailTab = "interview"; run("interview", {n}); };
  }
  if ($("copyQuestions")) $("copyQuestions").onclick = () => navigator.clipboard.writeText(questions).then(() => toast("Вопросы скопированы"), fail);
  if ($("newQuestions")) $("newQuestions").onclick = () => { detailTab = "interview"; run("interview_questions", {n}); };
  document.querySelectorAll("[data-dtab]").forEach(b => b.onclick = () => { detailTab = b.dataset.dtab; openVacancy(n); });
  document.querySelectorAll("[data-dupe]").forEach(b => b.onclick = async () => {   // склеить дубль или «это разные»
    if (b.dataset.dupe === "merge" && !confirm(`Склеить с № ${r.maybe_dupe}? Ссылка этой вакансии допишется к той, а эта карточка — с разбором, письмами и этапом — уйдёт в Корзину.`)) return;
    const res = await api("/api/dupe", {profile: state.profile, n, action: b.dataset.dupe}).catch(fail);
    if (!res) return;
    await refreshRows();
    goToVacancy(res.n);
    toast(b.dataset.dupe === "merge" ? `Склеено с № ${res.n}` : "Пометка снята — это разные вакансии");
  });
  document.querySelectorAll("[data-like]").forEach(b => b.onclick = () => {   // вакансия-отклик, на которую похожа эта
    goToVacancy(+b.dataset.like);
  });
  if ($("coFilter")) $("coFilter").onclick = () => openCompanyFilter(r.company);
  $("titleFilter").onclick = () => openTitleFilter(r.title);
  updateCardButtons();                          // уже в очереди — «в очереди (2-я)» вместо кнопки
}

// Вкладка «Резюме»: как подогнать резюме под вакансию — что включить, что можно не включать, «Обо мне», навыки. Версии — как у писем
function resumeFitTab(r, d, n) {
  if (!r.analyzed)
    return `<p class="hint">Подогнать резюме можно после разбора вакансии: модель берёт из него ваши сильные стороны под требования.</p>`;
  const versions = d.resume_fits || [];
  if (!versions.length)
    return `<div class="md"><p>Рекрутер и система отбора ищут в резюме слова и задачи из вакансии, а перегруженное резюме читают по диагонали. ИИ подскажет, что из вашего опыта показать под эту вакансию:</p>
       <ul><li><b>что включить</b> — 3–6 фактов из резюме и «Дополнительно о себе», которые закрывают задачи вакансии, и почему; чего в резюме ещё нет — с пометкой «добавьте в резюме»;</li>
         <li><b>что можно не включать</b> — опыт, слабо связанный с этой вакансией: его можно сократить или убрать;</li>
         <li><b>«Обо мне»</b> — новый текст на 3–4 предложения языком вакансии;</li>
         <li><b>ключевые навыки</b> — какие из ваших выделить и каких слов вакансии в резюме нет (добавлять, только если это правда).</li></ul>
       <p class="hint">Факты — только из резюме и «Дополнительно о себе», ничего не выдумывается; чего не хватает, модель отметит [в скобках]. Резюме в программе и на hh не меняется: новую версию резюме на hh вы создаёте сами и переносите туда то, что подходит. Занимает 1–2 минуты.</p>
       <p class="lettertools">${ibtn("newResumeFit", "ai", "ИИ подгонит резюме", "primary")} ${ibtn("textOwnBtn", "own", "Написать своё — например, итоговый текст «Обо мне», который поставили в резюме на hh")}</p></div>`
      + (draftOf(n, "resume") ? textEditor("resume", draftOf(n, "resume"), versions) : "");
  if (fitVersion.n !== n) fitVersion = {n, i: 0};
  const shown = versions[fitVersion.i] || versions[0];
  const vers = versionPicker(versions, fitVersion.i, "fitVer");
  if (draftOf(n, "resume")) return vers + textEditor("resume", draftOf(n, "resume"), versions);
  return vers + `<p class="lettertools">${ibtn("copyResumeFit", "copy", "Скопировать", "primary")}
      ${ibtn("textEditBtn", "edit", "Править — сохранится новой версией")}
      ${ibtn("textOwnBtn", "own", "Написать своё — например, итоговый текст «Обо мне», который поставили в резюме на hh")}
      ${ibtn("newResumeFit", "ai", "ИИ: новая версия — нынешний вариант сохранится в версиях")}
      ${ibtn("sentBtn", "sent", shown.sent ? `Отправлено ${ddmm(shown.sent)} — поправить дату или снять отметку` : "Отметить «Отправлено» — текст попадёт в «Артефакты»",
             shown.sent ? "sent" : "", shown.sent ? ddmm(shown.sent) : "")}
      <span class="hint">${versionNote(shown)}${shown.source ? "" : "проверьте факты и допишите то, что в [скобках]; "}на hh переносите сами</span></p>
    ${factsNote(shown)}<div class="md">${markAsk(markFacts(md(shown.text), shown.unverified))}</div>`;
}
function bindResumeFit(d, n) {
  if ($("fitVer")) $("fitVer").onchange = e => { fitVersion = {n, i: +e.target.value}; openVacancy(n); };
  const versions = d.resume_fits || [];
  if ($("copyResumeFit")) $("copyResumeFit").onclick = () => navigator.clipboard.writeText((versions[fitVersion.i] || versions[0]).text)
    .then(() => toast("Скопировано"), fail);
  if ($("newResumeFit")) $("newResumeFit").onclick = () => { fitVersion = {n, i: 0}; run("resume_fit", {n}); };
  bindTextEdit(n, "resume", versions, versions[fitVersion.i] || versions[0], () => { fitVersion = {n, i: 0}; });
  if ($("sentBtn")) $("sentBtn").onclick = () => openSentDialog(state.rows.find(x => x.n === n) || {}, n, "resume", versions[fitVersion.i] || versions[0]);
}

// Вкладка «Письма»: сопроводительное письмо к отклику и сообщение референсеру — у каждого свои версии
const REF_CHANNELS = [["telegram", "Telegram"], ["linkedin", "LinkedIn — сообщение"], ["invite", "LinkedIn — запрос в контакты (до 300 знаков)"],
                      ["setka", "Сетка"], ["email", "Почта"]];
function lettersTab(r, d, n) {
  const kinds = `<div class="lkinds">
      <button type="button" class="lkind ${letterKind === "cover" ? "on" : ""}" data-lkind="cover">Сопроводительное${d.letters.length ? ' <span class="ok">✓</span>' : ""}</button>
      <button type="button" class="lkind ${letterKind === "referrer" ? "on" : ""}" data-lkind="referrer">Референсеру${d.ref_letters.length ? ' <span class="ok">✓</span>' : ""}</button></div>`;
  if (!r.analyzed)
    return kinds + `<p class="hint">Письма пишутся по разбору вакансии: модель берёт из него сильные стороны под требования. Разбора ещё нет — нажмите «Разобрать заново» вверху.</p>`;
  const cover = letterKind === "cover";
  const versions = cover ? d.letters : d.ref_letters, kind = cover ? "cover" : "referrer";
  if (letterVersion.n !== n || letterVersion.kind !== letterKind) letterVersion = {n, i: 0, kind: letterKind};
  const shown = versions[letterVersion.i] || versions[0];
  if (!versions.length) return kinds + (cover
    ? `<div class="md"><p><b>Сопроводительное письмо</b> к отклику — по шаблону из профиля: та же длина и тон, а факты только из резюме и вакансии. Перед тем как ИИ напишет письмо, шаблон можно выбрать и поправить под эту вакансию.</p>
       <p class="lettertools">${ibtn("newLetter", "ai", "ИИ напишет письмо", "primary")} ${ibtn("textOwnBtn", "own", "Написать своё письмо")}</p></div>`
    : `<div class="md"><p><b>Сообщение референсеру</b> — короткое личное письмо знакомому в этой компании: напомнить о знакомстве, сказать, чем интересна вакансия, 1–2 факта из резюме и ясная просьба — передать резюме или рассказать о роли.</p>
       ${d.referrer ? `<p>Кому: <b>${esc(d.referrer)}</b></p><p class="lettertools">${ibtn("newRefLetter", "ai", "ИИ напишет сообщение", "primary")} ${ibtn("textOwnBtn", "own", "Написать своё сообщение")}</p>`
                    : `<p class="cwarn">Сначала укажите референсера — поле «Референсер» выше: выберите из контактов или впишите вручную.</p>`}</div>`)
    + (draftOf(n, kind) ? textEditor(kind, draftOf(n, kind), versions) : "");
  const channel = shown.channel ? (REF_CHANNELS.find(c => c[0] === shown.channel) || [])[1] : "";
  const vers = versionPicker(versions, letterVersion.i, "letterVer", d.templates > 1);
  if (draftOf(n, kind)) return kinds + vers + textEditor(kind, draftOf(n, kind), versions);
  return kinds + vers + `<p class="lettertools">${ibtn("copyLetter", "copy", "Скопировать", "primary")}
      ${ibtn("textEditBtn", "edit", "Править — сохранится новой версией, это останется в версиях")}
      ${ibtn("textOwnBtn", "own", "Написать своё — сохранится новой версией")}
      ${ibtn(cover ? "newLetter" : "newRefLetter", "ai", "ИИ: новая версия — нынешнее сохранится в версиях")}
      ${ibtn("sentBtn", "sent", shown.sent ? `Отправлено ${ddmm(shown.sent)} — поправить дату или снять отметку` : "Отметить «Отправлено» — с датой",
             shown.sent ? "sent" : "", shown.sent ? ddmm(shown.sent) : "")}
      ${cover && d.templates > 1 && shown.template ? `<span class="hint">шаблон: ${esc(shown.template)}</span>` : ""}
      ${!cover && shown.to ? `<span class="hint">кому: ${esc(shown.to)}${channel ? " · " + esc(channel) : ""}</span>` : ""}</p>
    ${versionNote(shown) ? `<p class="hint">${versionNote(shown).replace(/ · $/, ".")}</p>` : ""}
    ${factsNote(shown)}<div class="letter">${markAsk(markFacts(esc(shown.text), shown.unverified))}</div>`;
}

function bindLetters(r, d, n) {
  document.querySelectorAll("[data-lkind]").forEach(b => b.onclick = () => { letterKind = b.dataset.lkind; openVacancy(n); });
  if ($("letterVer")) $("letterVer").onchange = e => { letterVersion = {n, i: +e.target.value, kind: letterKind}; openVacancy(n); };
  const versions = letterKind === "cover" ? d.letters : d.ref_letters;
  if ($("copyLetter")) $("copyLetter").onclick = () => navigator.clipboard.writeText((versions[letterVersion.i] || versions[0]).text)
    .then(() => toast("Скопировано"), fail);
  if ($("newLetter")) { $("newLetter").onclick = () => openLetterDialog(n, d.letters.length > 0); }
  if ($("newRefLetter")) { $("newRefLetter").onclick = () => openReferrerLetterDialog(n, d); }
  const kind = letterKind === "cover" ? "cover" : "referrer";
  bindTextEdit(n, kind, versions, versions[letterVersion.i] || versions[0], () => { letterVersion = {n, i: 0, kind: letterKind}; });
  if ($("sentBtn")) $("sentBtn").onclick = () => openSentDialog(r, n, kind, versions[letterVersion.i] || versions[0]);
}

// «Отправлено»: дата отправки этой версии письма; этап воронки сама не меняет — предлагает «Откликнулся»
function openSentDialog(r, n, kind, v) {
  const today = new Date().toLocaleDateString("sv-SE");          // 2026-10-28
  const save = async date => {
    const res = await api("/api/letter/sent", {profile: state.profile, n, kind, key: v.key, date}).catch(fail);
    if (!res) return;
    closeWizard(); await refreshRows(); await openVacancy(n);
    const stage = (r.funnel || {}).stage;
    if (date && kind === "cover" && !stage)
      return toast("Отмечено. Отметить этап «Откликнулся»?", {label: "Откликнулся", onClick: async () => {
        await api("/api/funnel/stage", {profile: state.profile, n, stage: "applied", date}).catch(fail);
        await refreshRows(); openVacancy(n); toast("Этап «Откликнулся» отмечен");
      }});
    toast(date ? "Отмечено: отправлено — копия во вкладке «Артефакты»" : "Отметка снята, копия из «Артефактов» — в Корзине");
  };
  dialog({cover: "Письмо отправлено", referrer: "Сообщение отправлено", resume: "Резюме отправлено"}[kind], `
    <p class="hint">Версия: ${versionLabel({...v, sent: ""}, true)}. Отметка попадёт в список версий и в «Историю» вакансии, а копия текста — во вкладку «Артефакты». Сама программа ничего не отправляет.</p>
    ${field("Когда отправили", `<input type="date" id="sentDate" value="${esc(v.sent || today)}" max="${today}">`)}`,
    [...(v.sent ? [{label: "Снять отметку", left: true, onClick: () => save("")}] : []),
     {label: "Отмена"}, {label: "Сохранить", primary: true, onClick: () => {
       if (!$("sentDate").value) return toast("Укажите дату");
       save($("sentDate").value);
     }}]);
}

// Кнопки над письмом и резюме — иконками; что делает кнопка — в подсказке
const TOOL_ICONS = {
  copy: '<rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  own: '<path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6"/><path d="M12 12v6M9 15h6"/>',
  ai: '<path d="M11 3l1.8 4.7 4.7 1.8-4.7 1.8L11 16l-1.8-4.7L4.5 9.5l4.7-1.8z"/><path d="M18.5 14l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>',
  sent: '<path d="M22 2 11 13"/><path d="M22 2 15 22l-4-9-9-4z"/>',
};
const ibtn = (id, icon, title, cls = "", text = "") => `<button type="button" id="${id}" class="icon tool ${cls}" title="${esc(title)}" aria-label="${esc(title)}"><svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${TOOL_ICONS[icon]}</svg>${text ? `<span>${esc(text)}</span>` : ""}</button>`;

// Правка письма или резюме под вакансию и своё письмо. Черновик живёт, пока его не сохранят или не отменят:
// переход на другую вакансию или вкладку, обновление окна и новая версия от модели его не затирают
const SOURCE_NAME = {edit: "правка", own: "своё"};
const versionLabel = (v, many) => `${v.sent ? `✉ отправлено ${ddmm(v.sent)} · ` : ""}${v.current ? "текущая · " : ""}${SOURCE_NAME[v.source] || "ИИ"}${
  many && v.template ? " · " + esc(v.template) : ""} · ${esc(v.when)}`;
// Версии письма или резюме — выпадающим списком, новые сверху; одна версия — списка нет
const versionPicker = (versions, cur, id, many) => versions.length < 2 ? "" : `<label class="versions">Версия
    <select id="${id}">${versions.map((v, i) => `<option value="${i}" ${i === cur ? "selected" : ""}>${versionLabel(v, many)}</option>`).join("")}</select>
    <span class="hint">всего ${versions.length}</span></label>`;
// «Проверьте: этого нет в резюме» — числа и названия не из резюме, «о себе» и вакансии (сервер, fact_check):
// списком над текстом и подсветкой в тексте. Своя правка — проверка пересчитывается при открытии
const factsNote = v => (v.unverified || []).length ? `<p class="cwarn facts">Проверьте: этого нет ни в резюме, ни в вакансии — ${
  v.unverified.map(x => `«${esc(x)}»`).join(", ")}. Если это неправда — поправьте текст; если правда, но не в резюме — добавьте в «Дополнительно о себе», и отметка пропадёт.</p>` : "";
// Что дописать после проверки — в [квадратных скобках] («[уточните: размер команды]»): красным, чтобы не пропустить.
// Только в тексте, не в разметке; ссылки Markdown md() уже превратил в <a>
const markAsk = html => html.split(/(<[^>]*>)/).map(part => part.startsWith("<") ? part
  : part.replace(/\[[^\[\]\n]{2,300}\]/g, '<span class="ask">$&</span>')).join("");
function markFacts(html, words) {
  if (!words || !words.length) return html;
  const alt = words.map(w => esc(w).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).sort((a, b) => b.length - a.length).join("|");
  const rx = new RegExp(`(?<![\\p{L}\\d])(${alt})(?![\\p{L}\\d])`, "gu");
  return html.split(/(<[^>]*>)/).map(part => part.startsWith("<") ? part : part.replace(rx, '<mark class="unver">$1</mark>')).join("");
}
const versionNote = v => v.current && !v.source ? "" : `${v.current ? "" : "прежняя версия · "}${SOURCE_NAME[v.source] || "ИИ"} от ${esc(v.when)} · `;
let draftCache = {};
const draftKey = () => `drafts:${state.profile}`;
function drafts() {
  try { draftCache[state.profile] = JSON.parse(localStorage.getItem(draftKey()) || "{}"); } catch (e) {}
  return draftCache[state.profile] || (draftCache[state.profile] = {});
}
const draftOf = (n, kind) => drafts()[`${n}:${kind}`];
function setDraft(n, kind, dr) {
  const all = drafts();
  if (dr) all[`${n}:${kind}`] = dr; else delete all[`${n}:${kind}`];
  try { localStorage.setItem(draftKey(), JSON.stringify(all)); } catch (e) {}
}
function textEditor(kind, dr, versions) {
  const newer = versions.length && versions[0].at !== dr.base;        // пока правили, модель написала новую версию
  const what = {cover: "письмо", referrer: "сообщение", resume: "текст"}[kind];
  return `<div class="texteditor">
    <p class="hint">${dr.source === "edit" ? `Правка версии от ${esc(dr.from)}` : `Своё ${what}`} — сохранится новой версией, прежние останутся в списке версий. Черновик не пропадёт, если перейти на другую вакансию.</p>
    ${newer ? `<p class="cwarn">Пока вы правили, появилась новая версия — она в списке версий выше. Ваш текст не тронут.</p>` : ""}
    <textarea id="textEdit" rows="16" placeholder="${kind === "resume" ? "Например, итоговый текст «Обо мне», который поставили в резюме на hh" : "Текст " + (kind === "cover" ? "письма" : "сообщения")}">${esc(dr.text)}</textarea>
    <p class="lettertools"><button class="primary" id="textSave">Сохранить</button> <button id="textCancel">Отмена</button></p></div>`;
}
function bindTextEdit(n, kind, versions, shown, toNewest) {
  const base = versions[0] ? versions[0].at : "";
  if ($("textEditBtn")) $("textEditBtn").onclick = () => { setDraft(n, kind, {source: "edit", text: shown.text, orig: shown.text, from: shown.when, base}); openVacancy(n); };
  document.querySelectorAll("#textOwnBtn").forEach(b => b.onclick = () => { setDraft(n, kind, {source: "own", text: "", orig: "", base}); openVacancy(n); });
  const ta = $("textEdit");
  if (!ta) return;
  ta.oninput = () => { const dr = draftOf(n, kind); if (dr) setDraft(n, kind, {...dr, text: ta.value}); };
  $("textCancel").onclick = () => {
    const dr = draftOf(n, kind) || {};
    if (ta.value.trim() !== (dr.orig || "").trim() && !confirm("Выбросить правку? Текст не сохранится.")) return;
    setDraft(n, kind, null); openVacancy(n);
  };
  $("textSave").onclick = async () => {
    const dr = draftOf(n, kind) || {source: "own"};
    if (!ta.value.trim()) return toast("Текст пустой — нечего сохранять");
    if (dr.source === "edit" && ta.value.trim() === (dr.orig || "").trim()) return toast("Текст не менялся — сохранять нечего");
    const ok = await api("/api/text/save", {profile: state.profile, n, kind, text: ta.value, source: dr.source}).catch(fail);
    if (!ok) return;
    setDraft(n, kind, null); toNewest(); toast("Сохранено новой версией"); openVacancy(n);
  };
}

// Сообщение референсеру: канал, цель и что ещё учесть — модель видит резюме, вакансию, разбор и заметку о человеке
function openReferrerLetterDialog(n, d) {
  const last = d.ref_letters[0] || {};
  let channel = last.channel || "telegram", goal = last.goal || "pass";
  try { channel = last.channel || localStorage.getItem("refChannel") || channel; } catch (e) {}
  dialog("Сообщение референсеру", `
    <p>Кому: <b>${esc(d.referrer)}</b></p>
    <div class="row2">
      ${field("Где пишете", `<select id="rlChannel">${REF_CHANNELS.map(([v, name]) => `<option value="${v}" ${v === channel ? "selected" : ""}>${name}</option>`).join("")}</select>`)}
      ${field("О чём просите", `<div class="checks stack">
        <label><input type="radio" name="rlGoal" value="pass" ${goal === "pass" ? "checked" : ""}> Передать резюме нанимающему руководителю или HR</label>
        <label><input type="radio" name="rlGoal" value="learn" ${goal === "learn" ? "checked" : ""}> Рассказать о роли и команде — стоит ли откликаться</label></div>`)}
    </div>
    ${field("Что ещё учесть (необязательно)", `<textarea id="rlExtra" rows="3" placeholder="например: вместе работали в Сбере в 2019; на «ты»; упомянуть, что уже откликнулся на hh"></textarea>`)}
    <p class="hint">Модель видит резюме, вакансию, разбор и то, что записано о человеке в контактах (заметка, статус)${state.cloud ? " — с облачной моделью это уходит в GigaChat (Сбер)" : ""}. Программа ничего не отправляет: скопируйте сообщение и отправьте сами.</p>`,
    [{label: "Отмена"}, {label: "Написать сообщение", primary: true, onClick: () => {
      const ch = $("rlChannel").value;
      try { localStorage.setItem("refChannel", ch); } catch (e) {}
      closeWizard(); detailTab = "letter"; letterKind = "referrer"; letterVersion = {n, i: 0, kind: "referrer"};
      run("referrer_letter", {n, channel: ch, goal: document.querySelector('#wbody input[name="rlGoal"]:checked').value,
                              extra: $("rlExtra").value.trim()});
    }}]);
}

// Письмо по кнопке: сначала образец — его можно поправить для этого письма (и сохранить для следующих)
// ИИ пишет письмо: выбор шаблона и правка его текста под эту вакансию
async function openLetterDialog(n, again) {
  const res = await api(`/api/letter/templates?profile=${encodeURIComponent(state.profile)}`).catch(fail);
  if (!res) return;
  const list = res.templates;
  let tpl = list.find(t => t.default) || list[0];
  dialog(again ? "Новая версия письма от ИИ" : "ИИ напишет письмо", `
    <p class="hint">ИИ берёт из шаблона стиль, длину и структуру, а факты — только из резюме и вакансии. Поправьте шаблон под эту вакансию, если хотите: короче, другой акцент, другое начало. ${again ? "Нынешнее письмо сохранится в версиях." : ""}</p>
    ${list.length > 1 ? field("Шаблон", `<select id="lTpl">${list.map(t => `<option value="${t.id}" ${t.id === tpl.id ? "selected" : ""}>${esc(t.name)}${t.default ? " — по умолчанию" : ""}</option>`).join("")}</select>`) : ""}
    ${field("Текст шаблона", `<textarea id="lExample" class="tall">${esc(tpl.text)}</textarea>`)}
    <div class="lrow"><label class="checks"><input type="checkbox" id="lSave"> <span id="lSaveText">Сохранить в шаблон «${esc(tpl.name)}» — для следующих писем</span></label>
      <button type="button" id="lReset" title="Вернуть текст шаблона">Вернуть шаблон</button>
      <button type="button" id="lTpls" title="Завести шаблоны для разных писем — до трёх">Шаблоны…</button></div>`,
    [{label: "Отмена"}, {label: "Написать письмо", primary: true, onClick: () => {
      const example = $("lExample").value.trim();
      if (!example) return toast("Шаблон пустой — вставьте текст или верните шаблон");
      const changed = example !== tpl.text.trim();
      closeWizard(); detailTab = "letter"; letterKind = "cover"; letterVersion = {n, i: 0, kind: "cover"};
      run("letter", {n, template: tpl.id, ...(changed ? {example, save_example: $("lSave").checked} : {})});
    }}]);
  if ($("lTpl")) $("lTpl").onchange = () => {
    tpl = list.find(t => t.id === +$("lTpl").value);
    $("lExample").value = tpl.text; $("lSaveText").textContent = `Сохранить в шаблон «${tpl.name}» — для следующих писем`;
  };
  $("lReset").onclick = () => { $("lExample").value = tpl.text; };
  $("lTpls").onclick = () => openTemplates(tpl.id);
}

$("btnUpdate").onclick = () => startSearch();
$("btnRescore").onclick = () => openRescoreAll();

// Пересчёт оценок: а) только устаревшие — после оценки поменялись резюме, критерии или «о себе»;
// б) все разобранные в выбранных разделах — например, после смены модели. В скобках — сколько вакансий
function openRescoreAll() {
  const raw = r => !r.analyzed || r.stage === "none";            // не разобраны: модель была выключена или Ollama не запущена
  const RA = {mode: state.rows.some(raw) ? "new" : state.rows.some(r => r.criteria_changed) ? "stale" : "all"};
  const fits = r => RA.mode === "new" ? raw(r) : r.analyzed && r.stage !== "none" && (RA.mode === "all" || r.criteria_changed);
  const count = st => state.rows.filter(r => r.status === st && fits(r)).length;
  dialog("Пересчитать оценки", field("Что пересчитать?",
    `<div class="checks stack">
      <label><input type="radio" name="ramode" value="new" ${RA.mode === "new" ? "checked" : ""}> Неразобранные — ещё без оценки: например, сохранены, пока модель не была запущена (${state.rows.filter(raw).length})</label>
      <label><input type="radio" name="ramode" value="stale" ${RA.mode === "stale" ? "checked" : ""}> Только устаревшие — после оценки поменялись резюме, критерии или «Дополнительно о себе»</label>
      <label><input type="radio" name="ramode" value="all" ${RA.mode === "all" ? "checked" : ""}> Все вакансии в выбранных разделах — например, после смены модели или если оценки кажутся странными</label></div>`)
    + field("В каких разделах?", '<div class="checks" id="raBoxes"></div>',
      "Каждая выбранная вакансия получит разбор по текущим данным. В скобках — сколько таких вакансий в разделе. Комментарии, статусы и флаги сохранятся.")
    + '<p class="hint" id="raEst"></p>', [{label: "Отмена"}, {label: "Пересчитать", primary: true, id: "raGo"}]);
  const picked = () => [...document.querySelectorAll("#wbody [data-ra]")].filter(c => c.checked).map(c => c.dataset.ra);
  const est = () => {
    const n = picked().reduce((sum, st) => sum + count(st), 0);
    const none = RA.mode === "stale" && !state.statuses.some(([v]) => count(v));
    $("raEst").innerHTML = none ? "Устаревших оценок нет — всё оценено по текущим резюме, критериям и «о себе». Чтобы пересчитать заново, выберите «Все вакансии в выбранных разделах»."
      : n ? `Всего: ${n} — ${state.cloud ? `примерно ${Math.max(1, Math.ceil(n / 6))} мин` : RA.mode === "new" && state.two_stage ? `примерно ${Math.max(1, Math.ceil(n * .4))} мин: сначала быстрая оценка, полный разбор — для «да» и «возможно»` : `примерно ${n} мин`}. Разбор можно остановить, уже сделанное сохранится.`
      : "В выбранных разделах таких вакансий нет.";
    $("raGo").disabled = !n;
  };
  const boxes = (keep = null) => {
    $("raBoxes").innerHTML = state.statuses.map(([v, label]) => {
      const on = keep ? keep.includes(v) : ["new", "yes"].includes(v);
      return `<label><input type="checkbox" data-ra="${v}" ${on && count(v) ? "checked" : ""} ${count(v) ? "" : "disabled"}> ${esc(label)} (${count(v)})</label>`;
    }).join("");
    document.querySelectorAll("#wbody [data-ra]").forEach(c => c.onchange = est);
    est();
  };
  document.querySelectorAll('#wbody [name="ramode"]').forEach(r => r.onchange = () => {
    const keep = picked(); RA.mode = r.value; boxes(keep.length ? keep : null);
  });
  boxes();
  $("raGo").onclick = () => {
    if (!picked().length) return toast("Ничего не выбрано");
    closeWizard();
    run("rescore_all", {statuses: picked(), mode: RA.mode});
  };
}

// Свои статусы (до пяти): вкладки перед «Архивом». Встроенные не переименовываются и не удаляются
const MAX_STATUSES = 5, STATUS_MAX = 20;
const STATUS_COLORS = [["blue", "синий"], ["violet", "фиолетовый"], ["orange", "оранжевый"], ["teal", "бирюзовый"], ["pink", "розовый"]];
// Значок статуса: у встроенных — по смыслу, у своих — ромб цвета, выбранного при добавлении
const SICON = {
  new: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.7 4H7.3a2 2 0 0 0-1.8 1.1z"/>',
  yes: '<path d="M7 10v12"/><path d="M15 5.9 14 10h5.8a2 2 0 0 1 1.9 2.6l-2.3 8a2 2 0 0 1-1.9 1.4H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.8a2 2 0 0 0 1.8-1.1L12 2a3.1 3.1 0 0 1 3 3.9z"/>',   // палец вверх: звёздочка — у любимых сайтов
  interview: '<path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 8.6 8.6 0 0 1-3.8-.9L3 21l1.9-5.2A8.4 8.4 0 1 1 21 11.5z"/>',
  no: '<rect x="2" y="3" width="20" height="5" rx="1"/><path d="M4 8v11a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8"/><path d="M10 12h4"/>',
};
const DIAMOND = '<rect x="5.6" y="5.6" width="12.8" height="12.8" rx="2.5" transform="rotate(45 12 12)" fill="currentColor" stroke="none"/>';
const svgIcon = (inner, cls) => `<svg class="sticon ${cls}" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${inner}</svg>`;
const statusIcon = v => SICON[v] ? svgIcon(SICON[v], "s-" + v) : svgIcon(DIAMOND, "c-" + (state.status_colors?.[v] || "blue"));
function openStatuses() {
  const custom = state.statuses.filter(([v]) => state.custom_statuses.includes(v));
  const count = v => state.rows.filter(r => r.status === v).length;
  const full = custom.length >= MAX_STATUSES;
  dialog("Свои статусы", `
    <p class="hint">Свой статус — отдельная вкладка в таблице, перед «Архивом». Например, «Отложено» — для вакансий, к которым стоит вернуться позже. Можно завести до ${MAX_STATUSES}. Четыре встроенных статуса не меняются.</p>
    ${custom.length ? field("Ваши статусы", `<div class="stlist">${custom.map(([v, name]) => `
      <div class="strow" data-row="${v}">
        <span class="storder"><button type="button" data-up title="Выше">↑</button><button type="button" data-down title="Ниже">↓</button></span>
        <span class="stpick"><button type="button" class="sticonbtn" data-stcolor="${v}" title="Сменить цвет значка">${statusIcon(v)}</button>
          <span class="stpalette" hidden>${STATUS_COLORS.map(([c, label]) =>
            `<button type="button" data-color="${c}" title="${label}" class="${c === state.status_colors[v] ? "on" : ""}">${svgIcon(DIAMOND, "c-" + c)}</button>`).join("")}</span></span>
        <input type="text" maxlength="${STATUS_MAX}" data-st="${v}" value="${esc(name)}">
        <span class="muted">${count(v)} ${plural(count(v), "вакансия", "вакансии", "вакансий")}</span>
        <button data-stdel="${v}">Удалить</button></div>`).join("")}</div>`,
      "Чтобы переименовать, сменить цвет значка (нажмите на него) или поменять порядок вкладок (стрелки), внесите изменения и нажмите «Сохранить». Вакансии останутся в своих статусах.") : ""}
    ${full ? `<p class="hint">Заведено ${MAX_STATUSES} своих статусов — больше нельзя. Чтобы добавить новый, удалите один из этих.</p>`
      : field("Новый статус", `<div class="strow"><input type="text" id="stNew" maxlength="${STATUS_MAX}" placeholder="Например, Отложено">
      <button id="stAdd">Добавить</button></div>`, `Название — до ${STATUS_MAX} знаков, не повторяет другие статусы. Цвет значка программа выберет из свободных — его можно поменять в списке выше.`)}`,
    [{label: "Закрыть"}, {label: "Сохранить", primary: true, id: "stSave"}]);
  const send = body => api("/api/statuses", {profile: state.profile, ...body});
  const colors = {...state.status_colors};                     // выбранные в окне цвета — применяются по «Сохранить»
  const list = document.querySelector("#wbody .stlist");
  const arrows = () => list?.querySelectorAll(".strow").forEach((row, i, all) => {
    row.querySelector("[data-up]").disabled = i === 0;
    row.querySelector("[data-down]").disabled = i === all.length - 1;
  });
  arrows();
  list?.addEventListener("click", e => {
    const row = e.target.closest(".strow");
    const pick = e.target.closest("[data-stcolor]"), swatch = e.target.closest("[data-color]");
    if (pick || swatch) {                                        // значок — открыть палитру, цвет в ней — выбрать
      const palette = row.querySelector(".stpalette"), key = row.dataset.row;
      list.querySelectorAll(".stpalette").forEach(p => { if (p !== palette) p.hidden = true; });
      if (swatch) {
        colors[key] = swatch.dataset.color;
        row.querySelector("[data-stcolor]").innerHTML = svgIcon(DIAMOND, "c-" + colors[key]);
        palette.querySelectorAll("[data-color]").forEach(b => b.classList.toggle("on", b === swatch));
      }
      palette.hidden = !!swatch || !palette.hidden;
      return;
    }
    if (e.target.closest("[data-up]") && row.previousElementSibling) row.after(row.previousElementSibling);
    else if (e.target.closest("[data-down]") && row.nextElementSibling) row.before(row.nextElementSibling);
    else return;
    arrows();
  });
  if ($("stAdd")) {
    $("stAdd").onclick = async () => {
      const name = $("stNew").value.trim();
      if (!name) return toast("Введите название статуса");
      try { await send({do: "add", name}); await statusesChanged(); toast(`Статус «${name}» добавлен`); openStatuses(); } catch (e) { toast(e.message); }
    };
    $("stNew").onkeydown = e => { if (e.key === "Enter") $("stAdd").click(); };
  }
  $("stSave").onclick = async () => {
    try {
      for (const el of document.querySelectorAll("#wbody [data-st]")) {
        const old = custom.find(([v]) => v === el.dataset.st)[1], name = el.value.trim();
        if (name !== old) await send({do: "rename", key: el.dataset.st, name});
      }
      const order = [...document.querySelectorAll("#wbody [data-row]")].map(r => r.dataset.row);
      if (order.join() !== custom.map(([v]) => v).join()) await send({do: "order", keys: order});
      for (const [v] of custom)
        if (colors[v] !== state.status_colors[v]) await send({do: "color", key: v, color: colors[v]});
      if ($("stNew")?.value.trim()) await send({do: "add", name: $("stNew").value.trim()});
      await statusesChanged();
      closeWizard(); toast("Статусы сохранены");
    } catch (e) { await statusesChanged(); toast(e.message); }
  };
  document.querySelectorAll("#wbody [data-stdel]").forEach(b => b.onclick = () => deleteStatus(b.dataset.stdel, count(b.dataset.stdel)));
}

// Статусы поменялись — таблица заново, а открытая карточка — тоже: в её списке «Статус» должны быть новые
async function statusesChanged() {
  await load(state.profile);
  if (selected && state.rows.some(r => r.n === selected)) await openVacancy(selected);
}

function deleteStatus(key, n) {
  const name = state.statuses.find(([v]) => v === key)[1];
  const del = async () => {
    try {
      const res = await api("/api/statuses", {profile: state.profile, do: "delete", key, move_to: $("stMove")?.value || "new"});
      await statusesChanged();
      toast(res.moved ? `Статус «${name}» удалён, вакансий перенесено: ${res.moved}` : `Статус «${name}» удалён`);
      openStatuses();
    } catch (e) { toast(e.message); }
  };
  dialog(`Удалить статус «${name}»?`, n
    ? field(`В нём ${n} ${plural(n, "вакансия", "вакансии", "вакансий")}. Куда ${n === 1 ? "её" : "их"} перенести?`,
        `<select id="stMove">${state.statuses.filter(([v]) => v !== key).map(([v, l]) => `<option value="${v}" ${v === "new" ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`,
        "Смена статуса попадёт в «Историю» каждой вакансии.")
    : `<p>Вакансий в нём нет. Вкладка исчезнет из таблицы.</p>`,
    [{label: "Отмена", onClick: openStatuses}, {label: "Удалить", primary: true, onClick: del}]);
}

// Первый поиск нового профиля: без калибровки оценки неточны — начать с 15 вакансий
const FIRST_LIMIT = 15;
const ICON = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="vertical-align:-2px"><path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7"/><path d="M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7"/></svg>`;   // значок «Добавить вакансию по ссылке» — в тексте подсказок
function startSearch() {
  if (!state.profiles.length) return openWizard();
  if (state.hh?.state === "ask" && !rssOn()) return askHh();   // прежний профиль: сначала решение о поиске на hh.ru
  const go = () => state.rows.length ? run("update") : openFirstSearch();
  if (!hhOn()) return rssOn() ? go() : openAdd();            // hh выключен, но есть ленты — без предупреждения про hh
  hhWarning(go);
}
// Перед каждым поиском на hh.ru — напоминание о риске и где поиск выключить
function hhWarning(go) {
  dialog("Поиск на hh.ru — на ваш риск", `
    <p class="cwarn"><b>Соглашение hh.ru запрещает</b> программы для поиска и сбора данных с сайта (пп. 5.1.6, 5.1.7, 8.6 и 8.8 <a href="${HH_AGREEMENT}" target="_blank" rel="noopener">соглашения</a>). Отвечает за нарушение пользователь: hh может заблокировать аккаунт или доступ к сайту — в том числе по одному подозрению.</p>
    <p>Программа ищет с паузами и не больше ${state.hh.limit} запросов в день; сегодня сделано ${state.hh.used}. Для поиска выключите VPN.</p>
    <p class="hint">Выключить поиск на hh.ru можно в <a href="#" id="hhToSettings">«Параметры → Настройки»</a>. Без него: ${HH_MANUAL[0].toLowerCase() + HH_MANUAL.slice(1)}</p>`, [
    {label: "Отмена"},
    {label: "Искать на hh.ru", primary: true, onClick: () => { closeWizard(); go(); }},
  ]);
  $("hhToSettings").onclick = e => { e.preventDefault(); openSettings(); };
}
function openFirstSearch() {
  const need = state.calibration_need, all = state.search_limit ? `${state.search_limit}` : "все";
  dialog("Первый поиск", `<p>Критерии нового профиля пока базовые. Пока их не откалибровали под вас, модель может ошибаться: пропускать подходящие вакансии или хвалить лишние.</p>
    <p>Для начала загрузите <b>не больше ${FIRST_LIMIT} вакансий</b> — разбор займёт ${state.cloud ? "пару минут" : state.two_stage === false ? "около 15 минут" : "минут 5–10"}, и их хватит для калибровки. Остальные найденные подтянутся при следующих поисках. Разбор можно остановить кнопкой «Остановить» — уже сделанное сохранится.</p>
    <p>Вакансии можно добавлять и вручную — кнопкой ${ICON} «Добавить вакансию по ссылке» рядом с поиском. Удобно, если на hh.ru вы уже видели и подходящие, и неподходящие.</p>
    <p>Когда разобранных вакансий станет ${need} и больше, запустите калибровку: «Параметры → Калибровка критериев». Свои оценки удобно ставить сразу в карточке вакансии — «Поставить свои оценки»: калибровка соберёт из них набор и подстроит под них критерии.</p>
    <p class="hint">Для калибровки нужны вакансии с разными решениями — и подходящие, и неподходящие: если все они «нет» (или все «да»), модели не на чем учиться отличать одно от другого.</p>`, [
    {label: "Отмена", left: true},
    {label: `Загрузить по настройкам (${all})`, title: "Сколько новых вакансий за поиск — в «Параметры → Настройки»",
     onClick: () => { closeWizard(); run("update"); }},
    {label: `Загрузить ${FIRST_LIMIT} вакансий`, primary: true, onClick: () => { closeWizard(); run("update", {limit: FIRST_LIMIT}); }},
  ]);
}

// Разобранных вакансий хватает для калибровки, а её ещё не было — предложить (один раз для профиля)
function suggestCalibration() {
  const done = state.rows.filter(r => r.analyzed && r.stage !== "none");
  const key = "calibHint:" + state.profile;
  if (state.calibrated || done.length < state.calibration_need || recall(key) || $("wiz").classList.contains("open")) return;
  remember(key, "1");
  const kinds = [["да", r => DECISION_RANK(r.decision) === 3], ["возможно", r => DECISION_RANK(r.decision) === 2], ["нет", r => DECISION_RANK(r.decision) === 1]]
    .map(([name, f]) => [name, done.filter(f).length]);
  const mixed = kinds.filter(([, n]) => n).length > 1;
  dialog("Пора откалибровать критерии", `<p>Разобрано ${done.length} ${plural(done.length, "вакансия", "вакансии", "вакансий")} — этого хватает для калибровки. Программа соберёт набор из ваших оценок (их можно поставить в карточке вакансии или прямо в калибровке), сравнит с оценками модели и подстроит критерии. После этого разбор станет точнее.</p>
    <p>Решения модели сейчас: ${kinds.map(([name, n]) => `«${name}» — ${n}`).join(", ")}.</p>
    <p class="hint">${mixed ? "Для калибровки оцените вакансии с разными решениями — и подходящие, и неподходящие."
      : `Пока все решения одинаковые, а для калибровки нужны разные — и подходящие, и неподходящие. Добавьте вручную несколько других вакансий кнопкой ${ICON} «Добавить вакансию по ссылке».`}</p>`, [
    {label: "Позже"},
    {label: "Начать калибровку", primary: true, onClick: () => { closeWizard(); openCalibration(); }},
  ]);
}
$("btnAdd").onclick = () => { $("addbox").classList.toggle("open"); $("main").classList.toggle("withadd"); $("links").focus(); };
function openAdd() { $("addbox").classList.add("open"); $("main").classList.add("withadd"); $("links").focus(); }
// Страница вакансии, сохранённая в браузере, или письмо hh (.eml): кнопкой или перетаскиванием файла в окно — без обращения к сайту
async function addPages(files) {
  const letters = [...files].filter(isMail);
  if (letters.length) openMails(letters);
  const pages = [...files].filter(f => /\.html?$/i.test(f.name) || f.type === "text/html");
  if (!pages.length) return letters.length ? null : toast("Нужен файл страницы .html (сохраните вакансию в браузере: ⌘S или Ctrl+S) или письмо hh .eml");
  if (!state.profile) return openWizard();
  for (const f of pages) run("add_page", {page: await f.text(), name: f.name});
}
$("btnAddPage").onclick = () => $("pageFile").click();
$("pageFile").onchange = e => { addPages(e.target.files); e.target.value = ""; };

// Письма hh с вакансиями: из ссылок в письме сервер берёт только номера — в ссылках ключ входа в аккаунт
const isMail = f => /\.eml$/i.test(f.name) || f.type === "message/rfc822";
async function openMails(files) {
  if (!state.profile) return openWizard();
  const res = await api("/api/mails", {profile: state.profile,
    files: await Promise.all(files.map(async f => ({name: f.name, data: await fileB64(f)})))}).catch(fail);
  if (!res) return;
  const url = id => `https://hh.ru/vacancy/${id}`;
  const fresh = res.items.filter(i => i.state === "new"), fit = fresh.filter(i => i.fits);
  const where = i => [i.salary, i.company, i.city].filter(Boolean).map(esc).join(" · ");
  const row = i => `<label class="mailrow${i.fits ? "" : " muted"}">${i.state === "new" && res.hh_auto ? `<input type="checkbox" data-ml="${i.id}"${i.fits ? " checked" : ""}>` : ""}
      <span><a href="${url(i.id)}" target="_blank" rel="noopener">${esc(i.title)}</a>
      ${i.state === "added" ? `<span class="chip">уже в списке${i.n ? `, № ${String(i.n).padStart(2, "0")}` : ""}</span>` : i.state === "seen" ? `<span class="chip">уже встречалась</span>` : ""}
      ${i.contacts ? `<span class="chip" title="Контакты в этой компании — раздел «Контакты»">контакты: ${i.contacts}</span>` : ""}
      <br><span class="muted">${where(i)}${i.fits ? "" : " · не проходит отбор по названию"}</span></span></label>`;
  const head = res.letters.map(l => `${esc(l.kind)}${l.date ? `, ${ddmm(l.date)}` : ""}: ${l.count}`).join("; ");
  const old = res.items.filter(i => i.state !== "new");
  dialog("Вакансии из писем hh", `
    ${head ? `<p class="hint">${head}. Новых — ${fresh.length}, из них по названию подходят ${fit.length}.</p>` : ""}
    ${res.problems.map(p => `<p class="cwarn">${esc(p)}</p>`).join("")}
    ${fresh.length ? `<div class="checks stack">${fresh.map(row).join("")}</div>` : res.items.length ? `<p>Новых вакансий в письмах нет.</p>` : ""}
    ${old.length ? `<details><summary>Уже встречались — ${old.length}</summary><div class="checks stack">${old.map(row).join("")}</div></details>` : ""}
    ${fresh.length && !res.hh_auto ? `<p class="cwarn">Поиск на hh.ru выключен — программа не скачает вакансии сама. Откройте вакансию по ссылке, сохраните страницу (⌘S или Ctrl+S) и перетащите файл в окно или вставьте текст.</p>` : ""}`,
    [{label: "Закрыть"}, ...(fresh.length && res.hh_auto ? [{label: "Добавить выбранные", primary: true, id: "mlAdd"}] : [])]);
  if (!$("mlAdd")) return;
  $("mlAdd").onclick = () => {
    const ids = [...document.querySelectorAll("#wbody [data-ml]")].filter(c => c.checked).map(c => c.dataset.ml);
    if (!ids.length) return toast("Ничего не выбрано");
    closeWizard();
    run("add", {links: ids.map(url).join("\n")});
  };
}
const withFiles = e => [...(e.dataTransfer?.types || [])].includes("Files");
document.addEventListener("dragover", e => { if (!withFiles(e)) return; e.preventDefault(); document.body.classList.add("dropping"); });
document.addEventListener("dragleave", e => { if (!e.relatedTarget) document.body.classList.remove("dropping"); });
document.addEventListener("drop", e => {
  document.body.classList.remove("dropping");
  if (!withFiles(e)) return;
  e.preventDefault();
  if ($("wiz").classList.contains("open")) return;       // в мастере файлы (резюме) принимают свои поля
  addPages(e.dataTransfer.files);
});
$("btnAddGo").onclick = () => { const links = $("links").value.trim(); if (!links) return $("links").focus(); run("add", {links}); $("links").value = ""; };
$("links").onkeydown = e => { if (e.key === "Enter") $("btnAddGo").click(); };
$("btnAddText").onclick = () => {                         // вакансия текстом — когда сайт не отдаёт страницу
  dialog("Вставить текст вакансии", `
    ${field("Текст вакансии", '<textarea id="vtText" data-a="vt_text" rows="12" placeholder="Скопируйте со страницы вакансии всё: название, компанию, зарплату, обязанности, требования, условия"></textarea>',
      "Название, компанию, зарплату и город программа найдёт в тексте сама (если доступна модель), иначе названием станет первая строка.", true)}
    ${field("Ссылка на вакансию", '<input type="text" id="vtLink" placeholder="https://… — необязательно">', "Чтобы потом открыть вакансию из карточки.")}`,
    [{label: "Отмена"}, {label: "Добавить и разобрать", primary: true, id: "vtGo"}]);
  $("vtText").focus();
  $("vtGo").onclick = () => {
    const text = $("vtText").value.trim();
    if (text.length < 100) return markInvalid("vt_text", "Вставьте текст вакансии целиком — название, обязанности, требования.");
    closeWizard();
    run("add_text", {text, link: $("vtLink").value.trim()});
  };
};
// Подсказка к «Историям STAR» — по наведению на «i»
const STAR_TIP = "STAR — способ рассказать о своём опыте на поведенческий вопрос («Расскажите о случае, когда…») коротко и по делу:\n"
  + "S — Situation, ситуация: где и когда;\nT — Task, задача: что нужно было сделать именно вам;\n"
  + "A — Action, действия: что вы сделали сами, от первого лица;\nR — Result, результат: чем закончилось, лучше с цифрами.\n"
  + "Так интервьюер видит не общие слова, а конкретный пример.";
// Истории STAR: строка «Подойдёт на вопросы» каждой истории — в рамке, отдельно от абзаца
function storiesHtml(text) {
  return md(text)
    // модель иногда пишет «Пойдёт» или «Подходит» вместо «Подойдёт» — рамка всё равно нужна
    .replace(/(?:<br>)?(<b>(?:Подойд[её]т|Пойд[её]т|Подходит) на вопрос(?:ы|ах)?:?<\/b>[\s\S]*?)(?=<br>|<\/p>)/gi, '</p><div class="fitq">$1</div><p>')
    .replace(/<p>(?:<br>)?<\/p>/g, "").replace(/<p><br>/g, "<p>");
}
// Подготовка к интервью — на две секции вкладки: истории STAR (с ответами о пробелах) и раздел
// «Мои вопросы работодателю» без заголовка — у секции он свой. Вопросов нет — questions ""
function interviewParts(text) {
  text = text || "";
  const m = text.match(/^#+\s*Мои вопросы работодателю[^\n]*\n([\s\S]*?)(?=^## |$(?![\s\S]))/m);
  if (!m) return {stories: text.trim(), questions: ""};
  return {stories: (text.slice(0, m.index) + text.slice(m.index + m[0].length)).trim(), questions: m[1].trim()};
}
// Тема: как в системе, светлая или тёмная — кнопка с меню в шапке, запоминается в браузере
const THEMES = {
  system: ["Как в системе", `<svg viewBox="0 0 24 24" width="{w}" height="{w}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 3a9 9 0 0 0 0 18z" fill="currentColor"/></svg>`],
  light: ["Светлая", `<svg viewBox="0 0 24 24" width="{w}" height="{w}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>`],
  dark: ["Тёмная", `<svg viewBox="0 0 24 24" width="{w}" height="{w}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>`],
};
function applyTheme(t) {
  if (!THEMES[t]) t = "system";
  if (t === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
  const [label, icon] = THEMES[t];
  $("btnTheme").innerHTML = icon.replaceAll("{w}", 18);
  $("btnTheme").title = `Тема: ${label.toLowerCase()}`;
  document.querySelectorAll("[data-theme-opt]").forEach(b => {
    const [name, ic] = THEMES[b.dataset.themeOpt];
    b.innerHTML = `${ic.replaceAll("{w}", 16)}<span style="flex:1">${name}</span><span class="tick">${b.dataset.themeOpt === t ? "✓" : ""}</span>`;
  });
}
applyTheme(recall("theme"));
$("btnTheme").onclick = e => {
  e.stopPropagation();
  closeMenus("themeMenu");
  const m = $("themeMenu");
  m.hidden = !m.hidden;
  if (!m.hidden) fitMenu(m);
};
document.querySelectorAll("[data-theme-opt]").forEach(b => b.onclick = () => {
  remember("theme", b.dataset.themeOpt);
  applyTheme(b.dataset.themeOpt);
  $("themeMenu").hidden = true;
});
$("profile").onchange = e => {
  if (e.target.value === "__new") { e.target.value = state.profile; return openWizard(); }
  selected = null; closePhoneDetail(); $("detail").innerHTML = '<div class="empty">Выберите вакансию в списке.</div>'; load(e.target.value).catch(fail); };
// Ширина левой панели — в процентах окна, от 25% до 85%
function setLeft(pct) {
  if (pct == null) { $("main").style.removeProperty("--left"); return; }
  $("main").style.setProperty("--left", Math.min(85, Math.max(25, pct)) + "%");
}
setLeft(+recall("left") || null);
$("splitter").onpointerdown = e => {
  e.preventDefault();
  const sp = $("splitter"), box = $("main").getBoundingClientRect();
  sp.setPointerCapture(e.pointerId);
  sp.classList.add("drag"); document.body.classList.add("resizing");
  sp.onpointermove = ev => setLeft((ev.clientX - box.left) / box.width * 100);
  sp.onpointerup = () => {
    sp.onpointermove = sp.onpointerup = null;
    sp.classList.remove("drag"); document.body.classList.remove("resizing");
    remember("left", parseFloat($("main").style.getPropertyValue("--left")) || "");
  };
};
$("splitter").ondblclick = () => { setLeft(null); remember("left", ""); };

$("heads").onclick = e => {
  const fb = e.target.closest("[data-filter]");
  if (fb) { e.stopPropagation(); return openFilter(fb.dataset.filter, fb.closest("th")); }
  const th = e.target.closest("[data-sort]");
  if (!th) return;
  const key = th.dataset.sort;
  if (sort.key === key) setSort(key, -sort.dir); else setSort(key);
};
$("tabs").onclick = e => {
  if (e.target.closest("#addStatus")) return openStatuses();
  const b = e.target.closest("[data-tab]"); if (b) { tab = b.dataset.tab; $("fmenu").hidden = true; render(); }
};
$("rows").onclick = e => {
  const ref = e.target.closest("[data-ref]");          // референсер в таблице — сразу карточка контакта
  if (ref) return openReferrer(state.rows.find(r => r.n === +ref.dataset.ref));
  const tr = e.target.closest("tr[data-n]");
  if (!tr) return;
  detailTab = "analysis";
  if (PHONE.matches) { openPhoneDetail(!document.body.classList.contains("phone-detail")); openVacancy(+tr.dataset.n); return; }
  openVacancy(+tr.dataset.n).then(() => { if (innerWidth <= 860) $("detail").scrollIntoView({behavior: "smooth"}); });
};


// Панель с полным списком критериев под заголовком «Критерии»: у каждого К — оценка модели для этой вакансии
function toggleCriteria(d) {
  const pop = $("critPop");
  if (pop.classList.contains("open")) return closeCriteria();
  const marks = Object.fromEntries((d.parsed?.criteria || []).map(c => [c.k, c.mark]));
  const rows = d.criteria.split("\n").map(line => {
    const m = line.match(/^К(\d+)\.\s*(.*)$/);
    if (m) return `<div class="crow"><span class="cmark" title="Оценка модели для этой вакансии">${marks[m[1]] || "·"}</span><div><b>К${m[1]}.</b> ${esc(m[2])}</div></div>`;
    if (/^\s+\S/.test(line)) return `<div class="ccont">${esc(line.trim())}</div>`;
    if (!line.trim()) return "";
    return `<div class="chead">${esc(line)}</div>`;
  }).join("");
  pop.innerHTML = `<div class="cpop">
    <div class="cpop-head"><b>Критерии профиля</b><button class="x" id="critClose" aria-label="Закрыть">×</button></div>
    <div class="cbody">${rows || '<p class="hint">Критерии не заданы.</p>'}</div>
    <div class="cpop-foot"><button id="critEdit">Изменить критерии</button></div></div>`;
  pop.classList.add("open");
  $("critClose").onclick = closeCriteria;
  $("critEdit").onclick = async () => { closeCriteria(); await openEditProfile(); wgo(4); wizRender(); };
  pop.onclick = e => e.stopPropagation();
}
function closeCriteria() { const pop = $("critPop"); if (pop) { pop.classList.remove("open"); pop.innerHTML = ""; } }
document.addEventListener("click", closeCriteria);
document.addEventListener("keydown", e => { if (e.key === "Escape") closeCriteria(); });


async function start() {
  let mine = null;
  try { mine = sessionStorage.getItem("profile"); } catch (e) {}
  await load(mine || recall("profile")).catch(() => load());     // у вкладки — свой профиль, новая — с последнего выбранного
  if (!state.profiles.length) openWizard();     // первый запуск: профилей ещё нет — сразу мастер
  if (recall("tasksOpen") && state.tasks.length) setPanel(true);   // панель задач — как оставили
  const n = +(location.hash.match(/^#(\d+)$/) || [])[1];
  if (n && goToVacancy(n)) openPhoneDetail(false);
  if (!REMOTE) checkUpdates();
  checkWeekly();
}

// Есть новая версия: плашка со ссылкой на скачивание; «Скрыть» — до следующей версии
async function checkUpdates() {
  const u = await api("/api/updates").catch(() => null);
  if (u?.newer && recall("updHidden") !== u.latest.version) showUpdate(u);
}

function showUpdate(u) {
  $("updBar").innerHTML = `<b>Есть версия ${esc(u.latest.version)}</b> <span class="muted">(у вас ${esc(u.current)})</span>
    ${u.latest.notes ? `<details><summary>Что нового</summary><div class="small">${esc(u.latest.notes).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/\n/g, "<br>")}</div></details>` : ""}
    <a href="${esc(u.latest.url)}" target="_blank" rel="noopener">Скачать</a>
    ${u.mac_install ? `<button type="button" class="small" id="updCmd" title="Выйдите из программы и вставьте команду в Терминал: она скачает и поставит новую версию без предупреждения macOS">Скопировать команду для Терминала</button>` : ""}
    <button type="button" class="small" id="updHide" title="Не показывать до следующей версии">Скрыть</button>`;
  $("updBar").hidden = false;
  if ($("updCmd")) $("updCmd").onclick = () => navigator.clipboard.writeText(u.mac_install)
    .then(() => toast("Команда скопирована. Выйдите из программы («Параметры → Выйти из программы») и вставьте её в Терминал"), fail);
  $("updHide").onclick = () => { remember("updHidden", u.latest.version); $("updBar").hidden = true; };
}

// Кнопка «Проверить обновления»: проверка сейчас, ответ — в out; новая версия — и плашка сверху
async function checkUpdatesNow(btn, out) {
  btn.disabled = true;
  out.textContent = "Проверяю…";
  try {
    const u = await api("/api/updates", {check: true});
    if (u.problem) out.textContent = u.problem;
    else if (u.newer) {
      out.innerHTML = `Вышла версия ${esc(u.latest.version)} — <a href="${esc(u.latest.url)}" target="_blank" rel="noopener">скачать</a>; что нового — в плашке сверху.`;
      showUpdate(u);
    } else out.textContent = `Установлена последняя версия ${u.current}.`;
  } catch (e) { out.textContent = e.message; }
  btn.disabled = false;
}
