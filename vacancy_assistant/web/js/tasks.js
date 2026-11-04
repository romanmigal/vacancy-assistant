// Задачи к моделям: индикатор в шапке и панель «Задачи». Сами очереди (локальная модель и GigaChat) — на сервере;
// здесь — задачи своего профиля: идёт / в очереди / готово за последний час, лог по щелчку,
// «Остановить» и «Убрать из очереди». Чужие — одной строкой «задача другого профиля», без названий и логов.

const TASK_ACTIVE = ["queued", "running"];
const TASK_ICON = {running: "⏳", queued: "🕒", done: "✓", error: "⚠️", stopped: "⏹"};
// Список задач перерисовывается каждую секунду, и вращение песочных часов начиналось бы заново —
// рывком. Отрицательная задержка продолжает оборот с того места, где он был (оборот — 2 с, как в style.css)
const spinPhase = () => `style="animation-delay:-${(performance.now() % 2000 / 1000).toFixed(3)}s"`;
let openTask = null;                  // чей лог раскрыт на панели
const lastStatus = {}, seenLines = {};   // id → статус и число строк лога при прошлом опросе
let refreshing = false;

const isActive = t => TASK_ACTIVE.includes(t.status);
// Режим «Без модели»: эти действия зовут модель — кнопки неактивны, run() их не отправляет (сервер тоже откажет)
const NEEDS_MODEL = ["analyze", "refresh", "tune", "rescore_all", "letter", "referrer_letter", "interview", "interview_questions", "resume_fit", "market_advice",
  "fix_suggest", "fix_check", "fix_recheck", "market_recheck"];
const NO_MODEL_HINT = "Нужна модель — включите локальную или облачную в «Параметры → Настройки»";
const myTasks = () => (state.tasks || []).filter(t => !t.foreign);
const busyMine = () => myTasks().some(isActive);           // у профиля есть задачи — пачку не запустить
const tasksUrl = () => "/api/jobs" + (state && state.profile ? "?profile=" + encodeURIComponent(state.profile) : "");

// Запущенные из этой вкладки (sessionStorage): только им — «Готово» и итоги, у других вкладок и людей ничего не всплывает
function launched() { try { return JSON.parse(sessionStorage.getItem("myTasks")) || []; } catch (e) { return []; } }
function rememberLaunch(id) { try { sessionStorage.setItem("myTasks", JSON.stringify([...launched(), id].slice(-30))); } catch (e) {} }

function progress(t) {                   // «12/50» — из последней строки «[12/50] …» лога
  for (let i = t.log.length - 1; i >= 0; i--) {
    const m = t.log[i].match(/^\s*\[(\d+)\/(\d+)\]/);
    if (m) return `${m[1]}/${m[2]}`;
  }
  return "";
}

function taskStatus(t) {
  if (t.status === "running") {
    const now = t.inside ? `пропустила вперёд: ${t.inside}`
      : t.phase ? t.phase.charAt(0).toLowerCase() + t.phase.slice(1) : "идёт";
    return now + (progress(t) ? ` [${progress(t)}]` : "");
  }
  if (t.status === "queued") return `в очереди (${t.position}-я) · ${t.queue_name}`;
  return {done: "готово", error: "ошибка", stopped: "остановлено"}[t.status] || t.status;
}

