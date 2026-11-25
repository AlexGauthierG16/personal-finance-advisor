// Frontend behaviour for the page. Plain JS, no framework.
// Every figure shown comes from the API (computed in Python); this file only displays it.
"use strict";

// Starting budget for a student in Milan (EUR per month). Rough estimates; the user edits them.
const BUDGET_DEFAULTS = [
  ["Rent", "600"],          // a room in a shared flat
  ["Groceries", "200"],
  ["Eating out", "100"],
  ["Transport", "30"],      // monthly public transport pass
  ["Subscriptions", "20"],
  ["Shopping", "50"],
  ["Other", "40"],
];

const $ = (id) => document.getElementById(id);

function el(tag, props = {}, text = "") {
  const node = document.createElement(tag);
  Object.assign(node, props);
  if (text !== "") node.textContent = text; // textContent only: statement text is untrusted
  return node;
}

function setStatus(message, isError = false) {
  const status = $("status");
  status.textContent = message;
  status.classList.toggle("error", isError);
}

async function post(url, body) {
  let response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (e) {
    throw new Error("Could not reach the server. Is it running?");
  }
  let data = null;
  try {
    data = await response.json();
  } catch (e) {
    /* not JSON */
  }
  if (!response.ok) {
    const detail = data && (data.error || (typeof data.detail === "string" ? data.detail : null));
    throw new Error(detail || `The server returned an error (${response.status}).`);
  }
  return data;
}

// ---- budget form -----------------------------------------------------------

function buildBudgetForm() {
  const box = $("budget-fields");
  for (const [category, value] of BUDGET_DEFAULTS) {
    const wrap = el("div");
    const id = "budget-" + category.replace(/\W+/g, "-");
    const label = el("label", { htmlFor: id }, category);
    const input = el("input", { id, type: "number", min: "0", step: "0.01", value, required: true });
    input.dataset.category = category;
    wrap.append(label, input);
    box.append(wrap);
  }
}

function readBudget() {
  const budget = {};
  for (const input of document.querySelectorAll("#budget-fields input")) {
    const value = input.value.trim();
    if (value === "") throw new Error(`Enter a budget for ${input.dataset.category} (0 if none).`);
    budget[input.dataset.category] = value; // sent as text; the server parses it exactly
  }
  return budget;
}

// ---- rendering -------------------------------------------------------------

function signed(value) {
  // Display only: show "+" in front of positive variances. No arithmetic.
  return value.startsWith("-") || value === "0.00" ? value : "+" + value;
}

function fmt2(value) {
  // Display only: pad an API amount to two decimals ("600" -> "600.00", "-40" -> "-40.00").
  // String work, no arithmetic; anything else (e.g. more than two decimals) is shown unchanged.
  const m = /^(-?\d+)(?:\.(\d+))?$/.exec(String(value));
  if (!m) return String(value);
  const decimals = m[2] || "";
  return decimals.length >= 2 ? m[0] : `${m[1]}.${decimals.padEnd(2, "0")}`;
}

// ---- chart: budget vs actual (plain SVG; the only maths is geometry) -------

const SVG_NS = "http://www.w3.org/2000/svg";
const CHART = { width: 420, left: 8, right: 396, rowHeight: 46, barY: 22, barHeight: 12, radius: 4,
                tickTop: 18, tickHeight: 20 };

function svgEl(tag, attrs = {}, text = "") {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  if (text !== "") node.textContent = text;
  return node;
}

