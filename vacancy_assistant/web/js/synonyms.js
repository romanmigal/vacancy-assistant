// Синонимы компаний профиля: названия одной компании («Дойче Банк» = «Deutsche Bank») и пары «это разные».
// Нужны, чтобы находить кандидатов в референсеры, когда в вакансии компания по-русски, а в LinkedIn — по-английски.
// Пополняются из карточки (похожий кандидат «?»), из окна «Контакты» и в «Параметры → Синонимы компаний».
// Обычные скрипты (не модули): подключаются по порядку в index.html и видят функции друг друга.

const synApi = body => api("/api/synonyms/save", {profile: state.profile, ...body});

// Похожий кандидат «?» в карточке: одна ли это компания? Да — запомнить и выбрать, нет — запомнить «разные»
function askSameCompany(vacancyCompany, contact, onSame, onApart) {
  dialog("Одна ли это компания?", `
    <p>В вакансии — <b>${esc(vacancyCompany)}</b>, у контакта ${esc(contact.name)} — <b>${esc(contact.company)}</b>.</p>
    <p class="hint">Ответ запомнится в синонимах компаний профиля: «одна» — у вакансий и контактов с этими названиями совпадение станет точным, «разные» — эта пара больше не будет показываться как похожая. Поменять можно в «Параметры → Синонимы компаний».</p>`,
    [{label: "Отмена", left: true},
     {label: "Нет, разные", onClick: async () => {
       try { await synApi({action: "apart", a: vacancyCompany, b: contact.company}); closeWizard(); toast("Запомнил: разные компании"); onApart && onApart(); }
       catch (e) { fail(e); } }},
     {label: "Да, одна — выбрать", primary: true, onClick: async () => {
       try { await synApi({action: "same", a: vacancyCompany, b: contact.company}); closeWizard(); toast("Запомнил: одна компания"); onSame && onSame(); }
       catch (e) { fail(e); } }}]);
}

// Окно «Контакты»: компания контакта — та же, что у вакансий («MTS» = «МТС Банк»)
async function sameCompanyFor(contact, after) {
  const mine = [...new Set(state.rows.map(r => r.company).filter(Boolean))].sort((a, b) => a.localeCompare(b, "ru"));
  dialog("Та же компания, что…", `
    <p>Компания контакта ${esc(contact.name)}: <b>${esc(contact.company)}</b>.</p>
    ${field("Это та же компания, что", `<input id="synOther" class="wide" list="synList" placeholder="Название из вакансий или любое другое">
      <datalist id="synList">${mine.map(c => `<option value="${esc(c)}">`).join("")}</datalist>`,
      "Начните вводить — подскажут компании из ваших вакансий. Совпадение станет точным для всех вакансий и контактов с этими названиями.")}`,
    [{label: "Отмена", onClick: () => after ? after() : closeWizard()},
     {label: "Запомнить", primary: true, onClick: async () => {
       const other = $("synOther").value.trim();
       if (!other) return $("synOther").focus();
       try { await synApi({action: "same", a: other, b: contact.company}); toast("Запомнил: одна компания"); await refreshRows(); after ? after() : closeWizard(); }
       catch (e) { fail(e); } }}]);
  $("synOther").focus();
}

// «Параметры → Синонимы компаний»: группы одной компании и пары «разные» — разъединить, удалить, добавить
async function openSynonyms() {
  closeMenus();
  const d = await api(`/api/synonyms?profile=${encodeURIComponent(state.profile)}`).catch(fail);
  if (!d) return;
  const save = async (groups, apart, done) => {
    try { await synApi({action: "set", groups, apart}); toast(done); await refreshRows(); openSynonyms(); } catch (e) { fail(e); }
  };
  dialog("Синонимы компаний", `
    <p class="hint">Разные названия одной компании — например, в вакансии «Дойче Банк», а в LinkedIn «Deutsche Bank». По ним программа находит знакомых в компании вакансии (кандидатов в референсеры). Многое программа узнаёт сама — без «ООО» и кавычек, латиницей и кириллицей; здесь — то, что правилами не свести. Синонимы — свои у каждого профиля.</p>
    ${field("Одна компания", d.groups.length ? `<div class="synlist">${d.groups.map((g, i) => `<div class="synrow"><span>${g.map(esc).join(" = ")}</span>
      <button type="button" class="small" data-split="${i}" title="Названия снова будут разными компаниями">Разъединить</button></div>`).join("")}</div>`
      : '<p class="hint">Пока нет. Добавьте ниже, отметьте похожего кандидата «?» в карточке вакансии или нажмите «≡» у контакта в окне «Контакты».</p>')}
    ${d.apart.length ? field("Разные компании", `<div class="synlist">${d.apart.map((p, i) => `<div class="synrow"><span>${esc(p[0])} ≠ ${esc(p[1])}</span>
      <button type="button" class="small" data-unapart="${i}" title="Пара снова может показываться как похожая">Удалить</button></div>`).join("")}</div>`) : ""}
    ${field("Добавить", `<div class="synadd"><input id="synA" list="synAll" placeholder="Дойче Банк"> = <input id="synB" list="synAll" placeholder="Deutsche Bank">
      <button type="button" id="synAdd">Одна компания</button></div>
      <datalist id="synAll">${d.companies.map(c => `<option value="${esc(c)}">`).join("")}</datalist>`,
      "Подсказки — компании из ваших вакансий и контактов. Если одно из названий уже есть в группе, второе добавится к ней.")}`,
    [{label: "Закрыть"}]);
  document.querySelectorAll("[data-split]").forEach(b => b.onclick = () =>
    save(d.groups.filter((_, i) => i !== +b.dataset.split), d.apart, "Названия разъединены"));
  document.querySelectorAll("[data-unapart]").forEach(b => b.onclick = () =>
    save(d.groups, d.apart.filter((_, i) => i !== +b.dataset.unapart), "Пара удалена"));
  $("synAdd").onclick = async () => {
    const a = $("synA").value.trim(), b = $("synB").value.trim();
    if (!a || !b) return (a ? $("synB") : $("synA")).focus();
    try { await synApi({action: "same", a, b}); toast("Запомнил: одна компания"); await refreshRows(); openSynonyms(); } catch (e) { fail(e); }
  };
}

$("mSynonyms").onclick = openSynonyms;
