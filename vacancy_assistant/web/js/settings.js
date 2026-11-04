// Меню «Параметры», настройки, доступ из домашней сети.
// Обычные скрипты (не модули): подключаются по порядку в index.html и видят функции друг друга.

// ---------- Параметры: меню, настройки ----------
$("btnParams").onclick = e => {
  e.stopPropagation();
  closeMenus("paramsMenu");
  const m = $("paramsMenu");
  m.hidden = !m.hidden;
  if (!m.hidden) { $("mProfileName").textContent = `Профиль · ${state.name}`; fitMenu(m); }
};
// Справочники и аналитика: статистика, зарплаты, резюме против рынка, компании, контакты, где искать
$("btnInfo").onclick = e => {
  e.stopPropagation();
  closeMenus("infoMenu");
  const m = $("infoMenu");
  m.hidden = !m.hidden;
  if (!m.hidden) fitMenu(m);
};
document.addEventListener("keydown", e => { if (e.key === "Escape") closeMenus(); });
document.addEventListener("click", e => {
  closeMenus("colsMenu");
  if (!e.target.closest("#fmenu")) $("fmenu").hidden = true;        // окошко фильтра колонки — щелчок мимо закрывает
});
$("mEdit").onclick = () => { $("paramsMenu").hidden = true; openEditProfile(); };
if (REMOTE) $("mQuit").hidden = true;    // выключить программу можно только на основном компьютере
$("mQuit").onclick = async () => {
  $("paramsMenu").hidden = true;
  const busy = (state.tasks || []).some(isActive) ? "Идут задачи — они остановятся (уже сделанное сохранится). " : "";
  if (!confirm(busy + "Выйти из программы? Окно перестанет работать; снова открыть — запустить программу.")) return;
  await api("/api/quit", {}).catch(() => null);
  document.body.innerHTML = '<div class="empty" style="padding:40px">Программа закрыта. Это окно можно закрыть. Чтобы снова открыть — запустите «Помощник по вакансиям».</div>';
};
// Сразу на нужный шаг редактирования профиля
async function openEditStep(step) { await openEditProfile(); if (W.mode === "edit") { wgo(step); wizRender(); } }
$("mResume").onclick = () => { $("paramsMenu").hidden = true; openEditStep(2); };
$("mCrit").onclick = () => { $("paramsMenu").hidden = true; openEditStep(4); };
$("mLetter").onclick = () => { $("paramsMenu").hidden = true; openTemplates(); };
$("mCalib").onclick = () => { $("paramsMenu").hidden = true; openCalibration(); };
$("mSettings").onclick = () => { $("paramsMenu").hidden = true; openSettings(); };
if (REMOTE) $("mBackup").hidden = true;     // копии лежат на основном компьютере — там и работа с ними
$("mBackup").onclick = () => { $("paramsMenu").hidden = true; openBackup(); };
$("mHelp").onclick = () => { $("paramsMenu").hidden = true; window.open("/help/", "_blank", "noopener"); };   // README — новой вкладкой
$("mAbout").onclick = () => { $("paramsMenu").hidden = true; openAbout(); };

function openAbout() {
  dialog("О программе", `<div class="about">
      <img src="icon.svg" alt="" width="64" height="64">
      <div><h3>Помощник по вакансиям</h3><p class="hint">Версия ${esc(state.version)} · модель ${esc(state.model)} ·
        <a href="/help/docs/${encodeURIComponent("Что нового.md")}" target="_blank" rel="noopener">что нового</a></p></div></div>
    <p>Помогает искать работу и не тратить время на неподходящие вакансии — с hh.ru и с любых других сайтов:</p>
    <ul class="aboutlist">
      <li><b>Собирает вакансии</b>: по ссылке с любого сайта, из страницы, сохранённой в браузере, или из вставленного текста.
        ${state.hh?.state === "on" ? "Поиск на hh.ru по запросам профиля включён: программа ищет как браузер и сразу отсеивает лишнее по названию, в ваш аккаунт не входит и не откликается."
          : "Поиск на hh.ru программой выключен (по умолчанию: он нарушает соглашение hh) — включается в «Параметры → Настройки»."}</li>
      ${state.no_model
        ? `<li><b>Работает без модели</b>: вакансии сохраняются без разбора, этапы, контакты и статистика доступны; модель можно подключить в «Редактировать профиль».</li>`
        : `<li><b>Разбирает каждую</b> по вашему резюме и критериям: что подходит, чего не хватает, «Могу», «Хочу», оценка и решение — откликаться или нет.</li>
      <li><b>Подстраивается под вас</b>: калибровка сравнивает оценки модели с вашими и правит критерии, а если не согласны с оценкой одной вакансии — критерии можно поправить прямо из её карточки.</li>
      <li><b>Помогает откликнуться</b>: сопроводительное письмо в вашем стиле, только с фактами из резюме; что включить в резюме под вакансию; личное сообщение знакомому в компании.</li>
      <li><b>Готовит к интервью</b>: истории STAR из резюме и вопросы работодателю именно по этой вакансии.</li>`}
      <li><b>Ведёт поиск</b>: статусы, флаги, комментарии, этапы отклика с историей, контакты и референсеры, отчётность компании в ФНС, статистика и зарплаты по вакансиям.</li>
    </ul>
    <p class="hint">${state.no_model ? "Модель не используется: резюме и вакансии никуда не отправляются."
      : state.cloud
      ? "Сейчас вакансии оценивает облачная модель GigaChat (Сбер): резюме, критерии и вакансии уходят в Сбер. Вернуть локальную модель — «Параметры → Настройки → Модель»."
      : "Модель работает на этом компьютере (Gemma через Ollama): резюме и вакансии никуда не отправляются. По желанию можно подключить облачную модель GigaChat."}
      Все данные — в обычных файлах в папке профиля. Откликаетесь вы сами: программа ничего не отправляет работодателям.</p>
    ${state.contact ? `<p class="aboutmail"><b>Связаться с автором</b> — ошибка, вопрос или идея:
      <a href="mailto:${esc(state.contact)}?subject=${encodeURIComponent("Помощник по вакансиям")}&body=${encodeURIComponent(`\n\n—\nВерсия ${state.version}`)}">${esc(state.contact)}</a>
      <button type="button" id="aboutCopy" class="small" title="Если почтовая программа не открылась">Скопировать адрес</button></p>` : ""}
    <p class="hint">Свободная программа: лицензия <a href="https://www.gnu.org/licenses/gpl-3.0.html" target="_blank" rel="noopener">GNU GPL 3.0</a> —
      можно пользоваться, изменять и распространять, в том числе изменённой, но тоже открыто и под этой лицензией.
      ${state.source ? `<a href="${esc(state.source)}" target="_blank" rel="noopener">Исходный код</a>.` : ""}</p>
    ${REMOTE ? "" : `<p class="aboutupd"><button type="button" id="aboutUpd" class="small">Проверить обновления</button> <span id="aboutUpdOut" class="hint"></span></p>`}`,
    [{label: "Помощь", onClick: () => window.open("/help/", "_blank", "noopener")}, {label: "Закрыть", primary: true}]);
  if ($("aboutUpd")) $("aboutUpd").onclick = () => checkUpdatesNow($("aboutUpd"), $("aboutUpdOut"));
  if ($("aboutCopy")) $("aboutCopy").onclick = () => navigator.clipboard.writeText(state.contact).then(() => toast("Адрес скопирован"), fail);
}

