// Окно «Компании»: компании по вакансиям профиля — тип, сайт, страница на hh с рейтингом, ИТ-аккредитация,
// отчётность, вакансии.
// Сведения те же, что в блоке «О компании» карточки; пометка «агентство» — общая для списка и карточки.
let companiesCache = null;
let companiesFilter = {text: "", sort: "name"};

// «ООО «Ромашка»» и «ромашка» — одно и то же для поиска
const coNorm = s => ` ${(s || "").toLowerCase().replace(/ё/g, "е").replace(/[«»"'„“”]/g, " ")} `
  .replace(/\s(ооо|оао|пао|зао|ао|нао|ип|llc|ltd|inc|gmbh)(?=\s)/g, " ").replace(/\s+/g, " ").trim();

async function openCompanies() {
  closeMenus();
  companiesCache = await api(`/api/companies?profile=${encodeURIComponent(state.profile)}`).catch(fail);
  if (!companiesCache) return;
  dialog("Компании", `
    <p class="hint">Компании из вакансий профиля. Сведения те же, что в карточке вакансии в блоке «О компании»; пометка «кадровое агентство» действует на все вакансии компании.</p>
    <div class="ctools">
      <input type="search" id="coSearch" placeholder="Поиск по названию компании" value="${esc(companiesFilter.text)}">
      <label class="checks">Порядок <select id="coSort">
        <option value="name">по названию</option><option value="count">по числу вакансий</option><option value="rating">по рейтингу hh</option><option value="it">сначала с ИТ-аккредитацией</option>
      </select></label>
    </div>
    <div id="coList"></div>`, [{label: "Закрыть"}]);
  $("wiz").classList.add("wide");
  $("coSort").value = companiesFilter.sort;
  $("coSearch").oninput = () => { companiesFilter.text = $("coSearch").value; renderCompanies(); };
  $("coSort").onchange = () => { companiesFilter.sort = $("coSort").value; renderCompanies(); };
  renderCompanies();
  $("coSearch").focus();
}

function companyRow(c) {
  const num = x => String(x).replace(".", ",");
  const host = u => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch (e) { return u; } };
  const vacs = c.vacancies.map(n => state.rows.find(r => r.n === n)).filter(Boolean);
  const type = c.agency
    ? `<span class="chip agency" title="${esc(c.marked ? "Отмечено вами" : `${AGENCY_WHY[c.agency_why] || ""}${c.agency_why === "text" && c.agency_what ? `: «${c.agency_what}»` : ""}`)}">Кадровое агентство</span>`
    : `<span class="chip employer">Работодатель</span>`;
  const mark = `<button type="button" class="markbtn" data-coagency="${c.agency ? 0 : 1}" data-n="${c.n}">${c.agency ? "отметить, что это не агентство" : "отметить, что это кадровое агентство"}</button>`;
  const hh = c.hh ? `<a href="${esc(c.hh.url)}" target="_blank" rel="noopener" title="Страница работодателя на hh">hh.ru</a>
      ${c.hh.rating != null ? `<b>★ ${num(c.hh.rating)}</b>${c.hh.reviews != null ? ` <span class="muted">${c.hh.reviews} ${plural(c.hh.reviews, "отзыв", "отзыва", "отзывов")}</span>` : ""}`
        : `<span class="muted">${c.hh.rating_date ? "отзывов нет" : "без рейтинга"}</span>`}` : `<span class="muted">—</span>`;
  return `<tr>
    <td><button type="button" class="linkbtn cofilter coname" data-cofilter="${esc(JSON.stringify(c.names.length ? c.names : [c.name]))}" title="Все вакансии этой компании — во вкладке «Фильтр»">${esc(c.name)}</button>${c.names.length > 1 ? `<div class="cnote" title="Так компания названа в других вакансиях">${c.names.slice(1).map(esc).join(", ")}</div>` : ""}</td>
    <td>${type}<div>${mark}</div></td>
    <td>${c.site ? `<a href="${esc(c.site)}" target="_blank" rel="noopener">${esc(host(c.site))}</a>` : `<span class="muted">—</span>`}</td>
    <td class="nowrap">${hh}</td>
    <td>${c.hh?.it === true ? `<span class="s-good">есть</span>` : c.hh?.it === false ? "нет" : `<span class="muted" title="hh не сообщил — или вакансия не с hh">—</span>`}</td>
    <td>${c.finance ? `<a href="${esc(c.finance.url)}" target="_blank" rel="noopener" title="${c.finance.by_inn ? "Поиск по ИНН из текста вакансии" : "Поиск по названию — выберите компанию в списке по адресу"}">ФНС</a>` : `<span class="muted">—</span>`}</td>
    <td>${coVacancies(c.vacancies)}</td>
  </tr>`;
}

