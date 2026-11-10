// Колонки таблицы вакансий: какие показывать и в каком порядке. Меню — кнопка справа от вкладок статусов;
// флажок показывает или скрывает колонку, порядок — перетаскиванием или стрелками. Настройка хранится в профиле.
// Обычные скрипты (не модули): подключаются по порядку в index.html и видят функции друг друга.

const COLUMN_NAMES = {flag: "⚑ Флаг", score: "Оценка ИИ (могу/хочу)"};   // в меню понятнее, чем заголовок колонки

async function saveColumns(order, hidden) {
  const prev = state.columns;
  state.columns = {order, hidden};
  render(); renderColumns();
  try { await api("/api/profile/settings", {profile: state.profile, columns: state.columns}); }
  catch (e) { state.columns = prev; render(); renderColumns(); fail(e); }
}

function renderColumns() {
  const m = $("colsMenu");
  if (m.hidden) return;
  const list = tableColumns(), last = list.length - 1;
  m.innerHTML = `<div class="mhead">Колонки таблицы</div>` + list.map(({col: [key, name], hidden}, i) => `
    <div class="crow ${hidden ? "off" : ""}" draggable="true" data-col="${key}">
      <span class="grip" title="Перетащите, чтобы поменять порядок" aria-hidden="true">⠿</span>
      <label title="${key === LOCKED_COLUMN ? "«Вакансию» не скрыть: без неё строку не узнать" : ""}"><input type="checkbox" data-show="${key}" ${hidden ? "" : "checked"} ${key === LOCKED_COLUMN ? "disabled" : ""}>${esc(COLUMN_NAMES[key] || name)}${columnHere(key) ? "" : ' <span class="muted" title="Колонка видна только во вкладке «Фильтр»: в остальных вкладках у всех вакансий один статус. Место в таблице и флажок можно менять отсюда">(во вкладке «Фильтр»)</span>'}</label>
      <button type="button" class="mv" data-up="${i}" ${i ? "" : "disabled"} title="Выше — левее в таблице" aria-label="Выше">↑</button>
      <button type="button" class="mv" data-down="${i}" ${i < last ? "" : "disabled"} title="Ниже — правее в таблице" aria-label="Ниже">↓</button>
    </div>`).join("") + `
    <div class="cfoot"><span class="hint">Сверху вниз — слева направо</span><button type="button" id="colsReset" ${list.some(({col: [key], hidden}, i) => key !== COLUMNS[i][0] || hidden !== DEFAULT_HIDDEN.includes(key)) ? "" : "disabled"} title="Колонки и порядок по умолчанию: всё, кроме «Опубликовано», «Моей оценки», «Референсера» и «Артефактов»">По умолчанию</button></div>`;
}

const columnKeys = () => tableColumns().map(x => x.col[0]);
const hiddenKeys = () => tableColumns().filter(x => x.hidden).map(x => x.col[0]);
function moveColumn(from, to) {
  const keys = columnKeys();
  if (to < 0 || to >= keys.length || from === to) return;
  keys.splice(to, 0, keys.splice(from, 1)[0]);
  saveColumns(keys, hiddenKeys());
}

$("btnCols").onclick = e => {
  e.stopPropagation();
  closeMenus("colsMenu");
  const m = $("colsMenu"), b = $("btnCols").getBoundingClientRect();
  m.hidden = !m.hidden;
  m.style.top = b.bottom + 4 + "px";                   // поверх окна: панель таблицы прокручивается и обрезала бы меню
  m.style.right = Math.max(8, innerWidth - b.right) + "px";
  renderColumns();
};
$("colsMenu").onclick = e => {
  e.stopPropagation();
  const b = e.target.closest("button");
  if (!b) return;
  if (b.id === "colsReset") return saveColumns([], []);
  if (b.dataset.up) moveColumn(+b.dataset.up, +b.dataset.up - 1);
  if (b.dataset.down) moveColumn(+b.dataset.down, +b.dataset.down + 1);
};
$("colsMenu").onchange = e => {
  const key = e.target.dataset.show;
  if (!key) return;
  const hidden = hiddenKeys().filter(k => k !== key);
  saveColumns(columnKeys(), e.target.checked ? hidden : [...hidden, key]);
};
// Перетаскивание строк меню: бросили на строку — колонка встаёт на её место
let dragCol = null;
$("colsMenu").ondragstart = e => {
  const row = e.target.closest("[data-col]");
  if (!row) return;
  dragCol = row.dataset.col; row.classList.add("drag");
  e.dataTransfer.effectAllowed = "move";
  try { e.dataTransfer.setData("text/plain", dragCol); } catch (err) {}
};
$("colsMenu").ondragover = e => {
  const row = e.target.closest("[data-col]");
  if (!row || !dragCol) return;
  e.preventDefault();
  document.querySelectorAll("#colsMenu .over").forEach(x => x.classList.remove("over"));
  row.classList.add("over");
};
$("colsMenu").ondrop = e => {
  e.preventDefault();
  const row = e.target.closest("[data-col]"), keys = columnKeys();
  if (row && dragCol) moveColumn(keys.indexOf(dragCol), keys.indexOf(row.dataset.col));
  dragCol = null;
};
$("colsMenu").ondragend = () => { dragCol = null; renderColumns(); };
document.addEventListener("click", () => { $("colsMenu").hidden = true; });