// Какая модель разбирает страницы вакансий: та же, что оценивает вакансии (выбор «Модель» выше)
const llmPagesModel = cloud => cloud
  ? "Разбирает <b>облачная модель GigaChat</b> — та же, что оценивает вакансии: текст страницы отправляется в Сбер."
  : "Разбирает <b>локальная модель Gemma</b> — та же, что оценивает вакансии: текст страницы не покидает этот компьютер.";

function openSettings() {
  const hh = state.hh || {};
  dialog("Настройки", `
    ${field("Поиск на hh.ru", hhAutoBlock(hh.state === "on", hh.state === "on")
      + (hh.state === "on" ? `<p class="hint">Включён${hh.consent ? ` с ${ddmm(hh.consent)}.${hh.consent.slice(0, 4)}` : ""}. Запросов к hh.ru сегодня: ${hh.used} из ${hh.limit}.</p>`
         : hh.state === "ask" ? `<p class="cwarn">Решение ещё не принято — пока программа на hh.ru не ходит.</p>` : ""))}
    <div class="row2">
      ${field("Искать вакансии за последние, дней", `<input type="number" id="sDays" min="1" max="30" value="${state.search_days}" style="width:90px">`, "От 1 до 30. По умолчанию 7.")}
      ${field("Новых вакансий за один поиск", `<input type="number" id="sLimit" min="1" value="${state.search_limit ?? ""}" placeholder="все" style="width:90px">`, "По умолчанию 50. Пусто — все за период; остальные возьмутся при следующем поиске.")}
    </div>
    <p class="cwarn" id="sWarn" hidden></p>
    ${state.hh?.state === "on" ? field("Отсеянные по названию", `<button id="sRecheck">Перепроверить отсеянные…</button>`,
      "Вакансии с hh.ru, которые поиск за последние 14 дней отсеял по названию, — по нынешним правилам отбора. Подходящие можно добавить.") : ""}
    ${field("Ленты вакансий (RSS)", `<div class="checks stack">
        <label><input type="checkbox" id="sRssHabr" ${state.rss?.includes("habr") ? "checked" : ""}> Хабр Карьера — по поисковым запросам профиля</label>
        <label><input type="checkbox" id="sRssGeek" ${state.rss?.includes("geekjob") ? "checked" : ""}> GeekJob — последние 100 вакансий, отбор по названию</label></div>`,
      "Для ИТ. Сайты публикуют новые вакансии RSS-лентами — это их официальный способ подписки. Программа читает ленты при «Найти новые вакансии», не чаще раза в час, отбирает по названию и скачивает подходящие со страницы вакансии. Работает и при выключенном поиске на hh.ru.")}
    <div id="sCloud"></div>
    ${field("Как оценивать вакансии — для локальной модели", `<p class="cwarn" id="sStageCloud" hidden>С облачной моделью GigaChat каждая вакансия всегда получает полный разбор: он занимает секунды. Выбор ниже действует только для локальной модели.</p><div class="checks stack">
        <label><input type="radio" name="stage" value="2" ${state.two_stage_setting ? "checked" : ""}> <b>В две ступени</b> — быстрее (по умолчанию)</label>
        <label><input type="radio" name="stage" value="1" ${state.two_stage_setting ? "" : "checked"}> <b>В одну ступень</b> — точнее, но дольше</label></div>
      <p class="hint stagehint"><b>Две ступени:</b> сначала каждая вакансия получает быструю оценку — около 15 секунд: отметки по критериям, «Могу», «Хочу», общая оценка и решение. Полный разбор — около минуты: требования, сильные стороны, пробелы, пояснение к каждому критерию — делается только для «да» и «возможно», для остальных — кнопкой «Разобрать заново» в карточке. В 3–4 раза быстрее, но быстрая оценка ставит отметки без рассуждений и на пограничных вакансиях ошибается чаще: может отсеять подходящую.<br>
       <b>Одна ступень:</b> каждая вакансия сразу получает полный разбор. Модель сначала объясняет каждый критерий и только потом ставит оценку — решения точнее, а причина «нет» всегда видна. Зато около минуты на каждую вакансию: 50 вакансий — почти час.<br>
       Калибровка проверяет критерии тем же способом, что выбран здесь. Уже оценённые вакансии сами не переоцениваются.</p>`)}
    ${field("«Хочу» по вашим откликам", `<div class="checks"><label><input type="checkbox" id="sWantSimilar" ${state.want_similar ? "checked" : ""}> Поднимать «Хочу» у вакансий, похожих на ваши отклики</label></div>`,
      "Программа сравнивает каждую вакансию с последними 10 откликами за 90 дней (нужно хотя бы 3): та же роль и похожий текст — «Хочу» +1, похожа на три отклика и больше — +2. Без модели; «Хочу» модели в разборе не меняется, надбавка видна в карточке.")}
    <div id="sLlmBlock" ${state.no_model ? "hidden" : ""}>${field("Вакансии с других сайтов", `<div class="checks"><label><input type="checkbox" id="sLlmPages" ${state.llm_pages ? "checked" : ""}> Разрешаю разбирать страницы вакансий моделью</label></div>
      <p class="hint">Касается вакансий, добавленных по ссылке не с hh.ru или вставленным текстом. Модель находит на странице саму вакансию — без меню, кнопок и чужих вакансий — и берёт её текст дословно, а также находит компанию, зарплату и город.</p>
      <p class="hint" id="sLlmModel">${llmPagesModel(state.cloud)}</p>
      <p class="hint">Без разрешения страница сохраняется целиком, как есть. Уже добавленные вакансии не меняются.</p>`)}</div>
    <div id="sNet"></div>
    <div id="sData"></div>
    <div id="sUpd"></div>
    ${field("Свои статусы", `<button id="sStatuses">Свои статусы…</button>`,
      `Свои вкладки в таблице перед «Архивом», до пяти${state.custom_statuses?.length ? ` (сейчас: ${state.statuses.filter(([v]) => state.custom_statuses.includes(v)).map(([, n]) => `«${esc(n)}»`).join(", ")})` : ""}. То же — кнопкой «+» справа от вкладок. Изменения в окне выше, если они есть, сначала сохраните.`)}`, [{label: "Отмена"}, {label: "Сохранить", primary: true, id: "sSave"}]);
  $("sStatuses").onclick = openStatuses;
  if ($("sRecheck")) $("sRecheck").onclick = () => openRecheck();
  const warn = () => {        // большие значения — долгий поиск и разбор
    const days = +$("sDays").value, limit = $("sLimit").value.trim();
    const one = document.querySelector('#wbody input[name="stage"]:checked').value === "1";
    const big = days > 14 || !limit || +limit > (one ? 50 : 100);
    $("sWarn").hidden = !big;
    $("sWarn").textContent = !limit
      ? `Без ограничения за один поиск может прийти сотня вакансий и больше, и поиск с разбором займёт несколько часов. Разбор можно остановить — уже сделанное сохранится.`
      : `При таких значениях поиск и разбор займут заметное время: до ${limit} вакансий — около ${Math.round(+limit * (one ? 1 : 0.4) / 60 * 10) / 10} ч работы модели (${one ? "около минуты на вакансию" : "15 секунд на вакансию, минута на полный разбор подходящих"}).`;
  };
  bindHhAuto();
  $("sDays").oninput = $("sLimit").oninput = warn;
  document.querySelectorAll('#wbody input[name="stage"]').forEach(r => r.onchange = warn);
  warn();
  let cloudCfg = null;
  if (!REMOTE) api(`/api/cloud?profile=${encodeURIComponent(state.profile)}`).then(cl => {           // модель: локальная или облачная — только на этом компьютере
    cloudCfg = cl;
    $("sCloud").innerHTML = field(`Модель профиля «${esc(state.name)}»`, `<div class="checks stack">
        <label><input type="radio" name="mdl" value="local" ${cl.enabled || state.no_model ? "" : "checked"}> <b>Локальная</b> — ${esc(cl.local_model)} на этом компьютере, данные никуда не уходят</label>
        <label><input type="radio" name="mdl" value="cloud" ${cl.enabled ? "checked" : ""}> <b>Облачная</b> — GigaChat (Сбер): для компьютеров, где локальная модель не тянет</label>
        <label><input type="radio" name="mdl" value="none" ${state.no_model ? "checked" : ""}> <b>Без модели</b> — только трекер откликов: вакансии сохраняются без разбора, письма и подготовку к интервью не пишет</label></div>
      <div id="sCloudForm"></div>`, "У каждого профиля своя модель: решает сам человек, ведь с облачной моделью уходят его резюме и вакансии. Ключ GigaChat один на этот компьютер — его не нужно вводить для каждого профиля.");
    const show = () => {
      const pick = document.querySelector('#wbody input[name="mdl"]:checked').value, on = pick === "cloud", none = pick === "none";
      $("sCloudForm").innerHTML = on ? cloudFields(cl) + `<div id="sMask"></div>` : "";
      if (on) { bindCloudCheck(); loadMask(); }
      $("sStageCloud").hidden = !on;                    // ступени — только для локальной модели
      $("sLlmModel").innerHTML = llmPagesModel(on);
      document.querySelectorAll('#wbody input[name="stage"]').forEach(r => r.disabled = on || none);
      $("sLlmBlock").hidden = none;                     // без модели разбирать страницы некому — блок не показываем
    };
    document.querySelectorAll('#wbody input[name="mdl"]').forEach(r => r.onchange = show);
    show();
  }).catch(() => {});
  let maskCfg = null;
  // Что скрывается от GigaChat: метки вместо личных данных; прошлые работодатели — по выключателю
  const loadMask = async firms => {
    const m = await api(`/api/mask?profile=${encodeURIComponent(state.profile)}${firms == null ? "" : `&companies=${firms ? 1 : 0}`}`).catch(() => null);
    if (!m || !$("sMask")) return;
    if (firms == null) maskCfg = m;
    const checked = firms == null ? m.companies : firms;
    $("sMask").innerHTML = field("Что скрывается от GigaChat", `
      <p class="hint">Перед отправкой программа заменяет метками, а в ответе модели — обратно: ваше имя и фамилию («[Кандидат]»),
        имена знакомых из контактов (${m.contacts}), ссылки на личные профили (LinkedIn, Telegram, GitHub…), телефоны, почту и адрес из резюме.
        Компания вакансии не скрывается — без неё не написать письмо и не оценить вакансию.</p>
      <div class="checks"><label><input type="checkbox" id="sMaskFirms" ${checked ? "checked" : ""} ${m.past.length ? "" : "disabled"}> Скрывать и прошлых работодателей из резюме${m.past.length ? ` — ${m.past.map(esc).join(", ")}` : " — в резюме их не нашлось"}</label></div>
      <p class="hint">Тогда модель не узнает отрасль и размер этих компаний — оценка опыта может стать менее точной.</p>
      <details class="maskview"><summary>Как модель видит начало резюме</summary><pre>${esc(m.resume) || "Резюме пока нет."}</pre></details>`);
    $("sMaskFirms").onchange = () => { const open = $("sMask").querySelector("details").open; loadMask($("sMaskFirms").checked).then(() => { $("sMask").querySelector("details").open = open; }); };
  };
  let net = null;
  if (!REMOTE) api("/api/network").then(n => {      // доступ из домашней сети — настраивается только здесь
    net = n;
    $("sNet").innerHTML = field("Доступ из домашней сети",
      `<div class="checks"><label><input type="checkbox" id="sNetOn" ${n.enabled ? "checked" : ""}> Открывать окно с других устройств домашней сети (ноутбук, планшет, телефон)</label></div>
       <input type="password" id="sNetPw" autocomplete="new-password" placeholder="${n.has_password ? "пароль задан — введите новый, чтобы сменить" : "пароль для входа, не короче 6 символов"}" style="margin-top:8px; width:100%; max-width:360px; box-sizing:border-box">
       <div class="hint" id="sNetUrls"></div>`,
      "Только для домашней сети: соединение без шифрования, поэтому в кафе, офисе или гостинице не включайте. Mac может спросить, разрешить ли программе входящие подключения, — разрешите. Пока программа на этом компьютере работает, окно открывается и на других устройствах.");
    const urls = () => {
      const on = $("sNetOn").checked;
      $("sNetUrls").innerHTML = !on ? "" : n.running
        ? "Открывайте на другом устройстве:" + urlList(n.urls)
        : (n.error ? `<span class="err">${esc(n.error)}</span>` : "Адрес для других устройств появится после сохранения.");
    };
    $("sNetOn").onchange = urls;
    urls();
  }).catch(() => {});
  if (!REMOTE) api("/api/datadir").then(d => {      // папка с данными — только на этом компьютере
    $("sData").innerHTML = field("Папка с данными", `<div class="dpath"><code>${esc(d.home)}</code> <button type="button" id="sDataDir">Сменить папку…</button></div>`,
      "Здесь лежат профили (в папке «профили»), резервные копии и журнал. Можно перейти на другую папку — например, на облачном диске или с профилями с другого компьютера.");
    $("sDataDir").onclick = () => openDataDir();
  }).catch(() => {});
  let upd = null;
  if (!REMOTE) api("/api/updates").then(u => {       // проверка обновлений — общая для компьютера
    upd = u;
    $("sUpd").innerHTML = field("Обновления", `<div class="checks"><label><input type="checkbox" id="sUpdOn" ${u.enabled ? "checked" : ""}> Проверять обновления</label></div>
      <p class="aboutupd"><button type="button" id="sUpdNow" class="small">Проверить сейчас</button> <span id="sUpdOut" class="hint"></span></p>`,
      `Раз в день программа спрашивает у GitHub, есть ли новая версия, — простой запрос без данных о вас. Если есть, сверху появится ссылка на скачивание; сама программа ничего не скачивает. Сейчас: версия ${esc(u.current)}${u.newer ? `, доступна ${esc(u.latest.version)}` : u.enabled && u.latest ? ", это последняя" : ""}.`);
    $("sUpdNow").onclick = () => checkUpdatesNow($("sUpdNow"), $("sUpdOut"));
  }).catch(() => {});
  $("sSave").onclick = async () => {
    const days = +$("sDays").value, limit = $("sLimit").value.trim();
    if (!(days >= 1 && days <= 30)) return toast("Период поиска — от 1 до 30 дней");
    if (limit && !(+limit >= 1)) return toast("Сколько вакансий за поиск — число больше нуля или пусто");
    const hhWant = $("hhOn").checked;
    if (hhWant && !$("hhRisk").checked) return fail(new Error("Чтобы включить поиск на hh.ru, отметьте, что понимаете риск. Или выключите поиск."));
    try {
      if (hhWant !== (hh.state === "on") || hh.state === "ask")
        await api("/api/profile/settings", {profile: state.profile, hh_auto: hhWant, hh_risk: hhWant});
      const twoStage = document.querySelector('#wbody input[name="stage"]:checked').value === "2";
      const stageChanged = twoStage !== state.two_stage_setting;
      if (stageChanged) await api("/api/profile/settings", {profile: state.profile, two_stage: twoStage});
      const feeds = {habr: $("sRssHabr").checked, geekjob: $("sRssGeek").checked};
      if (feeds.habr !== !!state.rss?.includes("habr") || feeds.geekjob !== !!state.rss?.includes("geekjob"))
        await api("/api/profile/settings", {profile: state.profile, rss: feeds});
      if ($("sWantSimilar").checked !== state.want_similar)
        await api("/api/profile/settings", {profile: state.profile, want_similar: $("sWantSimilar").checked});
      if ($("sLlmPages").checked !== state.llm_pages)
        await api("/api/profile/settings", {profile: state.profile, llm_pages: $("sLlmPages").checked});
      if (days !== state.search_days || (limit ? +limit : null) !== state.search_limit)
        await api("/api/profile/settings", {profile: state.profile, search_days: days, search_limit: limit ? +limit : null});
      let modelOn = false;                                   // включили модель после «Без модели» — предложим разобрать
      if (cloudCfg) {
        const pick = document.querySelector('#wbody input[name="mdl"]:checked').value, wasNone = state.no_model;
        if (pick === "cloud") {
          if (!$("clConsent").checked) return fail(new Error("Отметьте согласие на отправку данных в GigaChat — без него облачную модель не включить."));
          await api("/api/cloud", {...cloudPayload(true), profile: state.profile});   // сервер сначала проверит, что GigaChat отвечает
          if (maskCfg && $("sMaskFirms") && $("sMaskFirms").checked !== maskCfg.companies)
            await api("/api/profile/settings", {profile: state.profile, hide_companies: $("sMaskFirms").checked});
        } else if (cloudCfg.enabled) await api("/api/cloud", {enabled: false, profile: state.profile});
        if (pick === "none" && !wasNone) await api("/api/profile/settings", {profile: state.profile, no_model: true});
        if (pick === "local" && wasNone) await api("/api/profile/settings", {profile: state.profile, no_model: false});
        modelOn = wasNone && pick !== "none";
      }
      let netOn = null;
      if (net && ($("sNetOn").checked !== net.enabled || $("sNetPw").value)) {
        const n = await api("/api/network", {enabled: $("sNetOn").checked, password: $("sNetPw").value});
        if (n.error) return fail(new Error(n.error));
        if (n.enabled && !net.running) netOn = n;           // только что включили — показать адрес
      }
      if (upd && $("sUpdOn").checked !== upd.enabled) {
        await api("/api/updates", {enabled: $("sUpdOn").checked});
        if (!$("sUpdOn").checked) $("updBar").hidden = true; else checkUpdates();
      }
      toast("Настройки сохранены");
      await load(state.profile);
      if (modelOn && state.unanalyzed) openAnalyzeSaved();
      else if (stageChanged) openStageChanged(twoStage);
      else if (netOn) openNetworkInfo(netOn); else closeWizard();
    } catch (e) { fail(e); }
  };
}

