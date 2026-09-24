"use strict";

const state = {
  health: null,
  conversation: null,
  catalog: [],
  busy: false,
  workspaceView: "catalogue",
  renderedResultId: null,
};

let toastTimer = null;
let dialogReturnFocus = null;

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];
const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&#039;");

function inlineMarkdown(value) {
  return escapeHtml(value)
    .replace(/\[([^\]]+)\]\((https:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>");
}

function tableCells(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((cell) => cell.trim());
}

function isTableDivider(line) {
  const cells = tableCells(line);
  return cells.length > 1 && cells.every((cell) => /^:?-{3,}:?$/.test(cell));
}

function renderSafeMarkdown(value) {
  const lines = String(value ?? "").replaceAll("\r\n", "\n").split("\n");
  const output = [];
  let inList = false;
  const closeList = () => {
    if (inList) output.push("</ul>");
    inList = false;
  };
  for (let index = 0; index < lines.length; index += 1) {
    const rawLine = lines[index];
    const line = rawLine.trim();
    if (line.includes("|") && index + 1 < lines.length && isTableDivider(lines[index + 1])) {
      closeList();
      const headers = tableCells(line);
      const rows = [];
      index += 2;
      while (index < lines.length && lines[index].trim().includes("|")) {
        rows.push(tableCells(lines[index]));
        index += 1;
      }
      index -= 1;
      output.push(`<div class="markdown-table-wrap"><table class="markdown-table"><thead><tr>${headers.map((cell) => `<th>${inlineMarkdown(cell)}</th>`).join("")}</tr></thead><tbody>${rows.map((row) => `<tr>${headers.map((_, cellIndex) => `<td>${inlineMarkdown(row[cellIndex] || "")}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`);
      continue;
    }
    const bullet = line.match(/^[-*]\s+(.+)$/);
    if (bullet) {
      if (!inList) output.push("<ul>");
      inList = true;
      output.push(`<li>${inlineMarkdown(bullet[1])}</li>`);
      continue;
    }
    closeList();
    if (!line) continue;
    if (/^-{3,}$/.test(line)) {
      output.push("<hr>");
    } else {
      output.push(`<p>${inlineMarkdown(line)}</p>`);
    }
  }
  closeList();
  return output.join("");
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = { message: `Request failed (${response.status}).` };
    try {
      detail = (await response.json()).detail || detail;
      if (Array.isArray(detail)) {
        detail = { message: detail[0]?.msg || `Request failed (${response.status}).` };
      }
    } catch (_) { /* noop */ }
    const error = new Error(detail.message || detail.error || "Request failed.");
    error.status = response.status;
    error.code = detail.error;
    throw error;
  }
  return response.json();
}

function money(cents, currency = "SGD") {
  try {
    return new Intl.NumberFormat("en-SG", {
      style: "currency",
      currency,
      currencyDisplay: "code",
    }).format((cents || 0) / 100);
  } catch (_) {
    return `${escapeHtml(currency)} ${((cents || 0) / 100).toFixed(2)}`;
  }
}

function latestResult() {
  return state.conversation?.latest_result || null;
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("visible");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove("visible"), 3200);
}

function setBusy(busy, label = "Checking enquiry…") {
  state.busy = busy;
  $("#sendButton").disabled = busy;
  $("#messageInput").disabled = busy;
  $("#newConversation").disabled = busy;
  $("#resetDemo").disabled = busy;
  $$("[data-prompt], .select-button, [data-quantity-index], #saveQuote, .confirm-version").forEach((button) => {
    button.disabled = busy;
  });
  $("#messageList").setAttribute("aria-busy", String(busy));
  $("#composerHint").textContent = busy ? label : "Enter sends · Shift+Enter adds a line";
  const existing = $("#processingState");
  if (busy && !existing) {
    $("#messageList").insertAdjacentHTML("beforeend", `<div id="processingState" class="message assistant processing-message" role="status"><span class="role">Quotation agent</span><div class="message-body"><span class="spinner" aria-hidden="true"></span><span>${escapeHtml(label)}</span></div></div>`);
    $("#messageList").scrollTop = $("#messageList").scrollHeight;
  } else if (!busy && existing) {
    existing.remove();
  }
}

async function refreshConversation() {
  if (!state.conversation?.id) return;
  state.conversation = await api(`/api/conversations/${encodeURIComponent(state.conversation.id)}`);
  render();
}

async function recoverConflict(error) {
  if (error.status !== 409) return false;
  try {
    await refreshConversation();
  } catch (_) { /* Keep the original conflict message. */ }
  return true;
}

function showDialog(dialog) {
  dialogReturnFocus = document.activeElement;
  dialog.showModal();
  window.requestAnimationFrame(() => dialog.querySelector(".icon-button")?.focus());
}

function safeLocalHref(value) {
  const href = String(value || "");
  return href.startsWith("/api/") ? href : "#";
}

async function createConversation() {
  const conversation = await api("/api/conversations", {
    method: "POST",
    body: JSON.stringify({ driver: state.health?.configured_driver || "offline" }),
  });
  state.conversation = conversation;
  state.workspaceView = "catalogue";
  state.renderedResultId = null;
  $("#catalogueBrowser").open = false;
  $("#versionHistory").open = false;
  $("#scenarioDetails").open = true;
  render();
  $("#messageInput").focus();
}

async function boot() {
  try {
    [state.health, state.catalog] = await Promise.all([api("/api/health"), api("/api/products")]);
    $("#datasetBadge").textContent = `Catalogue ${state.health.dataset_version}`;
    $("#driverBadge").textContent = state.health.configured_driver === "gateway" ? "Organizer LLM Gateway" : "Deterministic offline";
    // A browser session never inherits the previous visitor's enquiry. The
    // server keeps its audit history, while every page load gets a fresh ID.
    localStorage.removeItem("quotationConversationId");
    await createConversation();
    render();
  } catch (error) {
    showToast(error.message);
    $("#candidateSummary").textContent = "Catalogue unavailable";
    $("#candidateList").setAttribute("aria-busy", "false");
    $("#candidateList").innerHTML = `<div class="loading-state"><span class="empty-icon" aria-hidden="true">!</span><strong>Workbench unavailable</strong><span>${escapeHtml(error.message)}</span></div>`;
  }
}

async function sendMessage(content) {
  if (!content.trim() || state.busy) return;
  setBusy(true);
  $("#sendButton").textContent = "Checking…";
  try {
    state.conversation = await api(`/api/conversations/${state.conversation.id}/messages`, {
      method: "POST",
      body: JSON.stringify({ content: content.trim() }),
    });
    $("#messageInput").value = "";
    render();
  } catch (error) {
    showToast(error.message);
  } finally {
    setBusy(false);
    $("#sendButton").textContent = "Review enquiry";
  }
}

function render() {
  const resultId = state.conversation?.latest_result_message_id;
  if (resultId && resultId !== state.renderedResultId) {
    state.workspaceView = latestResult()?.quote_draft ? "quote" : "catalogue";
    state.renderedResultId = resultId;
    $("#scenarioDetails").open = false;
    $(".workspace-content").scrollTop = 0;
  }
  renderStatus();
  renderMessages();
  renderRequirements();
  renderCandidates();
  renderTrace();
  renderQuote();
  renderVersions();
  renderWorkspace();
}

function switchWorkspace(view, focus = false) {
  state.workspaceView = view;
  renderWorkspace();
  $(".workspace-content").scrollTop = 0;
  if (focus) $(`#${view}Tab`).focus();
}

function renderWorkspace() {
  const result = latestResult();
  const draft = result?.quote_draft;
  const versions = state.conversation?.quote_versions || [];
  const latestVersion = versions[versions.length - 1];
  const view = state.workspaceView;
  $$("[data-view]").forEach((tab) => {
    const selected = tab.dataset.view === view;
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
  });
  $("#catalogueView").hidden = view !== "catalogue";
  $("#quoteView").hidden = view !== "quote";
  $("#workspaceTitle").textContent = draft ? "Your quote, ready for review." : result ? "Find the right fit. Verify the details." : "A clear path to a confident quote.";
  const needsDetails = result?.ask_for?.some((slot) => slot !== "product_specification_or_model");
  $("#workspaceStep").textContent = draft ? "Step 3 of 3 · Review" : result && !needsDetails ? "Step 2 of 3 · Verify" : "Step 1 of 3 · Understand";
  $("#quoteTabStatus").textContent = latestVersion?.exportable ? `v${latestVersion.version} confirmed` : draft ? "Draft ready" : versions.length ? `${versions.length} saved` : "Not started";
  const alert = $("#workspaceAlert");
  const warnings = {
    explain_limitation: ["Compatibility conflict", "The requested model does not meet the requirements. Review the highlighted product and its source evidence below."],
    rule_violation: ["Policy blocked", "No quote was calculated. Review the policy explanation in the conversation before continuing."],
    invalid_quantity: ["Quantity needs attention", "Enter a positive whole number in the conversation to continue."],
    no_match: ["No matching product", "No catalogue model meets all stated requirements. Adjust a requirement before selecting a product."],
    budget_conflict: ["Budget needs attention", "Review the budget explanation in the conversation before continuing."],
  };
  const warning = draft?.within_budget === false
    ? ["Over budget", `This draft exceeds the stated budget by ${money(draft.over_budget_cents)}. Adjust the quantity or product if a lower total is required.`]
    : warnings[result?.status];
  alert.hidden = !warning;
  alert.innerHTML = warning ? `<strong>${escapeHtml(warning[0])}</strong>${escapeHtml(warning[1])}` : "";
  const dock = $("#quoteDock");
  dock.hidden = !draft;
  dock.classList.toggle("over", draft?.within_budget === false);
  dock.innerHTML = draft ? `<div><span>Draft total · ${draft.lines.reduce((count, line) => count + line.quantity, 0)} units</span><strong>${money(draft.total_cents)}</strong></div>${view === "catalogue" ? '<button id="returnToQuote" type="button">Review quote →</button>' : '<span class="dock-note">Calculated by the pricing tool</span>'}` : "";
  $("#returnToQuote")?.addEventListener("click", () => switchWorkspace("quote", true));
}

function renderStatus() {
  const result = latestResult();
  const chip = $("#conversationStatus");
  const driver = result?.configured_driver || state.health?.configured_driver || "offline";
  $("#driverBadge").classList.toggle("is-fallback", Boolean(result?.used_fallback));
  $("#driverBadge").textContent = result?.used_fallback
    ? "Offline fallback"
    : driver === "gateway" ? "Organizer LLM Gateway" : "Deterministic offline";
  const labels = {
    needs_clarification: "Needs details",
    ready_to_quote: "Draft ready",
    explain_limitation: "Conflict found",
    answer_with_evidence: "Evidence ready",
    no_match: "No match",
    budget_conflict: "Over budget",
    rule_violation: "Policy blocked",
    invalid_quantity: "Invalid quantity",
  };
  const status = result?.status === "ready_to_quote" && result.quote_draft?.within_budget === false
    ? "budget_conflict"
    : result?.status;
  const colors = {
    needs_clarification: "status-pending",
    ready_to_quote: "status-ready",
    answer_with_evidence: "status-review",
    explain_limitation: "status-warning",
    no_match: "status-warning",
    budget_conflict: "status-warning",
    rule_violation: "status-warning",
    invalid_quantity: "status-warning",
  };
  chip.textContent = result ? (labels[status] || "In review") : "Waiting";
  chip.className = `status-chip ${result ? (colors[status] || "status-review") : "status-idle"}`;
}

function renderMessages() {
  const list = $("#messageList");
  const messages = state.conversation?.messages || [];
  if (!messages.length) {
    list.innerHTML = `<div class="empty-state"><span class="empty-icon" aria-hidden="true">→</span><div><strong>Start with the customer’s words.</strong><span>Use a scenario or paste an English enquiry below.</span></div></div>`;
    return;
  }
  list.innerHTML = messages.map((message) => `
    <article class="message ${escapeHtml(message.role)}">
      <span class="role">${message.role === "user" ? "Customer" : "Quotation agent"}</span>
      <div class="message-body">${renderSafeMarkdown(message.content)}</div>
    </article>`).join("");
  list.scrollTop = list.scrollHeight;
}

function renderRequirements() {
  const ledger = $("#requirementLedger");
  const result = latestResult();
  if (!result?.ask_for?.length) {
    ledger.hidden = true;
    ledger.innerHTML = "";
    return;
  }
  const names = {
    quantity: "quantity",
    product_specification_or_model: "product selection",
    usb_c_video_requirement: "USB-C video",
    host_charging_requirement: "host charging",
    actual_vs_marketed_diagonal: "exact diagonal",
    minimum_host_pd_watts: "minimum PD",
  };
  ledger.innerHTML = `<strong>Still needed:</strong> ${result.ask_for.map((slot) => escapeHtml(names[slot] || slot)).join(" · ")}`;
  ledger.hidden = false;
}

function uniqueProducts(rows) {
  const seen = new Set();
  return rows.filter((row) => row && !seen.has(row.sku) && seen.add(row.sku));
}

function renderCandidates() {
  const result = latestResult();
  const suggestions = result?.suggestions || [];
  let rows = suggestions.length
    ? [...(result?.candidates || []), ...suggestions]
    : (result?.candidates || []);
  rows = uniqueProducts(rows);
  $("#candidateList").setAttribute("aria-busy", "false");
  $("#candidateSummary").textContent = suggestions.length
    ? `${suggestions.length} compatible alternative${suggestions.length === 1 ? "" : "s"}`
    : result?.candidates?.length
      ? `${result.candidates.length} catalogue match${result.candidates.length === 1 ? "" : "es"}`
      : result ? "Resolve the enquiry to find matching products" : "Start with the enquiry. We’ll bring the evidence here.";
  $("#catalogueTabCount").textContent = rows.length ? `${rows.length} product${rows.length === 1 ? "" : "s"}` : "Catalogue";
  $("#catalogueCount").textContent = `${state.catalog.length} monitors`;
  const welcome = `<div class="workspace-welcome"><span class="welcome-kicker">From enquiry to approved quote</span><h3>The right product.<br>The evidence to back it up.</h3><p>Describe what the customer needs. Review the fit, check the source, then approve an exact quotation.</p><div class="welcome-steps"><div class="welcome-step"><span>1</span><div><strong>Clarify the requirements</strong><p>Start in the conversation or try a demo scenario.</p></div></div><div class="welcome-step"><span>2</span><div><strong>Choose with evidence</strong><p>Compare relevant products and inspect official specifications.</p></div></div><div class="welcome-step"><span>3</span><div><strong>Review, confirm and export</strong><p>Save versions, see what changed and download the confirmed PDF.</p></div></div></div></div>`;
  const empty = `<div class="workspace-empty"><strong>${result?.status === "no_match" ? "No products meet these requirements" : "Let’s resolve the details first"}</strong><p>${result?.status === "no_match" ? "Change a requirement in the conversation. The full catalogue is available below for reference." : "Continue the conversation on the left. Relevant products will appear here when available."}</p></div>`;
  $("#candidateList").innerHTML = rows.length ? rows.map((product) => candidateCard(product, {
    suggested: suggestions.some((row) => row.sku === product.sku),
    incompatible: result?.status === "explain_limitation" && result?.candidates?.some((row) => row.sku === product.sku),
  })).join("") : result ? empty : welcome;
  // Keep the full catalogue separate from the Agent's filtered results.
  $("#browseList").innerHTML = state.catalog.map((product) => candidateCard(product, {
    incompatible: result?.conflicts?.some((conflict) => conflict.sku === product.sku),
  })).join("");
}

function candidateCard(product, flags) {
  const pd = product.usb_c_video === true
    ? product.usb_c_pd_watts == null ? "Host PD unknown" : `${product.usb_c_pd_watts}W host PD`
    : product.usb_c_video === false ? "No USB-C video" : "USB-C video unknown";
  const refresh = product.max_refresh_hz == null ? "Unknown" : `${product.max_refresh_hz} Hz`;
  const screen = product.screen_inches == null ? "Unknown" : `${product.screen_inches} in`;
  const resolution = product.resolution == null ? "Unknown" : product.resolution;
  const marker = flags.suggested
    ? `<span class="candidate-label suggestion">Compatible alternative</span>`
    : flags.incompatible
      ? `<span class="candidate-label">Requested model · conflict</span>`
      : `<span class="candidate-sku">${escapeHtml(product.sku)}</span>`;
  const canSelect = !flags.incompatible;
  return `<article class="candidate-card ${flags.suggested ? "suggested" : ""} ${flags.incompatible ? "incompatible" : ""}">
    <div class="candidate-top">
      <div>${marker}<h3 class="candidate-name">${escapeHtml(product.model)}</h3><span class="candidate-sku">${escapeHtml(product.name)}</span></div>
      <span class="price">${money(product.unit_price_cents)}</span>
    </div>
    <div class="spec-grid">
      <div class="spec-cell"><span>Viewable diagonal</span><strong>${escapeHtml(screen)}</strong></div>
      <div class="spec-cell"><span>Native resolution</span><strong>${escapeHtml(resolution)}</strong></div>
      <div class="spec-cell"><span>USB-C host link</span><strong>${escapeHtml(pd)}</strong></div>
      <div class="spec-cell"><span>Max preset refresh</span><strong>${escapeHtml(refresh)}</strong></div>
    </div>
    ${flags.incompatible ? '<p class="candidate-conflict">Does not meet the requested connection or charging requirements. Inspect the source before choosing an alternative.</p>' : ""}
    <div class="candidate-actions">
      <button class="evidence-button" data-sku="${escapeHtml(product.sku)}" type="button" aria-label="Inspect source evidence for ${escapeHtml(product.model)}">Inspect source evidence</button>
      ${canSelect ? `<button class="select-button" data-sku="${escapeHtml(product.sku)}" type="button" aria-label="Quote one ${escapeHtml(product.model)} at zero discount">Quote 1 unit</button>` : ""}
    </div>
  </article>`;
}

function renderTrace() {
  const trace = latestResult()?.trace || [];
  const tools = trace.filter((step) => step.tool);
  $("#toolTrace").innerHTML = tools.length
    ? `<details class="trace-audit">
        <summary><span>Tool activity & audit</span><small>${tools.length} verified action${tools.length === 1 ? "" : "s"}</small></summary>
        <div class="trace-steps">${tools.map((step, index) => `<div class="trace-step">
          <strong>${index + 1}. ${escapeHtml(step.tool)}</strong>
          <span>${escapeHtml(step.result || "completed")}</span>
          <pre>${escapeHtml(JSON.stringify(step.args || {}, null, 2))}</pre>
        </div>`).join("")}</div>
      </details>`
    : `<strong>Tool activity</strong> &nbsp;No lookup or calculation yet`;
}

function renderQuote() {
  const body = $("#quoteBody");
  const actions = $("#quoteActions");
  const draft = latestResult()?.quote_draft;
  $("#selectedProduct").hidden = !draft;
  $("#selectedProduct").innerHTML = draft ? `<span><strong>Selected:</strong> ${draft.lines.map((line) => `${escapeHtml(line.name)} × ${line.quantity}`).join(" · ")}</span><button id="changeProduct" type="button">View products →</button>` : "";
  $("#changeProduct")?.addEventListener("click", () => switchWorkspace("catalogue", true));
  if (!draft) {
    body.innerHTML = `<div class="empty-quote"><span class="quote-glyph" aria-hidden="true">SGD</span><div><strong>No calculated lines</strong><p>Confirm the requirements and select a product to create a draft.</p></div></div>`;
    actions.hidden = true;
    return;
  }
  body.innerHTML = `${draft.lines.map((line, index) => `
    <div class="quote-line">
      <div class="line-top"><div><strong>${escapeHtml(line.name)}</strong><br><span>${escapeHtml(line.sku)}</span></div><strong>${money(line.net_cents)}</strong></div>
      <div class="line-math">
        <span>${money(line.unit_price_cents)} each · ${(line.discount_bps / 100).toFixed(2)}% discount</span>
        <div class="quantity-control"><label for="qty-${index}">Qty</label><input id="qty-${index}" type="number" min="1" step="1" value="${line.quantity}" aria-label="Quantity for ${escapeHtml(line.name)}"><button type="button" data-quantity-index="${index}" data-model="${escapeHtml(line.sku)}">Update</button></div>
      </div>
    </div>`).join("")}
    <div class="total-block">
      ${draft.within_budget === undefined ? "" : `<div class="budget-row ${draft.within_budget ? "" : "over"}"><span>${draft.within_budget ? "Within stated budget" : `Over budget by ${money(draft.over_budget_cents)}`}</span><span>Validity ${draft.validity_days} days</span></div>`}
    </div>`;
  $$('[data-quantity-index]').forEach((button) => button.addEventListener("click", () => {
    const input = $(`#qty-${button.dataset.quantityIndex}`);
    const quantity = Number(input.value);
    if (!Number.isInteger(quantity) || quantity < 1) return showToast("Quantity must be a positive whole number.");
    sendMessage(`Change ${button.dataset.model} quantity to ${quantity} units.`);
  }));
  actions.hidden = false;
  $("#saveStatus").textContent = "";
}

function renderVersions() {
  const versions = state.conversation?.quote_versions || [];
  $("#versionCount").textContent = versions.length;
  $("#versionCount").setAttribute("aria-label", `${versions.length} saved version${versions.length === 1 ? "" : "s"}`);
  const versionCards = versions.map((version, index) => `<div class="version-item ${version.exportable ? "is-confirmed" : ""}">
        <div><span>Version ${version.version} · ${version.line_count} line${version.line_count === 1 ? "" : "s"}</span><small>${escapeHtml(version.status.replaceAll("_", " "))}</small></div>
        <strong>${money(version.total_cents)}</strong>
        <div class="version-actions">
          ${index ? `<button class="compare-version" data-from="${escapeHtml(versions[index - 1].id)}" data-to="${escapeHtml(version.id)}" type="button">Compare v${versions[index - 1].version} → v${version.version}</button>` : ""}
          ${version.confirmable ? `<button class="confirm-version" data-id="${escapeHtml(version.id)}" type="button">Confirm</button>` : ""}
          ${version.exportable ? `<a class="download-pdf" href="/api/quotes/${encodeURIComponent(version.id)}/pdf" download>Download confirmed PDF</a>` : ""}
        </div>
      </div>`);
  $("#versionList").innerHTML = versionCards.length ? versionCards[versionCards.length - 1] : "<p>Save a draft to begin the version history.</p>";
  $("#versionHistory").hidden = versions.length < 2;
  $("#versionHistoryLabel").textContent = `Earlier versions (${Math.max(0, versions.length - 1)})`;
  $("#historyList").innerHTML = versionCards.slice(0, -1).reverse().join("");
  $$(".compare-version").forEach((button) => button.addEventListener("click", () => openDiff(button.dataset.from, button.dataset.to)));
  $$(".confirm-version").forEach((button) => button.addEventListener("click", () => confirmVersion(button.dataset.id, button)));
  renderWorkspace();
}

async function saveQuote() {
  const button = $("#saveQuote");
  button.disabled = true;
  button.textContent = "Saving…";
  try {
    const saved = await api(`/api/conversations/${state.conversation.id}/quotes`, {
      method: "POST",
      body: JSON.stringify({
        result_message_id: state.conversation.latest_result_message_id,
        customer_display_name: $("#customerName").value.trim() || null,
      }),
    });
    state.conversation = await api(`/api/conversations/${state.conversation.id}`);
    renderVersions();
    $("#saveStatus").textContent = `Version ${saved.version} saved`;
    showToast(`Draft version ${saved.version} saved.`);
  } catch (error) {
    await recoverConflict(error);
    showToast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = "Save draft version";
  }
}

async function confirmVersion(quoteId, button) {
  const customer = $("#customerName").value.trim();
  const confirmedBy = $("#confirmedBy").value.trim();
  if (!customer || !confirmedBy) return showToast("Customer and confirmer are required.");
  if (button) {
    button.disabled = true;
    button.textContent = "Confirming…";
  }
  try {
    const quote = await api(`/api/quotes/${encodeURIComponent(quoteId)}`);
    await api(`/api/quotes/${encodeURIComponent(quoteId)}/confirm`, {
      method: "POST",
      body: JSON.stringify({
        snapshot_token: quote.snapshot_token,
        customer_display_name: customer,
        confirmed_by: confirmedBy,
      }),
    });
    state.conversation = await api(`/api/conversations/${state.conversation.id}`);
    renderVersions();
    showToast(`Version ${quote.version} confirmed and ready to export.`);
  } catch (error) {
    await recoverConflict(error);
    showToast(error.message);
  } finally {
    if (button?.isConnected) {
      button.disabled = false;
      button.textContent = "Confirm";
    }
  }
}

async function openDiff(fromId, toId) {
  try {
    const diff = await api(`/api/quotes/${encodeURIComponent(fromId)}/diff/${encodeURIComponent(toId)}`);
    const changes = diff.lines.changed || [];
    const added = diff.lines.added || [];
    const removed = diff.lines.removed || [];
    const currencyChange = diff.metadata_changes?.currency;
    const beforeCurrency = diff.comparable ? diff.currency : (currencyChange?.from || "SGD");
    const afterCurrency = diff.comparable ? diff.currency : (currencyChange?.to || "SGD");
    const fieldLabels = { quantity: "Quantity", gross_cents: "Subtotal", net_cents: "Line total", unit_price_cents: "Unit price", discount_cents: "Discount amount", discount_bps: "Discount" };
    const formatChange = (field, value, currency) => field.endsWith("_cents") ? money(value, currency) : field === "discount_bps" ? `${(value / 100).toFixed(2)}%` : escapeHtml(value);
    const changedHtml = changes.map((line) => `<div class="diff-line"><strong>Changed · ${escapeHtml(line.after?.model || line.before?.model || line.line_id)}</strong>${Object.entries(line.changes).map(([field, value]) => `<span>${escapeHtml(fieldLabels[field] || field.replaceAll("_", " "))}: ${formatChange(field, value.from, beforeCurrency)} → ${formatChange(field, value.to, afterCurrency)}</span>`).join("")}</div>`).join("");
    const addedHtml = added.map((line) => `<div class="diff-line"><strong>Added · ${escapeHtml(line.after?.model || line.line_id)}</strong><span>Quantity: ${escapeHtml(line.after?.quantity)}</span><span>Net: ${money(line.after?.net_cents, afterCurrency)}</span></div>`).join("");
    const removedHtml = removed.map((line) => `<div class="diff-line"><strong>Removed · ${escapeHtml(line.before?.model || line.line_id)}</strong><span>Quantity: ${escapeHtml(line.before?.quantity)}</span><span>Net: ${money(line.before?.net_cents, beforeCurrency)}</span></div>`).join("");
    $("#diffTitle").textContent = `Version ${diff.from.version} → Version ${diff.to.version}`;
    $("#diffContent").innerHTML = `
      <div class="diff-summary"><span>Total before</span><strong>${money(diff.totals.total_cents.from, beforeCurrency)}</strong><span>Total after</span><strong>${money(diff.totals.total_cents.to, afterCurrency)}</strong><span>Net change</span><strong>${diff.comparable ? money(diff.totals.total_cents.delta, diff.currency) : "Different currencies"}</strong></div>
      ${changedHtml || addedHtml || removedHtml ? changedHtml + addedHtml + removedHtml : "<p class=\"availability-warning\">No line changes.</p>"}
    `;
    showDialog($("#diffDialog"));
  } catch (error) {
    showToast(error.message);
  }
}

async function openEvidence(sku) {
  try {
    const product = await api(`/api/products/${encodeURIComponent(sku)}`);
    $("#dialogSku").textContent = `${product.sku} · Official ${product.brand} specification`;
    $("#dialogTitle").textContent = `${product.model} specification evidence`;
    $("#evidenceContent").innerHTML = `
      <p class="availability-warning">Stock and delivery timing are not available in this dataset. Every value below links to its source page.</p>
      ${product.evidence.map((item) => `<div class="evidence-row">
        <span class="field">${escapeHtml(item.field.replaceAll("_", " "))}</span>
        <span class="value">${escapeHtml(typeof item.value === "object" ? JSON.stringify(item.value) : item.value)}</span>
        <a href="${escapeHtml(item.source_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(product.brand)} source · page ${escapeHtml(item.pdf_page)}</a>
      </div>`).join("")}`;
    showDialog($("#evidenceDialog"));
  } catch (error) {
    showToast(error.message);
  }
}

$("#messageForm").addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage($("#messageInput").value);
});
$("#messageInput").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("#messageForm").requestSubmit();
  }
});
$$("[data-prompt]").forEach((button) => button.addEventListener("click", () => {
  $("#messageInput").value = button.dataset.prompt;
  $("#messageInput").focus();
}));
$("#newConversation").addEventListener("click", async () => {
  if (state.busy) return;
  await createConversation();
  showToast("New enquiry opened.");
});
$("#resetDemo").addEventListener("click", async () => {
  if (state.busy) return;
  await createConversation();
  showToast("Demo reset with a clean enquiry.");
});
$("#saveQuote").addEventListener("click", saveQuote);
$("#closeEvidence").addEventListener("click", () => $("#evidenceDialog").close());
$("#closeDiff").addEventListener("click", () => $("#diffDialog").close());
$("#evidenceDialog").addEventListener("click", (event) => {
  if (event.target === $("#evidenceDialog")) $("#evidenceDialog").close();
});
$("#diffDialog").addEventListener("click", (event) => {
  if (event.target === $("#diffDialog")) $("#diffDialog").close();
});
["#evidenceDialog", "#diffDialog"].forEach((selector) => {
  $(selector).addEventListener("close", () => {
    if (dialogReturnFocus?.isConnected) dialogReturnFocus.focus();
    dialogReturnFocus = null;
  });
});

document.addEventListener("DOMContentLoaded", boot);
// Delegate product actions so catalogue entries stay interactive after rendering.
$("#catalogueView").addEventListener("click", (event) => {
  const evidence = event.target.closest(".evidence-button");
  const select = event.target.closest(".select-button");
  if (evidence) openEvidence(evidence.dataset.sku);
  if (select && !state.busy) sendMessage(`Quote 1 ${select.dataset.sku} at zero discount.`);
});
$$("[data-view]").forEach((tab) => {
  tab.addEventListener("click", () => switchWorkspace(tab.dataset.view));
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const view = event.key === "Home" ? "catalogue" : event.key === "End" ? "quote" : state.workspaceView === "quote" ? "catalogue" : "quote";
    switchWorkspace(view, true);
  });
});
window.addEventListener("pageshow", async (event) => {
  if (!event.persisted) return;
  try {
    await createConversation();
  } catch (error) {
    showToast(error.message);
  }
});
