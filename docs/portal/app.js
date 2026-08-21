/**
 * Command Portal — static demo with local preferences (localStorage).
 */

const STORAGE_KEY = "stonewall_portal_settings_v1";

const defaultSettings = () => ({
  hourlyRate: 200,
  currency: "USD",
  density: "comfortable",
  showMatterIds: true,
  showRunwayBadges: true,
  reducedMotion: false,
});

function loadSettings() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultSettings();
    const parsed = JSON.parse(raw);
    return { ...defaultSettings(), ...parsed };
  } catch {
    return defaultSettings();
  }
}

function saveSettings(settings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

function formatMoney(amount, currency) {
  try {
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: currency || "USD",
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return `$${Math.round(amount)}`;
  }
}

function formatNumber(n) {
  return new Intl.NumberFormat("en-US").format(n);
}

const state = {
  settings: loadSettings(),
  data: {},
};

function applyGlobalSettings() {
  const { density, reducedMotion } = state.settings;
  document.body.classList.toggle("density-compact", density === "compact");
  document.body.classList.toggle("reduce-motion", reducedMotion);
  if (reducedMotion) {
    document.documentElement.style.scrollBehavior = "auto";
  }
}

function showToast(message) {
  let el = document.getElementById("portal-toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "portal-toast";
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = message;
  el.classList.add("is-visible");
  window.clearTimeout(showToast._t);
  showToast._t = window.setTimeout(() => el.classList.remove("is-visible"), 2200);
}

async function loadData() {
  const files = [
    "metrics.json",
    "cases.json",
    "deadlines.json",
    "artifacts.json",
    "playbooks.json",
    "patterns.json",
    "cast.json",
    "billing.json",
  ];
  const base = new URL("data/", window.location.href);
  const out = {};
  await Promise.all(
    files.map(async (name) => {
      const res = await fetch(new URL(name, base), { cache: "no-store" });
      if (!res.ok) throw new Error(`Failed to load ${name}`);
      out[name.replace(".json", "")] = await res.json();
    }),
  );
  state.data = out;
}

function renderDashboard() {
  const m = state.data.metrics || {};
  const root = document.getElementById("dash-metrics");
  if (!root) return;
  root.innerHTML = `
    <article class="metric"><strong>${formatNumber(m.cataloged_artifacts ?? 0)}</strong><span>cataloged artifacts</span></article>
    <article class="metric"><strong>${formatNumber(m.active_matters ?? 0)}</strong><span>active matters</span></article>
    <article class="metric"><strong>${formatNumber(m.pattern_tags ?? 0)}</strong><span>pattern tags</span></article>
    <article class="metric"><strong>${formatNumber(m.artifact_classes ?? 0)}</strong><span>artifact classes</span></article>
  `;

  const glance = document.getElementById("dash-glance");
  if (glance) {
    glance.innerHTML = `
      <li><strong>${m.urgent_runway ?? 0} matters inside urgent runway</strong><br><span>Deposition prep, mediation staging, and deadline confirmation surfaced in the board.</span></li>
      <li><strong>${m.packets_ready ?? 0} report packets nearly ready</strong><br><span>Chronology aligned, records pulled, and damages notes staged for downstream workflow.</span></li>
      <li><strong>${m.live_threads ?? 0} live witness-prep thread active</strong><br><span>Prior statements, chronology gaps, and issue clusters stay query-ready.</span></li>
    `;
  }
}

function renderCases() {
  const tbody = document.querySelector("#cases-table tbody");
  if (!tbody) return;
  const matters = state.data.cases?.matters || [];
  const { showMatterIds } = state.settings;
  tbody.innerHTML = matters
    .map((row) => {
      const idCell = showMatterIds
        ? `<td class="mono">${row.id}</td>`
        : `<td class="mono">—</td>`;
      return `<tr>
        ${idCell}
        <td>${row.label}</td>
        <td>${row.posture}</td>
        <td>${row.runway}</td>
        <td><span class="chip">${row.status}</span></td>
      </tr>`;
    })
    .join("");
}

function renderDeadlines() {
  const tbody = document.querySelector("#deadlines-table tbody");
  if (!tbody) return;
  const items = state.data.deadlines?.items || [];
  const { showMatterIds, showRunwayBadges } = state.settings;
  tbody.innerHTML = items
    .map((row) => {
      const matter = showMatterIds ? row.matter : "Matter";
      const band = showRunwayBadges ? row.band : "scheduled";
      const chipClass =
        band === "urgent" ? "chip chip--urgent" : band === "soon" ? "chip chip--soon" : "chip chip--planned";
      return `<tr>
        <td class="mono">${row.date}</td>
        <td class="mono">${matter}</td>
        <td>${row.label}</td>
        <td><span class="${chipClass}">${band}</span></td>
      </tr>`;
    })
    .join("");
}

function renderArtifacts() {
  const tbody = document.querySelector("#artifacts-table tbody");
  if (!tbody) return;
  const arts = state.data.artifacts?.artifacts || [];
  const { showMatterIds } = state.settings;
  tbody.innerHTML = arts
    .map(
      (a) => `<tr>
      <td class="mono">${a.id}</td>
      <td>${a.type}</td>
      <td class="mono">${showMatterIds ? a.matter : "—"}</td>
      <td>${a.summary}</td>
      <td class="mono">${a.date}</td>
    </tr>`,
    )
    .join("");
}

function renderPatterns() {
  const root = document.getElementById("pattern-list");
  if (!root) return;
  const patterns = state.data.patterns?.patterns || [];
  root.innerHTML = patterns
    .map(
      (p) => `<article class="pattern-card">
      <code>${p.code}</code>
      <p style="margin:8px 0 0;font-size:13px;color:var(--muted);">${p.band} · ${formatNumber(p.hits)} hits</p>
    </article>`,
    )
    .join("");
}

function renderPlaybooks() {
  const playbooks = state.data.playbooks || {};
  const modules = Array.isArray(playbooks.modules) ? playbooks.modules : [];
  const pipeline = Array.isArray(playbooks.pipeline) ? playbooks.pipeline : [];
  const qc = Array.isArray(playbooks.qc_checks) ? playbooks.qc_checks : [];
  const readiness = Array.isArray(playbooks.readiness_lanes) ? playbooks.readiness_lanes : [];

  const modulesRoot = document.getElementById("playbook-modules");
  if (modulesRoot) {
    modulesRoot.innerHTML = modules
      .map(
        (m) => `<article class="playbook-card">
      <div class="playbook-card__head">
        <span class="playbook-layer">${m.layer || "Layer"}</span>
        <span class="chip">${m.status || "active"}</span>
      </div>
      <h3>${m.title || "Untitled module"}</h3>
      <p>${m.summary || ""}</p>
      <code class="playbook-signal">${m.signal || ""}</code>
    </article>`,
      )
      .join("");
  }

  const pipeRoot = document.getElementById("playbook-pipeline");
  if (pipeRoot) {
    pipeRoot.innerHTML = pipeline
      .map((step, idx) => {
        if (typeof step === "string") {
          return `<li class="pipeline-step"><strong>Step ${idx + 1}</strong><span>${step}</span></li>`;
        }
        return `<li class="pipeline-step"><strong>${step.step || `Step ${idx + 1}`}</strong><span>${step.outcome || ""}</span></li>`;
      })
      .join("");
  }

  const qcRoot = document.getElementById("playbook-qc");
  if (qcRoot) {
    qcRoot.innerHTML = qc
      .map((item) => {
        const title = item.check || item.name || "Check";
        const desc = item.note || item.description || "";
        return `<li><strong>${title}</strong><br><span>${desc}</span></li>`;
      })
      .join("");
  }

  const readinessRoot = document.getElementById("playbook-readiness");
  if (readinessRoot) {
    readinessRoot.innerHTML = readiness
      .map((item) => {
        const title = item.lane || item.name || "Lane";
        const desc = item.value || item.description || "";
        return `<li><strong>${title}</strong><br><span>${desc}</span></li>`;
      })
      .join("");
  }
}

function renderCast() {
  const root = document.getElementById("cast-list");
  if (!root) return;
  const chars = state.data.cast?.characters || [];
  root.innerHTML = chars
    .map(
      (c) => `<article class="cast-card">
      <div class="cast-meta">${c.role}</div>
      <h3>${c.alias}</h3>
      <p style="margin:6px 0 0;font-size:14px;color:var(--muted);">${c.note}</p>
      <p style="margin:10px 0 0;font-size:13px;"><span class="chip">${formatNumber(c.matters)} matters</span></p>
    </article>`,
    )
    .join("");
}

function renderBilling() {
  const b = state.data.billing || {};
  const rate = Number(state.settings.hourlyRate) || Number(b.default_hourly) || 200;
  const currency = state.settings.currency || b.currency || "USD";
  const lineItems = b.line_items || [];
  const tbody = document.querySelector("#billing-table tbody");
  const totalHours = lineItems.reduce((s, row) => s + (Number(row.hours) || 0), 0);
  const totalAmt = totalHours * rate;

  const rateDisplay = document.getElementById("settings-rate-display");
  if (rateDisplay) rateDisplay.textContent = `${formatMoney(rate, currency)}/hr`;

  const billRateEl = document.getElementById("billing-rate-display");
  if (billRateEl) billRateEl.textContent = `${formatMoney(rate, currency)}/hr`;

  const summary = document.getElementById("billing-summary");
  if (summary) {
    summary.innerHTML = `
      <p class="billing-total">${formatMoney(totalAmt, currency)}</p>
      <p class="billing-note">${formatNumber(totalHours)} billable hours × ${formatMoney(rate, currency)}/hr (demo math — preferences only)</p>
    `;
  }

  if (tbody) {
    tbody.innerHTML = lineItems
      .map(
        (row) => `<tr>
        <td class="mono">${state.settings.showMatterIds ? row.matter : "Matter"}</td>
        <td>${row.phase}</td>
        <td class="mono">${row.hours}</td>
        <td class="mono">${formatMoney(row.hours * rate, currency)}</td>
      </tr>`,
      )
      .join("");
  }
}

function populateSettingsForm() {
  const s = state.settings;
  const hourly = document.getElementById("set-hourly");
  const currency = document.getElementById("set-currency");
  const density = document.getElementById("set-density");
  const matterIds = document.getElementById("set-matter-ids");
  const runway = document.getElementById("set-runway");
  const motion = document.getElementById("set-motion");

  if (hourly) hourly.value = String(s.hourlyRate);
  if (currency) currency.value = s.currency;
  if (density) density.value = s.density;
  if (matterIds) matterIds.checked = !!s.showMatterIds;
  if (runway) runway.checked = !!s.showRunwayBadges;
  if (motion) motion.checked = !!s.reducedMotion;
}

function bindSettingsForm() {
  const form = document.getElementById("settings-form");
  if (!form) return;

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const hourly = document.getElementById("set-hourly");
    const currency = document.getElementById("set-currency");
    const density = document.getElementById("set-density");
    const matterIds = document.getElementById("set-matter-ids");
    const runway = document.getElementById("set-runway");
    const motion = document.getElementById("set-motion");

    state.settings = {
      ...state.settings,
      hourlyRate: Math.max(0, Number(hourly?.value) || 0),
      currency: currency?.value || "USD",
      density: density?.value || "comfortable",
      showMatterIds: !!matterIds?.checked,
      showRunwayBadges: !!runway?.checked,
      reducedMotion: !!motion?.checked,
    };
    saveSettings(state.settings);
    applyGlobalSettings();
    renderCases();
    renderDeadlines();
    renderArtifacts();
    renderBilling();
    populateSettingsForm();
    showToast("Preferences saved locally in this browser.");
  });

  document.getElementById("settings-reset")?.addEventListener("click", () => {
    state.settings = defaultSettings();
    saveSettings(state.settings);
    applyGlobalSettings();
    populateSettingsForm();
    renderCases();
    renderDeadlines();
    renderArtifacts();
    renderBilling();
    showToast("Reset to defaults.");
  });

  document.getElementById("settings-export")?.addEventListener("click", () => {
    const blob = new Blob([JSON.stringify(state.settings, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "stonewall-portal-settings.json";
    a.click();
    URL.revokeObjectURL(a.href);
    showToast("Downloaded settings JSON.");
  });
}

function switchPage(name) {
  document.querySelectorAll(".page").forEach((p) => {
    p.classList.toggle("is-visible", p.id === `page-${name}`);
  });
  document.querySelectorAll(".portal-nav button[data-page]").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.page === name);
  });
  if (name === "billing" || name === "dashboard") renderBilling();
  if (name === "playbooks") renderPlaybooks();
}

function bindNav() {
  document.querySelectorAll(".portal-nav button[data-page]").forEach((btn) => {
    btn.addEventListener("click", () => switchPage(btn.dataset.page));
  });
}

async function init() {
  applyGlobalSettings();
  bindNav();
  bindSettingsForm();

  try {
    await loadData();
  } catch (err) {
    console.error(err);
    showToast("Could not load portal data JSON.");
    return;
  }

  renderDashboard();
  renderCases();
  renderDeadlines();
  renderArtifacts();
  renderPlaybooks();
  renderPatterns();
  renderCast();
  renderBilling();
  populateSettingsForm();

  const initial = new URLSearchParams(window.location.search).get("page");
  const allowed = [
    "dashboard",
    "cases",
    "deadlines",
    "artifacts",
    "playbooks",
    "patterns",
    "characters",
    "billing",
    "settings",
  ];
  switchPage(allowed.includes(initial) ? initial : "dashboard");
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