// Модель включили после «Без модели»: разобрать вакансии, сохранённые без разбора
function openAnalyzeSaved() {
  const n = state.unanalyzed;
  dialog("Модель включена", `<p>Без разбора сохранено ${n} ${plural(n, "вакансия", "вакансии", "вакансий")}. Разобрать ${n === 1 ? "её" : "их"} сейчас?</p>
    <p class="hint">${state.cloud ? "Облачная модель — несколько секунд на вакансию." : state.two_stage ? "Около 15 секунд на вакансию, для подходящих — ещё минута на полный разбор." : "Около минуты на вакансию."} Этапы, комментарии и статусы сохранятся. Можно и позже — по одной, кнопкой «Разобрать заново» в карточке.</p>`,
    [{label: "Не сейчас"}, {label: "Разобрать", primary: true, onClick: () => { closeWizard(); run("analyze"); }}]);
}

// Адреса для других устройств — каждый на своей строке, с кнопкой «скопировать» (переслать себе)
const COPY_ICON = '<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>';
function urlList(urls) {
  return `<div class="urls">${urls.map(u => `<div><b>${esc(u)}</b><button type="button" class="icon copyurl" data-url="${esc(u)}" title="Скопировать адрес" aria-label="Скопировать адрес">${COPY_ICON}</button></div>`).join("")}</div>`;
}
document.addEventListener("click", e => {
  const b = e.target.closest(".copyurl");
  if (b) navigator.clipboard.writeText(b.dataset.url).then(() => toast("Адрес скопирован"), fail);
});

