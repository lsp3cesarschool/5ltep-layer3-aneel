// 5L-TEP Layer 3 dashboard: static page, reads data/<profile>.json.
// No token is ever embedded: "Run Layer 3 now" links to the workflow page,
// where the steward runs it with their own GitHub login.
// Two languages: the page's own labels are in I18N below; texts that come from the data (the LLM's
// reasoning, event labels, profile descriptions) are machine-translated by the pipeline
// (src/translate.py) and arrive in data.translations.

const CATS = ["PDC", "SP", "DQE", "GES", "INVALID", "PENDING"];
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim();
const el = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const I18N = {
  en: {
    back: "← Back to the repository", eyebrow: "5L-TEP · Layer 3 · Anomaly Detection", loading: "Loading…",
    dataset: "Dataset", dataset_hint: "Each profile is one dataset, or one cut of a dataset, monitored by this repository",
    run: "Run Layer 3 now ↗", queue: "Review queue ↗", suggest: "Suggest events ↗", rejudge: "Re-judge ↗",
    rejudge_hint: "Opens the workflow: choose rejudge = stale (only what another model or prompt judged) or all",
    series_h: "Monthly series", log: "log scale",
    series_note: "Points mark months flagged by the ensemble (≥2 of 4 detectors), coloured by the LLM-as-a-Judge label (or the steward's decision, when there is one); click a point to see its details below. Dashed lines mark Page-Hinkley alarms (sustained level shifts).",
    anomalies_h: "Anomalies", f_all: "All", f_review: "Needs review", f_pending: "Not judged yet", mt_note: "",
    th_month: "Month", th_series: "Series", th_steward: "Steward", th_reasoning: "Reasoning (majority run)",
    events_h: "Event calendar", events_note: "verified by a steward · suggested by the LLM (unverified) · currency reforms",
    th_kind: "Kind", th_event: "Event", th_status: "Status", th_source: "Source",
    prov_h: "Provenance of this result", toolkit: "5L-TEP Layer 3 toolkit", source_code: "source code",
    layer4: "Layer 4 (provenance)",
    subtitle: "{a} to {b} · {n} months · generated {t} UTC",
    no_results: "No results yet", no_results_sub: "Run the Layer 3 workflow once (button on the right); this page fills in when it finishes.",
    load_error: "Could not load dashboard data",
    c_rate: "L3 pass rate", c_pass: "✓ pass", c_fail: "✗ fail", c_last: "last",
    c_flagged: "Anomalies flagged", c_judged: "Judged by the LLM", c_judge_now: "judge now: {m} ({s})",
    c_src_benchmark: "benchmark's choice", c_src_pinned: "pinned", c_earlier: "{n} judged by an earlier model/prompt",
    c_consistency: "Label consistency", c_unanimous: "{p}% unanimous (3 runs)",
    c_reviews: "Steward reviews", c_open: "{n} open", c_agreement: "agreement {p}%",
    c_drift: "Drift points", c_drift_note: "Page-Hinkley alarms",
    not_judged: "not judged", tip: "{l} · {v}/4 detectors{c} · click for details",
    model_hint: "model / prompt version that produced this judgment", drift: "drift", nothing: "Nothing to show.",
    no_events: "No events.", original: "Original (English): ",
    level: { pending: "pending", advisory: "advisory", "level-shift": "level shift" },
    status: { pending: "pending", decided: "decided", conflicting_labels: "conflicting labels" },
    cat: {},  // English names come from the profile
    kind: { policy: "policy", political: "political", external: "external", monetary: "monetary" },
    ev_status: { verified: "verified", suggested: "suggested", rejected: "rejected" },
    p_dataset: "Source dataset", p_resource: "Resource", p_sha: "SHA-256 of the file analysed", p_downloaded: "Downloaded",
    p_rows: "Rows read / excluded / without id", p_profile: "Profile", p_params: "Method parameters",
    p_env: "Environment", p_toolkit: "Toolkit", p_machine: "Machine-readable", p_all: "all results",
  },
  pt: {
    back: "← Voltar ao repositório", eyebrow: "5L-TEP · Camada 3 · Detecção de Anomalias", loading: "Carregando…",
    dataset: "Conjunto de dados", dataset_hint: "Cada perfil é um conjunto de dados, ou um recorte de um conjunto, monitorado por este repositório",
    run: "Rodar a Camada 3 agora ↗", queue: "Fila de revisão ↗", suggest: "Sugerir eventos ↗", rejudge: "Rejulgar ↗",
    rejudge_hint: "Abre o workflow: escolha rejudge = stale (só o que outro modelo ou prompt julgou) ou all",
    series_h: "Séries mensais", log: "escala logarítmica",
    series_note: "Os pontos marcam os meses sinalizados pelo ensemble (≥2 de 4 detectores), coloridos pelo rótulo do LLM-as-a-Judge (ou pela decisão do gestor, quando houver); clique num ponto para ver os detalhes abaixo. As linhas tracejadas marcam alarmes de Page-Hinkley (mudanças de nível sustentadas).",
    anomalies_h: "Anomalias", f_all: "Todas", f_review: "Precisam de revisão", f_pending: "Ainda não julgadas",
    mt_note: "Raciocínios e descrições traduzidos automaticamente do inglês pelo mesmo modelo local (o julgamento é feito em inglês); passe o mouse sobre um texto para ver o original.",
    th_month: "Mês", th_series: "Série", th_steward: "Gestor", th_reasoning: "Raciocínio (execução majoritária)",
    events_h: "Calendário de eventos", events_note: "verificados por um gestor · sugeridos pelo LLM (não verificados) · reformas monetárias",
    th_kind: "Tipo", th_event: "Evento", th_status: "Situação", th_source: "Fonte",
    prov_h: "Proveniência deste resultado", toolkit: "Kit da Camada 3 do 5L-TEP", source_code: "código-fonte",
    layer4: "Camada 4 (proveniência)",
    subtitle: "{a} a {b} · {n} meses · gerado em {t} UTC",
    no_results: "Ainda sem resultados", no_results_sub: "Rode o workflow da Camada 3 uma vez (botão à direita); esta página se preenche quando ele terminar.",
    load_error: "Não foi possível carregar os dados do painel",
    c_rate: "Taxa de aprovação L3", c_pass: "✓ aprovada", c_fail: "✗ reprovada", c_last: "últimos",
    c_flagged: "Anomalias sinalizadas", c_judged: "Julgadas pelo LLM", c_judge_now: "juiz atual: {m} ({s})",
    c_src_benchmark: "escolha do benchmark", c_src_pinned: "fixado", c_earlier: "{n} julgadas por modelo/prompt anterior",
    c_consistency: "Consistência dos rótulos", c_unanimous: "{p}% unânimes (3 execuções)",
    c_reviews: "Revisões do gestor", c_open: "{n} abertas", c_agreement: "concordância {p}%",
    c_drift: "Pontos de deriva", c_drift_note: "alarmes de Page-Hinkley",
    not_judged: "não julgada", tip: "{l} · {v}/4 detectores{c} · clique para detalhes",
    model_hint: "modelo / versão do prompt que produziu este julgamento", drift: "deriva", nothing: "Nada a mostrar.",
    no_events: "Nenhum evento.", original: "Original (inglês): ",
    level: { pending: "pendente", advisory: "recomendada", "level-shift": "mudança de nível" },
    status: { pending: "pendente", decided: "decidida", conflicting_labels: "rótulos conflitantes" },
    cat: { PDC: "Mudança por política", SP: "Padrão sazonal", DQE: "Evento de qualidade de dados",
           GES: "Mudança genuína de fiscalização", INVALID: "resposta inválida" },
    kind: { policy: "política pública", political: "política", external: "externo", monetary: "monetário" },
    ev_status: { verified: "verificado", suggested: "sugerido", rejected: "rejeitado" },
    p_dataset: "Conjunto de dados de origem", p_resource: "Recurso", p_sha: "SHA-256 do arquivo analisado", p_downloaded: "Baixado em",
    p_rows: "Linhas lidas / excluídas / sem identificador", p_profile: "Perfil", p_params: "Parâmetros do método",
    p_env: "Ambiente", p_toolkit: "Kit", p_machine: "Legível por máquina", p_all: "todos os resultados",
  },
};

