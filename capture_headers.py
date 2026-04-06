from __future__ import annotations

import json
from typing import Any

from playwright.sync_api import FrameLocator, Page, sync_playwright

from config import load_settings


def _click_first(candidates: list) -> bool:
    for locator in candidates:
        try:
            if locator.count() > 0:
                locator.first.click(timeout=3000)
                return True
        except Exception:
            continue
    return False


def _ensure_password_login_mode(scope: Page | FrameLocator) -> None:
    clicked = _click_first(
        [
            scope.locator("#passwordLogin"),
            scope.locator("#tab-password"),
            scope.locator("[data-type='password']"),
            scope.locator("[data-login='password']"),
            scope.locator("text=密码登录"),
        ]
    )
    if clicked:
        # Give UI a short time to switch input mode.
        try:
            scope.locator("#username").first.wait_for(timeout=3000)
        except Exception:
            pass


def _submit_login(scope: Page | FrameLocator) -> None:
    clicked = _click_first(
        [
            scope.locator("button[type='submit']"),
            scope.locator("input[type='submit']"),
            scope.locator("button.login-btn"),
            scope.locator("input.login-btn"),
        ]
    )
    if not clicked:
        scope.locator("#password").press("Enter")


def _fill_login_form(scope: Page | FrameLocator, school_id: str, school_pwd: str) -> None:
    _ensure_password_login_mode(scope)
    scope.locator("#username").first.wait_for(timeout=10000)
    scope.locator("#password").first.wait_for(timeout=10000)
    scope.locator("#username").fill(school_id)
    scope.locator("#password").fill(school_pwd)
    _submit_login(scope)


def capture_valid_headers() -> dict[str, Any]:
    settings = load_settings()
    if not settings.school_id or not settings.school_pwd:
        raise ValueError("SCHOOL_ID / SCHOOL_PWD is required in .env for header capture.")

    captured_headers: dict[str, Any] = {}

    with sync_playwright() as p:
        print(f"[config] PLAYWRIGHT_HEADLESS={settings.playwright_headless}")
        browser = p.chromium.launch(headless=settings.playwright_headless)
        context = browser.new_context()
        page = context.new_page()

        def handle_request(request) -> None:
            nonlocal captured_headers
            if "apiucloud.bupt.edu.cn" not in request.url:
                return

            headers = request.headers
            lowered = {k.lower() for k in headers.keys()}
            if "authorization" in lowered or "blade-auth" in lowered:
                captured_headers = headers
                print(f"[captured] {request.url}")

        page.on("request", handle_request)

        try:
            print("[step] open login page")
            page.goto(settings.login_url, wait_until="domcontentloaded")
            page.wait_for_timeout(1200)

            if page.locator("#loginIframe").count() > 0:
                page.wait_for_selector("#loginIframe", timeout=20000)
                frame = page.frame_locator("#loginIframe")
                _fill_login_form(frame, settings.school_id, settings.school_pwd)
            else:
                _fill_login_form(page, settings.school_id, settings.school_pwd)

            print("[step] go to homework page and wait for API requests")
            page.goto(settings.home_url, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(settings.capture_wait_seconds * 1000)
        finally:
            browser.close()

    if not captured_headers:
        raise RuntimeError(
            "No auth headers captured. Check selectors/login flow and retry."
        )

    settings.header_file.parent.mkdir(parents=True, exist_ok=True)
    settings.header_file.write_text(
        json.dumps(captured_headers, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[ok] headers saved to: {settings.header_file}")
    return captured_headers


if __name__ == "__main__":
    capture_valid_headers()