// Доступ из сети включили — показать, по какому адресу открывать
function openNetworkInfo(n) {
  dialog("Доступ из домашней сети", `<p>На другом устройстве в той же сети откройте в браузере:</p>
    ${n.urls.length ? urlList(n.urls) : "<p>адрес этого компьютера с портом 8766</p>"}
    <p>Программа спросит пароль, который вы задали. Вход запоминается на 30 дней; после перезапуска программы нужно войти снова.</p>
    <p class="hint">Выключить программу и поменять доступ из сети можно только на этом компьютере. Если страница не открывается — проверьте, что оба устройства в одной сети и что Mac разрешил программе входящие подключения («Системные настройки → Сеть → Брандмауэр»).</p>`, [{label: "Понятно", primary: true}]);
}

// Сменили способ оценки. На одну ступень — предложить полный разбор вакансиям, у которых есть только
// быстрая оценка; на две — ничего делать не нужно: готовые полные разборы точнее быстрой оценки
function openStageChanged(twoStage) {
  if (twoStage)
    return dialog("Способ оценки изменён", `<p>Новые вакансии будут оцениваться в две ступени: быстрая оценка всем, полный разбор — только «да» и «возможно».</p>
      <p class="hint">Уже сделанные полные разборы остаются — они точнее быстрой оценки, переоценивать их не нужно.</p>`, [{label: "Понятно", primary: true}]);
  const short = r => r.analyzed && r.stage === "short";
  const count = st => state.rows.filter(r => r.status === st && short(r)).length;
  const total = state.rows.filter(short).length;
  if (!total)
    return dialog("Способ оценки изменён", `<p>Новые вакансии будут сразу получать полный разбор. У всех уже оценённых вакансий полный разбор есть — переоценивать нечего.</p>`,
                  [{label: "Понятно", primary: true}]);
  dialog("Способ оценки изменён", field("Сделать полный разбор вакансиям, у которых есть только быстрая оценка?",
    `<div class="checks">${state.statuses.map(([v, label]) =>
      `<label><input type="checkbox" data-sc="${v}" ${v === "new" && count(v) ? "checked" : ""} ${count(v) ? "" : "disabled"}> ${esc(label)} (${count(v)})</label>`).join("")}</div>`,
    "Новые вакансии теперь сразу получают полный разбор. Уже оценённые можно переоценить так же — в скобках, сколько таких вакансий с одной быстрой оценкой. Комментарии, статусы и флаги сохранятся.")
    + '<p class="hint" id="scEst"></p>', [{label: "Не сейчас"}, {label: "Переоценить", primary: true, id: "scGo"}]);
  const picked = () => [...document.querySelectorAll("#wbody [data-sc]")].filter(c => c.checked).map(c => c.dataset.sc);
  const est = () => { const n = picked().reduce((sum, st) => sum + count(st), 0);
    $("scEst").textContent = n ? `Всего: ${n} — примерно ${n} мин (около минуты на вакансию). Разбор можно остановить, уже сделанное сохранится.` : "Ничего не выбрано."; };
  document.querySelectorAll("#wbody [data-sc]").forEach(c => c.onchange = est);
  est();
  $("scGo").onclick = () => {
    if (!picked().length) return toast("Ничего не выбрано");
    closeWizard();
    run("refresh", {reanalyze: picked(), reletters: [], only_short: true});
  };
}

