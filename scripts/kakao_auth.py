"""카카오 '나에게 보내기' 최초 토큰 발급 도우미 (로컬 PC에서 1회 실행).

사전 준비 (developers.kakao.com):
  1. 애플리케이션 생성 -> 앱 키에서 "REST API 키" 확인
  2. [제품 설정 > 카카오 로그인] 활성화, Redirect URI에 https://localhost:3000 등록
  3. [제품 설정 > 카카오 로그인 > 동의항목] "카카오톡 메시지 전송(talk_message)" 활성화
  4. [제품 설정 > 카카오 로그인 > 보안] Client Secret이 "사용함"으로 되어 있다면
     같은 화면에서 Client Secret 코드를 발급받아 아래 실행 시 함께 입력하세요.
     ("사용 안함"이면 비워두고 Enter)

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
    client_secret = input("Client Secret (미사용 시 Enter): ").strip()

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
    print("   ※ 인가 코드는 1회용이며 유효시간이 짧습니다 — 복사 후 바로 아래에 붙여넣으세요.\n")

    code = input("인가 코드: ").strip()

    token_data = {
        "grant_type": "authorization_code",
        "client_id": rest_key,
        "redirect_uri": REDIRECT_URI,
        "code": code,
    }
    if client_secret:
        token_data["client_secret"] = client_secret

    resp = requests.post(TOKEN_URL, data=token_data, timeout=20)
    if not resp.ok:
        print(f"\n[오류] 토큰 발급 실패 (HTTP {resp.status_code}): {resp.text}")
        print("\n주로 아래 원인 중 하나입니다:")
        print("- 인가 코드가 만료/재사용됨 -> 1)번 URL을 새로 열어 처음부터 다시 진행")
        print("- Client Secret이 '사용함'인데 위에서 입력하지 않음 (또는 그 반대)")
        print("- REST API 키가 이 앱의 키가 아님")
        resp.raise_for_status()
    data = resp.json()

    print("\n=== 발급 완료 — GitHub Secrets에 등록하세요 ===")
    print(f"KAKAO_REST_API_KEY  = {rest_key}")
    print(f"KAKAO_REFRESH_TOKEN = {data['refresh_token']}")
    if client_secret:
        print(f"KAKAO_CLIENT_SECRET = {client_secret}")
    print("\n(access_token은 저장할 필요 없습니다 — 매 실행 시 자동 발급됩니다)")


if __name__ == "__main__":
    main()
