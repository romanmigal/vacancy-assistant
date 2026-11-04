// Мастер профиля (создание и редактирование) и общее окно-диалог.
// Обычные скрипты (не модули): подключаются по порядку в index.html и видят функции друг друга.

// ---------- Мастер профиля: создание (первый запуск) и редактирование ----------
// Шаги: 0 модель (локальная или GigaChat, для локальной — проверка компьютера) → 1 о себе → 2 резюме → 3 что ищете → 4 критерии → 5 письмо → 6 сайты (поиск на hh.ru — по согласию).
// При редактировании — шаги 1–5, сохраняется только то, что поменяли.
// W.off — шаги, которые видны в строке шагов, но сейчас недоступны (серые)
const W = {mode: "create", seq: [], off: [], pos: 0, a: {}, check: null, created: null};
// 7 — отбор по названию: в списке шагов стоит между «Что ищете» и «Критерии модели»
const WNAMES = ["Модель", "О себе", "Резюме", "Что ищете", "Критерии модели", "Письмо", "Сайты", "Отбор по названию"];
const wstep = () => W.seq[W.pos];
// «Без модели» (#50): «Критерии модели» и «Письмо» видны серыми — пригодятся, когда включат модель
const MODEL_STEPS = [4, 5];
const wenabled = i => !W.off.includes(W.seq[i]) && !(W.a.no_model && MODEL_STEPS.includes(W.seq[i]));
const wnextPos = () => { for (let i = W.pos + 1; i < W.seq.length; i++) if (wenabled(i)) return i; return null; };
const wprevPos = () => { for (let i = W.pos - 1; i >= 0; i--) if (wenabled(i)) return i; return null; };
const wgo = step => { W.pos = W.seq.indexOf(step); };
// Шаги мастера: при создании — все; при правке — с «Модели» (её меняют только на этом компьютере), без «Сайтов»
const wizSeq = edit => edit ? (REMOTE ? [1, 2, 3, 7, 4, 5] : [0, 1, 2, 3, 7, 4, 5]) : [0, 1, 2, 3, 7, 4, 5, 6];

// «Мария Иванова» → «mariya» (как имя папки на сервере); если занято — mariya2, mariya3…
const TRANSLIT = Object.fromEntries([..."абвгдеёжзийклмнопрстуфхцчшщъыьэюя"].map((ch, i) => [ch,
  ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s",
   "t", "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"][i]]));
function suggestProfileId(name) {
  const first = (name.trim().split(/\s+/)[0] || "").toLowerCase();
  const slug = [...first].map(ch => TRANSLIT[ch] ?? ch).join("").replace(/[^a-z0-9]/g, "");
  if (!slug) return "";
  let id = slug, i = 2;
  while (state.profiles.includes(id)) id = `${slug}${i++}`;
  return id;
}

function openWizard() {
  // Новый профиль — по умолчанию GigaChat: не нужны Ollama, 8 ГБ на диске и 16 ГБ памяти; локальную можно выбрать
  Object.assign(W, {mode: "create", seq: [0, 1, 2, 3, 7, 4, 5, 6], off: [], pos: 0, created: null, idTouched: false,
                    a: {office: true, hybrid: true, remote: true, start: "2 недели", model_pick: "cloud"}});
  $("wiz").classList.add("open");
  wizCheck();
}
async function openEditProfile() {
  try {
    const a = await api(`/api/profile/answers?profile=${encodeURIComponent(state.profile)}`);
    // «Что ищете» при редактировании недоступен: туда ведёт только «Пересобрать из опросника»
    Object.assign(W, {mode: "edit", seq: wizSeq(true), off: [3], pos: 0, created: null, rebuild: false, a});
    if (!REMOTE) W.check = await api("/api/setup/check").catch(() => null);   // шаг «Модель»: память, Ollama, модель
    $("wiz").classList.add("open");
    wizRender();
  } catch (e) { fail(e); }
}
function closeWizard() { $("wiz").classList.remove("open", "wide"); if ($("calPeek")) $("calPeek").hidden = true; }
// Окно-диалог поверх программы: заголовок, содержимое и кнопки — {label, primary, left, id, title, onClick}.
// Кнопка без onClick просто закрывает окно. Мастер и калибровка рисуют окно сами — у них шаги.
function dialog(title, body, buttons) {
  $("wiz").classList.remove("wide");                // широкое окно (контакты) включают после dialog()
  $("wtitle").textContent = title;
  $("wsteps").innerHTML = "";
  $("wbody").innerHTML = body;
  $("wbody").scrollTop = 0;
  $("wfoot").replaceChildren(...buttons.map(b => {
    const el = document.createElement("button");
    el.textContent = b.label;
    el.classList.toggle("primary", !!b.primary);
    el.classList.toggle("left", !!b.left);
    if (b.id) el.id = b.id;
    if (b.title) el.title = b.title;
    el.onclick = b.onClick || closeWizard;
    return el;
  }));
  $("wiz").classList.add("open");
}
function wsave() {   // ответы со страницы — в W.a
  document.querySelectorAll("#wbody [data-a]").forEach(el => {
    if (el.type === "radio") { if (el.checked) W.a[el.dataset.a] = el.value === "1"; }
    else W.a[el.dataset.a] = el.type === "checkbox" ? el.checked : el.value;
  });
  if ("city_pick" in W.a && $("wcity")) {                // город: из списка или вписанный вручную
    const city = W.a.city_pick === "__other" ? (W.a.city_other || "").trim() : W.a.city_pick;
    if (city !== W.a.city) W.a.city_area = "";              // код города узнаем заново
    W.a.city = city;
  }
}
const field = (label, input, sub = "", req = false) => `<div class="field">${label ? `<label>${label}${req ? ' <span class="req" title="Обязательное поле">*</span>' : ""}</label>` : ""}${sub ? `<div class="sub">${sub}</div>` : ""}${input}</div>`;
const text = (key, ph = "") => `<input type="text" data-a="${key}" value="${esc(W.a[key] ?? "")}" placeholder="${esc(ph)}">`;
const area = (key, ph = "", cls = "", ro = false) => `<textarea class="${cls}" data-a="${key}" placeholder="${esc(ph)}" ${ro ? "readonly" : ""}>${esc(W.a[key] ?? "")}</textarea>`;
// Сфера профиля — ИТ: мастер предлагает ленты Хабр Карьеры и GeekJob (#39)
const isItField = f => /(^|[^а-яёa-z])(ит|it|ai)([^а-яёa-z]|$)|информацион|программ|разработ|devops|tech|технолог|цифров|data|данны/i.test(f || "");
const check = (key, label) => `<label><input type="checkbox" data-a="${key}" ${W.a[key] ? "checked" : ""}> ${label}</label>`;

