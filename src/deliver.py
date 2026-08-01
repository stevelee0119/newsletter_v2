"""발송 모듈 — 카카오톡 '나에게 보내기'(1순위) + 텔레그램(2순위) + Notion 동기화.

카카오 액세스 토큰은 리프레시 토큰으로 매회 갱신하며, 카카오가 새 리프레시
토큰을 발급하면 GH_PAT가 설정된 경우 GitHub Secret을 자동 갱신한다.

Notion 동기화는 카카오톡 발송과 동시에 실행되는 아카이브 채널로, 카카오·
텔레그램 성공 여부와 무관하게(선택 설정된 경우) 별도로 시도된다.
"""

from __future__ import annotations

import base64
import json
import logging
import os

import requests

log = logging.getLogger(__name__)

KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_MEMO_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
TELEGRAM_CHUNK = 4000
NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
NOTION_BLOCK_LIMIT = 100  # 단일 요청당 최대 자식 블록 수
NOTION_RICH_TEXT_LIMIT = 1900  # Notion rich_text content 최대 2000자 여유분


# ---------------------------------------------------------------- 카카오

def _kakao_refresh_access_token() -> str | None:
    """리프레시 토큰으로 액세스 토큰 발급. 회전된 리프레시 토큰은 Secret에 재저장.

    카카오 앱의 [카카오 로그인 > 보안]에서 Client Secret을 활성화한 경우
    KAKAO_CLIENT_SECRET 환경변수도 함께 설정해야 한다(미설정 시 401 오류).
    """
    rest_key = os.environ.get("KAKAO_REST_API_KEY")
    refresh_token = os.environ.get("KAKAO_REFRESH_TOKEN")
    if not rest_key or not refresh_token:
        return None

    token_data = {
        "grant_type": "refresh_token",
        "client_id": rest_key,
        "refresh_token": refresh_token,
    }
    client_secret = os.environ.get("KAKAO_CLIENT_SECRET")
    if client_secret:
        token_data["client_secret"] = client_secret

    resp = requests.post(KAKAO_TOKEN_URL, data=token_data, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    new_refresh = data.get("refresh_token")
    if new_refresh and new_refresh != refresh_token:
        log.info("카카오 리프레시 토큰이 회전되었습니다. Secret 갱신 시도.")
        if not update_github_secret("KAKAO_REFRESH_TOKEN", new_refresh):
            log.warning(
                "GH_PAT 미설정/실패 — KAKAO_REFRESH_TOKEN Secret을 수동으로 갱신하세요: %s...",
                new_refresh[:8],
            )
    return data["access_token"]


def send_kakao(summary: str, link_url: str) -> bool:
    """카카오톡 '나에게 보내기' — 요약 + 전체보기 링크."""
    try:
        access_token = _kakao_refresh_access_token()
        if not access_token:
            log.info("카카오 설정 없음 — 건너뜀")
            return False
        template = {
            "object_type": "text",
            "text": summary[:200],
            "link": {"web_url": link_url, "mobile_web_url": link_url},
            "button_title": "전체 보기",
        }
        resp = requests.post(
            KAKAO_MEMO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            data={"template_object": json.dumps(template, ensure_ascii=False)},
            timeout=20,
        )
        resp.raise_for_status()
        log.info("카카오톡 발송 완료")
        return True
    except Exception as e:
        log.error("카카오톡 발송 실패: %s", e)
        return False


# ---------------------------------------------------------------- 텔레그램

def send_telegram(full_text: str) -> bool:
    """텔레그램 봇으로 전문 발송 (4,000자 단위 분할)."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        log.info("텔레그램 설정 없음 — 건너뜀")
        return False

    chunks = _split_text(full_text, TELEGRAM_CHUNK)
    try:
        for chunk in chunks:
            resp = requests.post(
                TELEGRAM_API.format(token=token, method="sendMessage"),
                json={
                    "chat_id": chat_id,
                    "text": chunk,
                    "disable_web_page_preview": True,
                },
                timeout=20,
            )
            resp.raise_for_status()
        log.info("텔레그램 발송 완료 (%d개 메시지)", len(chunks))
        return True
    except Exception as e:
        log.error("텔레그램 발송 실패: %s", e)
        return False


def _split_text(text: str, limit: int) -> list[str]:
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    return chunks


# ---------------------------------------------------------------- Notion

def _notion_headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ['NOTION_API_KEY']}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _notion_title_property(database_id: str, headers: dict) -> str:
    """데이터베이스 스키마에서 title 타입 속성명을 찾는다 (한/영 사용자 DB 모두 대응)."""
    resp = requests.get(f"{NOTION_API_BASE}/databases/{database_id}", headers=headers, timeout=20)
    resp.raise_for_status()
    for name, prop in resp.json()["properties"].items():
        if prop.get("type") == "title":
            return name
    raise RuntimeError("Notion 데이터베이스에 title 속성이 없습니다")


def _paragraph_block(text: str) -> dict:
    rich_text = [{"type": "text", "text": {"content": text}}] if text else []
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text}}


def _text_to_blocks(text: str) -> list[dict]:
    """전문을 줄 단위 문단 블록으로 변환 (Notion rich_text 2000자 제한 대응)."""
    blocks = []
    for line in text.split("\n"):
        remaining = line
        while len(remaining) > NOTION_RICH_TEXT_LIMIT:
            blocks.append(_paragraph_block(remaining[:NOTION_RICH_TEXT_LIMIT]))
            remaining = remaining[NOTION_RICH_TEXT_LIMIT:]
        blocks.append(_paragraph_block(remaining))
    return blocks


def send_notion(full_text: str, title: str) -> bool:
    """Notion 데이터베이스에 뉴스레터 페이지를 생성 (카카오톡과 동시 실행되는 아카이브)."""
    if not os.environ.get("NOTION_API_KEY") or not os.environ.get("NOTION_DATABASE_ID"):
        log.info("Notion 설정 없음 — 건너뜀")
        return False
    try:
        database_id = os.environ["NOTION_DATABASE_ID"]
        headers = _notion_headers()
        title_prop = _notion_title_property(database_id, headers)
        blocks = _text_to_blocks(full_text)

        create_resp = requests.post(
            f"{NOTION_API_BASE}/pages",
            headers=headers,
            json={
                "parent": {"database_id": database_id},
                "properties": {
                    title_prop: {"title": [{"type": "text", "text": {"content": title}}]}
                },
                "children": blocks[:NOTION_BLOCK_LIMIT],
            },
            timeout=30,
        )
        create_resp.raise_for_status()
        page_id = create_resp.json()["id"]

        for i in range(NOTION_BLOCK_LIMIT, len(blocks), NOTION_BLOCK_LIMIT):
            batch = blocks[i : i + NOTION_BLOCK_LIMIT]
            append_resp = requests.patch(
                f"{NOTION_API_BASE}/blocks/{page_id}/children",
                headers=headers,
                json={"children": batch},
                timeout=30,
            )
            append_resp.raise_for_status()

        log.info("Notion 동기화 완료 (%d개 블록)", len(blocks))
        return True
    except Exception as e:
        log.error("Notion 동기화 실패: %s", e)
        return False


# ---------------------------------------------------------------- 발송 오케스트레이션

def deliver(summary: str, full_text: str, link_url: str, title: str) -> bool:
    """카카오톡·Notion을 동시 시도하고, DELIVERY_MODE에 따라 텔레그램을 발송한다.

    성공 여부는 실제 수신 채널인 카카오톡·텔레그램 기준으로 판단한다.
    Notion은 아카이브 동기화이므로 실패해도 워크플로 전체를 실패시키지 않는다.
    """
    mode = os.environ.get("DELIVERY_MODE", "all").lower()
    kakao_ok = send_kakao(summary, link_url)
    send_notion(full_text, title)
    if mode == "fallback" and kakao_ok:
        return True
    telegram_ok = send_telegram(full_text)
    return kakao_ok or telegram_ok


# ---------------------------------------------------------------- GitHub Secret 갱신

def update_github_secret(name: str, value: str) -> bool:
    """GH_PAT로 저장소 Actions Secret을 갱신 (libsodium sealed box)."""
    pat = os.environ.get("GH_PAT")
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not pat or not repo:
        return False
    try:
        from nacl import encoding, public

        headers = {
            "Authorization": f"Bearer {pat}",
            "Accept": "application/vnd.github+json",
        }
        key_resp = requests.get(
            f"https://api.github.com/repos/{repo}/actions/secrets/public-key",
            headers=headers,
            timeout=20,
        )
        key_resp.raise_for_status()
        key_data = key_resp.json()

        pub_key = public.PublicKey(key_data["key"].encode(), encoding.Base64Encoder())
        sealed = public.SealedBox(pub_key).encrypt(value.encode())
        encrypted_value = base64.b64encode(sealed).decode()

        put_resp = requests.put(
            f"https://api.github.com/repos/{repo}/actions/secrets/{name}",
            headers=headers,
            json={"encrypted_value": encrypted_value, "key_id": key_data["key_id"]},
            timeout=20,
        )
        put_resp.raise_for_status()
        log.info("GitHub Secret %s 갱신 완료", name)
        return True
    except Exception as e:
        log.error("GitHub Secret 갱신 실패: %s", e)
        return False
