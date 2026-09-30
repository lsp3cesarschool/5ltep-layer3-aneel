// 5L-TEP Layer 3 dashboard: static page, reads data/<profile>.json.
// No token is ever embedded: "Run Layer 3 now" links to the workflow page,
// where the steward runs it with their own GitHub login.

const CATS = ["PDC", "SP", "DQE", "GES", "INVALID", "PENDING"];
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
const el = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmt = (v) => Math.abs(v) >= 1e6 ? `${(v / 1e6).toLocaleString("en", { maximumFractionDigits: 1 })}M` : Math.round(v).toLocaleString("en");

function repoFromLocation() {
  const m = location.hostname.match(/^([^.]+)\.github\.io$/);
  const repo = location.pathname.split("/").filter(Boolean)[0];
  return m && repo ? `${m[1]}/${repo}` : "lsp3cesarschool/5ltep-layer3";
}
const REPO = repoFromLocation();
let charts = [];
let data = null;

// Final label of an anomaly: steward decision > LLM majority > pending.
function label(a) {
  if (a.review && a.review.status === "decided") return a.review.steward_category;
  return a.llm ? a.llm.category : "PENDING";
}

async function init() {
  el("run-link").href = `https://github.com/${REPO}/actions/workflows/layer3.yml`;
  el("issues-link").href = `https://github.com/${REPO}/issues?q=is%3Aissue+is%3Aopen+label%3Alayer3`;
  el("events-link").href = `https://github.com/${REPO}/actions/workflows/events.yml`;
  el("rejudge-link").href = `https://github.com/${REPO}/actions/workflows/layer3.yml`;
  const res = await fetch("data/index.json", { cache: "no-store" });
  const index = res.ok ? await res.json() : { profiles: [] };
  if (!index.profiles.length) {
    el("title").textContent = "No results yet";
    el("subtitle").textContent = "Run the Layer 3 workflow once (button on the right); this page fills in when it finishes.";
    return;
  }
  const wanted = new URLSearchParams(location.search).get("profile") || index.default;
  const select = el("profile");
  select.innerHTML = index.profiles.map((p) => `<option value="${esc(p.id)}">${esc(p.id)}</option>`).join("");
  select.value = index.profiles.some((p) => p.id === wanted) ? wanted : index.profiles[0].id;
  select.onchange = () => { history.replaceState(null, "", `?profile=${select.value}`); load(select.value); };
  el("logscale").onchange = drawCharts;
  el("filter").onchange = drawTable;
  load(select.value);
}

async function load(profileId) {
  data = await (await fetch(`data/${profileId}.json`, { cache: "no-store" })).json();
  const s = data.summary;
  el("title").textContent = s.profile.title;
  el("subtitle").textContent = `${s.analysis_period[0]} to ${s.analysis_period[1]} · ${s.months} months · generated ${s.generated_at.replace("T", " ").slice(0, 16)} UTC`;
  drawCards();
  drawCharts();
  drawTable();
  drawEvents();
  drawProvenance();
}

function drawEvents() {
  el("events").innerHTML = [...data.events].reverse().map((e) => `<tr>
    <td class="num">${esc(e.month)}</td><td>${esc(e.kind)}</td><td>${esc(e.label)}</td>
    <td>${e.status === "suggested" ? `<span class="tag" style="--c: var(--GES)">suggested</span>` : esc(e.status || "verified")}</td>
    <td class="muted">${esc(e.source)}</td></tr>`).join("") || `<tr><td colspan="5" class="muted">No events.</td></tr>`;
}