async function wizCheck() {
  W.check = await api("/api/setup/check").catch(e => { fail(e); return null; });
  if (!REMOTE && !state.profiles?.length) W.home = (await api("/api/datadir").catch(() => ({}))).home;
  wizRender();
}

function wizRender() {
  const edit = W.mode === "edit", step = wstep(), last = wnextPos() === null;
  $("wtitle").textContent = W.created ? "Профиль создан" : edit ? `Профиль: ${state.name}` : "Новый профиль";
  const offHint = s => W.a.no_model && MODEL_STEPS.includes(s) ? "Нужна модель — выберите её на шаге «Модель» или в «Параметры → Настройки»"
                     : s === 3 ? "Открывается кнопкой «Пересобрать из опросника» на шагах «Отбор по названию» и «Критерии модели»"
                               : "Станет доступен после «Дальше» на шаге «Что ищете»";
  $("wsteps").innerHTML = W.created ? "" : W.seq.map((s, i) => !wenabled(i)
    ? `<span class="off" title="${offHint(s)}">${i + 1}. ${WNAMES[s]}</span>`
    : `<span class="${i === W.pos ? "on" : i < W.pos && !edit ? "done" : ""}" data-go="${i}" style="${edit ? "cursor:pointer" : ""}">${i + 1}. ${WNAMES[s]}</span>`).join("");
  const c = W.check || {};
  let body = "", next = last && !W.rebuild ? (edit ? "Сохранить" : "Создать профиль") : "Дальше";
  if (W.created) {
    $("wbody").innerHTML = `<h3>Готово: профиль «${esc(W.created)}»</h3>
      <p>${W.a.no_model ? "Профиль без модели: вакансии сохраняются без разбора — ведите по ним статусы, этапы откликов и комментарии. Включить модель можно в «Параметры → Настройки»; тогда программа предложит разобрать сохранённые вакансии. " + (W.a.hh_auto ? "" : HH_MANUAL)
        : W.a.hh_auto ? "Программа будет искать вакансии на hh.ru по вашим должностям и разбирать их моделью."
        : "Добавляйте вакансии — программа разберёт их моделью по вашему резюме и критериям. " + HH_MANUAL + " Вакансии с других сайтов — по ссылке."}
        Письма — сопроводительное и референсеру — пишутся во вкладке «Письма» карточки вакансии, когда вы решите откликаться.</p>
      <p class="hint">Поменять ответы можно в «Параметры → Редактировать профиль». ${W.a.hh_auto ? "С чего лучше начать — программа подскажет, когда вы нажмёте «Найти новые вакансии»." : ""}</p>`;
    const finds = W.a.hh_auto || W.a.rss_habr || W.a.rss_geekjob;        // искать есть где: hh.ru или ленты (#39)
    $("wfoot").innerHTML = `<button id="wclose">Закрыть</button><button class="primary" id="wsearch">${finds ? "Найти новые вакансии" : "Добавить вакансию"}</button>`;
    $("wclose").onclick = closeWizard;
    $("wsearch").onclick = () => { closeWizard(); finds ? startSearch() : openAdd(); };
    return;
  }
  if (step === 0) {
    const pick = W.a.model_pick || (W.a.cloud ? "cloud" : "local");
    const opt = (v, title, sub) => `<label class="mpick ${pick === v ? "on" : ""}"><input type="radio" name="mpick" value="${v}" ${pick === v ? "checked" : ""}>
      <div><b>${title}</b><div class="sub">${sub}</div></div></label>`;
    const li = (ok, title, sub) => `<li><span class="ic ${ok === true ? "ok" : ok === "warn" ? "warn" : "bad"}">${ok === true ? "✓" : ok === "warn" ? "!" : "✕"}</span><div><b>${title}</b><div class="sub">${sub}</div></div></li>`;
    const first = !state.profiles?.length;          // первый запуск: профиля ещё нет — можно взять готовый
    body = `${W.mode === "create" && !REMOTE ? `${first ? `<h3>Уже есть профиль?</h3>` : ""}<div class="wimport"><div><b>${first ? "Профиль из экспорта" : "Переезжаете с другого компьютера?"}</b>
        <div class="sub">Архив, сохранённый на прежнем компьютере: «Параметры → Резервная копия → Экспорт для переноса…». Профиль перенесётся целиком — с вакансиями, разборами и контактами.</div></div>
        <button type="button" id="wImport">Загрузить профиль из архива…</button><input type="file" id="wImportFile" accept=".zip,application/zip" hidden></div>
      ${first ? `<div class="wimport"><div><b>Профили в другой папке</b>
        <div class="sub">Например, на облачном диске или в папке Obsidian: программа будет работать прямо с ней. Сейчас данные — в <code>${esc(W.home || "…")}</code>.</div></div>
        <button type="button" id="wDataDir">Выбрать папку…</button></div>
        <h3>Или создайте новый профиль</h3>` : ""}` : ""}
      <h3>Какой моделью разбирать вакансии?</h3>
      <p class="hint">Модель читает ваше резюме и вакансии, оценивает их и пишет письма. Выбор — для этого профиля; поменять можно позже: «Параметры → Настройки → Модель профиля».</p>
      <div class="mpicks">
        ${opt("cloud", "Облачная — GigaChat (Сбер)", "Не нагружает компьютер и в несколько раз быстрее локальной модели. Резюме, критерии и тексты вакансий отправляются на серверы Сбера; имя, телефон, почта и контакты скрываются метками. Нужен ключ GigaChat API — для физических лиц есть бесплатный лимит.")}
        ${opt("local", `Локальная — ${esc(c.model || "Gemma")}`, "Работает на этом компьютере: резюме и вакансии никуда не отправляются. Нужны Ollama, около 8 ГБ на диске и 16 ГБ памяти; около минуты на полный разбор вакансии.")}
        ${opt("none", "Без модели — только трекер откликов", "Таблица вакансий, статусы, этапы откликов, комментарии, контакты и статистика — без оценок, писем и подготовки к интервью. Если компьютер не тянет локальную модель, а отправлять данные в облако не хочется. Включить модель можно позже.")}
      </div>
      ${pick === "none" ? '<p class="hint">Вакансии будут сохраняться без разбора. Резюме всё равно стоит заполнить — оно понадобится, когда включите модель; критерии для неё соберутся из ваших ответов сами.</p>' : pick === "cloud" ? `<div id="wCloud">${W.a.cloud ? '<p class="hint">✓ GigaChat подключён для этого профиля.</p>' : '<p class="hint">Загружаю настройки GigaChat…</p>'}</div>` : `
      <h3>Проверка компьютера</h3>
      <ul class="checklist">
      ${li(c.memory_ok ? true : "warn", `Память: ${c.memory_gb ?? "?"} ГБ`, c.memory_ok ? "Достаточно." : `Рекомендуется ${c.min_memory_gb} ГБ — с меньшей памятью разбор будет медленным.`)}
      ${li(c.disk_ok ? true : "bad", `Свободно на диске: ${c.disk_free_gb} ГБ`, c.disk_ok ? "Достаточно." : `Для модели нужно около ${c.model_size_gb} ГБ.`)}
      ${li(c.ollama ? true : "bad", "Ollama — программа, которая запускает модель", c.ollama ? "Запущена." : c.ollama_installed
        ? "Установлена, но не запущена. Откройте приложение Ollama (или выполните в терминале <code>ollama serve</code>), затем нажмите «Проверить снова». Чтобы не запускать её каждый раз, в Ollama можно включить запуск при входе в систему." :
        'Не найдена. Скачайте с <a href="https://ollama.com/download" target="_blank" rel="noopener">ollama.com/download</a>, установите и запустите, затем нажмите «Проверить снова».')}
      ${li(c.model_ok ? true : "bad", `Модель ${esc(c.model || "")}`, c.model_ok ? "Скачана." : c.ollama
        ? `Не скачана (около ${c.model_size_gb} ГБ). <button id="wpull">Скачать модель</button><div class="progress" id="wprog"></div>` : "Сначала нужна Ollama.")}
      </ul>`}`;
    next = pick === "cloud" ? (W.a.cloud ? "Дальше" : "Подключить и дальше") : pick === "none" || edit || c.ollama && c.model_ok ? "Дальше" : "Дальше без модели";
  }
  if (step === 1) {
    body = `<h3>О себе</h3><p class="hint">Имя нужно для подписи писем.</p>
      ${field("Имя и фамилия", text("name", "Мария Иванова"), "", true)}
      ${field("Имя профиля", text("profile_id", "maria"), "Так профиль называется в списке профилей и в папке «профили». Латиница, цифры, «-» или «_», без пробелов."
        + (edit ? "" : " Подставляется само из имени — можно поменять."), true)}
      ${field("В письмах писать", `<div class="checks"><label><input type="radio" name="g" data-a="female" value="0" ${!W.a.female ? "checked" : ""}> «Буду рад обсудить»</label><label><input type="radio" name="g" data-a="female" value="1" ${W.a.female ? "checked" : ""}> «Буду рада обсудить»</label></div>`)}
      ${field("Ваша сфера", text("field", "например: финансы, маркетинг, ИТ, логистика"), "Пара слов — модель учитывает её, когда сравнивает вакансию с резюме.")}
      ${field("Когда можете выйти на работу", `<select data-a="start">${["сразу", "2 недели", "месяц"].map(v => `<option ${W.a.start === v ? "selected" : ""}>${v}</option>`).join("")}</select>`)}`;
  }
  if (step === 2) {
    // Резюме из файла вне папки профиля — только просмотр; загрузили новое — оно ляжет в папку профиля (резюме.md)
    const ro = edit && !W.a.resume_editable && !W.a.resume_to_profile;
    body = `<h3>Резюме</h3><p class="hint">Модель оценивает вакансии и пишет письма только по фактам из резюме и «Дополнительно о себе» — чего там нет, того она не учтёт.</p>
      ${ro ? `<p class="hint">Резюме берётся из файла <code>${esc(W.a.resume_file)}</code> вне папки профиля — правьте его там или загрузите новое из файла: оно сохранится в папке профиля и заменит этот файл в программе (сам файл не изменится).</p>` : ""}
      ${W.a.resume_to_profile ? `<p class="hint">Новое резюме сохранится в папке профиля (<code>резюме.md</code>) и заменит в программе файл <code>${esc(W.a.resume_file)}</code>. Сам файл не изменится.</p>` : ""}
      ${field("Файл резюме с hh.ru", `<input type="file" id="wpdf" accept=".txt,.md,.html,.htm,.pdf,text/plain,text/markdown,text/html,application/pdf">`,
               "На hh.ru: резюме → «Скачать» → <b>TXT</b> — так программа точно разберёт все разделы. PDF тоже подойдёт, но хуже: колонки PDF путают порядок блоков. Или вставьте текст резюме в поле ниже. Телефон, почта и дата рождения не переносятся.")}
      ${field(`Текст резюме <button type="button" class="info" data-example="resume" title="Пример резюме" aria-label="Пример резюме">i</button>`, `<div class="expop" id="ex-resume"></div>` + area("resume", "…или вставьте текст резюме сюда", "tall", ro), ro ? "" : "Проверьте текст после загрузки файла: модель опирается только на то, что здесь написано.", true)}
      ${field("Дополнительно о себе", area("facts", "- Использую ИИ в своих проектах: локальная LLM, свой помощник по вакансиям на Python\n- Английский — B2, переговоры с зарубежными вендорами", "facts"),
        "Опыт и факты, которых нет в резюме: пет-проекты, обучение, волонтёрство, отраслевые знания, языки. Каждый факт — с «- »: Enter начнёт следующий, длинный факт перенесётся и останется одним пунктом. Модель учитывает их наравне с резюме при разборе и оценке — пишите только правду. Хранится в файле «о себе.md» в папке профиля. Необязательно.")}`;
  }
  if (step === 3) {
    const known = (W.check || {}).areas || AREAS_FALLBACK;
    const other = !!W.a.city && !known.includes(W.a.city);           // город не из списка — «Другой…»
    const cities = known.map(x => `<option ${W.a.city === x ? "selected" : ""}>${esc(x)}</option>`).join("");
    body = `<h3>Что ищете</h3>
      ${field("Должности", area("titles", "Главный бухгалтер\nФинансовый директор"), "По одной на строку. По ним программа ищет на hh.ru.", true)}
      ${field("Город", `<div class="row2 tight">
          <select data-a="city_pick" id="wcity"><option value="">— выберите город —</option>${cities}<option value="__other" ${other ? "selected" : ""}>Другой…</option></select>
          <input type="text" data-a="city_other" id="wcityOther" placeholder="Название города, например Тула" value="${esc(other ? W.a.city : "")}" ${other ? "" : "hidden"}></div>`,
          "", true)}
      ${field("Зарплата от, ₽ в месяц", `<div class="row2 tight">${text("salary", "250 000")}<span></span></div>`, "Пусто — зарплата не важна.")}
      ${field("Формат работы", `<div class="checks">${check("office", "офис")}${check("hybrid", "гибрид")}${check("remote", "удалённо (по всей России)")}</div>`)}
      ${field("Занятость", `<div class="checks">${check("part_time", "рассматриваю и временные или проектные роли с частичной занятостью (зарплата может быть ниже)")}</div>`)}
      ${field("Что важно (плюсы)", area("important", "крупная компания\nпроизводство\nкоманда от 10 человек"), "По одному на строку. Не отсекают вакансию, но повышают «Хочу».")}
      ${field("Что точно не подходит", area("not_ok", "постоянные командировки\nтолько продажи"), "По одному на строку. Если это основная часть роли — вакансия не подходит.")}
      ${edit ? '<p class="hint">Поля заполнены прежними ответами — поправьте нужное или <button id="wclear" type="button">очистите все поля</button>. После «Дальше» ${state.no_model ? "поисковые запросы и фильтр по названию" : "критерии, поисковые запросы и фильтр по названию"} соберутся из ответов${state.no_model ? "" : " — их можно будет поправить на шаге «Критерии»"}.</p>' : ""}`;
  }
  if (step === 4) {
    body = `<h3>Критерии оценки моделью</h3><p class="hint">Модель читает каждую вакансию, которая прошла отбор по названию, и по этим критериям решает, подходит ли она, и ставит оценку. Критерии можно править прямо здесь.</p>
      ${field(`Критерии <button type="button" class="info" data-example="criteria" title="Пример критериев" aria-label="Пример критериев">i</button>`,
        `<div class="expop" id="ex-criteria"></div>` + area("criteria", "", "tall"))}
      ${edit ? `<div class="critactions">
          <button type="button" class="actcard" id="whist">
            <span class="acttitle">Выбрать из прежних версий</span>
            <span class="actsub">Все версии с эффективностью на калибровке — выбранная подставится в поле</span></button>
          <button type="button" class="actcard" id="wrebuild">
            <span class="acttitle">Пересобрать из опросника</span>
            <span class="actsub">Заново собрать критерии и отбор по названию из ответов «Что ищете». Текущий текст останется в версиях</span></button>
        </div><div class="expop" id="ex-hist"></div>` : ""}`;
  }
  if (step === 7) {
    body = `<h3>Отбор вакансий при поиске — без модели</h3><p class="hint">Прежде чем отдать вакансию модели, программа смотрит на её название и сразу отсеивает явно неподходящие — так разбор идёт быстрее. Слово можно указать не целиком, а только его начало: «финанс» подойдёт и для «Финансовый директор», и для «Директор по финансам». Каждое слово — с новой строки.</p>
      <div class="row2">
        ${field("Профессия", area("title_words"), "В названии должно быть хотя бы одно. Пусто — любые.")}
        ${field("Уровень", area("level_words"), "И хотя бы одно из этих. Пусто — любой уровень.")}
      </div>
      ${field("Стоп-слова", area("stop_words", "стажёр\nассистент\nпомощник"), "Если в названии есть одно из них — вакансия отсеивается.")}
      ${edit ? `<p class="hint">${`<button id="wrebuild" type="button">Пересобрать из опросника</button> — откроет опросник «Что ищете» с прежними ответами; после него заново соберутся и отбор по названию, и критерии модели.`}</p>` : ""}`;
  }
  if (step === 5) {
    body = `<h3>Образец письма</h3><p class="hint">Модель берёт из образца стиль и длину, а факты — только из резюме. Вставьте своё удачное письмо или поправьте заготовку: замените текст в [скобках].${edit ? " Это основной шаблон; ещё два — для писем другой структуры — в «Параметры → Шаблоны писем»." : ""}</p>
      ${field("Письмо", area("letter", "", "tall"))}
      ${edit ? `<div class="critactions">
          <button type="button" class="actcard" id="whistLetter">
            <span class="acttitle">Выбрать из прежних версий</span>
            <span class="actsub">Все сохранённые версии образца — выбранная подставится в поле</span></button>
        </div><div class="expop" id="ex-hist-letter"></div>` : ""}`;
  }
  if (step === 6) {
    body = `<h3>Поиск на hh.ru</h3>
      ${edit ? `<p class="hint">Включить или выключить поиск на hh.ru можно в «Параметры → Настройки».</p>`
             : `${hhAutoBlock(W.a.hh_auto, W.a.hh_risk)}<p class="hint">Решение можно поменять в любой момент: «Параметры → Настройки». Для работы с hh выключайте VPN.</p>`}
      ${!edit && isItField(W.a.field) ? `<h3>Ленты вакансий для ИТ</h3>
      <p>Хабр Карьера и GeekJob публикуют новые вакансии RSS-лентами — это их официальный способ подписки. Программа читает ленты при «Найти новые вакансии» (не чаще раза в час), отбирает по названию и скачивает подходящие — даже если поиск на hh.ru выключен.</p>
      ${field("", `<div class="checks stack">${check("rss_habr", "Хабр Карьера — по вашим поисковым запросам")}${check("rss_geekjob", "GeekJob — последние 100 вакансий, отбор по названию")}</div>`)}` : ""}
      ${W.a.no_model ? `<h3>Вакансии с других сайтов</h3>
      <p>Вакансию можно добавить по ссылке с любого сайта — например, с сайта компании. Без модели страница сохраняется целиком, как есть.</p>` : `<h3>Вакансии с других сайтов</h3>
      <p>Вакансию можно добавить по ссылке с любого сайта — например, с сайта компании. Рядом с вакансией там бывает лишнее: меню, кнопки, другие вакансии. Языковая модель может <b>вырезать со страницы саму вакансию</b> и найти в ней компанию, зарплату и город — так разбор и оценка точнее.</p>
      <p class="hint">Разбирает та же модель, что оценивает вакансии: ${W.a.cloud ? "облачная GigaChat — текст страницы отправляется в Сбер" : "локальная Gemma — текст страницы не покидает этот компьютер"}. Без разрешения страница сохраняется целиком, как есть. Изменить решение можно в любой момент: «Параметры → Настройки».</p>
      ${field("", `<div class="checks">${check("llm_pages", "Разрешаю разбирать страницы вакансий моделью")}</div>`)}`}`;
  }
  $("wbody").innerHTML = body;
  const cancel = edit || state.profiles.length > 0;
  // Первый запуск, профилей ещё нет: выйти из мастера тоже можно — вернуться потом через «+ Новый профиль…»
  $("wfoot").innerHTML = `${cancel ? '<button class="left" id="wcancel">Отмена</button>'
                                   : '<button class="left" id="wquit" title="Закрыть мастер; создать профиль можно позже: список профилей → «+ Новый профиль…»">Прервать и выйти</button>'}
    ${step === 0 && (W.a.model_pick || "local") === "local" && !W.a.cloud ? '<button id="wrecheck">Проверить снова</button>' : ""}
    ${wprevPos() !== null ? '<button id="wback">Назад</button>' : ""}
    ${edit && !last && !W.rebuild ? '<button id="wsavenow">Сохранить</button>' : ""}<button class="primary" id="wnext">${next}</button>`;
  if ($("wcancel")) $("wcancel").onclick = closeWizard;
  if ($("wquit")) $("wquit").onclick = async () => {
    const r = await api("/api/jobs").catch(() => null);
    const job = r && r.tasks.find(t => t.kind === "service" && isActive(t));   // например, идёт скачивание модели
    if (job) {
      if (!confirm(`Идёт «${job.title}». Остановить? Уже скачанное Ollama сохранит и докачает в следующий раз.`)) return;
      await api("/api/stop", {task_id: job.id}).catch(() => {});
    }
    closeWizard();
    render();
  };
  if ($("wrecheck")) $("wrecheck").onclick = wizCheck;
  if ($("wback")) $("wback").onclick = () => { wsave(); W.pos = wprevPos(); wizRender(); };
  if ($("wsavenow")) $("wsavenow").onclick = () => { wsave(); wizFinish(); };
  $("wnext").onclick = wizNext;
  if ($("wpull")) $("wpull").onclick = wizPull;
  // Шаг «Модель»: локальная или GigaChat — для этого профиля
  document.querySelectorAll("#wbody input[name=mpick]").forEach(r => r.onchange = () => {
    W.a.model_pick = r.value;
    if (r.value !== "cloud") W.a.cloud = false;
    wizRender();
  });
  if ($("wCloud") && !W.a.cloud) api("/api/cloud").then(cl => {   // форма ключа — общего для компьютера
    if (!$("wCloud") || $("clKey")) return;
    $("wCloud").innerHTML = cloudFields(cl);
    bindCloudCheck();
  }).catch(fail);
  if ($("wpdf")) $("wpdf").onchange = wizPdf;
  if ($("hhOn")) bindHhAuto();
  if ($("wDataDir")) $("wDataDir").onclick = () => openDataDir();
  if ($("wImport")) { $("wImport").onclick = () => $("wImportFile").click(); $("wImportFile").onchange = e => e.target.files[0] && importProfile(e.target.files[0]); }
  if ($("wrebuild")) $("wrebuild").onclick = () => {     // опросник с прежними ответами; «Критерии» — после «Дальше»
    wsave();
    Object.assign(W, {rebuild: true, off: [7, 4, 5]});
    wgo(3);
    wizRender();
  };
  if (step === 1 && !edit) {                             // имя профиля — из имени человека, пока его не правили руками
    const nameEl = document.querySelector("#wbody [data-a=name]"), idEl = document.querySelector("#wbody [data-a=profile_id]");
    const fill = () => { if (!W.idTouched) idEl.value = W.a.profile_id = suggestProfileId(nameEl.value); };
    nameEl.addEventListener("input", fill);
    idEl.addEventListener("input", () => { W.idTouched = !!idEl.value.trim(); });
    if (!idEl.value) fill();
  }
  bulletArea(document.querySelector("#wbody [data-a=facts]"));
  document.querySelectorAll("#wbody [data-example]").forEach(b => b.onclick = e => { e.stopPropagation(); showExample(b.dataset.example); });
  if ($("whist")) $("whist").onclick = e => { e.stopPropagation(); showCriteriaHistory(); };
  if ($("whistLetter")) $("whistLetter").onclick = e => { e.stopPropagation(); showCriteriaHistory("letter"); };
  const lt = document.querySelector("#wbody [data-a=letter]");
  if (lt) lt.addEventListener("input", () => { W.a.letter_origin = "manual"; });
  const crit = document.querySelector("#wbody [data-a=criteria]");
  if (crit) crit.addEventListener("input", () => { W.a.criteria_origin = "manual"; });   // правка руками — своя версия
  if ($("wcity")) $("wcity").onchange = e => {
    const other = e.target.value === "__other";
    $("wcityOther").hidden = !other;
    if (other) $("wcityOther").focus();
  };
  if ($("wclear")) $("wclear").onclick = () => {
    Object.assign(W.a, {titles: "", city: "", salary: "", office: false, hybrid: false, remote: false,
                        part_time: false, important: "", not_ok: ""});
    wizRender();
  };
  document.querySelectorAll("#wbody [data-a]").forEach(el => {
    el.addEventListener("input", () => clearInvalid(el));
    el.addEventListener("change", () => clearInvalid(el));
  });
  if (edit) document.querySelectorAll("#wsteps [data-go]").forEach(s => s.onclick = () => { wsave(); W.pos = +s.dataset.go; wizRender(); });
}

