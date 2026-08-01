"""Claude API 분류기 — 1회 호출로 섹션 배치 + 의미 중복 제거 + 중요도 정렬."""

from __future__ import annotations

import json
import logging

import anthropic

log = logging.getLogger(__name__)

SECTION_KEYS = [
    "special_counsel",
    "defense_general",
    "defense_nk_alliance",
    "defense_industry",
    "defense_intl_law",
    "law_assembly_gov",
    "law_general",
    "law_judiciary_agencies",
    "rulings",
    "schedules",
]

SECTION_DESC = """\
- special_counsel: 특검(특별검사) 수사·재판·관련 정치권 동향
- defense_general: 국방부·합참·각군·군 인사·군 사법/법무·병영 등 국방 일반
- defense_nk_alliance: 북한 동향, 한미동맹, 연합훈련, 주한미군, 주변국 군사 외교
- defense_industry: 방위사업청, 방산, 무기체계, 미래전·현대전 기술
- defense_intl_law: 해외 전쟁·분쟁, 국제법, ICC·ICJ 등 국제재판소
- law_assembly_gov: 국회(본회의·법사위·국방위·운영위 등), 대통령실, 정부 입법·정책
- law_general: 법무부·법제처·변협·로펌·리걸테크 등 법조계 일반
- law_judiciary_agencies: 법원·헌재·대검·검찰·경찰청·공수처·공소청·중수청 등 사법·수사기관 조직 동향
- rulings: 오늘의 주요 판결·결정 (대법원/헌재/하급심의 구체적 판결 내용)
- schedules: 오늘의 주요 일정 기사 (법조/국회/정치·정부/사회/인사 일정 정리 기사)"""

SYSTEM_PROMPT = """당신은 국방·법무 분야 일간 뉴스 브리핑의 편집장이다. 대한민국 군 법무 및 법조 종사자가 독자다.

기사 목록(id, 제목, 언론사, 검색 키워드)을 받아 아래 규칙으로 뉴스레터 섹션을 구성하라.

[섹션 정의]
{section_desc}

[규칙]
1. 각 기사를 가장 적합한 섹션 하나에만 배치하거나 탈락시킨다.
2. 같은 사건·발표를 다룬 기사는 제목이 서로 크게 다르더라도(예: 같은 사건의
   다른 측면─"OOO 조사"와 "OOO 피의자 출석"─을 다룬 제목, 인용구 위주 제목,
   요약 방식 차이 등) 반드시 1건만 남긴다. 검색 키워드(keyword)가 서로 달라
   수집된 기사(예: "특검"과 "대통령")라도 같은 인물·사건을 다루면 동일하게
   병합한다. 요약(description)까지 참고해 실제로 같은 사건인지 판단하라.
   남길 기사는 내용이 더 상세하거나 주요 언론사인 쪽을 택한다.
3. 독자와 무관한 기사(연예, 스포츠, 단순 주가·시황, 광고성, 지역 단신 등)는 탈락시킨다.
4. 섹션 내 순서는 중요도(정책적 파급력, 독자 관련성) 순으로 정렬한다.
5. 섹션별 최대 기사 수: {limits}
6. 판결 기사(rulings)는 구체적 판결·결정 내용이 있는 기사만. 기관 동향은 law_judiciary_agencies로.
7. 결과는 섹션 키별 기사 id 배열(JSON)로만 출력한다. 존재하지 않는 id를 만들지 마라."""


def _schema() -> dict:
    props = {
        k: {"type": "array", "items": {"type": "integer"}} for k in SECTION_KEYS
    }
    return {
        "type": "object",
        "properties": props,
        "required": SECTION_KEYS,
        "additionalProperties": False,
    }


def classify(candidates: list[dict], config: dict) -> dict[str, list[dict]]:
    """후보 기사를 섹션별로 배치해 {section_key: [기사]} 반환."""
    limits = config.get("section_limits") or {}
    client = anthropic.Anthropic()

    articles_payload = [
        {
            "id": i,
            "title": a["title"],
            "source": a["source"],
            "keyword": a["keyword"],
            "description": a.get("description", "")[:150],
        }
        for i, a in enumerate(candidates)
    ]

    system = SYSTEM_PROMPT.format(
        section_desc=SECTION_DESC,
        limits=json.dumps(limits, ensure_ascii=False),
    )

    response = client.messages.create(
        model=config.get("model", "claude-haiku-4-5"),
        max_tokens=8000,
        system=system,
        output_config={"format": {"type": "json_schema", "schema": _schema()}},
        messages=[
            {
                "role": "user",
                "content": "기사 목록:\n" + json.dumps(articles_payload, ensure_ascii=False),
            }
        ],
    )

    if response.stop_reason == "refusal":
        raise RuntimeError("분류 요청이 거부되었습니다 (stop_reason=refusal)")

    text = next(b.text for b in response.content if b.type == "text")
    result = json.loads(text)

    log.info(
        "분류 완료 (입력 %d건, 토큰 in=%d out=%d)",
        len(candidates), response.usage.input_tokens, response.usage.output_tokens,
    )

    sections: dict[str, list[dict]] = {}
    used: set[int] = set()
    for key in SECTION_KEYS:
        picked = []
        for i in result.get(key, []):
            if isinstance(i, int) and 0 <= i < len(candidates) and i not in used:
                picked.append(candidates[i])
                used.add(i)
        limit = limits.get(key)
        sections[key] = picked[:limit] if limit else picked
    return sections
