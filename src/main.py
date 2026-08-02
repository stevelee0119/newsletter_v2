"""오케스트레이션 진입점.

사용법:
    python -m src.main generate   # 수집 -> 중복제거 -> 분류 -> 조판, 파일 산출
    python -m src.main send       # 목표 시각(기본 06:28 KST)까지 대기 후 발송
    python -m src.main run        # generate + send (로컬 테스트용)

generate 산출물:
    newsletters/YYYY-MM-DD.md  — 저장소 커밋 대상(카카오 링크)
    out/newsletter.txt         — 발송용 전문
    out/summary.txt            — 카카오용 요약
당일 newsletters 파일이 이미 존재하면(이미 발송됨) 아무것도 생성하지 않고,
send는 out/ 산출물이 없으면 no-op으로 종료한다(백업 크론 중복 발송 방지).
"""

from __future__ import annotations

import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from .classify import classify
from .collect import collect_all, filter_resolved_freshness, resolve_links
from .dedupe import dedupe, gemini_content_dedupe
from .deliver import deliver
from .format_newsletter import format_newsletter, format_summary

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")

KST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "out"
ARCHIVE_DIR = ROOT / "newsletters"


def _load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _archive_path(now: datetime) -> Path:
    return ARCHIVE_DIR / f"{now.strftime('%Y-%m-%d')}.md"


def _link_url(now: datetime) -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if repo:
        return f"https://github.com/{repo}/blob/main/newsletters/{now.strftime('%Y-%m-%d')}.md"
    return "https://github.com"


def generate() -> bool:
    """뉴스레터 생성. 이미 당일분이 있으면 False(스킵)."""
    now = datetime.now(KST)
    archive = _archive_path(now)
    if archive.exists():
        log.info("당일 뉴스레터가 이미 존재합니다 (%s) — 생성 스킵", archive.name)
        return False

    config = _load_config()

    articles = collect_all(config)
    if not articles:
        raise RuntimeError("수집된 기사가 없습니다 — RSS 접근을 확인하세요")

    candidates = dedupe(articles, config)
    log.info("원문 링크 복원 및 본문 수집 중 (%d건)", len(candidates))
    resolve_links(candidates)
    candidates = gemini_content_dedupe(candidates, config)
    sections, daily_summary = classify(candidates, config)

    selected = [a for arts in sections.values() for a in arts]
    log.info("최종 선정: %d건", len(selected))

    lookback_hours = config.get("lookback_hours", 24)
    total_before = sum(len(arts) for arts in sections.values())
    for key, arts in sections.items():
        sections[key] = filter_resolved_freshness(arts, lookback_hours)
    total_after = sum(len(arts) for arts in sections.values())
    if total_after != total_before:
        log.info("발행일 재검증으로 %d건 제외 (%d -> %d)", total_before - total_after, total_before, total_after)

    full_text = format_newsletter(sections, config, now)
    summary = format_summary(now, daily_summary, _link_url(now))

    OUT_DIR.mkdir(exist_ok=True)
    ARCHIVE_DIR.mkdir(exist_ok=True)
    (OUT_DIR / "newsletter.txt").write_text(full_text, encoding="utf-8")
    (OUT_DIR / "summary.txt").write_text(summary, encoding="utf-8")
    archive.write_text(full_text, encoding="utf-8")
    log.info("생성 완료: %s (%d자)", archive.name, len(full_text))
    return True


def _wait_until_target() -> None:
    """TARGET_SEND_TIME(KST, 기본 06:28)까지 대기. 이미 지났으면 즉시 반환."""
    target_str = os.environ.get("TARGET_SEND_TIME", "06:28")
    max_wait_min = int(os.environ.get("MAX_WAIT_MIN", "55"))
    hh, mm = map(int, target_str.split(":"))

    now = datetime.now(KST)
    target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    wait_sec = (target - now).total_seconds()
    if wait_sec <= 0:
        log.info("목표 시각(%s KST) 경과 — 즉시 발송", target_str)
        return
    wait_sec = min(wait_sec, max_wait_min * 60)
    log.info("발송 대기: %.0f초 (목표 %s KST)", wait_sec, target_str)
    time.sleep(wait_sec)


def send() -> None:
    full_path = OUT_DIR / "newsletter.txt"
    summary_path = OUT_DIR / "summary.txt"
    if not full_path.exists():
        log.info("발송할 산출물이 없습니다 — 스킵 (이미 발송되었거나 생성 실패)")
        return

    now = datetime.now(KST)
    link_url = _link_url(now)
    title = f"{now.strftime('%Y-%m-%d')} 국방·법무 주요 뉴스 브리핑"

    _wait_until_target()

    ok = deliver(
        summary=summary_path.read_text(encoding="utf-8"),
        full_text=full_path.read_text(encoding="utf-8"),
        link_url=link_url,
        title=title,
    )
    if not ok:
        raise RuntimeError("모든 발송 채널이 실패했습니다")
    log.info("발송 완료")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "generate":
        generate()
    elif cmd == "send":
        send()
    elif cmd == "run":
        if generate():
            send()
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
