"use strict";

const state = {
  health: null,
  conversation: null,
  catalog: [],
  busy: false,
};

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
    throw new Error(detail.message || detail.error || "Request failed.");
  }
  return response.json();
}

function money(cents) {
  return new Intl.NumberFormat("en-SG", { style: "currency", currency: "SGD" }).format((cents || 0) / 100);
}

function latestResult() {
  return state.conversation?.latest_result || null;
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.classList.add("visible");
  window.setTimeout(() => toast.classList.remove("visible"), 2200);
}

async function createConversation() {
  const conversation = await api("/api/conversations", {
    method: "POST",
    body: JSON.stringify({ driver: state.health?.configured_driver || "offline" }),
  });
  state.conversation = conversation;
  localStorage.setItem("quotationConversationId", conversation.id);
  render();
  $("#messageInput").focus();
}

async function restoreConversation() {
  const saved = localStorage.getItem("quotationConversationId");
  if (!saved) return createConversation();
  try {
    state.conversation = await api(`/api/conversations/${encodeURIComponent(saved)}`);
  } catch (_) {
    localStorage.removeItem("quotationConversationId");
    await createConversation();
  }
}

async function boot() {
  try {
    [state.health, state.catalog] = await Promise.all([api("/api/health"), api("/api/products")]);
    $("#datasetBadge").textContent = `Catalogue ${state.health.dataset_version}`;
    $("#driverBadge").textContent = state.health.configured_driver === "gateway" ? "Organizer LLM Gateway" : "Deterministic offline";
    await restoreConversation();
    render();
  } catch (error) {
    showToast(error.message);
    $("#candidateList").innerHTML = `<div class="empty-state"><strong>Workbench unavailable</strong><span>${escapeHtml(error.message)}</span></div>`;
  }
}

async function sendMessage(content) {
  if (!content.trim() || state.busy) return;
  state.busy = true;
  $("#sendButton").disabled = true;
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
    state.busy = false;
    $("#sendButton").disabled = false;
    $("#sendButton").textContent = "Review enquiry";
  }
}

function render() {
  renderStatus();
  renderMessages();
  renderRequirements();
  renderCandidates();
  renderTrace();
  renderQuote();
  renderVersions();
}

function renderStatus() {
  const result = latestResult();
  const chip = $("#conversationStatus");
  const driver = result?.configured_driver || state.health?.configured_driver || "offline";
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
  chip.textContent = result ? (labels[result.status] || "In review") : "Waiting";
  chip.className = "status-chip " + (!result ? "status-idle" : result.status === "ready_to_quote" ? "status-ready" : ["rule_violation", "invalid_quantity", "no_match"].includes(result.status) ? "status-warning" : "status-review");
}

