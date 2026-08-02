"""1차(로컬) 중복 제거 — URL 정규화 + 제목 유사도 클러스터링.

LLM 호출 전에 후보 수를 줄여 토큰·시간을 절약한다.

같은 사건을 다룬 기사라도 언론사마다 제목을 크게 다르게 쓰는 경우(인용구,
관점, 부가 설명 차이)가 많아 문자열 편집거리 기반 유사도(token_set_ratio)만
으로는 놓치는 중복이 많다. 이를 보완하기 위해 두 가지 보조 신호를 함께
사용한다:
1) 핵심 명사(2글자 이상 어절) 겹침 비율(overlap coefficient) — 전체적으로
   제목이 비슷한 경우를 잡는다.
2) 특이 공유 어절(distinctive shared token) — "림팩", "윤한홍"처럼 이번
   배치 전체에서 드물게만 등장하는(문서빈도가 낮은) 단어를 두 제목이 공유
   하면, 나머지 표현이 크게 달라 전체 겹침 비율은 낮더라도 같은 사건일
   가능성이 매우 높다고 판단한다("특검", "조사"처럼 흔한 단어는 문서빈도가
   높아 이 신호에 기여하지 않는다).

기사가 어떤 키워드로 수집됐는지(category)는 중복 판단과 무관하다 — 같은
사건이 서로 다른 키워드(예: "특검"과 "대통령")로 각각 수집될 수 있으므로,
유사도 비교는 카테고리와 무관하게 전체 기사 대상으로 수행한다. category는
이후 후보 상한(candidate_limits) 적용에만 사용한다.
"""

from __future__ import annotations

import json
import logging
import math
import os
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


def _document_frequency(token_sets: list[set[str]]) -> dict[str, int]:
    df: dict[str, int] = {}
    for tokens in token_sets:
        for t in tokens:
            df[t] = df.get(t, 0) + 1
    return df


def _has_distinctive_shared_token(
    tokens_a: set[str], tokens_b: set[str], df: dict[str, int], n_docs: int, min_idf: float
) -> bool:
    """두 제목이 이번 배치에서 드문(고유한) 단어를 공유하는지 판단.

    "특검", "조사"처럼 배치 전체에 흔한 단어는 문서빈도(df)가 높아 idf가
    낮으므로 신호에 기여하지 않고, "림팩", "윤한홍"처럼 소수 기사에만
    등장하는 단어는 idf가 높아 하나만 공유해도 같은 사건 신호로 취급한다.
    """
    for t in tokens_a & tokens_b:
        idf = math.log((n_docs + 1) / (df.get(t, 1) + 1))
        if idf >= min_idf:
            return True
    return False


def _is_similar(
    norm_a: str,
    tokens_a: set[str],
    norm_b: str,
    tokens_b: set[str],
    threshold: float,
    overlap_threshold: float,
    min_shared_tokens: int,
    df: dict[str, int],
    n_docs: int,
    distinctive_idf: float,
) -> bool:
    """두 제목이 같은 사건을 다루는지 판단 (편집거리 유사도 OR 핵심어 겹침 OR 특이 공유 어절)."""
    if fuzz.token_set_ratio(norm_a, norm_b) >= threshold:
        return True
    if not tokens_a or not tokens_b:
        return False
    shared = tokens_a & tokens_b
    if len(shared) >= min_shared_tokens:
        overlap = len(shared) / min(len(tokens_a), len(tokens_b)) * 100
        if overlap >= overlap_threshold:
            return True
    return _has_distinctive_shared_token(tokens_a, tokens_b, df, n_docs, distinctive_idf)


def _media_rank(source: str, rank_list: list[str]) -> int:
    try:
        return rank_list.index(source)
    except ValueError:
        return len(rank_list)


def _detail_score(article: dict) -> int:
    return (
        len(article.get("title", ""))
        + len(article.get("description", ""))
        + len(article.get("full_text") or "")
    )


