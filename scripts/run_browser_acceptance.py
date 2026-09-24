"""Exercise the real browser UI from enquiry through confirmed PDF export."""
from __future__ import annotations

import base64
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import websocket
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_url(url: str, timeout: float = 15) -> bytes:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                return response.read()
        except Exception as exc:  # startup race
            last = exc
            time.sleep(0.1)
    raise RuntimeError(f"Timed out waiting for {url}: {last}")


class CDP:
    def __init__(self, url: str) -> None:
        self.ws = websocket.create_connection(url, timeout=10)
        self.counter = 0

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.counter += 1
        identifier = self.counter
        self.ws.send(json.dumps({"id": identifier, "method": method, "params": params or {}}))
        while True:
            message = json.loads(self.ws.recv())
            if message.get("id") == identifier:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message.get("result", {})

    def evaluate(self, expression: str, *, await_promise: bool = False) -> Any:
        result = self.call(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": await_promise, "returnByValue": True},
        ).get("result", {})
        if result.get("subtype") == "error":
            raise RuntimeError(result.get("description", "browser evaluation failed"))
        return result.get("value")

    def wait(self, expression: str, timeout: float = 15) -> Any:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.evaluate(expression)
            if value:
                return value
            time.sleep(0.1)
        raise RuntimeError(f"Browser condition timed out: {expression}")

    def close(self) -> None:
        self.ws.close()