function showTasks() {
  const tasks = (state.tasks || []).filter(t => t.status !== "removed");
  const active = tasks.filter(t => !t.foreign && isActive(t));
  const busy = active.length > 0, anyActive = tasks.some(isActive);
  // Пока у профиля идут задачи, пачку не запустить: кнопка hh недоступна (но на месте)
  $("btnUpdate").disabled = busy;
  $("btnUpdate").title = busy ? "Идут задачи профиля — найти новые вакансии можно, когда они закончатся (ход — на песочных часах)"
    : state.hh?.state === "ask" ? "Поиск на hh.ru ждёт вашего решения — щёлкните, чтобы выбрать"
    : $("btnUpdate").dataset.idle || "Найти новые вакансии на hh.ru — поиск по запросам профиля и разбор (на ваш риск: соглашение hh это запрещает)";
  $("btnRescore").disabled = busy;
  // Песочные часы всегда на месте: крутятся, пока идут любые задачи — свои или другого пользователя
  $("btnJob").classList.toggle("busy", anyActive);
  $("jobCount").textContent = active.length > 1 ? active.length : "";
  $("btnJob").title = busy ? `Задачи профиля: ${active.length} — показать ход, там же остановить`
    : anyActive ? "Идёт задача другого профиля — ваши задачи встанут в очередь"
    : "Задач сейчас нет — щелчок покажет законченные за последний час";
  $("joblist").innerHTML = tasks.length ? tasks.slice().reverse().map(t => t.foreign
    ? `<div class="task foreign"><div class="thead"><span class="ticon">${TASK_ICON[t.status]}</span>
         <span class="ttitle">Задача другого профиля</span>
         <span class="tstat">${t.status === "running" ? "идёт" : "в очереди"} · ${esc(t.queue_name)}</span></div></div>`
    : `<div class="task ${t.status} ${t.id === openTask ? "open" : ""}" data-task="${t.id}" title="Щелчок — показать или скрыть лог">
         <div class="thead"><span class="ticon" ${t.status === "running" ? spinPhase() : ""}>${TASK_ICON[t.status] || ""}</span><span class="ttitle">${esc(t.title)}</span>
           <span class="tstat">${esc(taskStatus(t))}</span>
           ${t.status === "running" ? `<button data-stop="${t.id}">Остановить</button>` : ""}
           ${t.status === "queued" ? `<button data-stop="${t.id}">Убрать из очереди</button>` : ""}</div>
         ${t.id === openTask ? `<pre>${t.log.map(esc).join("\n")}${t.error ? `\n<span class="err">${esc(t.error)}</span>` : ""}</pre>` : ""}
       </div>`).join("")
    : '<div class="tnone">Задач нет.</div>';
  const pre = document.querySelector("#joblist .task.open pre");
  if (pre) pre.scrollTop = pre.scrollHeight;
  updateCardButtons();
}

// Кнопки карточки: если такая задача уже в очереди — «в очереди (2-я)» или «идёт…» вместо кнопки
function updateCardButtons() {
  [["refreshCard", "refresh_card"], ["newInterview", "interview"], ["newQuestions", "interview_questions"], ["newResumeFit", "resume_fit"], ["newLetter", "letter"], ["newRefLetter", "referrer_letter"]]
    .forEach(([id, action]) => {
      const b = $(id), label = b && b.lastChild;
      if (b && state.no_model) {                          // «Без модели»: кнопка неактивна, «Разобрать заново» — только проверка
        if (action === "refresh_card") b.title = "Без модели: проверить, открыта ли вакансия на сайте, и обновить её текст — без разбора";
        else { b.disabled = true; b.title = NO_MODEL_HINT; b.classList.add("nomodel"); return; }
      }
      if (b && b.classList.contains("tool")) {            // кнопка-иконка: блокируем, состояние — подписью рядом и в подсказке
        const t = myTasks().find(t => isActive(t) && t.action === action && t.n === selected);
        if (!b.dataset.label) b.dataset.label = b.title;
        const st = !t ? "" : t.status === "running" ? "Идёт…" : `В очереди (${t.position}-я)`;
        b.disabled = !!t;
        b.title = st ? `${st} ${b.dataset.label}` : b.dataset.label;
        let s = b.querySelector(".qstate");
        if (st && !s) { s = document.createElement("span"); s.className = "qstate"; b.append(s); }
        if (s) { if (st) s.textContent = st; else s.remove(); }
        return;
      }
      if (!label || label.nodeType !== Node.TEXT_NODE) return;
      if (!b.dataset.label) b.dataset.label = label.textContent;
      const t = myTasks().find(t => isActive(t) && t.action === action && t.n === selected);
      b.disabled = !!t;
      label.textContent = !t ? b.dataset.label : t.status === "running" ? "Идёт…" : `В очереди (${t.position}-я)`;
    });
}

function seedTasks() {                  // задачи, которые уже были при загрузке, — от них «Готово» не ждём
  for (const t of state.tasks || []) if (!(t.id in lastStatus)) { lastStatus[t.id] = t.status; seenLines[t.id] = t.count; }
}

function setPanel(open) {
  $("joblog").classList.toggle("open", open);
  remember("tasksOpen", open ? "1" : "");
}

function showLog(id) { openTask = id; setPanel(true); showTasks(); }

