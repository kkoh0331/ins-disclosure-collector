from __future__ import annotations

import logging
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

try:  # Imported lazily in environments that only run parser unit tests.
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - exercised only when browser dependency is absent
    PlaywrightTimeoutError = TimeoutError
    sync_playwright = None

from insurance_disclosures.dbins import Attachment, Disclosure, classify_period, _parse_date


@dataclass(frozen=True)
class CompanySource:
    slug: str
    company: str
    list_url: str
    strategy: str


# Hyundai's generic serviceAction.do URL is only a site entry point. The official
# regular-management-disclosure menu is menuId=100999.
COMPANY_SOURCES: dict[str, CompanySource] = {
    "samsung": CompanySource(
        "samsung", "삼성화재",
        "https://www.samsungfire.com/v2/html/publication/02/J_020_010_001.html",
        "samsung",
    ),
    "kb": CompanySource(
        "kb", "KB손해보험", "https://www.kbinsure.co.kr/CG801010001.ec", "kb",
    ),
    "meritz": CompanySource(
        "meritz", "메리츠화재",
        "https://www.meritzfire.com/disclosure/managerial-announcement/periodic.do#!/",
        "meritz",
    ),
    "hyundai": CompanySource(
        "hyundai", "현대해상",
        "https://www.hi.co.kr/serviceAction.do?menuId=100999", "hyundai",
    ),
}

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
INCLUDE_RE = re.compile(r"경영통일공시|정기경영공시|경영공시", re.I)
EXCLUDE_RE = re.compile(
    r"검토보고서|연결검토보고서|감사보고서|사업보고서|영업보고서|지급여력감사보고서",
    re.I,
)
DOWNLOAD_RE = re.compile(r"pdf|다운로드|바로보기|첨부|filedownload|filedown", re.I)
DATE_RE = re.compile(r"20\d{2}[.년/-]\s*\d{1,2}[.월/-]\s*\d{1,2}")


def _year_from(text: str, posted_date: str | None = None) -> int | None:
    match = re.search(r"20\d{2}", text)
    if match:
        return int(match.group(0))
    fy = re.search(r"\bFY\s*['’]?(\d{2})\b", text, re.I)
    if fy:
        return 2000 + int(fy.group(1))
    return int(posted_date[:4]) if posted_date else None


def _period_fields(title: str, context: str) -> tuple[int | None, str, str, str | None]:
    posted_date = _parse_date(context)
    combined = f"{title} {context}"
    year = _year_from(combined, posted_date)
    year, kind, label = classify_period(combined, fallback_year=year)
    return year, kind, label, posted_date


def _safe_filename(value: str, fallback: str = "disclosure.pdf") -> str:
    name = Path(value.split("?")[0]).name
    name = re.sub(r"[^0-9A-Za-z가-힣._-]+", "_", name).strip("._")
    if not name or not name.lower().endswith(".pdf"):
        name = (name or fallback.rsplit(".", 1)[0]) + ".pdf"
    return name[:160]


def _is_real_url(href: str) -> bool:
    return bool(href and href.strip() not in {"#", "#none", "javascript:void(0);", "javascript:;"}
                and not href.lower().startswith("javascript:"))


def _within_lookback(posted_date: str | None, year: int | None, lookback_years: int) -> bool:
    cutoff = date.today() - timedelta(days=365 * max(0, lookback_years))
    if posted_date:
        try:
            return date.fromisoformat(posted_date) >= cutoff
        except ValueError:
            pass
    return year is None or year >= cutoff.year


def _make_disclosure(source: CompanySource, title: str, context: str, detail_url: str) -> Disclosure:
    year, kind, label, posted = _period_fields(title, context)
    if detail_url.startswith("http"):
        unique_url = detail_url
    else:
        unique_url = source.list_url + "#" + quote(f"{title}|{context}")
    return Disclosure(
        company=source.company,
        title=title.strip() or context.strip() or source.company,
        detail_url=unique_url,
        posted_date=posted,
        period_year=year,
        period_kind=kind,
        period_label=label,
    )


