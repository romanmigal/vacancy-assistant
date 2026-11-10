// Шаблоны сопроводительного письма: до трёх, у каждого название и своя история правок; один — по умолчанию.
// Основной — прежний «образец письма»: его же правит шаг «Образец письма» в мастере профиля
const tplQuery = () => `profile=${encodeURIComponent(state.profile)}`;
const tplWhich = id => id === 1 ? "letter" : `letter:${id}`;

async function openTemplates(pick) {
  const res = await api(`/api/letter/templates?${tplQuery()}`).catch(fail);
  if (res) drawTemplates(res, pick);
}

function drawTemplates(res, pick) {
  const list = res.templates;
  const cur = pick === "new" ? {id: null, name: "", text: "", default: false}
    : list.find(t => t.id === pick) || list.find(t => t.default) || list[0];
  dialog("Шаблоны писем", `
    <p class="hint">Образцы сопроводительного письма — разные по структуре: короткое для hh, развёрнутое для прямого обращения, ответ на вопросы из вакансии. ИИ берёт из шаблона стиль, длину и структуру, а факты — только из резюме и вакансии. Шаблон выбирают перед тем, как ИИ напишет письмо.</p>
    <label class="checks"><input type="checkbox" id="tplSamples" ${res.samples.on ? "checked" : ""}> Учитывать мои отправленные письма</label>
    <p class="hint">ИИ пишет по образцу двух ваших последних отправленных писем к похожей роли — тех, что вы поправили или написали сами и отметили «Отправлено»: их форма, длина и стиль важнее шаблона. Факты — по-прежнему только из резюме и вакансии. ${res.samples.count ? `Таких писем сейчас: ${res.samples.count}.` : "Таких писем пока нет — включённая галочка ничего не меняет."}</p>
    <div class="lkinds">${list.map(t => `<button type="button" class="lkind ${t.id === cur.id ? "on" : ""}" data-tpl="${t.id}">${esc(t.name)}${t.default ? " ★" : ""}</button>`).join("")}
      ${list.length < res.max ? `<button type="button" class="lkind ${cur.id === null ? "on" : ""}" data-tpl="new">+ Новый шаблон</button>` : ""}</div>
    ${field("Название", `<input id="tplName" maxlength="40" value="${esc(cur.name)}" placeholder="например: Короткое для hh">`)}
    ${field("Текст шаблона", `<textarea id="tplText" class="tall" placeholder="Вставьте письмо, которое вам нравится, — ИИ возьмёт из него тон, длину и структуру">${esc(cur.text)}</textarea>`)}
    <label class="checks"><input type="checkbox" id="tplDefault" ${cur.default ? "checked disabled" : ""}> По умолчанию — его ИИ берёт, если шаблон не выбран</label>
    ${cur.id ? `<p><button type="button" id="tplHist">Прежние версии этого шаблона</button></p><div id="tplHistList"></div>` : ""}`,
    [...(cur.id && cur.id !== 1 ? [{label: "Удалить шаблон", left: true, onClick: () => deleteTemplate(cur)}] : []),
     {label: "Закрыть", onClick: () => leaveTemplate(cur, closeWizard)},
     {label: "Сохранить", primary: true, onClick: () => saveTemplate(cur)}]);
  document.querySelectorAll("#wbody [data-tpl]").forEach(b => b.onclick = () =>
    leaveTemplate(cur, () => drawTemplates(res, b.dataset.tpl === "new" ? "new" : +b.dataset.tpl)));
  if ($("tplHist")) $("tplHist").onclick = () => templateHistory(cur);
  $("tplSamples").onchange = async e => {
    const on = e.target.checked;
    const r = await api("/api/letter/templates/save", {profile: state.profile, do: "samples", on}).catch(fail);
    if (r) { res.samples = r.samples; toast(on ? "Отправленные письма учитываются" : "Отправленные письма не учитываются"); }
    else e.target.checked = !on;
  };
}

const tplChanged = cur => $("tplName").value.trim() !== cur.name || $("tplText").value.trim() !== cur.text.trim();
function leaveTemplate(cur, go) {
  if (tplChanged(cur) && !confirm("Шаблон изменён и не сохранён. Выйти без сохранения?")) return;
  go();
}

async function saveTemplate(cur) {
  const res = await api("/api/letter/templates/save", {profile: state.profile, id: cur.id, name: $("tplName").value,
    text: $("tplText").value, default: $("tplDefault").checked}).catch(fail);
  if (!res) return;
  toast(cur.id ? "Шаблон сохранён" : "Шаблон добавлен");
  drawTemplates(res, res.id);
}

async function deleteTemplate(cur) {
  if (!confirm(`Удалить шаблон «${cur.name}»? Он и его прежние версии уйдут в Корзину. Письма, уже написанные по нему, останутся.`)) return;
  const res = await api("/api/letter/templates/save", {profile: state.profile, id: cur.id, do: "delete"}).catch(fail);
  if (!res) return;
  toast("Шаблон удалён");
  drawTemplates(res);
}

// Прежние версии шаблона — у каждого свои; выбранная подставляется в поле, применится по «Сохранить»
async function templateHistory(cur) {
  const box = $("tplHistList");
  if (box.innerHTML) { box.innerHTML = ""; return; }
  const res = await api(`/api/criteria/history?${tplQuery()}&which=${tplWhich(cur.id)}`).catch(fail);
  if (!res) return;
  box.innerHTML = res.versions.length ? res.versions.map((v, i) => `<div class="hver ${v.current ? "cur" : ""}">
      <div><b>${esc(v.date)}</b> · ${esc(v.source)}${v.current ? " · текущий" : ""}
        ${v.current ? "" : `<button type="button" data-tplv="${i}">Подставить</button>`}</div>
      <div class="htext">${esc(v.text.slice(0, 300))}${v.text.length > 300 ? "…" : ""}</div></div>`).join("")
    : `<p class="hint">Прежних версий пока нет — они появятся после правки шаблона.</p>`;
  box.querySelectorAll("[data-tplv]").forEach(b => b.onclick = () => {
    $("tplText").value = res.versions[+b.dataset.tplv].text;
    toast("Версия подставлена — нажмите «Сохранить», чтобы применить");
  });
}