def main() -> int:
    if not CHROME.exists():
        raise SystemExit(f"Chrome not found at {CHROME}")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "reports/evaluation/browser_acceptance" / run_id
    downloads = out / "downloads"
    downloads.mkdir(parents=True)
    app_port, debug_port = free_port(), free_port()
    db_path = Path(tempfile.gettempdir()) / f"quotation-browser-{run_id}.sqlite"
    chrome_profile = Path(tempfile.mkdtemp(prefix="quotation-chrome-"))
    app_log = (out / "uvicorn.log").open("w", encoding="utf-8")
    chrome_log = (out / "chrome.log").open("w", encoding="utf-8")
    env = {**os.environ, "APP_DB_PATH": str(db_path), "AGENT_DRIVER": "offline", "PYTHONDONTWRITEBYTECODE": "1"}
    app = subprocess.Popen(
        [str(ROOT / ".venv/bin/uvicorn"), "app.main:app", "--host", "127.0.0.1", "--port", str(app_port)],
        cwd=ROOT, env=env, stdout=app_log, stderr=subprocess.STDOUT,
    )
    chrome: subprocess.Popen[bytes] | None = None
    cdp: CDP | None = None
    try:
        wait_url(f"http://127.0.0.1:{app_port}/api/health")
        chrome = subprocess.Popen(
            [
                str(CHROME), "--headless=new", "--no-first-run", "--disable-gpu",
                "--disable-dev-shm-usage", "--no-sandbox", f"--remote-debugging-port={debug_port}",
                "--remote-allow-origins=*", f"--user-data-dir={chrome_profile}",
                f"http://127.0.0.1:{app_port}",
            ], stdout=chrome_log, stderr=subprocess.STDOUT,
        )
        pages = json.loads(wait_url(f"http://127.0.0.1:{debug_port}/json/list"))
        page = next(row for row in pages if row.get("type") == "page")
        cdp = CDP(page["webSocketDebuggerUrl"])
        cdp.call("Runtime.enable")
        cdp.call("Page.enable")
        cdp.call("Emulation.setDeviceMetricsOverride", {"width": 1600, "height": 1050, "deviceScaleFactor": 1, "mobile": False})
        cdp.call("Browser.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(downloads)})
        cdp.wait("document.readyState === 'complete' && document.querySelector('#datasetBadge').textContent.includes('2026')")

        steps: list[dict[str, Any]] = []

        def record(name: str, passed: bool, evidence: Any) -> None:
            steps.append({"step": name, "passed": bool(passed), "evidence": evidence})
            if not passed:
                raise RuntimeError(f"Acceptance failed: {name}: {evidence}")

        def send(message: str, expected_total: int) -> None:
            before = cdp.evaluate("state.conversation.messages.length")
            cdp.evaluate(
                f"document.querySelector('#messageInput').value={json.dumps(message)}; document.querySelector('#messageForm').requestSubmit();"
            )
            cdp.wait(f"!state.busy && state.conversation.messages.length > {before} && state.conversation.latest_result?.quote_draft?.total_cents === {expected_total}")

        catalogue_size = cdp.wait("state.catalog.length")
        record("v2 catalogue loads 50 records", catalogue_size == 50, catalogue_size)

        cdp.evaluate("document.querySelector('.select-button[data-sku=\"MON-L044\"]').click()")
        cdp.wait(
            "!state.busy && "
            "state.conversation.latest_result?.quote_draft?.lines?.[0]?.sku === 'MON-L044' && "
            "state.conversation.latest_result.quote_draft.lines[0].quantity === 1"
        )
        selected_line = cdp.evaluate(
            "state.conversation.latest_result.quote_draft.lines[0]"
        )
        record(
            "product-card selection forces quantity one",
            selected_line["sku"] == "MON-L044"
            and selected_line["quantity"] == 1
            and selected_line["net_cents"] == 11900,
            selected_line,
        )
        cdp.evaluate("createConversation()", await_promise=True)
        cdp.wait("state.conversation.messages.length === 0")

        cdp.evaluate("openEvidence('MON-L013')")
        cdp.wait("document.querySelector('#evidenceDialog').open && document.querySelector('#evidenceContent').innerText.includes('5120x2160')")
        lenovo_evidence = cdp.evaluate(
            "({sku: document.querySelector('#dialogSku').innerText, title: document.querySelector('#dialogTitle').innerText, links: [...document.querySelectorAll('#evidenceContent a')].map(a => a.innerText), rows: document.querySelectorAll('#evidenceContent .evidence-row').length})"
        )
        record(
            "Lenovo official evidence renders",
            "MON-L013" in lenovo_evidence["sku"]
            and "Lenovo" in lenovo_evidence["sku"]
            and lenovo_evidence["rows"] == 8
            and all("Lenovo source" in link for link in lenovo_evidence["links"]),
            lenovo_evidence,
        )
        cdp.evaluate("document.querySelector('#evidenceDialog').close()")

        previous_conversation = cdp.evaluate("state.conversation.id")
        send("Quote 1 S2425H.", 14900)
        cdp.call("Page.reload", {"ignoreCache": True})
        cdp.wait(
            f"document.readyState === 'complete' && state.conversation?.id && "
            f"state.conversation.id !== {json.dumps(previous_conversation)} && "
            "state.conversation.messages.length === 0"
        )
        clean_load = cdp.evaluate(
            "({id: state.conversation.id, messages: state.conversation.messages.length, versions: state.conversation.quote_versions.length})"
        )
        record(
            "page reload starts a clean enquiry",
            clean_load["id"] != previous_conversation
            and clean_load["messages"] == 0
            and clean_load["versions"] == 0,
            clean_load,
        )

        broad_brief = (
            "We’re refreshing a small office and need around 8 monitors. "
            "Staff use USB-C laptops, so we’d prefer one cable for video and charging. "
            "The total budget is about SGD 2,500."
        )
        before = cdp.evaluate("state.conversation.messages.length")
        cdp.evaluate(
            f"document.querySelector('#messageInput').value={json.dumps(broad_brief)}; document.querySelector('#messageForm').requestSubmit();"
        )
        cdp.wait(f"!state.busy && state.conversation.messages.length > {before} && state.conversation.latest_result?.candidates?.length > 3")
        broad_state = cdp.evaluate(
            "({message: state.conversation.messages.at(-1).content, displayRequirements: state.conversation.latest_result.display_requirements, visibleCards: document.querySelectorAll('#candidateList > .candidate-card').length, hiddenMatches: document.querySelectorAll('.match-browser .candidate-card').length, enabledSelections: document.querySelectorAll('#candidateList > .candidate-card .select-button:not(:disabled)').length, firstSelection: document.querySelector('#candidateList > .candidate-card .select-button')?.outerHTML})"
        )
        record(
            "broad brief is clarified and reduced to a three-product shortlist",
            "minimum laptop charging wattage" in broad_state["message"]
            and broad_state["visibleCards"] == 3
            and broad_state["hiddenMatches"] > 0
            and broad_state["enabledSelections"] == 0,
            broad_state,
        )
        shortlist_screenshot = cdp.call(
            "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True}
        )["data"]
        (out / "broad-brief-shortlist.png").write_bytes(
            base64.b64decode(shortlist_screenshot)
        )
        before = cdp.evaluate("state.conversation.messages.length")
        refinement = "Exactly 8. We need at least 90W charging; a 24-inch FHD screen is fine."
        cdp.evaluate(
            f"document.querySelector('#messageInput').value={json.dumps(refinement)}; document.querySelector('#messageForm').requestSubmit();"
        )
        cdp.wait(
            f"!state.busy && state.conversation.messages.length > {before} && "
            "state.conversation.latest_result?.candidates?.length === 3"
        )
        refined_state = cdp.evaluate(
            "({models: state.conversation.latest_result.candidates.map(row => row.model), visibleCards: document.querySelectorAll('#candidateList > .candidate-card').length, enabledSelections: document.querySelectorAll('#candidateList > .candidate-card .select-button:not(:disabled)').length, stillNeeded: document.querySelector('#requirementLedger').innerText})"
        )
        record(
            "follow-up constraints narrow the shortlist without losing prior requirements",
            refined_state["models"] == ["P2425HE", "T24D-4v", "T24D-40"]
            and refined_state["visibleCards"] == 3
            and refined_state["enabledSelections"] == 3
            and "charging wattage" not in refined_state["stillNeeded"],
            refined_state,
        )
        refined_screenshot = cdp.call(
            "Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True}
        )["data"]
        (out / "refined-shortlist.png").write_bytes(base64.b64decode(refined_screenshot))
        cdp.evaluate("document.querySelector('#candidateList > .candidate-card .select-button[data-sku=\"MON-007\"]').click()")
        cdp.wait("document.querySelector('#selectionDialog').open")
        cdp.evaluate("document.querySelector('#completeSelection').click()")
        cdp.wait(
            "!state.busy && state.conversation.latest_result?.quote_draft?.lines?.[0]?.quantity === 1"
        )
        mismatch_state = cdp.evaluate(
            "({warning: document.querySelector('#workspaceAlert').innerText, restore: document.querySelector('#restoreRequestedQuantity')?.innerText})"
        )
        record(
            "one-unit selection makes the original quantity mismatch explicit",
            "original enquiry mentions 8 units" in mismatch_state["warning"]
            and mismatch_state["restore"] == "Use 8 units",
            mismatch_state,
        )
        cdp.evaluate("document.querySelector('#restoreRequestedQuantity').click()")
        cdp.wait(
            "!state.busy && state.conversation.latest_result?.quote_draft?.lines?.[0]?.quantity === 8 && "
            "state.conversation.latest_result.quote_draft.total_cents === 231200"
        )
        record(
            "requested quantity is restored without reselecting the product",
            cdp.evaluate("state.conversation.latest_result.quote_draft.lines[0].quantity") == 8,
            cdp.evaluate("state.conversation.latest_result.quote_draft"),
        )
        cdp.evaluate("createConversation()", await_promise=True)
        cdp.wait("state.conversation.messages.length === 0")

        send("Quote 8 P2425HE. Budget SGD 2500.", 231200)
        cdp.evaluate("document.querySelector('#customerName').value='Example Customer'; document.querySelector('#confirmedBy').value='Browser Reviewer';")
        record("v1 draft displayed", cdp.evaluate("state.conversation.latest_result.quote_draft.total_cents") == 231200, 231200)
        cdp.evaluate("document.querySelector('#saveQuote').click()")
        cdp.wait("state.conversation.quote_versions.length === 1")
        v1 = cdp.evaluate("state.conversation.quote_versions[0]")
        record("v1 saved", v1["total_cents"] == 231200 and v1["status"] == "saved_draft", v1)

        send("Change quantity to 10 units.", 289000)
        cdp.evaluate("document.querySelector('#saveQuote').click()")
        cdp.wait("state.conversation.quote_versions.length === 2")
        versions = cdp.evaluate("state.conversation.quote_versions")
        record("v2 saved", versions[1]["total_cents"] == 289000, versions[1])

        cdp.evaluate("document.querySelector('.compare-version').click()")
        cdp.wait("document.querySelector('#diffDialog').open")
        diff_text = cdp.evaluate("document.querySelector('#diffContent').innerText")
        record("v1/v2 diff rendered", "578.00" in diff_text and "8 → 10" in diff_text, diff_text)

        cdp.evaluate("[...document.querySelectorAll('.confirm-version')].at(-1).click()")
        cdp.wait("document.querySelector('#approvalDialog').open")
        cdp.evaluate("document.querySelector('#completeApproval').click()")
        cdp.wait("state.conversation.quote_versions[1].exportable === true")
        confirmed = cdp.evaluate("state.conversation.quote_versions[1]")
        record("v2 confirmed", confirmed["status"] == "confirmed" and confirmed["exportable"], confirmed)

        cdp.evaluate("document.querySelector('.version-actions a[download]').click()")
        deadline = time.monotonic() + 15
        pdf_path: Path | None = None
        while time.monotonic() < deadline:
            candidates = [path for path in downloads.glob("*.pdf") if not path.name.endswith(".crdownload")]
            if candidates:
                pdf_path = candidates[0]
                break
            time.sleep(0.1)
        record("confirmed PDF downloaded", pdf_path is not None, [path.name for path in downloads.iterdir()])
        assert pdf_path is not None
        pdf_text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf_path)).pages)
        record("page/snapshot/PDF amount consistent", "SGD 2,890.00" in pdf_text and "P2425HE" in pdf_text, pdf_text[:500])

        screenshot = cdp.call("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True})["data"]
        (out / "browser-final.png").write_bytes(base64.b64decode(screenshot))
        version = cdp.call("Browser.getVersion")
        report = {
            "run_id": run_id,
            "tested_at": datetime.now(timezone.utc).isoformat(),
            "browser": version.get("product"),
            "driver": "offline",
            "dataset_version": "2026-09-22.v2",
            "steps": steps,
            "passed": all(step["passed"] for step in steps),
            "artifacts": {
                "shortlist_screenshot": "broad-brief-shortlist.png",
                "refined_shortlist_screenshot": "refined-shortlist.png",
                "screenshot": "browser-final.png",
                "pdf": str(pdf_path.relative_to(out)),
            },
        }
        (out / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (out / "report.md").write_text(
            "# Browser acceptance\n\n" + "\n".join(
                f"- [{'x' if step['passed'] else ' '}] {step['step']}" for step in steps
            ) + f"\n\nBrowser: `{report['browser']}`\n", encoding="utf-8"
        )
        print(out.relative_to(ROOT))
        return 0
    finally:
        if cdp:
            cdp.close()
        if chrome:
            chrome.terminate()
            try:
                chrome.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chrome.kill()
        app.terminate()
        try:
            app.wait(timeout=5)
        except subprocess.TimeoutExpired:
            app.kill()
        app_log.close()
        chrome_log.close()


if __name__ == "__main__":
    raise SystemExit(main())
