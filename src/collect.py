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
    """
    try:
        from googlenewsdecoder import gnewsdecoder
    except ImportError:
        gnewsdecoder = None

    def _resolve(article: dict) -> None:
        url = article["link"]
        if "news.google.com" not in url:
            return
        if gnewsdecoder is not None:
            try:
                result = gnewsdecoder(url, interval=0)
                if result.get("status") and result.get("decoded_url"):
                    article["link"] = result["decoded_url"]
                    return
            except Exception as e:
                log.debug("링크 디코딩 실패 (%s): %s", article["title"][:30], e)
        try:
            resp = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
            if "news.google.com" not in resp.url:
                article["link"] = resp.url
        except Exception as e:
            log.debug("링크 리다이렉트 실패 (%s): %s", article["title"][:30], e)

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        list(pool.map(_resolve, articles))


def filter_resolved_freshness(articles: list[dict], lookback_hours: int) -> list[dict]:
    """resolve_links() 이후 언론사 원문 URL 발행일로 신선도를 재검증(2차 안전망).

    구글 뉴스 pubDate는 원문 재크롤링/업데이트 시점으로 갱신되어 실제 최초
    발행일보다 최신으로 표시되는 경우가 있다. 최종 선정된 소수의 기사만 대상으로
    원문 URL에 새겨진 발행일(국내 언론사 URL 관례)과 대조해, 수집 범위보다 하루
    이상 오래된 것으로 확인되면 발송 직전에 제외한다.
    """
    cutoff = (datetime.now(KST) - timedelta(hours=lookback_hours)).date() - timedelta(days=1)
    kept = []
    for a in articles:
        url_date = _url_published_date(a["link"])
        if url_date is not None and url_date < cutoff:
            log.warning(
                "발행일 재검증에서 제외 (%s, %s): URL 발행일=%s, pubDate=%s",
                a["title"][:40], a.get("source"), url_date.isoformat(), a.get("published"),
            )
            continue
        kept.append(a)
    return kept
