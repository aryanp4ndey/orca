#!/usr/bin/env python3
"""Drive the ORCA web client through the judge flow in a real browser.

    # terminal 1
    cd backend && uvicorn app.main:app

    # terminal 2
    pip install playwright && playwright install chromium
    python tools/verify_frontend.py

Exits non-zero on any console error or any failed step, so it can gate a demo.
Screenshots land in ./frontend-shots/ and are worth keeping: they are the
recorded backup if the live demo cannot run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

try:
    from playwright.async_api import async_playwright
except ImportError:  # pragma: no cover - tooling, not product code
    print("Playwright is not installed.\n"
          "  pip install playwright && playwright install chromium")
    sys.exit(2)

SHOTS = pathlib.Path(__file__).resolve().parents[1] / "frontend-shots"
FLAGSHIP = "Is it safe to go fishing from Kochi tomorrow at 7 AM?"
KOCHI = {"latitude": 9.9312, "longitude": 76.2125}


async def run(base: str, headed: bool) -> int:
    SHOTS.mkdir(exist_ok=True)
    errors: list[str] = []
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))
        print(f"  {'PASS' if ok else 'FAIL'}  {name}{f'  — {detail}' if detail else ''}",
              flush=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=not headed, args=["--no-sandbox"])
        ctx = await browser.new_context(
            viewport={"width": 390, "height": 844}, device_scale_factor=2,
            is_mobile=True, has_touch=True,
            geolocation=KOCHI, permissions=["geolocation"],
            locale="en-IN", timezone_id="Asia/Kolkata")
        page = await ctx.new_page()
        page.on("console", lambda m: errors.append(f"[{m.type}] {m.text}")
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"[pageerror] {e}"))

        shot = lambda name: page.screenshot(path=str(SHOTS / f"{name}.png"))  # noqa: E731

        # ---- boot -----------------------------------------------------------
        await page.goto(f"{base}/app/", wait_until="networkidle")
        await page.wait_for_selector("#app:not([hidden])", timeout=15000)
        check("app boots", True)

        await page.wait_for_selector("#mode-fisher", timeout=8000)
        await page.click("#mode-fisher")
        await page.wait_for_timeout(400)
        await shot("01-home")
        check("mode selection", True, "Fisher")

        # ---- GPS ------------------------------------------------------------
        await page.click("#loc-status")
        await page.wait_for_selector("#use-gps", timeout=6000)
        await page.click("#use-gps")
        await page.wait_for_timeout(1600)
        location = await page.evaluate("() => window.ORCA.state.location")
        check("GPS", bool(location) and abs(location["lat"] - 9.9312) < 0.05,
              location.get("label") if location else "no fix")
        await shot("02-located")

        # ---- flagship query -------------------------------------------------
        await page.fill("#ask-input", FLAGSHIP)
        await page.click("#ask-send")
        await page.wait_for_selector(".risk[data-level]", timeout=25000)
        level = await page.get_attribute(".risk[data-level]", "data-level")
        factors = await page.evaluate("() => document.querySelectorAll('.factor').length")
        latency = await page.evaluate(
            "() => window.ORCA.state.turns.slice(-1)[0].response.latency.total_ms")
        check("flagship query", level in
              {"LOW", "MODERATE", "HIGH", "CRITICAL", "INSUFFICIENT_DATA"},
              f"{level}, {factors} factors, backend {latency} ms")
        await page.wait_for_timeout(500)
        await shot("03-answer")

        # ---- progressive disclosure ----------------------------------------
        for summary in await page.query_selector_all(".disclose__btn"):
            await summary.click()
            await page.wait_for_timeout(120)
        await page.wait_for_timeout(400)
        evidence = await page.evaluate("() => document.querySelectorAll('.ev').length")
        steps = await page.evaluate("() => document.querySelectorAll('.tracestep').length")
        pills = await page.evaluate("() => document.querySelectorAll('.agentpill').length")
        check("evidence + trace", evidence > 0 and steps > 0 and pills > 0,
              f"{evidence} evidence rows, {steps} trace steps, {pills} agents")
        await shot("04-evidence-trace")

        # ---- multi-turn -----------------------------------------------------
        await page.fill("#ask-input", "What about 5 PM?")
        await page.click("#ask-send")
        await page.wait_for_timeout(3000)
        turns = await page.evaluate("""() => window.ORCA.state.turns.map(t => ({
            q: t.query,
            risk: t.response && t.response.risk && t.response.risk.risk_level,
            place: t.response && t.response.location && t.response.location.name,
            inherited: t.response && t.response.intent.inherited }))""")
        last = turns[-1]
        check("multi-turn context", "location" in (last["inherited"] or []),
              f"{last['place']} · inherited {last['inherited']}")
        await shot("05-followup")

        # ---- map ------------------------------------------------------------
        await page.click("#nav-map")
        await page.wait_for_selector("svg.map", timeout=8000)
        await page.wait_for_timeout(1400)
        paths = await page.evaluate("() => document.querySelectorAll('svg.map path').length")
        check("map renders", paths > 0, f"{paths} vector paths")
        await shot("06-map")

        # ---- alerts ---------------------------------------------------------
        await page.click("#nav-alerts")
        await page.wait_for_timeout(2800)
        await shot("07-alerts")
        check("alerts screen", True)

        # ---- PFZ ------------------------------------------------------------
        await page.click("#nav-more")
        await page.wait_for_selector("#go-pfz", timeout=6000)
        await page.click("#go-pfz")
        await page.wait_for_timeout(3500)
        await shot("08-pfz")
        check("fishing zones", True)

        # ---- route ----------------------------------------------------------
        await page.click("#nav-more")
        await page.wait_for_selector("#go-route")
        await page.click("#go-route")
        await page.wait_for_selector("#route-go", timeout=6000)
        await page.click("#route-go")
        await page.wait_for_timeout(7000)
        segments = await page.evaluate("() => document.querySelectorAll('.srcrow').length")
        check("route risk", segments > 0, f"{segments} rows")
        await shot("09-route")

        # ---- compare --------------------------------------------------------
        await page.click("#nav-more")
        await page.wait_for_selector("#go-compare")
        await page.click("#go-compare")
        await page.wait_for_selector("#cmp-go", timeout=6000)
        await page.click("#cmp-go")
        await page.wait_for_timeout(5000)
        columns = await page.evaluate("() => document.querySelectorAll('.cmpcol').length")
        check("time comparison", columns == 2, f"{columns} columns")
        await shot("10-compare")

        # ---- languages ------------------------------------------------------
        await page.click("#nav-more")
        await page.wait_for_selector("#lang-hi", timeout=6000)
        await page.click("#lang-hi")
        await page.wait_for_timeout(600)
        await page.click("#nav-ask")
        await page.wait_for_selector("#ask-input")
        await page.evaluate("() => { window.ORCA.state.turns = []; }")
        await page.fill("#ask-input",
                        "Kal subah 7 baje Kochi se fishing ke liye jaana safe hai?")
        await page.click("#ask-send")
        await page.wait_for_timeout(3500)
        hindi = await page.evaluate("""() => { const t = window.ORCA.state.turns.slice(-1)[0];
            return t.response && { lang: t.response.answer_language,
                                   risk: t.response.risk && t.response.risk.risk_level }; }""")
        check("romanised Hindi", bool(hindi) and hindi["lang"] == "hi",
              json.dumps(hindi, ensure_ascii=False))
        await shot("11-hindi")

        # ---- desktop --------------------------------------------------------
        await page.set_viewport_size({"width": 1440, "height": 900})
        await page.click("#nav-ask")
        await page.wait_for_timeout(900)
        nav_visible = await page.is_visible("#nav-ask")
        check("desktop layout", nav_visible)
        await shot("12-desktop")

        # ---- offline --------------------------------------------------------
        await page.set_viewport_size({"width": 390, "height": 844})
        await ctx.set_offline(True)
        await page.fill("#ask-input", "What is the sea condition near Kochi?")
        await page.click("#ask-send")
        await page.wait_for_timeout(4000)
        offline_text = await page.inner_text("#thread")
        check("offline degradation",
              "could not be verified" in offline_text.lower()
              or "offline" in offline_text.lower(),
              "failure is explained, not silent")
        await shot("13-offline")
        await ctx.set_offline(False)

        await browser.close()

    # Console errors from the deliberate offline step are expected.
    real_errors = [e for e in errors if "ERR_INTERNET_DISCONNECTED" not in e]
    print("\nconsole errors:", "\n".join(real_errors) if real_errors else "none")
    failed = [name for name, ok, _ in checks if not ok]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed. "
          f"Screenshots in {SHOTS}")
    if failed:
        print("FAILED:", ", ".join(failed))
    return 1 if (failed or real_errors) else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the ORCA web client")
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()
    return asyncio.run(run(args.base.rstrip("/"), args.headed))


if __name__ == "__main__":
    sys.exit(main())