def _browser_candidates(page, source: CompanySource) -> list[dict[str, Any]]:
    """Extract clickable list entries from the rendered DOM, not raw templates."""
    if source.strategy == "samsung":
        items = page.locator("a").evaluate_all(
            "els => els.map((a, i) => ({i, text:(a.innerText||a.textContent||'').trim(), "
            "href:a.getAttribute('href')||'', onclick:a.getAttribute('onclick')||'', "
            "context:(a.closest('tr,li,section,article,div')?.innerText||a.parentElement?.innerText||'').trim()}))"
        )
        return [x for x in items if DOWNLOAD_RE.search(x["text"]) and re.search(r"FY|분기|상반기|결산|연간", x["text"], re.I)]

    if source.strategy == "kb":
        rows = page.locator("tr").evaluate_all(
            "els => els.map((tr, i) => ({i, text:(tr.innerText||'').trim(), "
            "links:Array.from(tr.querySelectorAll('a,button,[onclick]')).map((a,j)=>({j,text:(a.innerText||a.textContent||'').trim(),href:a.getAttribute('href')||'',onclick:a.getAttribute('onclick')||''}))}))"
        )
        result = []
        for row in rows:
            text = row["text"]
            if not INCLUDE_RE.search(text) or EXCLUDE_RE.search(text):
                continue
            first_link = row["links"][0] if row["links"] else {}
            result.append({
                "row_index": row["i"], "text": text,
                "links": row["links"],
                "href": first_link.get("href", ""),
                "onclick": first_link.get("onclick", ""),
                "link_index": 0,
                "context": text,
            })
        return result

    if source.strategy == "hyundai":
        rows = page.locator("tr").evaluate_all(
            "els => els.map((tr, i) => ({i, text:(tr.innerText||'').trim(), "
            "links:Array.from(tr.querySelectorAll('a,button,[onclick]')).map((a,j)=>({j,text:(a.innerText||a.textContent||'').trim(),href:a.getAttribute('href')||'',onclick:a.getAttribute('onclick')||''}))}))"
        )
        result = []
        for row in rows:
            text = row["text"]
            if not text or EXCLUDE_RE.search(text):
                continue
            for link in row["links"]:
                action = link.get("onclick", "")
                combined = f"{text} {link.get('text','')} {action}"
                if INCLUDE_RE.search(combined) or "fnGoDetailView" in action:
                    result.append({
                        "row_index": row["i"], "text": link.get("text") or text,
                        "row_text": text, "link_index": link["j"],
                        "href": link.get("href", ""), "onclick": action,
                        "context": text,
                    })
        # Some page versions put report names in links outside table rows.
        if not result:
            items = page.locator("a").evaluate_all(
                "els => els.map((a, i) => ({i,text:(a.innerText||a.textContent||'').trim(),href:a.getAttribute('href')||'',onclick:a.getAttribute('onclick')||'',context:(a.closest('tr')?.innerText||a.parentElement?.innerText||'').trim()}))"
            )
            result = [x for x in items if INCLUDE_RE.search(x["text"] + " " + x["context"])]
        return result

    # Meritz uses a JavaScript-driven page; after render, discover its report links.
    items = page.locator("a").evaluate_all(
        "els => els.map((a, i) => ({i, text:(a.innerText||a.textContent||'').trim(), "
        "href:a.getAttribute('href')||'', onclick:a.getAttribute('onclick')||'', "
        "context:(a.closest('tr,li,article,section,div')?.innerText||a.parentElement?.innerText||'').trim()}))"
    )
    return [x for x in items if (INCLUDE_RE.search(x["text"] + " " + x["context"]) or DOWNLOAD_RE.search(x["text"]))
            and not EXCLUDE_RE.search(x["text"])]