def dedupe(articles: list[dict], config: dict) -> list[dict]:
    """중복 제거 후 카테고리별 상한을 적용한 후보 목록 반환."""
    rank_list = config.get("media_rank") or []
    threshold = config.get("dedupe_threshold", 82)
    overlap_threshold = config.get("dedupe_overlap_threshold", 40)
    min_shared_tokens = config.get("dedupe_min_shared_tokens", 2)
    distinctive_idf = config.get("dedupe_distinctive_idf", 3.0)

    # 1) 동일 URL / 동일 (제목, 언론사) 제거 — 키워드가 달라 중복 수집된 경우
    seen: dict[tuple, dict] = {}
    for a in articles:
        key = (a["source"], normalize_title(a["title"]))
        if key not in seen:
            seen[key] = a
    unique = list(seen.values())

    # 2) 언론사 순위 → 상세도 순으로 정렬 후 그리디 클러스터링 (카테고리 무관)
    unique.sort(key=lambda a: (_media_rank(a["source"], rank_list), -_detail_score(a)))

    # 배치 전체 기준 문서빈도 — 특이 공유 어절 판단에 사용(대표 선정 여부와 무관하게 고정)
    all_tokens = [_significant_tokens(normalize_title(a["title"])) for a in unique]
    df = _document_frequency(all_tokens)
    n_docs = len(unique)

    representatives: list[dict] = []
    norm_cache: list[str] = []
    tokens_cache: list[set[str]] = []
    for a, tokens in zip(unique, all_tokens):
        norm = normalize_title(a["title"])
        is_dup = any(
            _is_similar(
                norm, tokens, rep_norm, rep_tokens,
                threshold, overlap_threshold, min_shared_tokens, df, n_docs, distinctive_idf,
            )
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


CONTENT_EXCERPT_CHARS = 1200  # Gemini/Claude에 넘길 본문 발췌 길이(비용·지연 통제)


def _content_excerpt(article: dict) -> str:
    """본문 전체(full_text)가 있으면 그걸, 없으면 RSS 요약(description)을 발췌."""
    text = article.get("full_text") or article.get("description") or ""
    return text[:CONTENT_EXCERPT_CHARS]


def gemini_content_dedupe(articles: list[dict], config: dict) -> list[dict]:
    """2단계 필터 — Gemini로 본문 전체를 분석해 (1) 같은 사건 기사 병합, (2) 과거 기사 제외.

    1단계(dedupe)는 제목 유사도 기반이라 표현이 크게 다른 동일 사건 기사를
    놓칠 수 있다. 이 단계는 원문 본문 전체(resolve_links가 채워둔 full_text,
    실패 시 RSS 요약으로 대체)를 근거로 Gemini에게 (1) 같은 사건인지, (2) 본문
    내용상 이미 지난 사건을 다루는 과거 기사인지 판단시켜 보완한다.
    GEMINI_API_KEY 미설정 시 건너뛴다(선택 기능).
    """
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        log.info("Gemini API 키 없음 — 2단계 콘텐츠 필터 건너뜀")
        return articles
    try:
        from google import genai
    except ImportError:
        log.warning("google-genai 패키지 미설치 — 2단계 콘텐츠 필터 건너뜀")
        return articles

    payload = [
        {"id": i, "title": a["title"], "content": _content_excerpt(a)}
        for i, a in enumerate(articles)
    ]
    prompt = (
        "다음은 오늘 수집된 국방·법무 뉴스 기사 후보 목록이다(id, 제목, 본문 발췌).\n\n"
        "[작업 1] 중복 묶기: 제목이 서로 크게 다르더라도 본문 내용상 실제로는 같은 "
        "사건·발표·판결을 다루는 기사들을 찾아 id로 그룹화하라. 단순히 같은 주제 "
        "범주(예: 둘 다 '특검' 관련)라는 이유만으로 묶지 말고, 같은 특정 사건을 "
        "다루는 경우에만 묶는다.\n\n"
        "[작업 2] 과거 기사 판단: 본문 내용상 오늘 새로 발생/발표된 사실이 아니라, "
        "이미 며칠 전에 일어난 사건을 새로운 진전 없이 재정리·재보도하는 기사라면 "
        "id를 stale_ids에 넣어라. 판단 근거는 본문에 명시된 구체적 날짜·시점 표현"
        "(예: '지난 O일', '앞서 O일')이지, 단순히 배경 설명으로 과거를 언급하는 "
        "것만으로는 과거 기사로 보지 않는다. 오늘 발표된 후속 진전·반응·분석 기사는 "
        "과거 기사가 아니다. 애매하면 stale_ids에 넣지 말고 남겨라(과탈락 방지).\n\n"
        f"기사 목록:\n{json.dumps(payload, ensure_ascii=False)}"
    )
    schema = {
        "type": "object",
        "properties": {
            "duplicate_groups": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "integer"}},
            },
            "stale_ids": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["duplicate_groups", "stale_ids"],
    }
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=config.get("gemini_model", "gemini-2.5-flash"),
            contents=prompt,
            config={"response_mime_type": "application/json", "response_json_schema": schema},
        )
        result = json.loads(response.text)
    except Exception as e:
        log.warning("Gemini 콘텐츠 필터 실패(건너뜀): %s", e)
        return articles

    stale = {i for i in result.get("stale_ids", []) if isinstance(i, int) and 0 <= i < len(articles)}
    for i in stale:
        log.info("Gemini 과거 기사로 판단해 제외: %s", articles[i]["title"][:40])

    rank_list = config.get("media_rank") or []
    drop: set[int] = set(stale)
    for group in result.get("duplicate_groups", []):
        valid = [i for i in group if isinstance(i, int) and 0 <= i < len(articles) and i not in stale]
        if len(valid) < 2:
            continue
        valid.sort(key=lambda i: (_media_rank(articles[i]["source"], rank_list), -_detail_score(articles[i])))
        drop.update(valid[1:])

    kept = [a for i, a in enumerate(articles) if i not in drop]
    if drop:
        log.info("Gemini 2단계 필터(중복+과거 기사): %d건 -> %d건", len(articles), len(kept))
    return kept
