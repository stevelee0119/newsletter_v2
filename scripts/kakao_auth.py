"""카카오 '나에게 보내기' 최초 토큰 발급 도우미 (로컬 PC에서 1회 실행).

사전 준비 (developers.kakao.com):
  1. 애플리케이션 생성 -> 앱 키에서 "REST API 키" 확인
  2. [제품 설정 > 카카오 로그인] 활성화, Redirect URI에 https://localhost:3000 등록
  3. [제품 설정 > 카카오 로그인 > 동의항목] "카카오톡 메시지 전송(talk_message)" 활성화

실행:
  python scripts/kakao_auth.py
"""

import urllib.parse

import requests

AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
REDIRECT_URI = "https://localhost:3000"


def main() -> None:
    rest_key = input("REST API 키: ").strip()

    params = urllib.parse.urlencode(
        {
            "client_id": rest_key,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": "talk_message",
        }
    )
    print("\n1) 아래 URL을 브라우저에서 열고 로그인·동의하세요:")
    print(f"\n   {AUTH_URL}?{params}\n")
    print("2) 이동된 주소창의 URL에서 code= 뒤의 값을 복사하세요.")
    print(f"   (예: {REDIRECT_URI}/?code=XXXX -> XXXX 부분. 페이지가 안 열려도 주소창에 code는 표시됩니다)\n")

    code = input("인가 코드: ").strip()

    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": rest_key,
            "redirect_uri": REDIRECT_URI,
            "code": code,
        },
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()

    print("\n=== 발급 완료 — GitHub Secrets에 등록하세요 ===")
    print(f"KAKAO_REST_API_KEY  = {rest_key}")
    print(f"KAKAO_REFRESH_TOKEN = {data['refresh_token']}")
    print("\n(access_token은 저장할 필요 없습니다 — 매 실행 시 자동 발급됩니다)")


if __name__ == "__main__":
    main()