def _list_pdf_links(page, base_url: str) -> list[Attachment]:
    raw = page.locator("a").evaluate_all(
        "els => els.map(a=>({text:(a.innerText||a.textContent||'').trim(),href:a.getAttribute('href')||'',onclick:a.getAttribute('onclick')||''}))"
    )
    found: dict[str, Attachment] = {}
    for item in raw:
        href = item.get("href", "").strip()
        label = item.get("text", "")
        if not _is_real_url(href):
            continue
        if not (".pdf" in href.lower() or DOWNLOAD_RE.search(label) or "filedownload" in href.lower()):
            continue
        url = urljoin(base_url, href)
        path_name = Path(urlparse(url).path).name
        if path_name.lower() in {"filedownload.do", "download.do", "filedown.do", "serviceaction.do"}:
            path_name = label or "disclosure.pdf"
        name = _safe_filename(path_name, label or "disclosure.pdf")
        found[url] = Attachment(name, url)
    return list(found.values())


def _candidate_title_context(source: CompanySource, candidate: dict[str, Any]) -> tuple[str, str]:
    if source.strategy == "kb":
        context = candidate.get("context", candidate.get("text", ""))
        title = candidate.get("text", "")
        # The page table may show FY 2026 only in the preceding year row; the
        # fallback year is derived from the publication date when available.
        return title, context
    if source.strategy == "hyundai":
        return candidate.get("text", ""), candidate.get("context", candidate.get("row_text", ""))
    return candidate.get("text", ""), candidate.get("context", "")


def _candidate_locator(page, source: CompanySource, candidate: dict[str, Any]):
    if source.strategy == "kb" and "row_index" in candidate:
        row = page.locator("tr").nth(candidate["row_index"])
        controls = row.locator("a,button,[onclick]")
        return controls.nth(0) if controls.count() else row
    if source.strategy == "hyundai" and "row_index" in candidate:
        row = page.locator("tr").nth(candidate["row_index"])
        controls = row.locator("a,button,[onclick]")
        index = candidate.get("link_index", 0)
        return controls.nth(index) if controls.count() > index else row
    if "i" in candidate:
        return page.locator("a").nth(candidate["i"])
    return None