// Образцы для полей «Текст резюме» и «Критерии»: панель с примером из профиля-примера (вымышленный ИТ-директор)
const EXAMPLE_NOTES = {
  resume: ["Модель видит только то, что написано в резюме: чего нет — того не учтёт.",
           "Места работы с годами, должностью, масштабом (люди, бюджет) и результатами с цифрами.",
           "Свободный формат: заголовки «##», списки «-», жирный «**…**» — по желанию."],
  criteria: ["Жёсткие критерии — К1., К2., … — каждый с новой строки. Если вакансия нарушает хотя бы один, модель ответит «нет».",
             "Пишите, что считать нарушением, а что нет: «Нарушение, если…», «Если не указано — ❓, это не нарушение».",
             "Мягкие — строки «+ …» (плюс) и «− …» (минус): не отсекают вакансию, но влияют на «Хочу»."],
};
let examples = null;
async function showExample(key) {
  const pop = $("ex-" + key);
  if (pop.classList.contains("open")) { pop.classList.remove("open"); pop.innerHTML = ""; return; }
  if (!examples) examples = await api("/api/setup/examples").catch(e => { fail(e); return null; });
  if (!examples) return;
  const title = key === "resume" ? "Пример резюме" : "Пример критериев";
  pop.innerHTML = `<div class="cpop">
    <div class="cpop-head"><b>${title}</b><button type="button" class="x" aria-label="Закрыть">×</button></div>
    <div class="cbody"><ul class="exnotes">${EXAMPLE_NOTES[key].map(t => `<li>${esc(t)}</li>`).join("")}</ul>
      <pre class="extext">${esc(examples[key])}</pre></div>
    <div class="cpop-foot"><span class="hint">Это вымышленный человек — замените на свои данные.</span>
      <button type="button" class="primary excopy">Скопировать пример</button></div></div>`;
  pop.classList.add("open");
  pop.onclick = e => e.stopPropagation();
  pop.querySelector(".x").onclick = () => { pop.classList.remove("open"); pop.innerHTML = ""; };
  pop.querySelector(".excopy").onclick = () => navigator.clipboard.writeText(examples[key]).then(() => toast("Пример скопирован"), fail);
}
document.addEventListener("click", () => document.querySelectorAll(".expop.open").forEach(p => { p.classList.remove("open"); p.innerHTML = ""; }));