// Language: ?lang= in the address > the visitor's last choice > the browser's language.
const LANG = (() => {
  const q = new URLSearchParams(location.search).get("lang");
  if (q === "en" || q === "pt") {
    try { localStorage.setItem("l3-lang", q); } catch (e) { /* storage blocked: fine */ }
    return q;
  }
  try {
    const saved = localStorage.getItem("l3-lang");
    if (saved === "en" || saved === "pt") return saved;
  } catch (e) { /* storage blocked: fine */ }
  return (navigator.language || "").toLowerCase().startsWith("pt") ? "pt" : "en";
})();
const LOCALE = LANG === "pt" ? "pt-BR" : "en";
const T = I18N[LANG];
const t = (key, vars = {}) => String(T[key] ?? I18N.en[key] ?? key).replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? "");
const fmt = (v) => Math.abs(v) >= 1e6
  ? `${(v / 1e6).toLocaleString(LOCALE, { maximumFractionDigits: 1 })}${LANG === "pt" ? " mi" : "M"}`
  : v !== 0 && Math.abs(v) < 1  // tiny values (old currencies converted to Reais) on the log axis
    ? v.toLocaleString(LOCALE, { maximumSignificantDigits: 2 })
    : Math.round(v).toLocaleString(LOCALE);
const num = (v, d = 2) => Number(v).toLocaleString(LOCALE, { minimumFractionDigits: d, maximumFractionDigits: d });