// ---------- Облачная модель GigaChat: одна форма для «Настроек» и шага «Модель» в мастере ----------
const CLOUD_MODELS = ["GigaChat-2", "GigaChat-2-Pro", "GigaChat-2-Max"];
function cloudFields(cl) {
  const models = [...new Set([...(cl.models || CLOUD_MODELS), cl.model])];
  return `<div class="cloudform">
    ${field("Ключ авторизации", `<input type="password" id="clKey" autocomplete="off" placeholder="${cl.has_key ? `ключ сохранён (…${esc(cl.key_tail)}) — вставьте новый, чтобы заменить` : "Authorization key из личного кабинета GigaChat"}">`,
      'Где взять: <a href="https://developers.sber.ru/studio" target="_blank" rel="noopener">developers.sber.ru</a> → войти по Сбер ID → проект GigaChat API → «Настройки API» → «Получить ключ». Для физических лиц есть бесплатный лимит.')}
    <div class="row2">
      ${field("Тип доступа", `<select id="clScope">${Object.entries(cl.scopes).map(([v, t]) => `<option value="${v}" ${v === cl.scope ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>`)}
      ${field("Модель", `<select id="clModel">${models.map(m => `<option ${m === cl.model ? "selected" : ""}>${esc(m)}</option>`).join("")}</select>`)}
    </div>
    <p class="hint">Рекомендуем <b>GigaChat-2-Pro</b>: на проверке совпал с вашими решениями так же, как Gemma, и в 8 раз быстрее. Max — дороже и на проверке ошибался чаще; GigaChat-2 не соблюдает формат оценки — для разбора не подходит. «Проверить подключение» покажет, какие модели доступны по вашему ключу.</p>
    <p class="calbar"><button type="button" id="clCheck">Проверить подключение</button><span class="hint" id="clResult"></span></p>
    <div class="checks"><label><input type="checkbox" id="clConsent" ${cl.consent ? "checked" : ""}> Понимаю: с облачной моделью резюме, критерии и тексты вакансий отправляются в GigaChat (Сбер) и обрабатываются на его серверах <span class="req">*</span></label></div>
    <p class="hint">Модель в облаке не нагружает компьютер и не требует Ollama. Калибровка в облаке менее повторяема: у GigaChat нет «зерна» случайности, поэтому одна и та же версия критериев может давать немного разные результаты.</p>
  </div>`;
}
function bindCloudCheck() {
  $("clCheck").onclick = async () => {
    $("clResult").textContent = "Проверяю…";
    try {
      const r = await api("/api/cloud/check", {auth_key: $("clKey").value.trim(), scope: $("clScope").value, model: $("clModel").value});
      if (r.models && r.models.length) {                   // список моделей — тот, что доступен по ключу
        const cur = $("clModel").value;
        $("clModel").innerHTML = r.models.map(m => `<option ${m === cur ? "selected" : ""}>${esc(m)}</option>`).join("");
      }
      $("clResult").textContent = `Работает: ${r.model} ответила «${r.reply}».`;
    } catch (e) { $("clResult").textContent = e.message; }
  };
}
const cloudPayload = enabled => ({enabled, auth_key: $("clKey").value.trim(), scope: $("clScope").value,
                                  model: $("clModel").value, consent: $("clConsent").checked});

// ---------- Резервная копия профиля ----------
const kb = n => n < 1024 * 1024 ? `${Math.max(1, Math.round(n / 1024))} КБ` : `${(n / 1024 / 1024).toFixed(1)} МБ`;
const when = iso => { const d = new Date(iso); return isNaN(d) ? iso : d.toLocaleString("ru-RU", {day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit"}).replace(",", ""); };

function openBackup() {
  dialog("Резервная копия", `
    <p class="hint">Копия — архив папки профиля: резюме, критерии, вакансии, разборы, письма, контакты, калибровка. Ключ GigaChat и пароль домашней сети в неё не входят.</p>
    <p class="cwarn">В архиве личные данные — резюме и контакты. Не отправляйте его незнакомым.</p>
    <div class="bkbtns"><button type="button" class="primary" id="bkSave" title="Копия профиля «${esc(state.name)}» в папку «копии»">Сохранить копию</button>
      <button type="button" id="bkExport" title="Копия профиля в выбранное место — например, на флешку или облачный диск, чтобы перенести на другой компьютер">Экспорт для переноса…</button></div>
    <p class="hint">Раз в неделю при запуске программа сама делает копию каждого профиля и хранит последние четыре; старые уходят в Корзину.</p>
    <div id="bkList" class="hint">Загружаю список копий…</div>
    <p class="hint">«Восстановить» возвращает текущий профиль к состоянию копии. Новый профиль из копии — через импорт: «+ Новый профиль…» → «Загрузить профиль из архива…».</p>`,
    [{label: "Закрыть", primary: true}]);
  $("bkSave").onclick = async () => {
    $("bkSave").disabled = true;
    try { const r = await api("/api/backup/save", {profile: state.profile}); backupList(r); toast("Копия сохранена"); }
    catch (e) { fail(e); } finally { $("bkSave").disabled = false; }
  };
  $("bkExport").onclick = async () => {
    try { const r = await api("/api/backup/export", {profile: state.profile}); await saveZip(r.file, r.data); }
    catch (e) { if (e.name !== "AbortError") fail(e); }
  };
  api("/api/backup").then(backupList).catch(e => { $("bkList").textContent = e.message; });
}

function backupList(r) {
  if (!$("bkList")) return;
  if (!r.copies.length) { $("bkList").innerHTML = "Копий пока нет."; return; }
  $("bkList").innerHTML = `<table class="bktable"><tr><th>Когда</th><th>Профиль</th><th>Размер</th><th class="bkhead">Восстановление профиля</th></tr>${r.copies.map((c, i) => `<tr>
      <td>${esc(when(c.created))}${c.auto ? ' <span class="hint">· авто</span>' : ""}</td>
      <td>${esc(c.name || c.profile)}</td><td class="nowrap">${kb(c.size)}</td>
      <td class="bkact">
        ${c.profile === state.profile ? `<button type="button" data-replace="${i}" title="Текущий профиль вернётся к состоянию этой копии; перед этим он сам сохранится в копию">Восстановить</button>` : ""}
        <button type="button" class="icon" data-show="${i}" title="Показать файл в папке" aria-label="Показать файл в папке"><svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg></button></td></tr>`).join("")}</table>`;
  $("bkList").querySelectorAll("[data-replace]").forEach(b => b.onclick = () => {
    const c = r.copies[+b.dataset.replace];
    if (confirm(`Восстановить профиль «${state.name}» из копии от ${when(c.created)}? Всё, что изменилось после неё, пропадёт из профиля — но текущее состояние сначала сохранится в отдельную копию, а прежняя папка уйдёт в Корзину.`))
      restoreBackup({file: c.file}, true);
  });
  $("bkList").querySelectorAll("[data-show]").forEach(b => b.onclick = () => api("/api/backup/show", {file: r.copies[+b.dataset.show].file}).catch(fail));
}

async function restoreBackup(src, replace) {
  try {
    const r = await api("/api/backup/restore", {...src, replace, profile: state.profile});
    closeWizard();
    await load(r.profile);
    toast(replace ? "Профиль восстановлен из копии" : `Восстановлено как новый профиль «${r.profile}»`);
  } catch (e) { fail(e); }
}

// Файл из окна выбора → base64 для сервера
async function fileB64(file) {
  const buf = new Uint8Array(await file.arrayBuffer());
  let bin = ""; for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  return btoa(bin);
}

// Архив — куда выберет человек (Chrome, Edge); в других браузерах — в «Загрузки»
async function saveZip(name, b64) {
  const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const blob = new Blob([bytes], {type: "application/zip"});
  if (window.showSaveFilePicker) {
    const h = await window.showSaveFilePicker({suggestedName: name, types: [{description: "Копия профиля", accept: {"application/zip": [".zip"]}}]});
    const w = await h.createWritable(); await w.write(blob); await w.close();
    return toast("Копия сохранена — перенесите файл на другой компьютер");
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  toast("Копия скачана в «Загрузки» — перенесите файл на другой компьютер");
}

// ---------- Папка с данными: перейти на другую — профили в ней подхватываются, нет — создать новый ----------
async function openDataDir() {
  const d = await api("/api/datadir").catch(fail);
  if (!d) return;
  let chosen = null;
  dialog("Папка с данными", `
    <p>Сейчас: <code>${esc(d.home)}</code>${d.profiles.length ? ` — ${d.profiles.length} ${plural(d.profiles.length, "профиль", "профиля", "профилей")}` : ""}.</p>
    <p class="hint">Программа ищет профили в папке «профили» внутри выбранной. Прежняя папка остаётся как есть: в ней ничего не переносится и не удаляется — вернуться можно так же.</p>
    <div class="dpick"><button type="button" class="primary" id="ddPick">Выбрать папку…</button>
      <span class="muted">или путь:</span><input type="text" id="ddPath" placeholder="/Users/имя/Documents/Вакансии" spellcheck="false">
      <button type="button" id="ddCheck">Проверить</button></div>
    <div id="ddInfo"></div>
    <p class="hint">Ключ GigaChat, пароль домашней сети и настройка обновлений хранятся в папке данных: в новой папке, если их там нет, их нужно будет ввести заново.</p>`,
    [{label: "Отмена", onClick: () => state.profiles.length ? closeWizard() : openWizard()},   // первый запуск — назад в мастер
     {label: "Перейти на эту папку", primary: true, id: "ddGo"}]);
  $("ddGo").disabled = true;
  const show = info => {
    chosen = info.problem ? null : info.home;
    $("ddGo").disabled = !chosen;
    if (info.home) $("ddPath").value = info.home;
    $("ddInfo").innerHTML = info.problem ? `<p class="cwarn">${esc(info.problem)}</p>`
      : info.home === d.home ? `<p class="hint">Это та же папка, с которой программа работает сейчас.</p>`
      : info.profiles.length ? `<p>В папке ${info.profiles.length} ${plural(info.profiles.length, "профиль", "профиля", "профилей")}: ${info.profiles.map(n => `<b>${esc(n)}</b>`).join(", ")}. После перехода ${info.profiles.length === 1 ? "он появится" : "они появятся"} в списке профилей.</p>`
      : `<p class="cwarn">В этой папке профилей нет. После перехода создайте новый профиль — или загрузите его из экспорта.</p>`;
    if (info.home === d.home) { chosen = null; $("ddGo").disabled = true; }
  };
  $("ddPick").onclick = async () => {
    $("ddPick").disabled = true;
    try { const r = await api("/api/datadir/pick", {}); if (r.picked) show(r); }
    catch (e) { fail(e); } finally { $("ddPick").disabled = false; }
  };
  $("ddCheck").onclick = () => api("/api/datadir/inspect", {path: $("ddPath").value}).then(show).catch(fail);
  $("ddPath").onkeydown = e => { if (e.key === "Enter") $("ddCheck").click(); };
  $("ddGo").onclick = async () => {
    try {
      const r = await api("/api/datadir/set", {path: chosen});
      closeWizard();
      await load();
      if (!r.profiles.length) { openWizard(); toast("Папка сменена. Профилей в ней нет — создайте новый или загрузите из экспорта"); }
      else toast(`Папка сменена: ${r.profiles.length} ${plural(r.profiles.length, "профиль", "профиля", "профилей")}`);
    } catch (e) { fail(e); }
  };
}

// ---------- Перенос профиля с другого компьютера (мастер → «Загрузить профиль из архива») ----------
async function importProfile(file) {
  try {
    const data = await fileB64(file), i = await api("/api/backup/inspect", {data});
    dialog("Перенос профиля", `
      <p>Профиль <b>${esc(i.name)}</b> из копии от ${esc(when(i.created))}.</p>
      ${field("Имя папки профиля", `<input type="text" id="impName" value="${esc(i.suggested)}" style="width:240px">`,
        i.suggested === i.profile ? "Как на прежнем компьютере. Буквы, цифры, «-» или «_»."
          : `Профиль «${esc(i.profile)}» на этом компьютере уже есть — поэтому другое имя. Можно поменять.`)}
      ${i.cloud && !i.has_key ? '<p class="cwarn">Профиль работал с облачной моделью GigaChat, а ключа GigaChat на этом компьютере нет: он хранится отдельно от профиля и в копию не входит. После загрузки предложу ввести ключ или перейти на локальную модель.</p>' : ""}`,
      [{label: "Отмена"}, {label: "Загрузить профиль", primary: true, id: "impGo"}]);
    $("impGo").onclick = async () => {
      try {
        const r = await api("/api/backup/restore", {data, name: $("impName").value.trim()});
        closeWizard();
        await load(r.profile);
        toast(`Профиль «${i.name}» перенесён`);
        if (i.cloud && !i.has_key) askCloudKey();
      } catch (e) { fail(e); }
    };
  } catch (e) { fail(e); }
}

// Профиль с GigaChat, а ключа на этом компьютере нет: ввести ключ или перейти на локальную модель
function askCloudKey() {
  dialog("Модель профиля", `<p>На прежнем компьютере профиль работал с облачной моделью GigaChat. Ключ GigaChat в копию не входит, а на этом компьютере его нет — без него вакансии не разобрать.</p>
    <p class="hint">Введите ключ в настройках или переключите профиль на локальную модель. Модель можно поменять в любой момент: «Параметры → Настройки → Модель профиля».</p>`,
    [{label: "Локальная модель", onClick: async () => {
        try { await api("/api/cloud", {enabled: false, profile: state.profile}); await load(state.profile); closeWizard(); toast("Профиль переключён на локальную модель"); }
        catch (e) { fail(e); } }},
     {label: "Ввести ключ GigaChat", primary: true, onClick: () => openSettings()}]);
}

// Отсеянные поиском по названию, которые проходят отбор по нынешним правилам: после обновления
// программы и по кнопке в настройках. Добавить — скачать и разобрать, как ссылкой
async function openRecheck(quiet) {
  const res = await api(`/api/recheck?profile=${encodeURIComponent(state.profile)}`).catch(e => (quiet ? null : fail(e)));
  if (!res) return;
  if (!res.items.length) return quiet ? null : toast("Ничего не нашлось: всё отсеянное за 14 дней не подходит и сейчас");
  const url = id => `https://hh.ru/vacancy/${id}`;
  dialog("Раньше отсеяны, теперь проходят", `
    <p class="hint">Поиск на hh.ru за последние 14 дней отсеял эти вакансии по названию. Правила отбора поменялись: например, «СТО» кириллицей теперь считается CTO, а «Технический директор» без уточнения отрасли проходит на оценку моделью. Отметьте, какие добавить: программа скачает их и разберёт.</p>
    <div class="checks stack">${res.items.map(r => `<label><input type="checkbox" data-rc="${r.id}" checked>
      <a href="${url(r.id)}" target="_blank" rel="noopener">${esc(r.title)}</a> <span class="muted">${ddmm(r.date)}</span></label>`).join("")}</div>
    ${res.hh_auto ? "" : `<p class="cwarn">Поиск на hh.ru выключен — программа не скачает их сама. Откройте вакансию на hh и добавьте её текстом или сохранённой страницей.</p>`}`,
    [{label: "Закрыть"}, ...(res.hh_auto ? [{label: "Добавить выбранные", primary: true, id: "rcAdd"}] : [])]);
  if (!$("rcAdd")) return;
  $("rcAdd").onclick = () => {
    const ids = [...document.querySelectorAll("#wbody [data-rc]")].filter(c => c.checked).map(c => c.dataset.rc);
    if (!ids.length) return toast("Ничего не выбрано");
    closeWizard();
    run("add", {links: ids.map(url).join("\n")});
  };
}

