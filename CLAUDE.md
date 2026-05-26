# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 프로젝트 개요

KSD Seibro Open API를 이용해 **매일 신규상장종목을 조회**하고, 그 중 **단일종목형 ETF/ETN**이 있으면 Gmail로 이메일 알림을 발송하는 자동화 에이전트.

## 파일 구성 및 역할

| 파일 | 역할 |
|------|------|
| `etf_etn_monitor.py` | 핵심 실행 스크립트 (API 호출 → 파싱 → 필터 → 이메일 발송) |
| `admin.html` | 설정 관리 모바일 웹 UI + 브라우저 기반 자동화 |
| `setup_cron.sh` | Mac cron 자동화 등록 스크립트 |
| `config.json` | admin.html에서 내보내는 설정 파일 (런타임 생성, git 제외 권장) |
| `etf_etn_monitor.log` | 실행 로그 (런타임 생성) |

## 실행 명령

```bash
# 의존성 설치 (최초 1회)
pip3 install requests

# 오늘 날짜로 실행
python3 etf_etn_monitor.py

# 특정 날짜 테스트 (YYYYMMDD)
python3 etf_etn_monitor.py 20260520

# Mac cron 등록 (평일 오전 8시 자동 실행)
chmod +x setup_cron.sh && ./setup_cron.sh

# cron 확인 / 제거
crontab -l
crontab -r
```

## 설정 흐름 (Configuration Flow)

```
admin.html (브라우저 UI)
    ↓ "💾 저장" 버튼
config.json (자동 생성)
    ↓ 스크립트 시작 시 load_config() 자동 로드
etf_etn_monitor.py (전역 변수 덮어쓰기)
```

`config.json`이 없으면 스크립트 상단 하드코딩 기본값으로 동작한다. `config.json`의 키 이름과 Python 전역 변수의 매핑은 `load_config()` 함수 참고.

## 핵심 아키텍처

### Python 스크립트 실행 흐름

```
main()
 ├─ 날짜 결정 (argv[1] 또는 오늘)
 ├─ 주말 스킵
 ├─ calc_date_range()   ← SEARCH_PERIOD 기반 begin/end 계산
 ├─ fetch_new_listings()  ← Seibro API HTTP GET
 ├─ parse_listings()      ← XML 적응형 파싱
 ├─ get_product_type()    ← ETF/ETN 판별 (이름 + 유형코드)
 ├─ is_single_stock_type() ← INDEX_KEYWORDS 역방향 매칭
 └─ send_gmail()          ← SMTP SSL, 다중 수신자
```

### Seibro API

- **엔드포인트**: `http://seibro.or.kr/OpenPlatform/callOpenAPI.jsp`
- **인증**: `key` 쿼리 파라미터 (SEIBRO_API_KEY)
- **조회 오퍼레이션**: `apiId=getStkListInfo`
- **날짜 파라미터**: `params=ALT_BEGIN_DT:YYYYMMDD,ALT_EXPRY_DT:YYYYMMDD`
- **응답 형식**: XML (실제 태그명은 API 서버 버전마다 다를 수 있음)

### 검색기간(SEARCH_PERIOD) 옵션

| 값 | 동작 |
|----|------|
| `"today"` | begin=오늘, end=오늘 |
| `"past3"` | begin=오늘-2일, end=오늘 |
| `"future3"` | begin=오늘, end=오늘+2일 |
| `"custom"` | CUSTOM_BEGIN_DATE / CUSTOM_END_DATE 사용 |

### 단일종목형 판별 로직

`is_single_stock_type()`은 **포지티브 판별이 아닌 네거티브 필터** 방식을 사용한다:
1. ETF/ETN 브랜드명(KODEX, TIGER 등)과 "ETF"/"ETN" 문자열 제거
2. 남은 이름에 `INDEX_KEYWORDS` 중 하나라도 포함되면 → 지수/테마형 (False)
3. 어떤 키워드도 없으면 → 단일종목형 (True)
4. API 응답에 `UNIIT_STK_YN` 필드가 있으면 해당 값 우선 사용

### XML 파싱 적응 전략

Seibro API 응답의 실제 태그명이 불확실하므로 `parse_listings()`는 `row → item → list → record → data` 순서로 태그를 탐색하고, 없으면 반복 출현하는 태그를 자동 감지한다. **첫 실행 시 로그에 찍히는 "첫 번째 종목 필드"를 확인해 실제 필드명을 파악**해야 한다.

### admin.html 브라우저 자동화

- `allorigins.win` CORS 프록시를 통해 브라우저에서 직접 Seibro API 호출 (Claude 서버 미경유)
- `setTimeout` 기반 스케줄러 — 탭이 열려 있는 동안만 동작
- 설정은 `localStorage`에 영속 저장
- 단일종목 발견 시 브라우저 `Notification API`로 알림

## 필드명 불확실성 대응

Seibro API의 XML 응답 필드명은 문서화가 불충분하므로, 코드 전반에서 여러 후보 필드명을 순차 시도한다:

```python
# 패턴 예시
name = next(
    (stock.get(f) for f in ["KR_NM", "ISIN_NM", "STK_NM", "ITEM_NM"] if stock.get(f)),
    "이름 없음"
)
```

실제 응답에서 새 필드명이 발견되면 각 함수의 후보 리스트에 추가한다.

## 주의사항

- `config.json`에 Gmail 앱 비밀번호가 평문 저장됨 → `.gitignore`에 추가 권장
- Seibro API는 HTTP (비암호화) — 프록시 환경에서 패킷 노출 가능
- 브라우저 자동화는 탭이 닫히면 중단됨 → 안정적 운영은 Python + cron/Task Scheduler 권장
- `future3` 모드로 조회 시 아직 상장 안 된 예정 종목도 포함될 수 있으므로 결과 해석 주의