// A text from the data, in the page's language when the pipeline has translated it.
function tr(text) {
  if (LANG === "en" || !text || !data || !data.translations) return text;
  return (data.translations[LANG] || {})[text] || text;
}
// The same, as HTML that shows the original on hover when it was translated.
function trHtml(text) {
  const out = tr(text);
  return out !== text ? `<span title="${esc(t("original") + text)}">${esc(out)}</span>` : esc(text);
}

// Short name of a category: hand-written for the four standard codes, else from the profile.
function categoryName(code) {
  if (T.cat[code]) return T.cat[code];
  return data.categories[code] ? tr(data.categories[code]).split(":")[0] : "";
}

function repoFromLocation() {
  const m = location.hostname.match(/^([^.]+)\.github\.io$/);
  const repo = location.pathname.split("/").filter(Boolean)[0];
  return m && repo ? `${m[1]}/${repo}` : "lsp3cesarschool/5ltep-layer3";
}
const REPO = repoFromLocation();
let charts = [];
let data = null;

// Address of this page with some parameters changed, keeping the others and the anchor.
function pageUrl(changes) {
  const q = new URLSearchParams(location.search);
  for (const [k, v] of Object.entries(changes)) q.set(k, v);
  return `?${q.toString()}${location.hash}`;
}

function applyStaticLabels() {
  document.documentElement.lang = LANG === "pt" ? "pt-BR" : "en";
  document.title = t("eyebrow");
  document.querySelectorAll("[data-i18n]").forEach((n) => { n.textContent = t(n.dataset.i18n); });
  document.querySelectorAll("[data-i18n-title]").forEach((n) => { n.title = t(n.dataset.i18nTitle); });
  el("mt-note").hidden = !T.mt_note;
  for (const lang of ["en", "pt"]) {
    const link = el(`lang-${lang}`);
    link.href = pageUrl({ lang });
    link.classList.toggle("current", lang === LANG);
  }
}