// Один раз на профиль после обновления, где поменялся отбор по названию, — предложить перепроверить
async function offerRecheck() {
  const key = "recheck56:" + state.profile;
  try { if (localStorage.getItem(key) || state.hh?.state !== "on") return; localStorage.setItem(key, "1"); } catch (e) { return; }
  const res = await api(`/api/recheck?profile=${encodeURIComponent(state.profile)}`).catch(() => null);
  if (res?.items.length)
    toast(`Отбор по названию стал точнее: ${res.items.length} ${plural(res.items.length, "вакансия", "вакансии", "вакансий")} из отсеянных за 2 недели теперь ${plural(res.items.length, "проходит", "проходят", "проходят")}`,
          {label: "Показать", onClick: () => openRecheck()});
}

// «Где искать вакансии»: общий список из программы и свои ссылки профиля. Ссылки открываются в браузере,
// программа по ним ничего не скачивает
$("mLinks").onclick = () => { closeMenus(); openLinks(); };

async function openLinks() {
  const res = await api(`/api/links?profile=${encodeURIComponent(state.profile)}`).catch(fail);
  if (!res) return;
  const favs = new Set(res.favorite_urls);
  const star = url => `<button class="icon lnkfav${favs.has(url) ? " on" : ""}" data-lfav="${esc(url)}" title="${favs.has(url) ? "Убрать из любимых" : "В любимые — список под звёздочкой в шапке"}" aria-label="Любимый сайт" aria-pressed="${favs.has(url)}">${STAR}</button>`;
  const link = (l, own) => `<li class="lnk">${star(l.url)}<a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.name)}</a>
      ${own ? `<button class="icon lnkdel" data-ldel="${esc(l.id)}" title="Удалить ссылку" aria-label="Удалить ссылку">×</button>` : ""}
      ${l.about ? `<div class="hint">${esc(l.about)}</div>` : ""}
      ${l.auto ? `<div class="lnkauto">В программу: ${esc(l.auto)}</div>` : ""}</li>`;
  const pub = l => link(l);
  const ownList = res.own.map(l => ({name: l["название"], url: l["адрес"], about: l["описание"], id: l.id}));
  const spheres = res.spheres.length ? `Ссылки для сферы профиля (${esc(res.spheres.join(", "))}) и общие; для других сфер — свёрнуты.` : "Сфера профиля не определилась: открыты общие ссылки, ссылки для сфер — свёрнуты.";
  dialog("Где искать вакансии", `
    <p class="hint">${spheres} Ссылки открываются в браузере; программа по ним ничего не скачивает. Понравившуюся вакансию добавьте ссылкой или текстом. Список проверен ${ddmm(res.groups[0]?.items[0]?.checked || "")}: каналы живые, в них в основном настоящие вакансии.</p>
    <section class="lgroup"><h3>Свои ссылки</h3>
      ${ownList.length ? `<ul class="lnks">${ownList.map(l => link(l, true)).join("")}</ul>` : `<p class="hint">Каналы, чаты и сайты, которые вы нашли сами, — они видны только в этом профиле.</p>`}
      <div class="lnkadd" id="lAddBox" hidden>
        <input type="text" id="lName" placeholder="Название, например «Чат ИТ-директоров»" maxlength="80">
        <input type="text" id="lUrl" placeholder="Адрес: https://…">
        <input type="text" id="lAbout" placeholder="Чем полезен — необязательно" maxlength="300">
        <button class="primary" id="lSave">Добавить</button></div>
      <button id="lAdd">+ Добавить ссылку</button></section>
    ${res.groups.map(g => `<section class="lgroup"><h3>${esc(g.name)}</h3>
      ${g.auto ? `<p class="lnkauto">${esc(g.auto)}</p>` : ""}
      ${g.items.length ? `<ul class="lnks">${g.items.map(pub).join("")}</ul>` : ""}
      ${g.other.length ? `<details><summary>Для других сфер (${g.other.length})</summary><ul class="lnks">${g.other.map(pub).join("")}</ul></details>` : ""}
    </section>`).join("")}`, [{label: "Закрыть"}]);
  $("lAdd").onclick = () => { $("lAddBox").hidden = false; $("lAdd").hidden = true; $("lName").focus(); };
  $("lSave").onclick = async () => {
    try {
      await api("/api/links/save", {profile: state.profile, do: "add", name: $("lName").value, url: $("lUrl").value, about: $("lAbout").value});
      toast("Ссылка добавлена"); openLinks();
    } catch (e) { fail(e); }
  };
  document.querySelectorAll("#wbody [data-lfav]").forEach(b => b.onclick = async () => {
    const on = !b.classList.contains("on");
    try {
      await api("/api/links/save", {profile: state.profile, do: "favorite", url: b.dataset.lfav, on});
      b.classList.toggle("on", on); b.setAttribute("aria-pressed", on);
      b.title = on ? "Убрать из любимых" : "В любимые — список под звёздочкой в шапке";
    } catch (e) { fail(e); }
  });
  document.querySelectorAll("#wbody [data-ldel]").forEach(b => b.onclick = async () => {
    try { await api("/api/links/save", {profile: state.profile, do: "delete", id: b.dataset.ldel}); openLinks(); } catch (e) { fail(e); }
  });
}

