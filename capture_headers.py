from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from playwright.sync_api import FrameLocator, Page, sync_playwright

from config import load_settings


UCLOUD_ORIGIN = "https://ucloud.bupt.edu.cn"
STUDENT_HOME_PREFIX = f"{UCLOUD_ORIGIN}/uclass/#/student/homePage"
STUDENT_HOME_URL_RE = re.compile(
    r"https://ucloud\.bupt\.edu\.cn/uclass/#/student/homePage\?[^\s\"'<>]*roleId=([0-9]+)[^\s\"'<>]*"
)
ROLE_ID_RE = re.compile(r"(?:roleId|role_id)=([0-9]+)")


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


def _student_home_url_from_text(text: str) -> str:
    if not text:
        return ""

    home_match = STUDENT_HOME_URL_RE.search(text)
    if home_match:
        return home_match.group(0)

    role_match = ROLE_ID_RE.search(text)
    if role_match:
        return f"{STUDENT_HOME_PREFIX}?roleId={role_match.group(1)}"

    return ""


def _read_page_hints(page: Page) -> str:
    try:
        return page.evaluate(
            """() => {
                const chunks = [window.location.href];
                for (const storage of [window.localStorage, window.sessionStorage]) {
                    for (let i = 0; i < storage.length; i += 1) {
                        const key = storage.key(i);
                        chunks.push(key || "", storage.getItem(key) || "");
                    }
                }
                for (const link of Array.from(document.querySelectorAll("a[href]"))) {
                    chunks.push(link.href || "");
                }
                chunks.push(document.body ? document.body.innerText : "");
                return chunks.join("\\n");
            }"""
        )
    except Exception:
        return ""


def _discover_student_home_url(page: Page, seen_urls: list[str]) -> str:
    for text in [page.url, *reversed(seen_urls), _read_page_hints(page)]:
        discovered = _student_home_url_from_text(text)
        if discovered:
            return discovered
    return ""


def _try_enter_student_role(page: Page) -> None:
    clicked = _click_first(
        [
            page.locator("text=学生").first,
            page.locator("text=学生空间").first,
            page.locator("text=学生端").first,
            page.locator("text=进入学生").first,
        ]
    )
    if clicked:
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            page.wait_for_timeout(2000)


def _persist_env_value(key: str, value: str, path: Path = Path(".env")) -> None:
    if not value:
        return

    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    updated = False
    for index, raw in enumerate(lines):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw:
            continue
        current_key, _ = raw.split("=", 1)
        if current_key.strip() == key:
            lines[index] = f"{key}={value}"
            updated = True
            break

    if not updated:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(f"{key}={value}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def capture_valid_headers() -> dict[str, Any]:
    settings = load_settings()
    if not settings.school_id or not settings.school_pwd:
        raise ValueError("SCHOOL_ID / SCHOOL_PWD is required in .env for header capture.")

    captured_headers: dict[str, Any] = {}
    captured_student_home_url = ""
    seen_urls: list[str] = []

    with sync_playwright() as p:
        print(f"[config] PLAYWRIGHT_HEADLESS={settings.playwright_headless}")
        browser = p.chromium.launch(headless=settings.playwright_headless)
        context = browser.new_context()
        page = context.new_page()

        def handle_request(request) -> None:
            nonlocal captured_headers, captured_student_home_url
            seen_urls.append(request.url)
            if not captured_student_home_url:
                captured_student_home_url = _student_home_url_from_text(request.url)

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
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                page.wait_for_timeout(2000)

            captured_student_home_url = (
                captured_student_home_url
                or _discover_student_home_url(page, seen_urls)
            )
            if not captured_student_home_url:
                _try_enter_student_role(page)
                captured_student_home_url = _discover_student_home_url(page, seen_urls)

            target_home_url = captured_student_home_url or settings.home_url
            if not target_home_url:
                target_home_url = f"{STUDENT_HOME_PREFIX}?roleId=1318863781576577025"

            page.goto(target_home_url, wait_until="domcontentloaded")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(settings.capture_wait_seconds * 1000)
            captured_student_home_url = (
                captured_student_home_url
                or _discover_student_home_url(page, seen_urls)
                or target_home_url
            )
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
    if captured_student_home_url:
        _persist_env_value("UCLOUD_HOME_URL", captured_student_home_url)
        print(f"[ok] UCLOUD_HOME_URL saved: {captured_student_home_url}")
    return captured_headers


if __name__ == "__main__":
    capture_valid_headers()