// Links built from data: only http(s), so a "javascript:" address can never run.
const safeUrl = (u) => (/^https?:\/\//i.test(String(u || "")) ? String(u) : "#");

// A category as a coloured tag; anything outside the known codes is shown escaped and uncoloured.
function catTag(c) {
  const known = CATS.includes(c) ? c : "PENDING";
  return `<span class="tag" style="--c: var(--${known})">${esc(c)}</span>`;
}

// Final label of an anomaly: steward decision > LLM majority > pending.
function label(a) {
  if (a.review && a.review.status === "decided") return a.review.steward_category;
  return a.llm ? a.llm.category : "PENDING";
}

async function init() {
  applyStaticLabels();
  el("repo-link").href = el("footer-repo-link").href = `https://github.com/${REPO}`;
  el("readme-link").href = `https://github.com/${REPO}#readme`;
  el("leiame-link").href = `https://github.com/${REPO}/blob/main/LEIAME.md`;
  el("run-link").href = `https://github.com/${REPO}/actions/workflows/layer3.yml`;
  el("issues-link").href = `https://github.com/${REPO}/issues?q=is%3Aissue+is%3Aopen+label%3Alayer3`;
  el("events-link").href = `https://github.com/${REPO}/actions/workflows/events.yml`;
  el("rejudge-link").href = `https://github.com/${REPO}/actions/workflows/layer3.yml`;
  const res = await fetch("data/index.json", { cache: "no-store" });
  const index = res.ok ? await res.json() : { profiles: [] };
  if (!index.profiles.length) {
    el("title").textContent = t("no_results");
    el("subtitle").textContent = t("no_results_sub");
    return;
  }
  const wanted = new URLSearchParams(location.search).get("profile") || index.default;
  const select = el("profile");
  select.innerHTML = index.profiles.map((p) => `<option value="${esc(p.id)}">${esc(p.title || p.id)}</option>`).join("");
  el("profile-picker").hidden = index.profiles.length < 2;  // a selector with one option says nothing
  select.value = index.profiles.some((p) => p.id === wanted) ? wanted : index.profiles[0].id;
  select.onchange = () => { history.replaceState(null, "", pageUrl({ profile: select.value })); load(select.value); };
  el("logscale").onchange = drawCharts;
  el("filter").onchange = drawTable;
  load(select.value);
}

async function load(profileId) {
  data = await (await fetch(`data/${profileId}.json`, { cache: "no-store" })).json();
  const s = data.summary;
  el("title").textContent = tr(s.profile.title);
  el("subtitle").textContent = t("subtitle", { a: s.analysis_period[0], b: s.analysis_period[1], n: s.months,
    t: s.generated_at.replace("T", " ").slice(0, 16) });
  drawCards();
  drawCharts();
  drawTable();
  drawEvents();
  drawProvenance();
  const m = location.hash.match(/^#anomaly-(.+)-(\d{4}-\d{2})$/);  // link to one anomaly
  if (m) showAnomaly(m[1], m[2]);
}

function drawEvents() {
  el("events").innerHTML = [...data.events].reverse().map((e) => `<tr>
    <td class="num">${esc(e.month)}</td><td>${esc(T.kind[e.kind] || e.kind)}</td><td>${trHtml(e.label)}</td>
    <td>${e.status === "suggested" ? `<span class="tag" style="--c: var(--GES)">${esc(T.ev_status.suggested)}</span>` : esc(T.ev_status[e.status || "verified"] || e.status)}</td>
    <td class="muted">${esc(e.source)}</td></tr>`).join("") || `<tr><td colspan="5" class="muted">${esc(t("no_events"))}</td></tr>`;
}

function drawCards() {
  const s = data.summary, l3 = s.layer3, an = s.anomalies, h = s.hitl;
  const open = Object.values(h.open_by_level || {}).reduce((a, b) => a + b, 0);
  const source = s.llm.model_source === "benchmark" ? t("c_src_benchmark")
    : s.llm.model_source === "pinned" ? t("c_src_pinned") : s.llm.model_source;
  const cards = [
    [t("c_rate"), l3.l3_rate === null ? "–" : `${(l3.l3_rate * 100).toLocaleString(LOCALE, { maximumFractionDigits: 1 })}%`,
      `${l3.l3_pass ? t("c_pass") : t("c_fail")} · ${t("c_last")} ${l3.window ? `${l3.window[0]}…${l3.window[1]}` : "–"}`, l3.l3_pass ? "pass" : "fail"],
    [t("c_flagged"), an.flagged, Object.entries(an.by_series).map(([k, v]) => `${k}: ${v}`).join(" · ")],
    [t("c_judged"), `${an.judged} / ${an.flagged}`,
      t("c_judge_now", { m: s.llm.model, s: source }) +
      (s.llm.judged_by_other_model_or_prompt ? ` · ${t("c_earlier", { n: s.llm.judged_by_other_model_or_prompt })}` : "")],
    [t("c_consistency"), s.llm.mean_consistency === null ? "–" : num(s.llm.mean_consistency),
      s.llm.unanimous_rate === null ? "" : t("c_unanimous", { p: (s.llm.unanimous_rate * 100).toFixed(0) })],
    [t("c_reviews"), `${h.decided} / ${h.issues}`, t("c_open", { n: open }) +
      (h.human_llm_agreement === null ? "" : ` · ${t("c_agreement", { p: (h.human_llm_agreement * 100).toFixed(0) })}`)],
    [t("c_drift"), Object.values(an.drift_points).reduce((a, b) => a + b, 0), t("c_drift_note")],
  ];
  el("cards").innerHTML = cards.map(([k, v, n, cls]) =>
    `<div class="card"><div class="label">${esc(k)}</div><div class="value ${cls || ""}">${esc(v)}</div><div class="note">${esc(n)}</div></div>`).join("");
  el("legend").innerHTML = CATS.map((c) =>
    `<span style="--c: var(--${c})">${c === "PENDING" ? esc(t("not_judged")) : c}${categoryName(c) ? ` · ${esc(categoryName(c))}` : ""}</span>`).join("");
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
    title.textContent = `${name}: ${tr(data.summary.series[name])}`;
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
        pointHoverRadius: 7, pointHitRadius: 8, backgroundColor: css(c), borderColor: css(c), order: 1 })),
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
        // Clicking an anomaly point opens its row in the Anomalies table below.
        onClick: (evt, _els, chart) => {
          const hit = chart.getElementsAtEventForMode(evt, "nearest", { intersect: true }, false)
            .find((e) => e.datasetIndex > 0);
          if (hit) showAnomaly(name, data.months[hit.index]);
        },
        onHover: (evt, _els, chart) => {
          const over = chart.getElementsAtEventForMode(evt, "nearest", { intersect: true }, false)
            .some((e) => e.datasetIndex > 0);
          chart.canvas.style.cursor = over ? "pointer" : "default";
        },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: {
            label: (ctx) => {
              const a = info[ctx.label];
              if (ctx.datasetIndex === 0) return `${name}: ${fmt(ctx.parsed.y)}`;
              return a ? t("tip", { l: label(a), v: a.votes, c: a.llm ? ` · C=${num(a.llm.consistency)}` : "" }) : "";
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
  const level = (l) => T.level[l === "mandatory" ? "pending" : l] || l;  // "mandatory": name used until 30/09/2026
  el("rows").innerHTML = rows.map((a) => {
    const llm = a.llm ? catTag(a.llm.category) +
      (a.llm.review_level !== "none" ? ` <span class="muted">${esc(level(a.llm.review_level))}</span>` : "") +
      `<br><span class="muted" title="${esc(t("model_hint"))}">${esc(a.llm.model)} · ${esc(a.llm.prompt_version)}</span>`
      : `<span class="muted">${esc(t("not_judged"))}</span>`;
    const steward = a.review
      ? `<a href="${esc(safeUrl(a.review.url))}" target="_blank" rel="noopener">#${esc(a.review.issue)}</a> ` +
        (a.review.status === "decided" ? catTag(a.review.steward_category)
          : `<span class="muted">${esc(T.status[a.review.status] || a.review.status)}</span>`)
      : "";
    return `<tr id="${rowId(a.series, a.month)}"><td class="num">${esc(a.month)}</td><td>${esc(a.series)}</td>
      <td class="num">${esc(a.votes)}/4 · ${num(a.score)}${a.near_drift ? ` · ${esc(t("drift"))}` : ""}<br><span class="muted">${esc(a.detectors.join(", "))}</span></td>
      <td>${llm}</td><td class="num">${a.llm ? num(a.llm.consistency) : ""}</td><td>${steward}</td>
      <td class="reason">${a.llm ? trHtml(a.llm.reasoning) : ""}</td></tr>`;
  }).join("") || `<tr><td colspan="7" class="muted">${esc(t("nothing"))}</td></tr>`;
}

function rowId(series, month) {
  return `anomaly-${String(series).replace(/[^\w-]/g, "_")}-${month}`;
}

function showAnomaly(series, month) {
  let row = document.getElementById(rowId(series, month));
  if (!row) {  // hidden by the table filter: show everything
    el("filter").value = "all";
    drawTable();
    row = document.getElementById(rowId(series, month));
  }
  if (!row) return;
  history.replaceState(null, "", `${location.search}#${row.id}`);
  row.scrollIntoView({ behavior: "smooth", block: "center" });
  row.classList.remove("flash");
  void row.offsetWidth;  // restart the highlight animation
  row.classList.add("flash");
}

function drawProvenance() {
  const s = data.summary, src = s.source, agg = src.aggregation || {};
  const n = (v) => (v || 0).toLocaleString(LOCALE);
  const items = [
    [t("p_dataset"), src.dataset_url ? `<a href="${esc(safeUrl(src.dataset_url))}" rel="noopener">${esc(src.dataset_url)}</a>` : esc(src.resource_url)],
    [t("p_resource"), esc(src.resource_url)],
    [t("p_sha"), `<code>${esc(src.checksum_sha256)}</code>`],
    [t("p_downloaded"), esc(src.download_started_at || "")],
    [t("p_rows"), `${n(agg.rows_read)} / ${n(agg.rows_excluded)} / ${n(agg.rows_missing_key)}`],
    [t("p_profile"), `<a href="https://github.com/${REPO}/blob/main/profiles/${esc(s.profile.id)}.json">${esc(s.profile.id)}</a> (sha256 <code>${esc((src.profile_sha256 || "").slice(0, 12))}</code>)`],
    [t("p_params"), `<code>${esc(JSON.stringify(s.method_parameters))}</code>`],
    [t("p_env"), esc(`Python ${s.environment.python}; ${Object.entries(s.environment.packages).map(([k, v]) => `${k} ${v}`).join(", ")}`)],
    [t("p_toolkit"), esc(s.toolkit)],
    [t("p_machine"), `<a href="https://github.com/${REPO}/blob/main/results/${esc(s.profile.id)}/layer3_summary.json">layer3_summary.json</a> · <a href="https://github.com/${REPO}/tree/main/results/${esc(s.profile.id)}">${esc(t("p_all"))}</a>`],
  ];
  el("provenance").innerHTML = items.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${v}</dd>`).join("");
}

init().catch((e) => { el("title").textContent = t("load_error"); console.error(e); });
