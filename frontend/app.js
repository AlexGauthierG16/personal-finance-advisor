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

function renderResults(data) {
  const rows = $("rows");
  rows.replaceChildren();
  for (const r of data.rows) {
    const tr = el("tr");
    if (r.over_budget) tr.classList.add("over");
    const variance = el("td", { className: "num variance" }, signed(r.variance));
    if (r.over_budget) variance.append(el("span", { className: "over-label" }, "over"));
    tr.append(
      el("th", { scope: "row" }, r.category),
      el("td", { className: "num" }, r.actual),
      el("td", { className: "num" }, r.budget),
      variance,
    );
    rows.append(tr);
  }

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
  $("tools").textContent = data.tools_used.length
    ? "Figures looked up with: " + data.tools_used.join(", ")
    : "No figures were looked up for this answer.";
  $("answer-box").hidden = false;
}

for (const button of document.querySelectorAll(".example")) {
  button.addEventListener("click", () => {
    $("question").value = button.textContent;
    $("question").focus();
  });
}

buildBudgetForm();
$("budget-form").addEventListener("submit", analyse);
$("ask-form").addEventListener("submit", ask);
