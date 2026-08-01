# newsletter_v2 — 국방·법무 뉴스레터 자동 발송 시스템

국방·군 법무 및 법조 분야 종사자를 위한 **일간 뉴스 브리핑을 완전 자동으로 생성·발송**하는 프로그램입니다.

매일 **06:30 이전에** 카카오톡(요약+링크)·텔레그램(전문)으로 뉴스레터를 발송하고, 카카오톡 발송과 **동시에 Notion에도 아카이브를 동기화**합니다. GitHub Actions에서 클라우드로 자동 실행되므로 **로컬 PC를 켜둘 필요가 없고, 인프라 비용도 들지 않습니다.**

## 주요 기능

- **자동 뉴스 수집**: Google News RSS(한국판)에서 지정 키워드 52개로 검색, **발송 시각 기준 24시간 이내 작성된 국내 언론 기사만** 수집
- **2단계 중복 제거**: 로컬 유사도 클러스터링(무료) → Claude API 1회 호출로 의미 기반 중복까지 최종 제거, 토큰·시간 낭비 방지
- **자동 분류·조판**: Claude API가 기사를 5개 섹션(특검 / 국방·군 법무 / 법조·공직·수사기관 / 판결 / 일정)으로 배치하고 중요도순 정렬, 과거 작성 사례와 동일한 포맷으로 조판
- **3중 발송**: 카카오톡 "나에게 보내기"(1순위) + Notion 아카이브 동기화(동시) + 텔레그램 전문(2순위)
- **06:30 수신 보장 설계**: GitHub Actions cron 지연을 흡수하기 위해 05:40에 조기 시작해 미리 생성해두고 06:28에 발송, 06:45 백업 실행으로 이중화
- **무인 운영**: 카카오 액세스 토큰은 매 실행 자동 갱신, 리프레시 토큰 회전 시 GitHub Secret도 자동 재저장

## 동작 방식

```
05:40 KST  GitHub Actions 실행
  → 1. collect  : Google News RSS × 52 키워드 병렬 수집 (24시간 이내 작성분만, 국내 언론)
  → 2. dedupe   : URL/제목 유사도 클러스터링(rapidfuzz) → 후보 ≤185건
  → 3. classify : Claude API 1회 호출 (섹션 분류 + 의미 중복 제거 + 중요도 정렬)
  → 4. format   : 과거 사례 포맷으로 조판 → newsletters/YYYY-MM-DD.md 커밋
06:28 KST  → 5. deliver  : 카카오톡 발송 + Notion 동기화(동시) + 텔레그램 발송
06:45 KST  백업 실행 (본 실행이 실패한 경우에만 생성 후 즉시 발송)
```

## 뉴스레터 구성

1. 5대 특검 분야
2. 국방·군 법무 동향 — [국방 일반] [북한·한미동맹] [방산·미래전 등] [국제·국제법 등]
3. 법조·공직·수사기관 동향 — [국회·정부] [법조일반] [사법·수사기관]
4. 🧑‍⚖️ 오늘의 주요 판결
5. 🗓️ 오늘의 주요 일정 종합

## 프로젝트 구조

```
newsletter_v2/
├── config.yaml                    # 키워드·섹션 분량·언론사 순위 등 전체 설정
├── requirements.txt                # Python 의존성
├── src/
│   ├── collect.py                  # Google News RSS 수집 (키워드별 병렬, 24시간 필터)
│   ├── dedupe.py                   # 1차 로컬 중복 제거 (URL 정규화 + 유사도 클러스터링)
│   ├── classify.py                 # Claude API 분류 (섹션 배치 + 의미 중복 제거 + 정렬)
│   ├── format_newsletter.py        # 뉴스레터 조판 (전문 + 카카오용 요약)
│   ├── deliver.py                  # 카카오톡·텔레그램·Notion 발송, GitHub Secret 자동 갱신
│   └── main.py                     # 오케스트레이션 (generate / send / run)
├── scripts/
│   └── kakao_auth.py               # 카카오 최초 토큰 발급 도우미 (로컬 1회 실행)
├── newsletters/                    # 발송된 뉴스레터 아카이브 (자동 커밋됨)
└── .github/workflows/
    └── newsletter.yml              # 스케줄러 (본 실행 + 백업 실행)
```

## 빠른 시작

```bash
git clone https://github.com/stevelee0119/newsletter_v2.git
cd newsletter_v2
pip install -r requirements.txt
```

자동 발송을 위해서는 GitHub Secrets 등록 등 최초 설정이 필요합니다 — **[SETUP.md](SETUP.md)** 를 순서대로 따라 하시면 됩니다 (Anthropic API 키 → 카카오 앱 생성 및 토큰 발급 → 텔레그램 봇 생성 → Notion 인테그레이션 연결).

로컬에서 1회 실행해 결과를 확인하려면:

```bash
export ANTHROPIC_API_KEY=...
export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=...   # 선택
python -m src.main run
```

## 설정 변경

모든 설정은 [`config.yaml`](config.yaml)에서 관리합니다.

| 항목 | 설명 |
|---|---|
| `model` | 분류에 사용할 Claude 모델 (기본 `claude-haiku-4-5`) |
| `lookback_hours` | 수집 시효 — 발송 시각 기준 몇 시간 이내 기사만 포함 (기본 24) |
| `keywords` | 카테고리별 검색 키워드 목록 |
| `candidate_limits` | 1차 중복 제거 후 LLM에 넘길 카테고리별 후보 상한 |
| `dedupe_threshold` | 제목 유사도 클러스터링 임계값 (0~100) |
| `section_limits` | 뉴스레터 섹션별 최대 기사 수 |
| `media_rank` | 언론사 우선순위 (중복 기사 대표 선정 기준) |
| `source_blocklist` | 수집에서 제외할 언론사 |
| `fixed_links` | 뉴스레터 말미에 고정으로 붙는 링크 |

발송 시각·발송 채널은 [`.github/workflows/newsletter.yml`](.github/workflows/newsletter.yml)의 cron 및 `TARGET_SEND_TIME`, `DELIVERY_MODE` 환경변수로 조정합니다.

## 발송 채널

| 채널 | 우선순위 | 내용 | 필요 Secrets |
|---|---|---|---|
| 카카오톡 | 1순위 | 헤드라인 요약 + "전체 보기" 링크 (텍스트 템플릿 200자 제한) | `KAKAO_REST_API_KEY`, `KAKAO_REFRESH_TOKEN`, (필요 시) `KAKAO_CLIENT_SECRET` |
| Notion | 카카오톡과 동시 | 전문 아카이브 페이지 생성 | `NOTION_API_KEY`, `NOTION_DATABASE_ID` |
| 텔레그램 | 2순위 | 전문 (4,000자 단위 분할) | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |

## 비용

- **인프라**: GitHub Actions — 공개 저장소는 무료 무제한, 비공개 저장소는 월 2,000분 무료
- **Claude API**: 실행당 Haiku 모델 기준 약 10~50원 수준 (기사 본문은 전송하지 않고 제목·언론사만 사용해 토큰 상한 고정)

## 문서

- **[PRD.md](PRD.md)** — 제품 요구사항 문서 (설계 근거, 아키텍처, 제약사항)
- **[SETUP.md](SETUP.md)** — 최초 설정 가이드 (카카오·텔레그램·Notion·GitHub Secrets)
- **[config.yaml](config.yaml)** — 키워드·섹션·언론사 순위 설정