function drawCards() {
  const s = data.summary, l3 = s.layer3, an = s.anomalies, h = s.hitl;
  const open = Object.values(h.open_by_level || {}).reduce((a, b) => a + b, 0);
  const cards = [
    ["L3 pass rate", l3.l3_rate === null ? "–" : `${(l3.l3_rate * 100).toFixed(1)}%`,
      `${l3.l3_pass ? "✓ pass" : "✗ fail"} · last ${l3.window ? `${l3.window[0]}…${l3.window[1]}` : "–"}`, l3.l3_pass ? "pass" : "fail"],
    ["Anomalies flagged", an.flagged, Object.entries(an.by_series).map(([k, v]) => `${k}: ${v}`).join(" · ")],
    ["Judged by the LLM", `${an.judged} / ${an.flagged}`,
      `judge now: ${s.llm.model} (${s.llm.model_source === "benchmark" ? "benchmark's choice" : s.llm.model_source})` +
      (s.llm.judged_by_other_model_or_prompt ? ` · ${s.llm.judged_by_other_model_or_prompt} judged by an earlier model/prompt` : "")],
    ["Label consistency", s.llm.mean_consistency === null ? "–" : s.llm.mean_consistency.toFixed(2),
      s.llm.unanimous_rate === null ? "" : `${(s.llm.unanimous_rate * 100).toFixed(0)}% unanimous (3 runs)`],
    ["Steward reviews", `${h.decided} / ${h.issues}`, `${open} open${h.human_llm_agreement === null ? "" : ` · agreement ${(h.human_llm_agreement * 100).toFixed(0)}%`}`],
    ["Drift points", Object.values(an.drift_points).reduce((a, b) => a + b, 0), "Page-Hinkley alarms"],
  ];
  el("cards").innerHTML = cards.map(([k, v, n, cls]) =>
    `<div class="card"><div class="label">${esc(k)}</div><div class="value ${cls || ""}">${esc(v)}</div><div class="note">${esc(n)}</div></div>`).join("");
  el("legend").innerHTML = CATS.map((c) =>
    `<span style="--c: var(--${c})">${c === "PENDING" ? "not judged" : c}${data.categories[c] ? ` · ${esc(data.categories[c].split(":")[0])}` : ""}</span>`).join("");
}

function drawCharts() {
  charts.forEach((c) => c.destroy());
  charts = [];
  const box = el("charts");
  box.innerHTML = "";
  const log = el("logscale").checked;
  for (const [name, values] of Object.entries(data.series)) {
    const title = document.createElement("div");
    title.className = "chart-title";
    title.textContent = `${name}: ${data.summary.series[name]}`;
    const wrap = document.createElement("div");
    wrap.className = "chart-box";
    const canvas = document.createElement("canvas");
    wrap.appendChild(canvas);
    box.append(title, wrap);

    const idx = Object.fromEntries(data.months.map((m, i) => [m, i]));
    const byCat = Object.fromEntries(CATS.map((c) => [c, data.months.map(() => null)]));
    const info = {};
    for (const a of data.anomalies.filter((a) => a.series === name)) {
      byCat[label(a)][idx[a.month]] = values[idx[a.month]] || null;
      info[a.month] = a;
    }
    const driftMonths = new Set((data.drift[name] || []).map((p) => p.alarm_month));
    const datasets = [
      { label: name, data: values.map((v) => (log && v <= 0 ? null : v)), borderColor: css("muted"),
        borderWidth: 1.2, pointRadius: 0, tension: 0.1, order: 2 },
      ...CATS.map((c) => ({ label: c, data: byCat[c], showLine: false, pointRadius: 4.5,
        pointHoverRadius: 7, backgroundColor: css(c), borderColor: css(c), order: 1 })),
    ];
    const driftLines = {
      id: "driftLines",
      afterDatasetsDraw(chart) {
        const { ctx, chartArea: { top, bottom }, scales: { x } } = chart;
        ctx.save();
        ctx.strokeStyle = css("DQE");
        ctx.setLineDash([4, 4]);
        for (const m of driftMonths) {
          if (!(m in idx)) continue;
          const px = x.getPixelForValue(idx[m]);
          ctx.beginPath(); ctx.moveTo(px, top); ctx.lineTo(px, bottom); ctx.stroke();
        }
        ctx.restore();
      },
    };
    charts.push(new Chart(canvas, {
      type: "line",
      plugins: [driftLines],
      data: { labels: data.months, datasets },
      options: {
        maintainAspectRatio: false, animation: false, spanGaps: true,
        interaction: { mode: "nearest", intersect: false, axis: "x" },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: {
            label: (ctx) => {
              const a = info[ctx.label];
              if (ctx.datasetIndex === 0) return `${name}: ${fmt(ctx.parsed.y)}`;
              return a ? `${label(a)} · ${a.votes}/4 detectors${a.llm ? ` · C=${a.llm.consistency}` : ""}` : "";
            },
          } },
        },
        scales: {
          x: { ticks: { maxTicksLimit: 14, color: css("muted") }, grid: { display: false } },
          y: { type: log ? "logarithmic" : "linear", ticks: { color: css("muted"), callback: (v) => fmt(v) }, grid: { color: css("border") } },
        },
      },
    }));
  }
}