function chartNumber(text) {
  // For positions only: the labels always print the API's own strings.
  const n = Number(text);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

function round2(n) {
  return Math.round(n * 100) / 100;
}

function barPath(x, y, w, h, radius) {
  // Square at the baseline (left), rounded at the data end (right).
  const r = Math.min(radius, w, h / 2);
  return `M${round2(x)} ${y}h${round2(w - r)}a${r} ${r} 0 0 1 ${r} ${r}v${h - 2 * r}` +
         `a${r} ${r} 0 0 1 ${-r} ${r}h${-round2(w - r)}z`;
}

function renderChart(rows) {
  const c = CHART;
  const plotWidth = c.right - c.left;
  const largest = Math.max(0, ...rows.flatMap((r) => [chartNumber(r.actual), chartNumber(r.budget)])) || 1;
  const xAt = (amount) => c.left + (plotWidth * chartNumber(amount)) / largest;
  const height = rows.length * c.rowHeight;

  const svg = svgEl("svg", {
    viewBox: `0 0 ${c.width} ${height}`,
    role: "img",
    "aria-label": "Bar chart of actual spending against budget for each category. The table above has the same figures.",
  });
  svg.append(svgEl("line", { class: "chart-baseline", x1: c.left, x2: c.left, y1: 0, y2: height }));

  rows.forEach((r, i) => {
    const y = i * c.rowHeight;
    const g = svgEl("g", { class: "chart-row" });
    g.append(svgEl("title", {},
      `${r.category}: actual ${fmt2(r.actual)}, budget ${fmt2(r.budget)}, variance ${signed(fmt2(r.variance))}, ` +
      (r.over_budget ? "over budget" : "within budget")));
    g.append(svgEl("rect", { class: "chart-hit", x: 0, y, width: c.width, height: c.rowHeight }));
    g.append(svgEl("text", { class: "chart-category", x: c.left, y: y + 14 }, r.category));
    const amounts = `${fmt2(r.actual)} / ${fmt2(r.budget)}` +
      (r.over_budget ? ` (${signed(fmt2(r.variance))} over)` : "");
    g.append(svgEl("text", { class: "chart-amounts", x: c.right, y: y + 14, "text-anchor": "end" }, amounts));

    const barWidth = xAt(r.actual) - c.left;
    if (barWidth > 0) {
      g.append(svgEl("path", {
        class: r.over_budget ? "bar-over" : "bar-under",
        d: barPath(c.left, y + c.barY, barWidth, c.barHeight, c.radius),
      }));
    }
    const tickX = round2(xAt(r.budget));
    const tick = { x1: tickX, x2: tickX, y1: y + c.tickTop, y2: y + c.tickTop + c.tickHeight };
    g.append(svgEl("line", { class: "tick-halo", ...tick }));
    g.append(svgEl("line", { class: "tick", ...tick }));
    svg.append(g);
  });
  $("chart").replaceChildren(svg);
}
// ---- end chart ---------------------------------------------------------------

function renderResults(data) {
  const rows = $("rows");
  rows.replaceChildren();
  for (const r of data.rows) {
    const tr = el("tr");
    if (r.over_budget) tr.classList.add("over");
    const variance = el("td", { className: "num variance" }, signed(fmt2(r.variance)));
    if (r.over_budget) variance.append(el("span", { className: "over-label" }, "over"));
    tr.append(
      el("th", { scope: "row" }, r.category),
      el("td", { className: "num" }, fmt2(r.actual)),
      el("td", { className: "num" }, fmt2(r.budget)),
      variance,
    );
    rows.append(tr);
  }

  renderChart(data.rows);

  const summary = $("summary");
  summary.replaceChildren();
  const add = (label, value, extra = "") => {
    const dt = el("dt", {}, label);
    const dd = el("dd", {}, value);
    if (extra === "savings") {
      dt.className = "savings-label";
      dd.className = "savings-value" + (value.startsWith("-") ? " negative" : "");
    }
    summary.append(dt, dd);
  };
  add("Income", data.income);
  add("Transferred to your own accounts (not counted)", data.transfers);
  add("Savings (income minus spending)", data.savings, "savings");
  $("results").hidden = false;
}

function renderReview(data) {
  const nr = data.needs_review;
  const list = $("review-list");
  list.replaceChildren();
  $("review").hidden = false;
  if (nr.items.length === 0) {
    $("review-intro").textContent = "Nothing to review: every transaction has a category.";
    return;
  }
  $("review-intro").textContent =
    `${nr.items.length} transaction(s) could not be categorised reliably (${nr.spend} in total). ` +
    "They are not in the table above but are counted as spending in your savings. " +
    "Pick the right category for each one.";
  for (const item of nr.items) {
    const li = el("li", { className: "review-item" });
    const what = el("div", { className: "what" });
    what.append(
      el("div", { className: "when" }, item.date),
      el("div", {}, `${item.description} — ${item.amount}`),
    );

    const select = el("select", { id: "cat-" + item.id });
    select.setAttribute("aria-label", `Category for ${item.description}`);
    select.append(el("option", { value: "" }, "Choose a category…"));
    for (const c of data.assignable_categories) select.append(el("option", { value: c }, c));
    const button = el("button", { type: "button", disabled: true }, "Assign");
    select.addEventListener("change", () => { button.disabled = select.value === ""; });
    button.addEventListener("click", () => assign(item.id, select.value, button));

    const controls = el("div", { className: "controls" });
    controls.append(select, button);
    li.append(what, controls);
    list.append(li);
  }
}

function render(data) {
  renderResults(data);
  renderReview(data);
  $("ask").hidden = false;
}

function clearAnswer() {
  $("answer-box").hidden = true;
  $("warning").hidden = true;
}

// ---- preview: what is sent to the AI ---------------------------------------

let previewToken = 0; // ignore answers for a file the user has already replaced

function renderPreview(data) {
  const rows = $("preview-rows");
  rows.replaceChildren();
  for (const r of data.rows) {
    const tr = el("tr");
    if (r.masked) tr.classList.add("masked");
    const sent = el("td", { className: "sent" }, r.sent);
    if (r.masked) sent.append(el("span", { className: "masked-label" }, "masked"));
    tr.append(el("td", {}, r.original), sent);
    rows.append(tr);
  }
  $("preview-summary").textContent =
    data.masked_count === 0
      ? `${data.rows.length} descriptions. Nothing needed masking.`
      : `${data.rows.length} descriptions; personal data was masked in ${data.masked_count} of them.`;
  $("preview").hidden = false;
}

async function onFileChosen() {
  const token = ++previewToken;
  const button = $("analyse-btn");
  button.disabled = true;
  $("preview").hidden = true;
  const file = $("file").files[0];
  if (!file) return setStatus("");
  setStatus("Checking what would be sent to the AI\u2026");
  try {
    const data = await post("/api/preview", { csv: await file.text() });
    if (token !== previewToken) return;
    renderPreview(data);
    button.disabled = false;
    setStatus("Check what is sent to the AI above, set your budget, then click Analyse.");
  } catch (e) {
    if (token === previewToken) setStatus(e.message, true);
  }
}

// ---- actions ---------------------------------------------------------------

async function analyse(event) {
  event.preventDefault();
  const file = $("file").files[0];
  if (!file) return setStatus("Choose a CSV file first.", true);
  const button = $("analyse-btn");
  button.disabled = true;
  setStatus("Reading and categorising your transactions…");
  try {
    const budget = readBudget();
    const csv = await file.text();
    const data = await post("/api/analyse", { csv, budget });
    clearAnswer();
    render(data);
    setStatus(`Done: ${data.transaction_count} transactions analysed.`);
  } catch (e) {
    setStatus(e.message, true);
  } finally {
    button.disabled = false;
  }
}

async function assign(id, category, button) {
  button.disabled = true;
  setStatus("Updating…");
  try {
    const data = await post("/api/review", { id, category });
    clearAnswer();
    render(data);
    setStatus("Updated.");
  } catch (e) {
    setStatus(e.message, true);
    button.disabled = false;
  }
}

async function ask(event) {
  event.preventDefault();
  const question = $("question").value.trim();
  if (!question) return setStatus("Write a question first.", true);
  const button = $("ask-btn");
  button.disabled = true;
  setStatus("Thinking…");
  try {
    const data = await post("/api/ask", { question });
    showAnswer(data);
    setStatus("");
  } catch (e) {
    setStatus(e.message, true);
  } finally {
    button.disabled = false;
  }
}

function verificationText(data) {
  const prefix = "Numbers checked against tool results: ";
  if (!data.finished) return prefix + "not checked, the agent ran out of steps";
  if (data.unverified_numbers.length > 0) return prefix + "not verified: " + data.unverified_numbers.join(", ");
  if (data.numbers_checked === 0) return prefix + "no numbers in this answer";
  return prefix + "all verified";
}

function renderHow(data) {
  const list = $("steps");
  list.replaceChildren();
  for (const step of data.steps) {
    const li = el("li", { className: step.ok ? "" : "failed" });
    li.append(el("code", {}, step.label), " \u2192 ", el("span", {}, step.summary));
    list.append(li);
  }
  $("steps-empty").hidden = data.steps.length > 0;
  const verification = $("verification");
  verification.textContent = verificationText(data);
  verification.classList.toggle("bad", !data.finished || data.unverified_numbers.length > 0);
}

function showAnswer(data) {
  const warning = $("warning");
  let answer = data.answer;
  if (data.warning) {
    // The server puts the warning in the first paragraph, then the original answer.
    const [first, ...rest] = data.answer.split("\n\n");
    warning.textContent =
      rest.length > 0
        ? `${first} Treat these figures with caution.`
        : `Some numbers could not be verified: ${data.unverified_numbers.join(", ")}. Treat them with caution.`;
    answer = rest.length > 0 ? rest.join("\n\n") : data.answer;
    warning.hidden = false;
  } else {
    warning.hidden = true;
  }
  $("answer").textContent = answer;
  renderHow(data);
  $("answer-box").hidden = false;
}

for (const button of document.querySelectorAll(".example")) {
  button.addEventListener("click", () => {
    $("question").value = button.textContent;
    $("question").focus();
  });
}

buildBudgetForm();
$("file").addEventListener("change", onFileChosen);
$("budget-form").addEventListener("submit", analyse);
$("ask-form").addEventListener("submit", ask);
