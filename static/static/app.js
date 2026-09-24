const $ = (sel) => document.querySelector(sel);
let state = null;

function money(n) {
  const cur = (state?.settings?.currency || "$");
  const sign = n < 0 ? "-" : "";
  return `${sign}${cur}${Math.abs(Number(n) || 0).toFixed(2)}`;
}

function toast(msg) {
  const el = $("#toast");
  el.hidden = false;
  el.textContent = msg;
  setTimeout(() => { el.hidden = true; }, 2800);
}

async function api(url, opts) {
  const res = await fetch(url, opts);
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Request failed");
  return data;
}

function render() {
  const s = state;
  const name = (s.settings.her_name || "").trim();
  $("#greeting").textContent = name ? `${name}'s Nook` : "Nook";
  const now = new Date();
  $("#clockline").textContent = now.toLocaleString([], { weekday: "long", hour: "numeric", minute: "2-digit" });

  const open = s.open_shift;
  if (open) {
    $("#statusKicker").textContent = "On the clock";
    $("#statusTitle").textContent = `In since ${open.clock_in.slice(11)}`;
    $("#statusDetail").textContent = open.note || "Punch out when she finishes. Custom time still works.";
    $("#punchBtn").textContent = "Punch out";
    $("#punchBtn").classList.add("out");
  } else {
    $("#statusKicker").textContent = "Ready";
    $("#statusTitle").textContent = name ? `${name} can punch in` : "Punch in when she starts";
    $("#statusDetail").textContent = "Live punch, or Custom time if she is entering a shift later.";
    $("#punchBtn").textContent = "Punch in";
    $("#punchBtn").classList.remove("out");
  }

  $("#todayHours").textContent = s.today.hours.toFixed(2);
  $("#weekHours").textContent = s.week.hours.toFixed(2);
  $("#weekRange").textContent = `${s.week.start} → ${s.week.end}`;
  $("#monthPay").textContent = money(s.month.earned);
  $("#monthLabel").textContent = s.month.label;
  $("#owed").textContent = money(s.all.owed);
  $("#weekEarned").textContent = money(s.week.earned);
  $("#weekPaidHint").textContent = `paid ${money(s.week.paid)} · OT ${s.week.overtime_hours}h`;
  $("#monthEarned").textContent = money(s.month.earned);
  $("#monthPaidHint").textContent = `paid ${money(s.month.paid)} · OT ${s.month.overtime_hours}h`;
  $("#owedBig").textContent = money(s.all.owed);
  $("#allHint").textContent = `earned ${money(s.all.earned)} · paid ${money(s.all.paid)} · bonuses ${money(s.all.bonuses)}`;

  $("#shiftRows").innerHTML = s.shifts.map((row) => `
    <tr>
      <td>${row.clock_in}</td>
      <td>${row.clock_out ? row.clock_out : '<span class="live">on the clock</span>'}</td>
      <td>${row.hours.toFixed(2)}</td>
      <td>${row.note || ""}</td>
      <td><button class="linkish" data-del-shift="${row.id}">delete</button></td>
    </tr>
  `).join("") || `<tr><td colspan="5">No shifts yet.</td></tr>`;

  $("#bonusList").innerHTML = s.bonuses.map((row) => `
    <li><span>${row.paid_on} · ${money(row.amount)} · ${row.note || "bonus"}</span>
    <button class="linkish" data-del-bonus="${row.id}">delete</button></li>
  `).join("") || "<li>No bonuses yet.</li>";

  $("#payList").innerHTML = s.payments.map((row) => `
    <li><span>${row.paid_on} · ${money(row.amount)} · ${row.note || "paid"}</span>
    <button class="linkish" data-del-pay="${row.id}">delete</button></li>
  `).join("") || "<li>No payments yet.</li>";

  const form = $("#settingsForm");
  for (const key of ["her_name", "hourly_rate", "currency", "overtime_after", "overtime_multiplier", "week_starts"]) {
    if (form[key]) form[key].value = s.settings[key] ?? "";
  }
}

async function refresh() {
  state = await api("/api/state");
  render();
}

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.toggle("on", b === btn));
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("on", p.id === `panel-${btn.dataset.tab}`));
  });
});

$("#punchBtn").addEventListener("click", async () => {
  try {
    state = await api("/api/punch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: state.open_shift ? "out" : "in" }),
    });
    render();
    toast(state.open_shift ? "Punched in." : "Punched out.");
  } catch (err) {
    toast(err.message);
  }
});

$("#customBtn").addEventListener("click", () => {
  const d = new Date();
  const form = $("#customForm");
  form.date.value = d.toISOString().slice(0, 10);
  form.clock_in.value = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  form.clock_out.value = "";
  form.note.value = "";
  $("#customDialog").showModal();
});
$("#cancelCustom").addEventListener("click", () => $("#customDialog").close());

$("#customForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  try {
    state = await api("/api/punch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: "custom",
        date: form.date.value,
        clock_in: form.clock_in.value,
        clock_out: form.clock_out.value,
        note: form.note.value,
      }),
    });
    render();
    $("#customDialog").close();
    toast("Custom shift saved.");
  } catch (err) {
    toast(err.message);
  }
});

document.body.addEventListener("click", async (e) => {
  const t = e.target;
  try {
    if (t.dataset.delShift) {
      state = await api(`/api/shift/${t.dataset.delShift}/delete`, { method: "POST" });
      render();
    } else if (t.dataset.delBonus) {
      state = await api(`/api/bonus/${t.dataset.delBonus}/delete`, { method: "POST" });
      render();
    } else if (t.dataset.delPay) {
      state = await api(`/api/payment/${t.dataset.delPay}/delete`, { method: "POST" });
      render();
    }
  } catch (err) {
    toast(err.message);
  }
});

$("#bonusForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    state = await api("/api/bonus", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount: f.amount.value, paid_on: f.paid_on.value, note: f.note.value }),
    });
    f.reset();
    render();
    toast("Bonus added.");
  } catch (err) {
    toast(err.message);
  }
});

$("#payForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    state = await api("/api/payment", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ amount: f.amount.value, paid_on: f.paid_on.value, note: f.note.value }),
    });
    f.reset();
    render();
    toast("Payment recorded. Still owed updated.");
  } catch (err) {
    toast(err.message);
  }
});

$("#settingsForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  const payload = Object.fromEntries(new FormData(f).entries());
  state = await api("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  render();
  toast("Settings saved.");
});

$("#importForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const file = e.target.file.files[0];
  if (!file) return toast("Choose a CSV file.");
  const body = new FormData();
  body.append("file", file);
  const res = await fetch("/api/import", { method: "POST", body });
  const data = await res.json();
  if (!res.ok) return toast(data.error || "Import failed");
  state = data;
  render();
  const r = data.import_result || {};
  $("#importMsg").textContent = `Imported ${r.added || 0} row(s).` + (r.errors?.length ? ` Issues: ${r.errors.join(" | ")}` : "");
  toast("Import finished.");
});

refresh().catch((err) => toast(err.message));
setInterval(() => { if (state?.open_shift) refresh(); }, 60000);