// Вакансии компании: название — строкой-ссылкой, под ним оценка и раздел
function coVacancies(ns) {
  const status = k => (state.statuses.find(([s]) => s === k) || [, ""])[1];
  return `<ul class="covacs">${ns.map(n => state.rows.find(r => r.n === n)).filter(Boolean).map(r => `<li><button type="button" class="linkbtn" data-covac="${r.n}">${esc(r.title)}</button>
      <div class="covmeta">${r.score != null ? `Оценка: <b class="${scoreClass(r.score)}">${r.score}</b>` : "Без оценки"} · Раздел: ${esc(status(r.status))}</div></li>`).join("")}</ul>`;
}

// Строка «Работодатель скрыт» — всегда в конце списка: вакансии без названия компании и как её узнать
function anonymousRow(ns) {
  return `<tr class="coanon">
    <td><b>Работодатель скрыт</b><div class="cnote">${ns.length} ${plural(ns.length, "вакансия", "вакансии", "вакансий")}</div></td>
    <td><span class="chip">Работодатель скрыт</span></td>
    <td colspan="4"><details class="coanonhelp"><summary>Как узнать компанию</summary><ul>
      <li><b>Спросите рекрутера.</b> На первом звонке или в ответе на отклик название обычно называют — прямо спросите, о какой компании речь.</li>
      <li><b>Поищите текст вакансии.</b> Скопируйте необычную фразу из описания и найдите её в Яндексе или Google в кавычках: компания часто публикует ту же вакансию открыто — на своём сайте или на другом сайте вакансий.</li>
      <li><b>Соберите приметы.</b> Отрасль, продукт, размер команды, системы и стек, город, метро или адрес офиса — по ним компания нередко угадывается; адрес — проверьте на карте, кто сидит в здании.</li>
      <li><b>Спросите знакомых.</b> Покажите описание тем, кто работает в отрасли, или поищите в LinkedIn и Сетке людей с похожей должностью — бывшие сотрудники узнают компанию по описанию.</li>
      <li><b>Узнали компанию</b> — напишите её в комментарии к вакансии: так видно, к кому вы уже откликались.</li>
    </ul></details></td>
    <td>${coVacancies(ns)}</td>
  </tr>`;
}

const itRank = c => c.hh?.it === true ? 0 : c.hh?.it === false ? 1 : 2;

function renderCompanies() {
  const all = companiesCache.items, anon = companiesCache.anonymous;
  const q = coNorm(companiesFilter.text);
  const list = all.filter(c => !q || c.names.some(n => coNorm(n).includes(q)));
  const by = {
    name: (a, b) => a.name.localeCompare(b.name, "ru"),
    count: (a, b) => b.vacancies.length - a.vacancies.length || a.name.localeCompare(b.name, "ru"),
    rating: (a, b) => (b.hh?.rating ?? -1) - (a.hh?.rating ?? -1) || a.name.localeCompare(b.name, "ru"),
    it: (a, b) => itRank(a) - itRank(b) || a.name.localeCompare(b.name, "ru"),   // есть, нет, нет сведений
  }[companiesFilter.sort];
  list.sort(by);
  const anonShown = anon.length && (!q || ["работодатель скрыт", "анонимный", "не указана"].some(w => w.includes(q)));
  $("coList").innerHTML = !all.length
    ? `<p class="empty">Компаний пока нет — они появятся, когда в списке будут вакансии.</p>`
    : `<p class="hint">${list.length === all.length ? `Всего: ${all.length}` : `Найдено ${list.length} из ${all.length}`}
        ${anon.length ? ` · со скрытым работодателем: ${anon.length} ${plural(anon.length, "вакансия", "вакансии", "вакансий")} — в конце списка` : ""}</p>
      ${list.length || anonShown ? `<div class="ctable"><table class="contacts companies"><thead><tr><th>Название</th><th>Тип</th><th>Сайт</th><th>Страница на hh</th><th title="Аккредитация Минцифры, как её указывает hh">ИТ-аккредитация</th><th>Отчётность</th><th>Вакансии</th></tr></thead>
        <tbody>${list.map(companyRow).join("")}${anonShown ? anonymousRow(anon) : ""}</tbody></table></div>` : `<p class="muted">Ничего не нашлось.</p>`}`;
  document.querySelectorAll("#coList [data-cofilter]").forEach(b => b.onclick = () => { closeWizard(); openCompanyFilter(JSON.parse(b.dataset.cofilter)); });
  document.querySelectorAll("#coList [data-covac]").forEach(b => b.onclick = () => {
    const n = +b.dataset.covac, row = state.rows.find(r => r.n === n);
    closeWizard();
    if (row) { tab = row.status; openVacancy(n); }
  });
  document.querySelectorAll("#coList [data-coagency]").forEach(b => b.onclick = async () => {
    const v = b.dataset.coagency === "1";
    if (await api("/api/company/agency", {profile: state.profile, n: +b.dataset.n, agency: v}).catch(fail) === undefined) return;
    toast(v ? "Отмечено: кадровое агентство — для всех вакансий компании" : "Отмечено: работодатель — для всех вакансий компании");
    companiesCache = await api(`/api/companies?profile=${encodeURIComponent(state.profile)}`).catch(fail) || companiesCache;
    renderCompanies();
    await refreshRows();
  });
}

$("mCompanies").onclick = openCompanies;
