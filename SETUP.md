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
5. [제품 설정 → 카카오 로그인 → 보안] **Client Secret** 상태 확인
   - "사용함(활성화)"으로 되어 있다면 **코드 생성**을 눌러 Client Secret 값을 발급받아 메모해두세요 (다음 단계에서 입력).
   - "사용 안함"이면 이 단계는 건너뛰어도 됩니다.
6. 로컬 PC에서 토큰 발급 (1회):
   ```bash
   pip install requests
   python scripts/kakao_auth.py
   ```
   REST API 키 입력 → Client Secret 입력(5번에서 활성화한 경우만, 아니면 Enter) → 안내에 따라 브라우저 로그인 → 인가 코드 입력 → 출력된 값을 Secrets에 등록:
   - `KAKAO_REST_API_KEY`
   - `KAKAO_REFRESH_TOKEN`
   - `KAKAO_CLIENT_SECRET` (5번에서 활성화한 경우만)

> 리프레시 토큰은 유효기간 2개월이며, 프로그램이 매 실행 시 자동 갱신합니다.
> 갱신된 토큰을 Secret에 자동 재저장하려면 아래 3번(GH_PAT)을 함께 설정하세요.
> 미설정 시 토큰 회전 시점에 텔레그램/로그로 수동 갱신 안내가 표시됩니다.
>
> **토큰 발급 시 `401 Client Error`가 발생한다면** 5번의 Client Secret 설정을 놓친 경우가 가장
> 흔한 원인입니다. 보안 탭에서 상태를 다시 확인하고, 인가 코드는 1회용이므로 URL을 새로 열어
> 처음부터 다시 진행하세요.

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

## 5. Notion 동기화 설정 (선택, 카카오톡과 동시 발송)

1. https://www.notion.so/my-integrations → **New integration** 생성
   - Associated workspace: 뉴스레터를 저장할 워크스페이스 선택
   - Capabilities: **Insert content** 활성화 확인
   - 생성 후 표시되는 **Internal Integration Secret** 복사 (`ntn_...` 또는 `secret_...`)
2. Notion에서 뉴스레터를 쌓을 **데이터베이스**를 새로 만들거나 기존 것을 사용
3. 해당 데이터베이스 페이지 우측 상단 **···** → **연결(Connections)** → 1번에서 만든 인테그레이션 추가 (이 단계를 빠뜨리면 API가 403을 반환합니다)
4. 데이터베이스 URL에서 ID 추출: `https://www.notion.so/워크스페이스/<32자리ID>?v=...` 의 32자리 문자열이 **database_id**
5. Secrets 등록:
   - `NOTION_API_KEY`
   - `NOTION_DATABASE_ID`

> 데이터베이스에 제목(title) 속성만 있으면 되고, 그 외 속성(태그, 날짜 등)은 자유롭게 추가해도 됩니다 — 프로그램은 title 속성만 채웁니다.

---

## 5-1. Gemini API 키 설정 (선택, 2단계 콘텐츠 중복·과거 기사 필터)

미설정 시 이 단계만 자동으로 건너뛰고 나머지(수집·1차 중복제거·Claude 분류·발송)는 그대로 정상 작동합니다.

1. https://aistudio.google.com/apikey 접속 → Google 계정으로 로그인
2. **"Create API key"** → **"Create API key in new project"** 선택(기존 프로젝트를 선택하면 무료 할당량이 `0`으로 나올 수 있습니다)
3. 생성된 키(`AIza...`로 시작) 복사
4. Secrets 등록: `GEMINI_API_KEY`

> **재실행해도 429(RESOURCE_EXHAUSTED, quota_limit_value: 0) 오류가 계속 난다면**: 새 프로젝트로도
> 해결되지 않는 계정 차원의 문제일 수 있습니다. 아래를 확인하세요.
> - [console.cloud.google.com/billing](https://console.cloud.google.com/billing)에서 해당 프로젝트에
>   **결제 계정이 연결되어 있는지** 확인 (무료 한도 내 사용은 과금되지 않습니다 — 최근 정책상 결제
>   계정 연결 자체가 무료 할당량 부여 조건인 경우가 있습니다)
> - **Google Workspace(회사/조직) 계정**이라면 관리자가 Generative Language API 사용을 막아뒀을 수
>   있습니다 — 이 경우 개인 Gmail 계정으로 새로 키를 발급하세요

## 6. 동작 확인

1. 저장소 → **Actions** 탭 → `daily-newsletter` → **Run workflow** (수동 실행)
2. 실행 로그에서 수집→분류→발송 확인, 카카오톡/텔레그램 수신 확인
3. `newsletters/` 폴더에 당일 아카이브가 커밋되었는지 확인

> 수동 실행 시에도 06:28 KST 이전이면 그 시각까지 대기 후 발송합니다.
> 즉시 발송을 테스트하려면 워크플로의 `TARGET_SEND_TIME`을 지난 시각으로 잠시 바꾸거나,
> 06:28 이후에 실행하세요.

---

## 7. 운영 스케줄

| 시각 (KST) | 동작 |
|---|---|
| 05:27 | 본 실행 시작 (Actions 지연 흡수 버퍼) |
| ~05:45–06:15 | 수집(24시간 이내 기사만)·중복제거·분류·조판, 아카이브 커밋 |
| 06:28 | 발송 (카카오 요약+링크와 Notion 동기화 동시 실행, 텔레그램 전문) |
| 06:45 | 백업 실행 — 이미 발송됐으면 즉시 종료, 아니면 생성 후 즉시 발송 |

## 8. 설정 변경

- **키워드/섹션 분량/언론사 순위**: `config.yaml`
- **수집 시효**: `config.yaml`의 `lookback_hours` (기본 24)
- **발송 시각**: `.github/workflows/newsletter.yml`의 cron 및 `TARGET_SEND_TIME`
- **발송 모드**: 같은 파일의 `DELIVERY_MODE` (`all`=카카오+Notion+텔레그램 / `fallback`=카카오 실패 시만 텔레그램, Notion은 항상 동시 시도)
- **모델**: `config.yaml`의 `model` (기본 `claude-sonnet-5`, 비용 우선 시 `claude-haiku-4-5`), Gemini 2단계 모델은 `gemini_model`
- **중복 판단 민감도**: `config.yaml`의 `dedupe_threshold` / `dedupe_overlap_threshold` / `dedupe_distinctive_idf`

## 9. 로컬 테스트

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=...
export GEMINI_API_KEY=...                                 # 선택 (2단계 콘텐츠 필터)
export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...        # 선택
export NOTION_API_KEY=... NOTION_DATABASE_ID=...          # 선택
python -m src.main run
```
