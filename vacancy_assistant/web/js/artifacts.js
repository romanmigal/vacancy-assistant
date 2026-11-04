// Вкладка «Артефакты»: что ушло работодателю или пришло от него — отправленные письма и резюме
// (отметка «Отправлено» на вкладках «Письма» и «Резюме»), приложенные файлы и заметки о переписке. Новые сверху
const ART_ICONS = {
  file: '<path d="M21.4 11.1 12.2 20.3a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5"/>',
  note: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
  open: '<path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  remove: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/>',
};
Object.assign(TOOL_ICONS, ART_ICONS);
const ART_KIND = {cover: "Письмо", referrer: "Референсеру", resume: "Резюме", file: "Файл", note: "Заметка"};
const artSize = size => size >= 1048576 ? `${(size / 1048576).toFixed(1)} МБ` : `${Math.max(1, Math.round(size / 1024))} КБ`;

function artifactsTab(r, d, n) {
  const list = d.artifacts || [];
  return `<p class="hint">Всё, что ушло работодателю или пришло от него. Письма и резюме попадают сюда отметкой «Отправлено» на вкладках «Письма» и «Резюме»; файлы — тестовое, презентация, оффер — копируются в папку профиля и попадают в резервную копию.</p>
    <p class="lettertools">${ibtn("artFile", "file", "Приложить файл — копия в папке профиля, до 25 МБ", "primary", "Файл")}
      ${ibtn("artNote", "note", "Заметка о переписке — например, ответ HR в Telegram", "", "Заметка")}
      <input type="file" id="artInput" hidden></p>
    ${list.length ? `<div class="artlist">${list.map((e, i) => `<div class="artitem ${e.missing ? "missing" : ""}">
        <div class="arthead"><span class="hkind">${ART_KIND[e.type] || e.type}</span><b>${esc(e.title)}</b>
          <span class="muted">${ddmm(e.date)}.${e.date.slice(0, 4)}${e.size ? " · " + artSize(e.size) : ""}${e.missing ? " · файла нет на месте" : ""}</span>
          <span class="arttools">${e.text != null ? ibtn(`artCopy${i}`, "copy", "Скопировать текст") : ""}
            ${e.type === "file" ? ibtn(`artOpen${i}`, "open", REMOTE ? "Открыть файл можно только на основном компьютере" : "Открыть файл") : ""}
            ${ibtn(`artDel${i}`, "remove", ["cover", "referrer", "resume"].includes(e.type)
              ? "Убрать из артефактов — в Корзину; отметка «Отправлено» у версии тоже снимется" : "Убрать из артефактов — в Корзину")}</span></div>
        ${e.text && !e.text.includes("\n") && e.text.length <= 200 ? `<div class="artshort">${esc(e.text)}</div>`
          : e.text ? `<details class="arttext" ${i === 0 && e.text.length < 600 ? "open" : ""}><summary>${esc(e.text.split("\n").find(Boolean).slice(0, 120))}</summary><div class="letter">${esc(e.text)}</div></details>` : ""}
      </div>`).join("")}</div>`
      : `<p class="muted">Артефактов пока нет.</p>`}`;
}

function bindArtifacts(d, n) {
  const list = d.artifacts || [];
  const done = res => { if (res) { refreshRows(); openVacancy(n); } };
  $("artFile").onclick = () => $("artInput").click();
  $("artInput").onchange = async e => {
    const file = e.target.files[0];
    if (!file) return;
    if (file.size > 25 * 1048576) return toast("Файл больше 25 МБ — его в программу не взять");
    toast(`Прикладываю «${file.name}»…`);
    done(await api("/api/artifacts/add", {profile: state.profile, n, do: "file", name: file.name, data: await fileB64(file)}).catch(fail));
  };
  $("artNote").onclick = () => {
    const today = new Date().toLocaleDateString("sv-SE");
    dialog("Заметка о переписке", `
      <div class="row2">${field("О чём", `<input id="anTitle" maxlength="80" placeholder="например: Ответ HR в Telegram">`)}
        ${field("Когда", `<input type="date" id="anDate" value="${today}" max="${today}">`)}</div>
      ${field("Текст", `<textarea id="anText" class="tall" placeholder="Что написали вам или вы — своими словами или копией сообщения"></textarea>`)}`,
      [{label: "Отмена"}, {label: "Сохранить", primary: true, onClick: async () => {
        if (!$("anText").value.trim()) return toast("Текст пустой");
        const res = await api("/api/artifacts/add", {profile: state.profile, n, do: "note", title: $("anTitle").value,
          text: $("anText").value, date: $("anDate").value}).catch(fail);
        if (res) { closeWizard(); done(res); toast("Заметка сохранена"); }
      }}]);
  };
  list.forEach((e, i) => {
    if ($(`artCopy${i}`)) $(`artCopy${i}`).onclick = () => navigator.clipboard.writeText(e.text).then(() => toast("Скопировано"), fail);
    if ($(`artOpen${i}`)) $(`artOpen${i}`).onclick = () => REMOTE ? toast("Открыть файл можно только на основном компьютере")
      : api("/api/artifacts/open", {profile: state.profile, n, id: e.id}).catch(fail);
    $(`artDel${i}`).onclick = async () => {
      if (!confirm(`Убрать «${e.title}» из артефактов? Файл уйдёт в Корзину.`)) return;
      done(await api("/api/artifacts/remove", {profile: state.profile, n, id: e.id}).catch(fail));
    };
  });
}
