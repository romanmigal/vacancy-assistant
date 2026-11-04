// Трекер контактов: список знакомых (выгрузка LinkedIn и вручную), статус переписки, заметка;
// в карточке вакансии — кандидаты в референсеры из этого списка.
// Обычные скрипты (не модули): подключаются по порядку в index.html и видят функции друг друга.

let contactsCache = null;                     // {contacts, statuses} — последний ответ /api/contacts
let contactsFilter = {text: "", withVacancies: false};

async function loadContacts() {
  contactsCache = await api(`/api/contacts?profile=${encodeURIComponent(state.profile)}`);
  return contactsCache;
}

const statusName = v => ((contactsCache?.statuses || []).find(s => s[0] === v) || ["", "—"])[1];

async function openContacts() {
  closeMenus();
  if (!await loadContacts().catch(fail)) return;
  dialog("Контакты", `
    <p class="hint">Знакомые, через которых можно подать резюме. Программа сама сверяет их компании с компаниями вакансий и показывает кандидатов в референсеры в карточке вакансии. Контакты хранятся только на этом компьютере.</p>
    <div class="ctools">
      <input type="search" id="cSearch" placeholder="Поиск: имя, компания, должность" value="${esc(contactsFilter.text)}">
      <label class="checks"><input type="checkbox" id="cWithVac" ${contactsFilter.withVacancies ? "checked" : ""}> только с вакансиями</label>
      <span class="grow"></span>
      <button type="button" id="cImport">Загрузить из LinkedIn…</button>
      <button type="button" class="primary" id="cAdd">+ Добавить</button>
      <input type="file" id="cFile" accept=".zip,.csv" hidden>
    </div>
    <details class="chelp"><summary>Как выгрузить контакты из LinkedIn</summary>
      <ol><li>LinkedIn → «Я» → «Настройки и конфиденциальность» → «Конфиденциальность данных» → «Получить копию своих данных» (Download my data).</li>
        <li>Выберите <b>первый вариант — «Download larger data archive, including connections…»</b> и нажмите «Request archive». Отдельные пункты ниже (Articles, Invitations, Profile…) не подходят: в них нет списка контактов, Invitations — это только приглашения.</li>
        <li>LinkedIn пришлёт <b>два письма</b>: сначала базовый архив (без контактов), примерно через сутки — полный (<b>Complete_…</b>). Загружайте полный: скачайте архив .zip и загрузите его сюда как есть — программа сама возьмёт из него файл Connections.csv и больше ничего не прочитает.</li></ol>
      <p class="hint">Если человек уже есть в контактах (узнаём по ссылке на профиль или по имени — кириллицей или латиницей), дубля не будет: компания и должность возьмутся из LinkedIn, а прежние, если были другими, допишутся в заметку («раньше: …»); имя, статус и заметка сохранятся. Почту в выгрузке LinkedIn видно, только если человек это разрешил.</p></details>
    <div id="cList"></div>`, [{label: "Закрыть"}]);
  $("wiz").classList.add("wide");
  $("cSearch").oninput = () => { contactsFilter.text = $("cSearch").value; renderContacts(); };
  $("cWithVac").onchange = () => { contactsFilter.withVacancies = $("cWithVac").checked; renderContacts(); };
  $("cAdd").onclick = () => editContact({}, openContacts);
  $("cImport").onclick = () => $("cFile").click();
  $("cFile").onchange = async () => {
    const f = $("cFile").files[0];
    if (!f) return;
    const data = await new Promise((ok, bad) => {
      const rd = new FileReader();
      rd.onload = () => ok(rd.result.split(",")[1]); rd.onerror = bad; rd.readAsDataURL(f);
    });
    try {
      const r = await api("/api/contacts/import", {profile: state.profile, name: f.name, data});
      toast(`LinkedIn: ${r.read} ${plural(r.read, "контакт", "контакта", "контактов")} — новых ${r.added}, обновлено ${r.updated}`
            + (r.conflicts ? `; у ${r.conflicts} компания или должность была другой — прежнее записано в заметку` : ""));
      await refreshRows();
      openContacts();
    } catch (e) { fail(e); }
  };
  renderContacts();
}

