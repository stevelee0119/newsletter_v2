# 설치 가이드 (최초 1회 설정)

이 문서의 설정을 마치면 매일 06:30 이전에 카카오톡·텔레그램으로 뉴스레터가 자동 발송됩니다.
설정 후에는 **PC를 켜둘 필요가 없습니다** (GitHub Actions가 클라우드에서 실행).

## 0. 준비물

- 이 GitHub 저장소 (가능하면 **Public** 권장 — Actions 무료 무제한. Private이면 무료 2,000분/월 한도)
- Anthropic API 키 (https://platform.claude.com)
- 카카오 계정 / 텔레그램 계정

---

## 1. Anthropic API 키

1. https://platform.claude.com → API Keys → 키 생성
2. 저장소 → Settings → Secrets and variables → Actions → **New repository secret**
   - Name: `ANTHROPIC_API_KEY`, Value: 발급받은 키

---

## 2. 카카오톡 "나에게 보내기" 설정

1. https://developers.kakao.com → 내 애플리케이션 → **애플리케이션 추가**
2. 생성한 앱 → [앱 키] 에서 **REST API 키** 복사
3. [제품 설정 → 카카오 로그인] **활성화**, Redirect URI에 `https://localhost:3000` 등록
4. [제품 설정 → 카카오 로그인 → 동의항목] → **카카오톡 메시지 전송(talk_message)** → "이용 중 동의"로 설정
5. 로컬 PC에서 토큰 발급 (1회):
   ```bash
   pip install requests
   python scripts/kakao_auth.py
   ```
   안내에 따라 브라우저 로그인 → 인가 코드 입력 → 출력된 값을 Secrets에 등록:
   - `KAKAO_REST_API_KEY`
   - `KAKAO_REFRESH_TOKEN`

> 리프레시 토큰은 유효기간 2개월이며, 프로그램이 매 실행 시 자동 갱신합니다.
> 갱신된 토큰을 Secret에 자동 재저장하려면 아래 3번(GH_PAT)을 함께 설정하세요.
> 미설정 시 토큰 회전 시점에 텔레그램/로그로 수동 갱신 안내가 표시됩니다.

## 3. GH_PAT (카카오 토큰 자동 갱신용, 권장)

1. GitHub → Settings → Developer settings → **Fine-grained personal access token** 생성
   - Repository access: 이 저장소만
   - Permissions: **Secrets → Read and write**
2. Secret 등록: `GH_PAT`

---

## 4. 텔레그램 봇 설정

1. 텔레그램에서 **@BotFather** 검색 → `/newbot` → 봇 이름/아이디 지정 → **봇 토큰** 복사
2. 만든 봇에게 아무 메시지나 1개 전송 (대화 시작)
3. 브라우저에서 `https://api.telegram.org/bot<봇토큰>/getUpdates` 접속
   → `"chat":{"id": 123456789, ...}` 의 숫자가 **chat_id**
4. Secrets 등록:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`

---

## 5. 동작 확인

1. 저장소 → **Actions** 탭 → `daily-newsletter` → **Run workflow** (수동 실행)
2. 실행 로그에서 수집→분류→발송 확인, 카카오톡/텔레그램 수신 확인
3. `newsletters/` 폴더에 당일 아카이브가 커밋되었는지 확인

> 수동 실행 시에도 06:28 KST 이전이면 그 시각까지 대기 후 발송합니다.
> 즉시 발송을 테스트하려면 워크플로의 `TARGET_SEND_TIME`을 지난 시각으로 잠시 바꾸거나,
> 06:28 이후에 실행하세요.

---

## 6. 운영 스케줄

| 시각 (KST) | 동작 |
|---|---|
| 05:40 | 본 실행 시작 (Actions 지연 흡수 버퍼) |
| ~05:45–06:15 | 수집·중복제거·분류·조판, 아카이브 커밋 |
| 06:28 | 발송 (카카오 요약+링크, 텔레그램 전문) |
| 06:45 | 백업 실행 — 이미 발송됐으면 즉시 종료, 아니면 생성 후 즉시 발송 |

## 7. 설정 변경

- **키워드/섹션 분량/언론사 순위**: `config.yaml`
- **발송 시각**: `.github/workflows/newsletter.yml`의 cron 및 `TARGET_SEND_TIME`
- **발송 모드**: 같은 파일의 `DELIVERY_MODE` (`all`=둘 다 / `fallback`=카카오 실패 시만 텔레그램)
- **모델**: `config.yaml`의 `model` (기본 `claude-haiku-4-5`, 품질 우선 시 `claude-sonnet-5`)

## 8. 로컬 테스트

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...   # 선택
python -m src.main run
```
