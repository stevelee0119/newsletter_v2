"""뉴스레터 조판 — 과거 작성 사례 포맷 재현."""

from __future__ import annotations

from datetime import datetime

WEEKDAYS_KO = ["월", "화", "수", "목", "금", "토", "일"]


def _header_date(now: datetime) -> str:
    # 예: '26. 7. 31.(금)
    return f"'{now.year % 100}. {now.month}. {now.day}.({WEEKDAYS_KO[now.weekday()]})"


def _bullets(articles: list[dict]) -> list[str]:
    lines = []
    for a in articles:
        source = f"({a['source']})" if a.get("source") else ""
        lines.append(f"• {a['title']}{source}")
        lines.append(a["link"])
    return lines


def _subsection(label: str, articles: list[dict]) -> list[str]:
    if not articles:
        return []
    return [f"[{label}]", *_bullets(articles), ""]


def format_newsletter(sections: dict[str, list[dict]], config: dict, now: datetime) -> str:
    """발송용 플레인 텍스트 뉴스레터 생성."""
    out: list[str] = []
    out.append(f"🗞️ [{_header_date(now)} 국방·법무 주요 뉴스 브리핑] 🗞️")
    out.append("")

    # 1️⃣ 특검
    out.append("1️⃣ 5대 특검 분야")
    out.append("")
    if sections.get("special_counsel"):
        out.extend(_bullets(sections["special_counsel"]))
    else:
        out.append("• (해당 기사 없음)")
    out.append("")
    out.append("")

    # 2️⃣ 국방·군 법무 동향
    out.append("2️⃣ 국방·군 법무 동향")
    out.append("")
    out.extend(_subsection("국방 일반", sections.get("defense_general", [])))
    out.extend(_subsection("북한·한미동맹", sections.get("defense_nk_alliance", [])))
    out.extend(_subsection("방산·미래전 등", sections.get("defense_industry", [])))
    out.extend(_subsection("국제·국제법 등", sections.get("defense_intl_law", [])))
    out.append("")

    # 3️⃣ 법조·공직·수사기관 동향
    out.append("3️⃣ 법조·공직·수사기관 동향")
    out.append("")
    out.extend(_subsection("국회·정부", sections.get("law_assembly_gov", [])))
    out.extend(_subsection("법조일반", sections.get("law_general", [])))
    out.extend(_subsection("사법·수사기관", sections.get("law_judiciary_agencies", [])))
    out.append("")

    # 4️⃣ 판결
    out.append("4️⃣ 🧑‍⚖️ 오늘의 주요 판결")
    out.append("")
    if sections.get("rulings"):
        out.extend(_bullets(sections["rulings"]))
    else:
        out.append("• (해당 기사 없음)")
    out.append("")
    out.append("")

    # 5️⃣ 일정
    out.append("5️⃣ 🗓️ 오늘의 주요 일정 종합")
    out.append("")
    for a in sections.get("schedules", []):
        source = f"({a['source']})" if a.get("source") else ""
        out.append(f"• {a['title']}{source} : {a['link']}")
    for fixed in config.get("fixed_links") or []:
        out.append(f"• {fixed['label']} : {fixed['url']}")
    out.append("//끝//")

    # 연속 빈 줄 정리 (최대 2줄)
    text_lines: list[str] = []
    blank = 0
    for line in out:
        blank = blank + 1 if line == "" else 0
        if blank <= 2:
            text_lines.append(line)
    return "\n".join(text_lines).strip() + "\n"


def format_summary(
    now: datetime, daily_summary: str, link_url: str, max_len: int = 200
) -> str:
    """카카오톡 텍스트 템플릿(200자 제한)용 요약.

    링크는 버튼 렌더링 여부와 무관하게 항상 보이도록 본문 텍스트에도 그대로
    노출한다(카카오톡은 텍스트 안의 URL을 자동으로 하이퍼링크 처리한다).
    링크 줄은 절대 잘리지 않도록 예산을 먼저 확보하고, 남는 길이만큼만
    daily_summary를 채운다.
    """
    head = f"🗞️ {_header_date(now)} 국방·법무 브리핑"
    link_line = f"▶ 전체 보기: {link_url}" if link_url else ""

    reserved = len(head) + len(link_line) + (2 if link_line else 1)
    remaining = max_len - reserved
    summary = daily_summary.strip()
    if remaining > 0 and summary:
        if len(summary) > remaining:
            summary = summary[: max(remaining - 1, 0)].rstrip() + "…"
    else:
        summary = ""

    parts = [head]
    if summary:
        parts.append(summary)
    if link_line:
        parts.append(link_line)
    return "\n".join(parts)
