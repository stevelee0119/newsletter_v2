"""1차(로컬) 중복 제거 — URL 정규화 + 제목 유사도 클러스터링.

LLM 호출 전에 후보 수를 줄여 토큰·시간을 절약한다.

같은 사건을 다룬 기사라도 언론사마다 제목을 크게 다르게 쓰는 경우(인용구,
관점, 부가 설명 차이)가 많아 문자열 편집거리 기반 유사도(token_set_ratio)만
으로는 놓치는 중복이 많다. 이를 보완하기 위해 핵심 명사(2글자 이상 어절)
겹침 비율(overlap coefficient)을 보조 신호로 함께 사용한다.

기사가 어떤 키워드로 수집됐는지(category)는 중복 판단과 무관하다 — 같은
사건이 서로 다른 키워드(예: "특검"과 "대통령")로 각각 수집될 수 있으므로,
유사도 비교는 카테고리와 무관하게 전체 기사 대상으로 수행한다. category는
이후 후보 상한(candidate_limits) 적용에만 사용한다.
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


def _significant_tokens(norm_title: str) -> set[str]:
    """2글자 이상 어절만 추출 (조사·단음절 어미 등 노이즈 제거)."""
    return {w for w in norm_title.split() if len(w) >= 2}


def _is_similar(
    norm_a: str,
    tokens_a: set[str],
    norm_b: str,
    tokens_b: set[str],
    threshold: float,
    overlap_threshold: float,
    min_shared_tokens: int,
) -> bool:
    """두 제목이 같은 사건을 다루는지 판단 (편집거리 유사도 OR 핵심어 겹침)."""
    if fuzz.token_set_ratio(norm_a, norm_b) >= threshold:
        return True
    if not tokens_a or not tokens_b:
        return False
    shared = tokens_a & tokens_b
    if len(shared) < min_shared_tokens:
        return False
    overlap = len(shared) / min(len(tokens_a), len(tokens_b)) * 100
    return overlap >= overlap_threshold


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
    overlap_threshold = config.get("dedupe_overlap_threshold", 40)
    min_shared_tokens = config.get("dedupe_min_shared_tokens", 2)

    # 1) 동일 URL / 동일 (제목, 언론사) 제거 — 키워드가 달라 중복 수집된 경우
    seen: dict[tuple, dict] = {}
    for a in articles:
        key = (a["source"], normalize_title(a["title"]))
        if key not in seen:
            seen[key] = a
    unique = list(seen.values())

    # 2) 언론사 순위 → 상세도 순으로 정렬 후 그리디 클러스터링 (카테고리 무관)
    unique.sort(key=lambda a: (_media_rank(a["source"], rank_list), -_detail_score(a)))

    representatives: list[dict] = []
    norm_cache: list[str] = []
    tokens_cache: list[set[str]] = []
    for a in unique:
        norm = normalize_title(a["title"])
        tokens = _significant_tokens(norm)
        is_dup = any(
            _is_similar(norm, tokens, rep_norm, rep_tokens, threshold, overlap_threshold, min_shared_tokens)
            for rep_norm, rep_tokens in zip(norm_cache, tokens_cache)
        )
        if not is_dup:
            representatives.append(a)
            norm_cache.append(norm)
            tokens_cache.append(tokens)

    # 3) 카테고리별 후보 상한 적용 (대표 기사가 최종 배정된 category 기준)
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