// Пока идут задачи — обновляем таблицу, как только скачана вакансия или закончена её оценка
async function refreshRows() {
  if (refreshing) return;
  refreshing = true;
  try { const st = await api(`/api/state?profile=${encodeURIComponent(state.profile)}`); state = {...st, tasks: state.tasks}; render(); }
  catch (e) { /* не страшно — обновим на следующей строке */ }
  refreshing = false;
}

// Без своих задач тоже раз в 5 секунд смотрим очереди: задачу мог запустить другой пользователь — часы закрутятся
setInterval(async () => {
  if (polling || !state || document.hidden) return;
  const r = await api(tasksUrl()).catch(() => null);
  if (!r || polling) return;
  state.tasks = r.tasks;
  seedTasks();
  showTasks();
  if (r.tasks.some(isActive)) poll();
}, 5000);

function poll() {
  if (polling) return;
  polling = setInterval(async () => {
    const r = await api(tasksUrl()).catch(() => null);
    if (!r) return;
    state.tasks = r.tasks;
    showTasks();
    const ended = [];
    for (const t of r.tasks.filter(t => !t.foreign)) {
      const was = lastStatus[t.id], seen = seenLines[t.id] || 0;
      const fresh = t.count > seen ? t.log.slice(-(t.count - seen)) : [];
      lastStatus[t.id] = t.status; seenLines[t.id] = t.count;
      if (t.status === "running" && fresh.some(l => /оценка \d|Скачал и сохранил|Сохранил под номером|▶ Оцениваю/.test(l))) refreshRows();
      if (TASK_ACTIVE.includes(was) && !isActive(t)) ended.push(t);
    }
    if (!r.tasks.some(isActive)) { clearInterval(polling); polling = null; }
    if (!ended.length) return;
    await load(state.profile);
    if (selected) openVacancy(selected);
    ended.filter(t => launched().includes(t.id)).forEach(finished);
  }, 1000);
}

// Задача из этой вкладки закончилась: ошибка — панель с её логом, иначе — сообщение и итоги
function finished(t) {
  if (t.status === "error") return showLog(t.id);
  if (t.status === "removed") return;
  if (!$("joblog").classList.contains("open"))                    // панель открыта — там и так видно
    toast(t.status === "stopped" ? `Остановлено: ${t.title}` : `Готово: ${t.title}`, {label: "Показать лог", onClick: () => showLog(t.id)});
  if (t.action === "tune" && t.status === "done") openCalibration(2);   // показать итог автонастройки
  else if (["fix_suggest", "fix_check", "fix_recheck"].includes(t.action) && t.status === "done" && F.n) openFix(F.n);   // итог правки по вакансии
  else if (["market_advice", "market_recheck"].includes(t.action) && t.status === "done") openMarket(true);   // «Резюме против рынка»
  else if (t.kind === "batch") suggestCalibration();
}

async function run(action, extra) {
  if (state.no_model && NEEDS_MODEL.includes(action)) return toast(NO_MODEL_HINT);
  try {
    const r = await api("/api/run", {profile: state.profile, action, ...extra});
    rememberLaunch(r.task_id);
    const ahead = (state.tasks || []).some(t => isActive(t) && t.queue === r.task.queue && t.id !== r.task_id);
    state.tasks = [...(state.tasks || []).filter(t => t.id !== r.task_id), r.task];
    lastStatus[r.task_id] = r.task.status; seenLines[r.task_id] = 0;
    toast(ahead ? `Поставлено в очередь: ${r.task.title} (${r.position}-я)` : `Запущено: ${r.task.title}`);
    $("btnJob").classList.remove("blink"); void $("btnJob").offsetWidth; $("btnJob").classList.add("blink");
    showTasks(); poll();
  } catch (e) { fail(e); }
}

$("btnJob").onclick = () => setPanel(!$("joblog").classList.contains("open"));
$("jobclose").onclick = () => setPanel(false);
$("joblist").onclick = e => {
  const stop = e.target.closest("[data-stop]");
  if (stop) return api("/api/stop", {profile: state.profile, task_id: +stop.dataset.stop})
    .then(r => { state.tasks = r.tasks; showTasks(); }, fail);
  const row = e.target.closest(".task[data-task]");
  if (row && !e.target.closest("pre")) { openTask = +row.dataset.task === openTask ? null : +row.dataset.task; showTasks(); }
};
