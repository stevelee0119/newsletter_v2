"""구글 뉴스 RSS 수집기.

키워드별 Google News RSS(한국판)를 병렬 조회해 최근 기사를 모은다.
"""

from __future__ import annotations

import email.utils
import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests

log = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
RSS_BASE = "https://news.google.com/rss/search"
HEADERS = {"User-Agent": "Mozilla/5.0 (newsletter-bot)"}
_URL_DATE_RE = re.compile(r"(20\d{6})")
_META_DATE_PATTERNS = [
    re.compile(r'property=["\']article:published_time["\'][^>]*content=["\']([^"\']+)["\']', re.I),
    re.compile(r'content=["\']([^"\']+)["\'][^>]*property=["\']article:published_time["\']', re.I),
    re.compile(r'itemprop=["\']datePublished["\'][^>]*content=["\']([^"\']+)["\']', re.I),
    re.compile(r'name=["\']publish(?:ed)?-?date["\'][^>]*content=["\']([^"\']+)["\']', re.I),
    re.compile(r'"datePublished"\s*:\s*"([^"]+)"'),
]


def _rss_url(keyword: str) -> str:
    query = f'"{keyword}" when:1d'
    return f"{RSS_BASE}?{urllib.parse.urlencode({'q': query, 'hl': 'ko', 'gl': 'KR', 'ceid': 'KR:ko'})}"