function renderContacts() {
  const all = contactsCache.contacts;
  const q = contactsFilter.text.trim().toLowerCase();
  const list = all.filter(c => (!contactsFilter.withVacancies || c.vacancies.length)
    && (!q || [c.name, c.company, c.position, c.note].join(" ").toLowerCase().includes(q)));
  const shown = list.slice(0, 300);
  $("cList").innerHTML = !all.length
    ? `<p class="empty">Контактов пока нет. Загрузите выгрузку LinkedIn или добавьте знакомых вручную.</p>`
    : `<p class="hint">${list.length === all.length ? `Всего: ${all.length}` : `Найдено ${list.length} из ${all.length}`}${list.length > shown.length ? ` — показаны первые ${shown.length}, уточните поиск` : ""}. С вакансиями в их компаниях: ${all.filter(c => c.vacancies.length).length}.</p>
      <div class="ctable"><table class="contacts"><thead><tr><th>Имя</th><th>Компания</th><th>Должность</th><th>Статус</th><th title="Вакансии в компании контакта">Вакансии</th><th></th></tr></thead><tbody>
      ${shown.map(c => `<tr data-id="${c.id}">
        <td>${c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener">${esc(c.name)}</a>` : esc(c.name)}${c.source === "linkedin" ? ' <span class="src" title="Из выгрузки LinkedIn">in</span>' : ""}${c.note ? `<div class="cnote">${esc(c.note)}</div>` : ""}</td>
        <td>${esc(c.company)}</td><td class="muted">${esc(c.position)}</td>
        <td><select data-status="${c.id}">${contactsCache.statuses.map(([v, n]) => `<option value="${v}" ${v === c.status ? "selected" : ""}>${n}</option>`).join("")}</select>${c.status && c.status_date ? ` <span class="muted sdate" title="Когда отмечен статус">${ddmm(c.status_date)}</span>` : ""}</td>
        <td>${c.vacancies.map(v => `<button type="button" class="small ${v.exact ? "" : "near"}" data-vac="${v.n}" title="${v.exact ? "Открыть вакансию" : "Похожее название компании — проверьте. Открыть вакансию"}">${String(v.n).padStart(2, "0")}${v.exact ? "" : "?"}</button>`).join(" ")}</td>
        <td class="nowrap"><button type="button" class="small" data-edit="${c.id}" title="Изменить">✎</button> <button type="button" class="small danger" data-del="${c.id}" title="Удалить">✕</button></td>
      </tr>`).join("")}</tbody></table></div>`;
  const byId = id => all.find(c => c.id === id);
  document.querySelectorAll("[data-status]").forEach(s => s.onchange = async () => {
    const c = byId(s.dataset.status);
    await api("/api/contacts/save", {profile: state.profile, contact: {...c, status: s.value}}).catch(fail);
    c.status = s.value; c.status_date = s.value ? todayIso() : "";
    renderContacts(); refreshRows(); toast("Статус сохранён");
  });
  document.querySelectorAll("[data-edit]").forEach(b => b.onclick = () => editContact(byId(b.dataset.edit), openContacts));
  document.querySelectorAll("[data-del]").forEach(b => b.onclick = async () => {
    const c = byId(b.dataset.del);
    if (!confirm(`Удалить контакт «${c.name}»?`)) return;
    await api("/api/contacts/delete", {profile: state.profile, id: c.id}).catch(fail);
    contactsCache.contacts = all.filter(x => x.id !== c.id); renderContacts(); refreshRows();
  });
  document.querySelectorAll("[data-vac]").forEach(b => b.onclick = () => {
    const n = +b.dataset.vac, row = state.rows.find(r => r.n === n);
    closeWizard();
    if (row) { tab = row.status; openVacancy(n); }
  });
}

// Новый контакт или правка; after — что открыть после сохранения (список контактов или карточку)
function editContact(c, after) {
  const f = (key, label, ph = "") => field(label, `<input id="ce_${key}" class="wide" value="${esc(c[key] || "")}" placeholder="${ph}">`);
  dialog(c.id ? "Контакт" : "Новый контакт", `
    <div class="row2">${f("name", "Имя *", "Иван Петров")}${f("company", "Компания", "МТС")}</div>
    <div class="row2">${f("position", "Должность", "директор по ИТ")}${f("url", "Ссылка на профиль", "LinkedIn, Сетка, Telegram")}</div>
    <div class="row2">${f("email", "Почта или телефон")}
      ${field("Статус", `<select id="ce_status">${(contactsCache?.statuses || [["", "—"]]).map(([v, n]) => `<option value="${v}" ${v === (c.status || "") ? "selected" : ""}>${n}</option>`).join("")}</select>`)}</div>
    ${field("Заметка", `<textarea id="ce_note" rows="2" placeholder="откуда знакомы, о чём договорились">${esc(c.note || "")}</textarea>`)}`,
    [{label: "Отмена", onClick: () => after ? after() : closeWizard()},
     {label: "Сохранить", primary: true, onClick: async () => {
       const contact = {id: c.id};
       for (const k of ["name", "company", "position", "url", "email", "status", "note"]) contact[k] = $("ce_" + k).value.trim();
       if (!contact.name) return toast("Укажите имя");
       try {
         const r = await api("/api/contacts/save", {profile: state.profile, contact});
         await refreshRows();
         if (after) after({...contact, id: r.id}); else closeWizard();
       } catch (e) { fail(e); }
     }}]);
  $("ce_name").focus();
}

// Кандидаты в референсеры в карточке: выбрать одного — он станет референсером вакансии
function referrerCandidates(r, d) {
  const list = (d.referrer_candidates || []).filter(c => c.id !== r.referrer_contact?.id);   // уже выбранного — не повторяем
  if (!r.analyzed) return "";
  const chips = list.map(c => {
    const label = [c.name, c.position].filter(Boolean).join(", ");
    return `<button type="button" class="chip ${c.exact ? "" : "near"}" data-pick="${esc(c.id)}"
      title="${esc(c.company)}${c.exact ? "" : " — похожее название компании, проверьте"}${c.status ? " · " + esc(statusName(c.status)) : ""}">${esc(label)}${c.exact ? "" : " ?"}</button>`;
  }).join("");
  return `<div class="refcands">${list.length ? `<span class="hint">Из контактов:</span> ${chips}`
      : `<span class="hint">${(d.referrer_candidates || []).length ? "Других" : "В контактах никого"} из «${esc(r.people_query || r.company)}»${(d.referrer_candidates || []).length ? " в контактах нет" : ""}.</span>`}
    <button type="button" class="linkbtn" id="addContact">+ новый контакт…</button></div>`;
}

function bindReferrerCandidates(r, d, n) {
  const pick = async c => {
    const text = [c.name, c.position, c.company].filter(Boolean).join(", ");
    await api("/api/referrer", {profile: state.profile, n, text, contact_id: c.id}).catch(fail);
    r.referrer = text; render(); openVacancy(n); toast("Референсер выбран");
  };
  document.querySelectorAll("[data-pick]").forEach(b => b.onclick = () => pick(d.referrer_candidates.find(c => c.id === b.dataset.pick)));
  if ($("openReferrer")) $("openReferrer").onclick = () => openReferrer(r);
  if ($("addContact")) $("addContact").onclick = async () => {
    if (!contactsCache) await loadContacts().catch(() => {});
    editContact({company: r.company}, async c => { closeWizard(); if (c) await pick(c); });
  };
}

// Карточка референсера вакансии: контакт из трекера — правка; вписан вручную — новый контакт из этого текста,
// после сохранения он и становится референсером (связь с контактом)
async function openReferrer(r) {
  if (!contactsCache) await loadContacts().catch(fail);
  const back = async () => { closeWizard(); await refreshRows(); if (selected === r.n) openVacancy(r.n); };
  const linked = r.referrer_contact && (contactsCache?.contacts || []).find(c => c.id === r.referrer_contact.id);
  if (linked) return editContact(linked, back);
  const [name, position, ...rest] = (r.referrer || "").split(",").map(x => x.trim());
  editContact({name, position, company: rest.join(", ") || r.company}, async c => {
    if (c) await api("/api/referrer", {profile: state.profile, n: r.n, contact_id: c.id,
                                       text: [c.name, c.position, c.company].filter(Boolean).join(", ")}).catch(fail);
    await loadContacts().catch(() => {});
    back();
  });
}

$("mContacts").onclick = openContacts;