def _click_for_pdf(page, source: CompanySource, candidate: dict[str, Any], temp_dir: Path, logger: logging.Logger) -> list[Attachment]:
    page.goto(source.list_url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(1600)
    target = _candidate_locator(page, source, candidate)
    if target is None or target.count() == 0:
        return []

    captured_responses: list[Any] = []
    def on_response(response):
        try:
            headers = response.headers
            content_type = headers.get("content-type", "").lower()
            disposition = headers.get("content-disposition", "").lower()
            if "pdf" in content_type or ".pdf" in disposition or ".pdf" in response.url.lower():
                captured_responses.append(response)
        except Exception:
            pass

    page.on("response", on_response)
    try:
        try:
            with page.expect_download(timeout=12000) as download_info:
                target.click(timeout=8000)
            download = download_info.value
            filename = _safe_filename(download.suggested_filename, "disclosure.pdf")
            local = temp_dir / f"{source.slug}_{int(time.time() * 1000)}_{filename}"
            download.save_as(local)
            download_url = download.url or ""
            if not download_url.startswith(("http://", "https://")):
                download_url = source.list_url + "#download=" + quote(filename)
            return [Attachment(filename, download_url, local)]
        except PlaywrightTimeoutError:
            # Some sites open a detail panel instead of triggering a download.
            page.wait_for_timeout(1200)
            links = _list_pdf_links(page, page.url)
            if links:
                return links
            if captured_responses:
                response = captured_responses[-1]
                body = response.body()
                if body.startswith(b"%PDF-"):
                    local = temp_dir / f"{source.slug}_{int(time.time() * 1000)}_captured.pdf"
                    local.write_bytes(body)
                    return [Attachment(local.name, response.url, local)]
            return []
    except Exception as exc:
        logger.warning("%s 클릭형 첨부 처리 실패: %s", source.company, exc)
        return []
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass


def discover_company_documents(
    slug: str,
    lookback_years: int = 3,
    max_documents: int | None = None,
    logger: logging.Logger | None = None,
) -> list[tuple[Disclosure, list[Attachment]]]:
    """Use a rendered browser for non-DB company disclosure pages.

    It handles direct PDF anchors and common JavaScript-triggered downloads.
    The source sites change their front-end markup periodically, so the caller
    should treat a zero-result collection as an actionable source warning.
    """
    log = logger or logging.getLogger(__name__)
    source = COMPANY_SOURCES[slug]
    temp_dir = Path(tempfile.gettempdir()) / "insurance-disclosure-browser-downloads"
    temp_dir.mkdir(parents=True, exist_ok=True)

    if sync_playwright is None:
        raise RuntimeError(
            "Playwright가 설치되어 있지 않습니다. requirements.txt 설치 후 "
            "'python -m playwright install chromium'을 실행하세요."
        )
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT, accept_downloads=True, locale="ko-KR")
        page = context.new_page()
        try:
            page.goto(source.list_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2200)
            # Hyundai and Meritz load list content through client-side requests.
            try:
                page.wait_for_load_state("networkidle", timeout=7000)
            except PlaywrightTimeoutError:
                pass

            candidates = _browser_candidates(page, source)
            if not candidates:
                log.warning("%s: 브라우저 렌더링 후 공시 후보를 찾지 못했습니다: %s", source.company, source.list_url)
                return []

            results: list[tuple[Disclosure, list[Attachment]]] = []
            seen: set[str] = set()
            for candidate in candidates:
                title, row_context = _candidate_title_context(source, candidate)
                context_text = row_context or candidate.get("text", "")
                year, kind, label, posted = _period_fields(title, context_text)
                if not _within_lookback(posted, year, lookback_years):
                    continue
                if source.strategy in {"kb", "meritz", "hyundai"}:
                    combined = f"{title} {context_text}"
                    # Only collect regular management-unified disclosures, not
                    # review/audit statements or general quarterly reports.
                    if not INCLUDE_RE.search(combined) and source.strategy != "hyundai":
                        continue
                    if EXCLUDE_RE.search(combined):
                        continue
                identity = f"{title}|{label}|{posted}"
                if identity in seen:
                    continue
                seen.add(identity)

                href = candidate.get("href", "").strip()
                attachments: list[Attachment] = []
                # Prefer a browser click first. It carries the site's cookies and
                # can catch JavaScript downloads or inline PDF responses.
                attachments = _click_for_pdf(page, source, candidate, temp_dir, log)
                if not attachments and _is_real_url(href):
                    direct_url = urljoin(source.list_url, href)
                    if ".pdf" in direct_url.lower() or DOWNLOAD_RE.search(title) or "filedownload" in direct_url.lower():
                        attachments = [Attachment(_safe_filename(urlparse(direct_url).path, title), direct_url)]
                if not attachments and _is_real_url(href):
                    # If the entry itself is a detail view, navigate to it and
                    # inspect the rendered detail panel for PDF attachments.
                    try:
                        page.goto(urljoin(source.list_url, href), wait_until="domcontentloaded", timeout=30000)
                        page.wait_for_timeout(1000)
                        attachments = _list_pdf_links(page, page.url)
                    except Exception:
                        pass
                if not attachments:
                    log.warning("%s: PDF 링크를 확인하지 못함: %s", source.company, title)
                    continue

                detail_url = href if _is_real_url(href) else source.list_url + "#" + quote(identity)
                disclosure = _make_disclosure(source, title, context_text, detail_url)
                results.append((disclosure, attachments))
                log.info("%s: %s -> 첨부 %d개", source.company, disclosure.title, len(attachments))
                if max_documents and len(results) >= max_documents:
                    break

            if not results:
                log.warning("%s: 최근 %d년 대상 공시/PDF를 찾지 못했습니다. 사이트 구조 점검이 필요합니다.", source.company, lookback_years)
            return results
        finally:
            context.close()
            browser.close()