// Прежние версии критериев с эффективностью: совпадение решений модели с вашими оценками
// Прежние версии: критерии (с эффективностью на калибровке) или образец письма (which = "letter")
async function showCriteriaHistory(which = "criteria") {
  const letter = which === "letter", key = letter ? "letter" : "criteria";
  const pop = $(letter ? "ex-hist-letter" : "ex-hist");
  if (pop.classList.contains("open")) { pop.classList.remove("open"); pop.innerHTML = ""; return; }
  wsave();
  let vs;
  try { vs = (await api(`/api/criteria/history?profile=${encodeURIComponent(state.profile)}&which=${which}`)).versions; }
  catch (e) { return fail(e); }
  const date = d => { const [y, m, rest] = d.split("-"); return `${rest.slice(0, 2)}.${m}.${y}${rest.length > 2 ? rest.slice(2) : ""}`; };
  const eff = (m, v) => !m ? (v.kind === "manual" ? '<b class="s-bad">ручная правка — на калибровке не проверялась</b>' : '<span class="muted">эффективность не измерялась</span>')
    : `<b class="${m["пропущено"] ? "s-bad" : m["совпало"] === m["всего"] ? "s-good" : "s-mid"}">совпало ${m["совпало"]} из ${m["всего"]}</b> · пропущено подходящих ${m["пропущено"]} · лишних «да» ${m["лишних"]}`;
  const inField = (W.a[key] || "").trim();
  pop.innerHTML = `<div class="cpop">
    <div class="cpop-head"><b>${letter ? "Прежние версии образца письма" : "Прежние версии критериев"}</b><button type="button" class="x" aria-label="Закрыть">×</button></div>
    <div class="cbody">
      <p class="hint">${letter ? "Все сохранённые версии образца. Выбранная подставится в поле — применится по «Сохранить»."
        : "Эффективность — насколько решения модели с этими критериями совпали с вашими оценками на калибровке. Самое важное — «пропущено подходящих»: лучше 0."}</p>
      ${vs.length ? vs.map(v => `<div class="hver ${v.current ? "cur" : ""} ${!letter && v.kind === "manual" && !v.measure ? "unchecked" : ""}">
        <div class="hver-head"><b>${esc(date(v.date))}</b> ${v.current ? '<span class="chip used">текущая</span>' : ""}
          ${v.text.trim() === inField && !v.current ? '<span class="chip">сейчас в поле</span>' : ""}</div>
        <div class="t-meta">${esc(v.source.replace(/(\d{4})-(\d{2})-(\d{2})/, "$3.$2.$1"))}</div>
        ${letter ? "" : `<div class="heff">${eff(v.measure, v)}</div>`}
        <details><summary>Показать текст</summary><pre class="extext">${esc(v.text)}</pre></details>
        <div class="hver-btns">${v.text.trim() === inField ? "" : `<button type="button" data-take="${v.id}">Взять эту версию</button>`}
          ${v.kind === "manual" && !v.measure && !v.current ? `<button type="button" class="danger" data-del="${v.id}">Удалить</button>` : ""}</div>
      </div>`).join("") : `<p class="hint">Прежних версий пока нет. Они появятся после правки${letter ? " образца" : " критериев или автонастройки"}.</p>`}
    </div></div>`;
  pop.classList.add("open");
  pop.onclick = e => e.stopPropagation();
  pop.querySelector(".x").onclick = () => { pop.classList.remove("open"); pop.innerHTML = ""; };
  pop.querySelectorAll("[data-del]").forEach(b => b.onclick = async () => {
    if (!confirm(`Удалить эту ручную версию ${letter ? "образца письма" : "критериев"}? Её нельзя будет вернуть.`)) return;
    try {
      await api("/api/criteria/delete", {profile: state.profile, id: +b.dataset.del, which});
      pop.classList.remove("open"); pop.innerHTML = "";
      await showCriteriaHistory(which);            // список заново
      toast("Версия удалена");
    } catch (e) { fail(e); }
  });
  pop.querySelectorAll("[data-take]").forEach(b => b.onclick = () => {
    const v = vs.find(x => x.id === +b.dataset.take);
    W.a[key] = v.text;
    W.a[key + "_origin"] = "history";
    wizRender();
    toast("Версия подставлена в поле — нажмите «Сохранить», чтобы применить");
  });
}