function renderMessages() {
  const list = $("#messageList");
  const messages = state.conversation?.messages || [];
  if (!messages.length) {
    list.innerHTML = `<div class="empty-state"><strong>Start with the customer’s words.</strong><span>Use a demo case or paste an English enquiry below.</span></div>`;
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
  const isBrowse = !rows.length;
  if (isBrowse) rows = state.catalog;
  rows = uniqueProducts(rows);
  $("#candidateSummary").textContent = suggestions.length
    ? `${suggestions.length} compatible alternative${suggestions.length === 1 ? "" : "s"}`
    : result?.candidates?.length
      ? `${result.candidates.length} catalogue match${result.candidates.length === 1 ? "" : "es"}`
      : `${state.catalog.length} verified Dell monitor records`;
  $("#candidateList").innerHTML = rows.map((product) => candidateCard(product, {
    suggested: suggestions.some((row) => row.sku === product.sku),
    incompatible: result?.status === "explain_limitation" && result?.candidates?.some((row) => row.sku === product.sku),
    browse: isBrowse,
  })).join("");
  $$(".evidence-button").forEach((button) => button.addEventListener("click", () => openEvidence(button.dataset.sku)));
  $$(".select-button").forEach((button) => button.addEventListener("click", () => sendMessage(`Choose ${button.dataset.model} at zero discount.`)));
}

function candidateCard(product, flags) {
  const pd = product.usb_c_video ? `${product.usb_c_pd_watts}W host PD` : "No USB-C video";
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
      <div class="spec-cell"><span>Viewable diagonal</span><strong>${escapeHtml(product.screen_inches)} in</strong></div>
      <div class="spec-cell"><span>Native resolution</span><strong>${escapeHtml(product.resolution)}</strong></div>
      <div class="spec-cell"><span>USB-C host link</span><strong>${escapeHtml(pd)}</strong></div>
      <div class="spec-cell"><span>Max preset refresh</span><strong>${escapeHtml(product.max_refresh_hz)} Hz</strong></div>
    </div>
    <div class="candidate-actions">
      <button class="evidence-button" data-sku="${escapeHtml(product.sku)}" type="button">Inspect source evidence</button>
      ${canSelect ? `<button class="select-button" data-model="${escapeHtml(product.model)}" type="button">Select for quote</button>` : ""}
    </div>
  </article>`;
}

function renderTrace() {
  const trace = latestResult()?.trace || [];
  const tools = trace.filter((step) => step.tool);
  $("#toolTrace").innerHTML = tools.length
    ? `<div class="trace-summary"><strong>Verified actions</strong><span>${tools.map((step) => escapeHtml(step.tool)).join(" → ")}</span></div>
      <details class="trace-audit">
        <summary>Inspect tool audit (${tools.length})</summary>
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
  if (!draft) {
    body.innerHTML = `<div class="empty-quote"><span class="quote-glyph" aria-hidden="true">$</span><strong>No calculated lines</strong><p>Select a product only after the requirements are confirmed.</p></div>`;
    actions.hidden = true;
    return;
  }
  body.innerHTML = `${draft.lines.map((line, index) => `
    <div class="quote-line">
      <div class="line-top"><div><strong>${escapeHtml(line.name)}</strong><br><span>${escapeHtml(line.sku)}</span></div><strong>${money(line.net_cents)}</strong></div>
      <div class="line-math">
        <span>${money(line.unit_price_cents)} each · ${(line.discount_bps / 100).toFixed(2)}% discount</span>
        <div class="quantity-control"><label for="qty-${index}">Qty</label><input id="qty-${index}" type="number" min="1" step="1" value="${line.quantity}"><button type="button" data-quantity-index="${index}" data-model="${escapeHtml(line.name.replace(/^Dell\s+|\s+Monitor$/g, ""))}">Update</button></div>
      </div>
    </div>`).join("")}
    <div class="total-block">
      <div class="total-row"><span>Draft total</span><strong>${money(draft.total_cents)}</strong></div>
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
  $("#versionList").innerHTML = versions.length
    ? versions.map((version, index) => `<div class="version-item">
        <div><span>Version ${version.version} · ${version.line_count} line${version.line_count === 1 ? "" : "s"}</span><small>${escapeHtml(version.status.replaceAll("_", " "))}</small></div>
        <strong>${money(version.total_cents)}</strong>
        <div class="version-actions">
          ${index ? `<button class="compare-version" data-from="${escapeHtml(versions[index - 1].id)}" data-to="${escapeHtml(version.id)}" type="button">Compare v${versions[index - 1].version} → v${version.version}</button>` : ""}
          ${version.confirmable ? `<button class="confirm-version" data-id="${escapeHtml(version.id)}" type="button">Confirm</button>` : ""}
          ${version.exportable ? `<a href="/api/quotes/${encodeURIComponent(version.id)}/pdf" download>Download PDF</a>` : ""}
        </div>
      </div>`).join("")
    : "<p>No versions saved yet.</p>";
  $$(".compare-version").forEach((button) => button.addEventListener("click", () => openDiff(button.dataset.from, button.dataset.to)));
  $$(".confirm-version").forEach((button) => button.addEventListener("click", () => confirmVersion(button.dataset.id)));
}

async function saveQuote() {
  const button = $("#saveQuote");
  button.disabled = true;
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
    showToast(error.message);
  } finally {
    button.disabled = false;
  }
}

async function confirmVersion(quoteId) {
  const customer = $("#customerName").value.trim();
  const confirmedBy = $("#confirmedBy").value.trim();
  if (!customer || !confirmedBy) return showToast("Customer and confirmer are required.");
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
    showToast(error.message);
  }
}

async function openDiff(fromId, toId) {
  try {
    const diff = await api(`/api/quotes/${encodeURIComponent(fromId)}/diff/${encodeURIComponent(toId)}`);
    const changes = diff.lines.changed || [];
    $("#diffTitle").textContent = `Version ${diff.from.version} → Version ${diff.to.version}`;
    $("#diffContent").innerHTML = `
      <div class="diff-summary"><span>Total before</span><strong>${money(diff.totals.total_cents.from)}</strong><span>Total after</span><strong>${money(diff.totals.total_cents.to)}</strong><span>Net change</span><strong>${money(diff.totals.total_cents.delta)}</strong></div>
      ${changes.length ? changes.map((line) => `<div class="diff-line"><strong>${escapeHtml(line.after?.model || line.before?.model || line.line_id)}</strong>${Object.entries(line.changes).map(([field, value]) => `<span>${escapeHtml(field.replaceAll("_", " "))}: ${escapeHtml(value.from)} → ${escapeHtml(value.to)}${value.delta === undefined ? "" : ` (Δ ${escapeHtml(value.delta)})`}</span>`).join("")}</div>`).join("") : "<p class=\"availability-warning\">No line changes.</p>"}
    `;
    $("#diffDialog").showModal();
  } catch (error) {
    showToast(error.message);
  }
}

async function openEvidence(sku) {
  try {
    const product = await api(`/api/products/${encodeURIComponent(sku)}`);
    $("#dialogSku").textContent = `${product.sku} · Official Dell manual`;
    $("#dialogTitle").textContent = `${product.model} specification evidence`;
    $("#evidenceContent").innerHTML = `
      <p class="availability-warning">Stock and delivery timing are not available in this dataset. Every value below links to its source page.</p>
      ${product.evidence.map((item) => `<div class="evidence-row">
        <span class="field">${escapeHtml(item.field.replaceAll("_", " "))}</span>
        <span class="value">${escapeHtml(typeof item.value === "object" ? JSON.stringify(item.value) : item.value)}</span>
        <a href="${escapeHtml(item.source_url)}" target="_blank" rel="noopener noreferrer">Dell source · page ${escapeHtml(item.pdf_page)}</a>
      </div>`).join("")}`;
    $("#evidenceDialog").showModal();
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
  localStorage.removeItem("quotationConversationId");
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

document.addEventListener("DOMContentLoaded", boot);
