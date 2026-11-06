from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup

LIST_URL = (
    "https://www.idbins.com/pc/bizxpress/contentTemplet/pb/mp/rg/list.jsp"
)
USER_AGENT = (
    "Mozilla/5.0 (compatible; InsuranceDisclosureResearchBot/0.1; "
    "+https://github.com/your-org/insurance-disclosure-collector)"
)
DATE_RE = re.compile(r"(20\d{2})[.년/-]\s*(\d{1,2})[.월/-]\s*(\d{1,2})")


@dataclass(frozen=True)
class Disclosure:
    company: str
    title: str
    detail_url: str
    posted_date: str | None
    period_year: int | None
    period_kind: str
    period_label: str


@dataclass(frozen=True)
class Attachment:
    filename: str
    url: str
    # Some company sites expose downloads only after a browser-side JavaScript action.
    # In that case the Playwright adapter saves the response to a temporary local file.
    local_path: Path | None = None


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/pdf,application/xhtml+xml,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
        }
    )
    return session


def _fetch_text(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=(10, 40))
    response.raise_for_status()
    # Requests usually detects this page's encoding, but DB's legacy pages may
    # omit a reliable charset. The HTML meta tag can still be read by BeautifulSoup.
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def _parse_date(value: str) -> str | None:
    match = DATE_RE.search(value)
    if not match:
        return None
    year, month, day = map(int, match.groups())
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def classify_period(title: str, fallback_year: int | None = None) -> tuple[int | None, str, str]:
    """Normalize all insurers' disclosure titles to comparable reporting periods.

    For management disclosures, second-quarter / 2-of-4-quarter / first-half
    documents all represent the six-month (H1) reporting date.
    """
    year_match = re.search(r"20\d{2}", title)
    if year_match:
        year = int(year_match.group(0))
    else:
        fy_match = re.search(r"\bFY\s*['’]?(\d{2})\b", title, re.IGNORECASE)
        year = (2000 + int(fy_match.group(1))) if fy_match else fallback_year

    normalized = re.sub(r"\s+", "", title).lower()
    if re.search(r"(?:1/4|1분기|1stquarter)", normalized):
        kind = "Q1"
    elif re.search(r"(?:2/4|2분기|상반기|반기|2ndquarter)", normalized):
        kind = "H1"
    elif re.search(r"(?:3/4|3분기|3rdquarter)", normalized):
        kind = "Q3"
    elif re.search(r"(?:4/4|4분기|결산|연간|사업연도)", normalized):
        kind = "ANNUAL"
    elif "경영통일공시" in normalized or (year and "현황" in normalized):
        kind = "ANNUAL"
    else:
        kind = "OTHER"
    label = f"{year}_{kind}" if year else f"UNKNOWN_{kind}"
    return year, kind, label


def _extract_listing_links(html: str) -> list[tuple[str, str, str | None]]:
    soup = BeautifulSoup(html, "html.parser")
    found: dict[str, tuple[str, str, str | None]] = {}

    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "").strip()
        title = " ".join(anchor.get_text(" ", strip=True).split())
        if not title or "view.jsp" not in href.lower():
            continue
        if not ("DB손해보험" in title or "동부화재" in title):
            continue

        detail_url = urljoin(LIST_URL, href)
        # The registration date is commonly in the containing table row. Fall
        # back through nearby containers for markup variants.
        container = anchor.find_parent("tr") or anchor.parent
        row_text = ""
        for _ in range(4):
            if container is None:
                break
            row_text = " ".join(container.get_text(" ", strip=True).split())
            if _parse_date(row_text):
                break
            container = container.parent
        posted = _parse_date(row_text)
        found[detail_url] = (title, detail_url, posted)

    return list(found.values())


def discover_disclosures(
    session: requests.Session,
    lookback_years: int = 3,
    max_documents: int | None = None,
    logger: logging.Logger | None = None,
) -> list[Disclosure]:
    """Read DB's regular-management-disclosure list and resolve detail URLs."""
    log = logger or logging.getLogger(__name__)
    listing_html = _fetch_text(session, LIST_URL)
    rows = _extract_listing_links(listing_html)
    if not rows:
        raise RuntimeError(
            "DB손해보험 공시 목록에서 상세 페이지 링크를 찾지 못했습니다. "
            "사이트 HTML 구조가 변경되었는지 확인하세요."
        )

    cutoff = date.today() - timedelta(days=365 * max(0, lookback_years))
    disclosures: list[Disclosure] = []

    for title, detail_url, posted_date in rows:
        period_year, period_kind, period_label = classify_period(title)
        if posted_date:
            try:
                if date.fromisoformat(posted_date) < cutoff:
                    continue
            except ValueError:
                pass
        elif period_year and period_year < cutoff.year:
            continue

        disclosures.append(
            Disclosure(
                company="DB손해보험",
                title=title,
                detail_url=detail_url,
                posted_date=posted_date,
                period_year=period_year,
                period_kind=period_kind,
                period_label=period_label,
            )
        )
        if max_documents and len(disclosures) >= max_documents:
            break

    log.info("공시 목록에서 %d건 확인 (기간 필터 적용 후)", len(disclosures))
    return disclosures


def discover_attachments(
    session: requests.Session, disclosure: Disclosure, logger: logging.Logger | None = None
) -> list[Attachment]:
    log = logger or logging.getLogger(__name__)
    html = _fetch_text(session, disclosure.detail_url)
    soup = BeautifulSoup(html, "html.parser")
    attachments: dict[str, Attachment] = {}

    for anchor in soup.select("a[href]"):
        href = anchor.get("href", "").strip()
        text = anchor.get_text(" ", strip=True)
        parsed_path = urlparse(href).path
        filename = unquote(Path(parsed_path).name)
        # The visible attachment name may carry the .pdf suffix even where a
        # site's href is an intermediate download endpoint.
        if not filename.lower().endswith(".pdf") and not text.lower().endswith(".pdf"):
            continue
        if not filename.lower().endswith(".pdf"):
            filename = text.strip()
        if not filename:
            continue
        url = urljoin(disclosure.detail_url, href)
        attachments[url] = Attachment(filename=filename, url=url)

    result = sorted(attachments.values(), key=lambda x: x.filename)
    if not result:
        log.warning("PDF 첨부파일을 찾지 못함: %s", disclosure.title)
    return result


def download_pdf(
    session: requests.Session,
    attachment: Attachment,
    destination: Path,
    min_bytes: int = 1000,
) -> tuple[str, int]:
    """Download and verify a PDF, returning (sha256, byte_count)."""
    import hashlib

    response = session.get(attachment.url, timeout=(10, 90), stream=True)
    response.raise_for_status()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    total = 0
    first = b""
    try:
        with temp_path.open("wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 128):
                if not chunk:
                    continue
                if len(first) < 8:
                    first += chunk[: 8 - len(first)]
                output.write(chunk)
                digest.update(chunk)
                total += len(chunk)
        if total < min_bytes or not first.startswith(b"%PDF-"):
            raise ValueError(
                f"PDF로 확인되지 않는 응답입니다: {attachment.url} "
                f"(bytes={total}, content-type={response.headers.get('content-type')})"
            )
        temp_path.replace(destination)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
    finally:
        response.close()
    return digest.hexdigest(), total