// Незаполненное обязательное поле: красная рамка и подсказка прямо под полем
function markInvalid(key, msg) {
  const el = document.querySelector(`#wbody [data-a=${key}]`);
  const box = el && el.closest(".field");
  if (!box) { toast(msg); return; }
  box.classList.add("invalid");
  if (!box.querySelector(".ferr")) box.insertAdjacentHTML("beforeend", `<div class="ferr">${esc(msg)}</div>`);
}
function clearInvalid(el) {
  const box = el.closest(".field");
  if (box) { box.classList.remove("invalid"); box.querySelector(".ferr")?.remove(); }
}
const AREAS_FALLBACK = ["Москва", "Санкт-Петербург", "Екатеринбург", "Новосибирск", "Нижний Новгород", "Казань",
                        "Краснодар", "Самара", "Ростов-на-Дону", "Владивосток"];

async function wizPull() {
  $("wpull").disabled = true;
  const started = await api("/api/setup/pull", {}).catch(fail);
  if (!started) return;
  const timer = setInterval(async () => {
    const r = await api("/api/jobs").catch(() => null);
    const job = r && r.tasks.find(t => t.id === started.task_id);
    if (!job) return;
    const prog = $("wprog");
    if (prog) prog.textContent = job.log.filter(Boolean).slice(-3).join("\n") + (job.error ? "\n" + job.error : "");
    if (!isActive(job)) { clearInterval(timer); if (!job.error) wizCheck(); else if ($("wpull")) $("wpull").disabled = false; }
  }, 1000);
}

