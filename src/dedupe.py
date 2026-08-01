"""1차(로컬) 중복 제거 — URL 정규화 + 제목 유사도 클러스터링.

LLM 호출 전에 후보 수를 줄여 토큰·시간을 절약한다.
"""

from __future__ import annotations

import logging
import re

from rapidfuzz import fuzz

log = logging.getLogger(__name__)

_BRACKET_RE = re.compile(r"[\[\(【〈<「](단독|속보|종합|영상|포토|사진|르포|인터뷰|기획|현장)[^\]\)】〉>」]*[\]\)】〉>」]")
_PUNCT_RE = re.compile(r"[^\w가-힣 ]")


def normalize_title(title: str) -> str:
    t = _BRACKET_RE.sub(" ", title)
    t = _PUNCT_RE.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip().lower()


def _media_rank(source: str, rank_list: list[str]) -> int:
    try:
        return rank_list.index(source)
    except ValueError:
        return len(rank_list)


def _detail_score(article: dict) -> int:
    return len(article.get("title", "")) + len(article.get("description", ""))


def dedupe(articles: list[dict], config: dict) -> list[dict]:
    """중복 제거 후 카테고리별 상한을 적용한 후보 목록 반환."""
    rank_list = config.get("media_rank") or []
    threshold = config.get("dedupe_threshold", 82)

    # 1) 동일 URL / 동일 (제목, 언론사) 제거 — 키워드가 달라 중복 수집된 경우
    seen: dict[tuple, dict] = {}
    for a in articles:
        key = (a["source"], normalize_title(a["title"]))
        if key not in seen:
            seen[key] = a
    unique = list(seen.values())

    # 2) 언론사 순위 → 상세도 순으로 정렬 후 그리디 클러스터링
    unique.sort(key=lambda a: (_media_rank(a["source"], rank_list), -_detail_score(a)))

    representatives: list[dict] = []
    norm_cache: list[str] = []
    for a in unique:
        norm = normalize_title(a["title"])
        is_dup = any(
            a["category"] == rep["category"]
            and fuzz.token_set_ratio(norm, rep_norm) >= threshold
            for rep, rep_norm in zip(representatives, norm_cache)
        )
        if not is_dup:
            representatives.append(a)
            norm_cache.append(norm)

    # 3) 카테고리별 후보 상한 적용
    limits = config.get("candidate_limits") or {}
    counts: dict[str, int] = {}
    capped: list[dict] = []
    for a in representatives:
        cat = a["category"]
        limit = limits.get(cat, 999)
        if counts.get(cat, 0) < limit:
            capped.append(a)
            counts[cat] = counts.get(cat, 0) + 1

    log.info(
        "중복 제거: %d건 -> 고유 %d건 -> 클러스터 대표 %d건 -> 후보 %d건",
        len(articles), len(unique), len(representatives), len(capped),
    )
    return capped