function drawTable() {
  const f = el("filter").value;
  const rows = data.anomalies.filter((a) =>
    f === "all" || (f === "pending" && !a.llm) ||
    (f === "review" && a.llm && a.llm.review_level !== "none" && !(a.review && a.review.status === "decided")));
  el("rows").innerHTML = rows.map((a) => {
    const llm = a.llm ? `<span class="tag" style="--c: var(--${a.llm.category})">${a.llm.category}</span>` +
      (a.llm.review_level !== "none" ? ` <span class="muted">${a.llm.review_level}</span>` : "") +
      `<br><span class="muted" title="model / prompt version that produced this judgment">${esc(a.llm.model)} · ${esc(a.llm.prompt_version)}</span>`
      : `<span class="muted">pending</span>`;
    const steward = a.review
      ? `<a href="${esc(a.review.url)}" target="_blank" rel="noopener">#${a.review.issue}</a> ` +
        (a.review.status === "decided" ? `<span class="tag" style="--c: var(--${a.review.steward_category})">${a.review.steward_category}</span>` : `<span class="muted">${esc(a.review.status)}</span>`)
      : "";
    return `<tr><td class="num">${a.month}</td><td>${esc(a.series)}</td>
      <td class="num">${a.votes}/4 · ${a.score.toFixed(2)}${a.near_drift ? " · drift" : ""}<br><span class="muted">${a.detectors.join(", ")}</span></td>
      <td>${llm}</td><td class="num">${a.llm ? a.llm.consistency.toFixed(2) : ""}</td><td>${steward}</td>
      <td class="reason">${esc(a.llm ? a.llm.reasoning : "")}</td></tr>`;
  }).join("") || `<tr><td colspan="7" class="muted">Nothing to show.</td></tr>`;
}

function drawProvenance() {
  const s = data.summary, src = s.source, agg = src.aggregation || {};
  const items = [
    ["Source dataset", src.dataset_url ? `<a href="${esc(src.dataset_url)}">${esc(src.dataset_url)}</a>` : esc(src.resource_url)],
    ["Resource", esc(src.resource_url)],
    ["SHA-256 of the file analysed", `<code>${esc(src.checksum_sha256)}</code>`],
    ["Downloaded", esc(src.download_started_at || "")],
    ["Rows read / excluded / without id", `${(agg.rows_read || 0).toLocaleString("en")} / ${(agg.rows_excluded || 0).toLocaleString("en")} / ${(agg.rows_missing_key || 0).toLocaleString("en")}`],
    ["Profile", `<a href="https://github.com/${REPO}/blob/main/profiles/${esc(s.profile.id)}.json">${esc(s.profile.id)}</a> (sha256 <code>${esc((src.profile_sha256 || "").slice(0, 12))}</code>)`],
    ["Method parameters", `<code>${esc(JSON.stringify(s.method_parameters))}</code>`],
    ["Environment", esc(`Python ${s.environment.python}; ${Object.entries(s.environment.packages).map(([k, v]) => `${k} ${v}`).join(", ")}`)],
    ["Toolkit", esc(s.toolkit)],
    ["Machine-readable", `<a href="https://github.com/${REPO}/blob/main/results/${esc(s.profile.id)}/layer3_summary.json">layer3_summary.json</a> · <a href="https://github.com/${REPO}/tree/main/results/${esc(s.profile.id)}">all results</a>`],
  ];
  el("provenance").innerHTML = items.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("");
}

init().catch((e) => { el("title").textContent = "Could not load dashboard data"; console.error(e); });