async function wizPdf(e) {
  const file = e.target.files[0];
  if (!file) return;
  const buf = new Uint8Array(await file.arrayBuffer());
  let bin = ""; for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode.apply(null, buf.subarray(i, i + 0x8000));
  try {
    const r = await api("/api/setup/resume", {data: btoa(bin)});
    W.a.resume = r.resume;
    if (W.mode === "edit" && !W.a.resume_editable) W.a.resume_to_profile = true;   // файл вне профиля не трогаем
    wizRender(); toast("Резюме прочитано — проверьте текст");
  } catch (err) { fail(err); }
}

async function wizNext() {
  wsave();
  const step = wstep(), create = W.mode === "create", edit = !create;
  document.querySelectorAll("#wbody .field.invalid").forEach(f => { f.classList.remove("invalid"); f.querySelector(".ferr")?.remove(); });
  const bad = [];
  const need = (cond, key, msg) => { if (!cond) { bad.push(key); markInvalid(key, msg); } };
  if (step === 1) {
    need((W.a.name || "").trim(), "name", "Укажите имя и фамилию — они нужны для подписи писем.");
    const id = (W.a.profile_id || "").trim(), own = W.mode === "edit" ? state.profile : null;
    if (!/^[\w-]{1,40}$/u.test(id)) need(false, "profile_id", "Латиница, цифры, «-» или «_», без пробелов, например maria.");
    else need(id === own || !state.profiles.includes(id), "profile_id", `Профиль «${id}» уже есть — выберите другое имя.`);
  }
  if (step === 0) {           // «Без модели» (#50) — выбран явно или локальная модель не готова («Дальше без модели»)
    const pick = W.a.model_pick || (W.a.cloud ? "cloud" : "local"), c = W.check || {};
    // при правке локальная остаётся локальной, даже если Ollama сейчас не запущена; «Без модели» — только явно
    W.a.no_model = pick === "none" || (!edit && pick === "local" && !(c.ollama && c.model_ok));
    W.a.model_pick = W.a.no_model ? "none" : pick;
  }
  if (step === 0 && W.a.model_pick === "cloud" && !W.a.cloud) {   // GigaChat выбран, но ещё не подключён
    if (!$("clKey")) return toast("Подождите — загружаю настройки GigaChat");
    if (!$("clConsent").checked) return toast("Отметьте согласие на отправку данных в GigaChat");
    $("wnext").disabled = true;
    // ключ общий для компьютера — сохраняем и проверяем; выбор модели запишется в профиль при создании
    try { await api("/api/cloud", cloudPayload(true)); W.a.cloud = true; toast("GigaChat подключён"); }
    catch (e) { $("wnext").disabled = false; return fail(e); }
  }
  if (step === 2) need((W.a.resume || "").trim(), "resume", "Добавьте резюме: загрузите выгрузку с hh.ru или вставьте текст.");
  if (step === 3 && W.a.city_pick === "__other" && W.a.city && !W.a.city_area) {   // проверяем город на hh.ru
    try {
      const area = await api(`/api/setup/area?name=${encodeURIComponent(W.a.city)}`);
      W.a.city = area.name; W.a.city_area = area.id;
      $("wcityOther").value = area.name;
      toast(`Город: ${area.name}${area.region ? ", " + area.region : ""}`);
    } catch (e) { bad.push("city_other"); markInvalid("city_other", e.message); }
  }
  if (step === 3) {
    need((W.a.titles || "").trim(), "titles", "Укажите хотя бы одну должность.");
    need(W.a.city, W.a.city_pick === "__other" ? "city_other" : "city_pick",
         W.a.city_pick === "__other" ? "Впишите название города." : "Выберите город.");
  }
  if (step === 6 && W.a.hh_auto) need(W.a.hh_risk, "hh_risk", "Чтобы включить поиск на hh.ru, отметьте, что понимаете риск. Или выключите поиск.");
  if (bad.length) {
    document.querySelector("#wbody .field.invalid")?.scrollIntoView({behavior: "smooth", block: "center"});
    toast("Заполните обязательные поля — они отмечены красным");
    return;
  }
  if (step === 3) {
    if (create || W.rebuild) {   // при создании и пересборке критерии и фильтр собираются из ответов заново
      W.a.criteria = W.a.title_words = W.a.level_words = W.a.stop_words = undefined;
      const pv = await api("/api/setup/preview", {answers: W.a}).catch(e => { fail(e); return null; });
      if (!pv) return;
      for (const k of ["criteria", "title_words", "level_words", "stop_words"]) W.a[k] = pv[k];
      W.a.criteria_origin = "questionnaire";
      if (!W.a.letter) W.a.letter = pv.letter;      // заготовка — с должностью, подписью и «рад/рада»
      if (W.rebuild) {                               // опросник снова недоступен, открыты «Критерии»
        Object.assign(W, {rebuild: false, off: [3]});
        wgo(7);
        toast("Критерии собраны из опросника — проверьте их");
        return wizRender();
      }
    }
  }
  if (step === 7 && !(W.a.title_words || "").trim() && !(W.a.level_words || "").trim()
      && !confirm("Слова профессии и уровня пустые — тогда отсев по названию пропустит к модели любые вакансии из выдачи hh "
                  + "(например, продажников), и разбор займёт намного больше времени. Оставить пустыми?")) return;
  if (wnextPos() === null) return wizFinish();
  W.pos = wnextPos();
  wizRender();
}