// Любимые сайты: звёздочка в шапке, список ссылок — открываются в новой вкладке
const STAR = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3l-5.6 2.9 1.1-6.2L3 9.6l6.2-.9z"/></svg>';
$("btnFavs").onclick = async e => {
  e.stopPropagation();
  closeMenus("favMenu");
  const m = $("favMenu");
  if (!m.hidden) { m.hidden = true; return; }
  const res = await api(`/api/links/favorites?profile=${encodeURIComponent(state.profile)}`).catch(fail);
  if (!res) return;
  m.innerHTML = `<div class="mhead">Любимые сайты</div>
    ${res.favorites.map(f => {
      const host = new URL(f.url).hostname.replace(/^www\./, "");
      return `<a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.name)}${host === f.name.toLowerCase() ? "" : `<span class="muted">${esc(host)}</span>`}</a>`;
    }).join("")
      || `<p class="hint favempty">Пока пусто. Отметьте звёздочкой сайты в окне «Где искать вакансии».</p>`}
    <div class="msep"></div><button id="favAll">Где искать вакансии…</button>`;
  m.hidden = false;
  m.style.right = "0px";                          // не выходить за левый край узкого окна
  const left = m.getBoundingClientRect().left;
  if (left < 8) m.style.right = (left - 8) + "px";
  m.querySelectorAll("a").forEach(a => a.onclick = () => { m.hidden = true; });
  $("favAll").onclick = () => { m.hidden = true; openLinks(); };
};