def _parse_pubdate(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return email.utils.parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None


def _url_published_date(url: str):
    """기사 URL에 포함된 발행일(YYYYMMDD, 국내 언론사 URL 관례)을 추출.

    구글 뉴스의 pubDate는 원문 재크롤링/업데이트 시점으로 갱신되는 경우가 있어
    실제 최초 발행일보다 최신으로 표시될 수 있다. URL에 새겨진 발행일은 대부분
    바뀌지 않으므로 pubDate 신뢰도를 보강하는 2차 신호로 사용한다.
    """
    for match in _URL_DATE_RE.finditer(url):
        try:
            return datetime.strptime(match.group(1), "%Y%m%d").date()
        except ValueError:
            continue
    return None


def _parse_iso(text: str) -> datetime | None:
    try:
        return datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    except ValueError:
        return None


def _fetch_page_published(url: str) -> datetime | None:
    """기사 원문 페이지의 메타태그에서 실제 발행 시각을 추출(베스트 에포트).

    URL에 날짜가 새겨져 있지 않은 언론사(네이버 뉴스 등 아이디 기반 URL 포함)
    에도 적용 가능한, 더 신뢰도 높은 신선도 신호. 실패해도 예외를 전파하지
    않고 None을 반환한다.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        text = resp.text[:150_000]
    except Exception:
        return None
    for pat in _META_DATE_PATTERNS:
        m = pat.search(text)
        if m:
            dt = _parse_iso(m.group(1))
            if dt:
                return dt if dt.tzinfo else dt.replace(tzinfo=KST)
    return None


def _clean_title(title: str, source: str) -> str:
    # 구글 뉴스 제목은 "제목 - 언론사" 형태
    suffix = f" - {source}"
    if source and title.endswith(suffix):
        title = title[: -len(suffix)]
    return title.strip()


def fetch_keyword(keyword: str, category: str, since: datetime) -> list[dict]:
    """단일 키워드의 RSS를 조회해 기사 dict 목록을 반환."""
    try:
        resp = requests.get(_rss_url(keyword), headers=HEADERS, timeout=20)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as e:  # 개별 키워드 실패는 건너뜀
        log.warning("RSS 수집 실패 (%s): %s", keyword, e)
        return []

    articles = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source = (item.findtext("source") or "").strip()
        desc = (item.findtext("description") or "").strip()
        pub = _parse_pubdate(item.findtext("pubDate"))
        if not title or not link:
            continue
        # 발행 시각을 확인할 수 없거나 수집 범위(기본 24시간)보다 오래된 기사는 제외
        if pub is None or pub < since:
            continue
        articles.append(
            {
                "title": _clean_title(title, source),
                "link": link,
                "source": source,
                "description": re.sub(r"<[^>]+>", "", desc)[:300],
                "published": pub.astimezone(KST).isoformat() if pub else None,
                "keyword": keyword,
                "category": category,
            }
        )
    return articles


def collect_all(config: dict) -> list[dict]:
    """config의 전체 키워드를 병렬 수집."""
    since = datetime.now(timezone.utc) - timedelta(hours=config.get("lookback_hours", 28))
    blocklist = set(config.get("source_blocklist") or [])

    jobs = []
    for category, keywords in config["keywords"].items():
        for kw in keywords:
            jobs.append((kw, category))

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(fetch_keyword, kw, cat, since): kw for kw, cat in jobs}
        for fut in as_completed(futures):
            results.extend(fut.result())

    if blocklist:
        results = [a for a in results if a["source"] not in blocklist]

    log.info("수집 완료: %d건 (키워드 %d개)", len(results), len(jobs))
    return results


def resolve_links(articles: list[dict], max_workers: int = 8) -> None:
    """구글 뉴스 리다이렉트 링크를 언론사 원문 링크로 복원(베스트 에포트).

    선정된 소수의 기사에 대해서만 호출할 것. 실패 시 구글 링크 유지.
    원문 링크 복원에 성공하면 그 페이지의 메타태그에서 실제 발행 시각도 함께
    읽어와 article["page_published"]에 저장한다(filter_resolved_freshness가
    사용하는 2차 안전망 — URL에 날짜가 없는 언론사에도 적용됨).
    """
    try:
        from googlenewsdecoder import gnewsdecoder
    except ImportError:
        gnewsdecoder = None

    def _resolve(article: dict) -> None:
        url = article["link"]
        if "news.google.com" in url:
            if gnewsdecoder is not None:
                try:
                    result = gnewsdecoder(url, interval=0)
                    if result.get("status") and result.get("decoded_url"):
                        article["link"] = result["decoded_url"]
                except Exception as e:
                    log.debug("링크 디코딩 실패 (%s): %s", article["title"][:30], e)
            if "news.google.com" in article["link"]:
                try:
                    resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
                    if "news.google.com" not in resp.url:
                        article["link"] = resp.url
                except Exception as e:
                    log.debug("링크 리다이렉트 실패 (%s): %s", article["title"][:30], e)

        if "news.google.com" not in article["link"]:
            article["page_published"] = _fetch_page_published(article["link"])

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        list(pool.map(_resolve, articles))


def filter_resolved_freshness(articles: list[dict], lookback_hours: int) -> list[dict]:
    """resolve_links() 이후 실제 발행 시각으로 신선도를 재검증(2차 안전망).

    구글 뉴스 pubDate는 원문 재크롤링/업데이트 시점으로 갱신되어 실제 최초
    발행일보다 최신으로 표시되는 경우가 있다. 최종 선정된 소수의 기사만 대상
    으로, (1) 원문 페이지 메타태그의 실제 발행 시각(page_published, 시간 단위
    정밀도)을 최우선으로 쓰고, 없으면 (2) URL에 새겨진 발행일(국내 언론사 URL
    관례, 날짜 단위 정밀도라 하루 여유를 둠)로 보조 판단한다. 둘 다 못 구하면
    (예: 네이버 뉴스처럼 URL에 날짜가 없고 메타태그 추출도 실패) 통과시킨다 —
    구글 pubDate 기준으로는 이미 수집 단계에서 24시간 이내로 필터링된 상태다.
    """
    now_utc = datetime.now(timezone.utc)
    strict_cutoff = now_utc - timedelta(hours=lookback_hours)
    lenient_cutoff_date = (now_utc - timedelta(hours=lookback_hours)).astimezone(KST).date() - timedelta(days=1)

    kept = []
    for a in articles:
        page_dt = a.get("page_published")
        if page_dt is not None:
            page_dt_utc = page_dt.astimezone(timezone.utc) if page_dt.tzinfo else page_dt.replace(tzinfo=timezone.utc)
            if page_dt_utc < strict_cutoff:
                log.warning(
                    "발행일 재검증에서 제외 (%s, %s): 페이지 실제 발행시각=%s, pubDate=%s",
                    a["title"][:40], a.get("source"), page_dt_utc.isoformat(), a.get("published"),
                )
                continue
            kept.append(a)
            continue

        url_date = _url_published_date(a["link"])
        if url_date is not None and url_date < lenient_cutoff_date:
            log.warning(
                "발행일 재검증에서 제외 (%s, %s): URL 발행일=%s, pubDate=%s",
                a["title"][:40], a.get("source"), url_date.isoformat(), a.get("published"),
            )
            continue
        kept.append(a)
    return kept