async function wizFinish() {
  try {
    if (W.mode === "edit") {
      const wasNone = state.no_model;
      const r = await api("/api/profile/update", {profile: state.profile, answers: W.a});
      toast(r.changed.length ? "Сохранено: " + r.changed.join(", ") : "Изменений нет");
      await load(r.profile);
      if (wasNone && !state.no_model && state.unanalyzed) return openAnalyzeSaved();   // включили модель — разобрать сохранённое
      const rescore = r.changed.some(c => ["критерии", "сфера", "занятость", "дополнительно о себе", "резюме"].includes(c));
      const reletter = r.changed.includes("образец письма");
      if (rescore || reletter) openAfterEdit(rescore, reletter); else closeWizard();
      return;
    }
    const r = await api("/api/setup/create", {answers: W.a});
    W.created = r.profile;
    selected = null;
    await load(r.profile);
    wizRender();
  } catch (e) { fail(e); }
}

// После правки профиля: переоценить вакансии по новым критериям и/или написать новые версии писем
function openAfterEdit(rescore, reletter) {
  if (state.no_model) { closeWizard(); return; }        // «Без модели» (#50): переоценивать нечем
  const count = (st, pred) => state.rows.filter(r => r.status === st && pred(r)).length;
  const boxes = (name, pred, defaults) => `<div class="checks">${state.statuses.map(([v, label]) =>
    `<label><input type="checkbox" data-${name}="${v}" ${defaults.includes(v) ? "checked" : ""}> ${esc(label)} (${count(v, pred)})</label>`).join("")}</div>`;
  dialog("Профиль сохранён", `
    ${rescore ? field("Переоценить вакансии по новым критериям и фактам о себе?", boxes("re", r => true, ["new"]),
      "Модель разберёт выбранные вакансии заново — около минуты на каждую. Комментарии, статусы и флаги сохранятся.") : ""}
    ${reletter ? field("Написать новые версии писем по новому образцу?", boxes("rl", r => r.letter, ["new", "yes"]),
      "Только для вакансий, где письмо уже есть (в скобках — сколько их). Прежние письма сохранятся — их видно в карточке, на вкладке «Письмо», в строке «Версии».") : ""}
    <p class="hint" id="aeEstimate"></p>`, [{label: "Не сейчас"}, {label: "Запустить", primary: true, id: "aeGo"}]);
  const picked = name => [...document.querySelectorAll(`#wbody [data-${name}]`)].filter(c => c.checked).map(c => c.dataset[name]);
  const estimate = () => {
    const re = picked("re"), rl = picked("rl");
    const n = state.rows.filter(r => re.includes(r.status)).length + state.rows.filter(r => r.letter && rl.includes(r.status)).length;
    $("aeEstimate").textContent = n ? `Всего задач для модели: ${n} — примерно ${n} мин. Разбор можно остановить, уже сделанное сохранится.` : "Ничего не выбрано.";
  };
  document.querySelectorAll("#wbody input[type=checkbox]").forEach(c => c.onchange = estimate);
  estimate();
  $("aeGo").onclick = () => {
    const re = picked("re"), rl = picked("rl");
    if (!re.length && !rl.length) return toast("Ничего не выбрано");
    closeWizard();
    run("refresh", {reanalyze: re, reletters: rl});
  };
}
