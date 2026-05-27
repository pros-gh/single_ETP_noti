#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KSD Seibro 신규상장 단일종목형 ETF/ETN 모니터링 에이전트
=====================================================
매일 장 시작 전(오전 8시) Seibro Open API를 통해 당일 신규상장종목을 조회하고,
단일종목형 ETF 또는 ETN이 발견되면 Gmail로 이메일 알림을 발송합니다.

[ 실행 방법 ]
1. pip install requests  (필요 라이브러리 설치)
2. 아래 CONFIG 섹션에 Gmail 앱 비밀번호 입력
3. python3 etf_etn_monitor.py              # 오늘 날짜로 실행
   python3 etf_etn_monitor.py 20260520    # 특정 날짜로 테스트

[ Gmail 앱 비밀번호 발급 방법 ]
1. Google 계정 → 보안 → 2단계 인증 활성화
2. Google 계정 → 보안 → 앱 비밀번호 → 새 앱 비밀번호 생성
3. 생성된 16자리 비밀번호를 GMAIL_APP_PASSWORD에 입력

[ Mac cron 자동 실행 설정 ]
  setup_cron.sh 스크립트 참고
"""

import sys
import os
import re
import json
import requests
import xml.etree.ElementTree as ET
import smtplib
import logging
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ============================================================
#  CONFIG - 기본값 (admin.html에서 저장한 config.json이 있으면 자동으로 덮어씀)
# ============================================================

# Seibro Open API 인증키 (변경 불필요)
SEIBRO_API_KEY = "814afc0ebba9a9e2d8e3530eb4da1c5fa1d980809bdf26fcfc82a46f0534cca3"

# Seibro API 엔드포인트
SEIBRO_API_URL = "https://seibro.or.kr/OpenPlatform/callOpenAPI.jsp"

# 기본 설정값 (admin.html에서 저장한 config.json이 있으면 자동으로 덮어씀)
GMAIL_USER = "guardism@gmail.com"
GMAIL_APP_PASSWORD = "여기에_앱_비밀번호_16자리_입력"
EMAIL_TO_LIST = ["guardism@gmail.com"]

# 검색기간: "today" | "past3" | "future3" | "custom"
SEARCH_PERIOD = "today"
CUSTOM_BEGIN_DATE = ""   # YYYYMMDD (custom일 때만 사용)
CUSTOM_END_DATE   = ""   # YYYYMMDD (custom일 때만 사용)

# 로그 파일 경로
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "etf_etn_monitor.log")

# ============================================================
#  config.json 자동 로드 (admin.html에서 내보낸 파일)
# ============================================================
def load_config():
    global GMAIL_USER, GMAIL_APP_PASSWORD, EMAIL_TO_LIST
    global SEARCH_PERIOD, CUSTOM_BEGIN_DATE, CUSTOM_END_DATE
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if not os.path.exists(config_path):
        return
    try:
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)
        if cfg.get("senderEmail"):
            GMAIL_USER = cfg["senderEmail"]
        if cfg.get("appPassword"):
            GMAIL_APP_PASSWORD = cfg["appPassword"]
        if cfg.get("recipients") and isinstance(cfg["recipients"], list):
            EMAIL_TO_LIST = [r for r in cfg["recipients"] if r]
        if cfg.get("searchPeriod"):
            SEARCH_PERIOD = cfg["searchPeriod"]
        if cfg.get("customBeginDate"):
            CUSTOM_BEGIN_DATE = cfg["customBeginDate"].replace("-", "")
        if cfg.get("customEndDate"):
            CUSTOM_END_DATE = cfg["customEndDate"].replace("-", "")
        print(f"[config.json 로드] 발송={GMAIL_USER}, 수신={EMAIL_TO_LIST}, 기간={SEARCH_PERIOD}")
    except Exception as e:
        print(f"[경고] config.json 로드 실패: {e}")

load_config()

# ============================================================
#  검색 날짜 범위 계산
# ============================================================
def calc_date_range(base_date: str) -> tuple[str, str]:
    """
    SEARCH_PERIOD 설정에 따라 조회 시작/종료 날짜를 반환합니다.
    base_date: 'YYYYMMDD' 형식의 기준일(오늘)
    반환: (begin_str, end_str) 모두 'YYYYMMDD'
    """
    dt = datetime.strptime(base_date, "%Y%m%d")
    if SEARCH_PERIOD == "past3":
        begin = dt - timedelta(days=2)
        end   = dt
    elif SEARCH_PERIOD == "future3":
        begin = dt
        end   = dt + timedelta(days=2)
    elif SEARCH_PERIOD == "custom":
        begin_s = CUSTOM_BEGIN_DATE or base_date
        end_s   = CUSTOM_END_DATE   or base_date
        return begin_s, end_s
    else:  # "today" (기본값)
        begin = end = dt
    return begin.strftime("%Y%m%d"), end.strftime("%Y%m%d")

# ============================================================
#  단일종목형 판별 키워드 (이 단어가 있으면 지수/테마형으로 분류)
# ============================================================
INDEX_KEYWORDS = [
    # 국내 지수
    "코스피", "KOSPI", "코스닥", "KOSDAQ", "KRX", "코넥스", "KONEX",
    "200", "100", "150", "50", "300",
    "지수", "인덱스", "INDEX",
    # 해외 지수
    "S&P", "SP500", "나스닥", "NASDAQ", "다우", "DOW", "러셀", "RUSSELL",
    "니케이", "NIKKEI", "항셍", "항생", "상해", "CSI", "DAX", "유로",
    "미국", "중국", "일본", "유럽", "글로벌", "아시아", "신흥",
    # 테마/섹터
    "섹터", "업종", "반도체", "바이오", "헬스케어", "2차전지", "배터리",
    "배당", "고배당", "성장", "가치", "모멘텀", "퀄리티", "우량",
    "그린", "친환경", "ESG", "클린", "탄소",
    "메타버스", "클라우드", "AI", "인공지능", "빅데이터", "핀테크",
    "게임", "엔터", "미디어", "콘텐츠",
    # 원자재/채권
    "금", "은", "구리", "원유", "천연가스", "원자재", "에너지",
    "채권", "국채", "회사채",
    # 레버리지/인버스
    "레버리지", "인버스", "곱버스", "2X", "3X",
    # 기타 다종목 키워드
    "TOP", "PLUS", "MID", "SMALL", "LARGE",
]

# ============================================================
#  로깅 설정
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


# ============================================================
#  Seibro API 호출
# ============================================================
def fetch_new_listings(begin_str: str, end_str: str):
    """
    Seibro getStkListInfo API를 호출하여 XML 응답을 반환합니다.
    begin_str, end_str: 'YYYYMMDD' 형식의 조회 시작/종료일
    """
    params = {
        "key": SEIBRO_API_KEY,
        "apiId": "getStkListInfo",
        "params": f"ALT_BEGIN_DT:{begin_str},ALT_EXPRY_DT:{end_str}",
    }
    logger.info(f"Seibro API 호출: {begin_str} ~ {end_str}")
    try:
        response = requests.get(SEIBRO_API_URL, params=params, timeout=30)
        response.raise_for_status()
        logger.debug(f"API 응답 원문:\n{response.text[:2000]}")
        return response.text
    except requests.Timeout:
        logger.error("API 호출 시간 초과 (30초)")
    except requests.HTTPError as e:
        logger.error(f"HTTP 오류: {e.response.status_code}")
    except requests.RequestException as e:
        logger.error(f"API 호출 실패: {e}")
    return None


# ============================================================
#  XML 파싱
# ============================================================
def parse_listings(xml_text: str) -> list[dict]:
    """
    XML 응답에서 종목 목록을 파싱합니다.

    Seibro API 실제 응답 구조:
      <vector result="N">
        <data vectorkey="0" type="Document">
          <result>
            <FIELD_NAME value="값"/>  ← value 속성으로 값이 담김
            ...
          </result>
        </data>
        ...
      </vector>
    """
    if not xml_text or not xml_text.strip():
        logger.warning("API 응답이 비어 있습니다.")
        return []

    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError as e:
        logger.error(f"XML 파싱 실패: {e}")
        logger.error(f"응답 내용 (처음 500자): {xml_text[:500]}")
        return []

    stocks = []

    # ── 1순위: vector > data > result 구조 (실제 Seibro 응답 형식) ──
    result_elems = root.findall(".//data/result")
    if result_elems:
        logger.info(f"'data/result' 구조로 {len(result_elems)}개 행 발견")
        for result_elem in result_elems:
            stock = {}
            for field in result_elem:
                # <FIELD_NAME value="값"/> 형태
                val = field.get("value")
                if val is not None:
                    stock[field.tag] = val.strip()
                else:
                    stock[field.tag] = (field.text or "").strip()
            if stock:
                stocks.append(stock)
        logger.info(f"파싱 완료: 총 {len(stocks)}개 종목")
        if stocks:
            logger.debug(f"첫 번째 종목 필드: {list(stocks[0].keys())}")
        return stocks

    # ── 2순위: 기타 row/item/record 텍스트 기반 구조 (fallback) ──
    rows = []
    for tag in ("row", "item", "list", "record", "result"):
        rows = root.findall(f".//{tag}")
        if rows:
            logger.info(f"'{tag}' 태그로 {len(rows)}개 행 발견 (fallback)")
            break

    if not rows:
        tag_counts: dict = {}
        for elem in root.iter():
            if len(elem) > 0:
                tag_counts[elem.tag] = tag_counts.get(elem.tag, 0) + 1
        repeating = [t for t, c in tag_counts.items() if c > 1]
        if repeating:
            rows = root.findall(f".//{repeating[0]}")
            logger.info(f"반복 태그 '{repeating[0]}'로 {len(rows)}개 행 발견 (fallback)")

    for row in rows:
        stock = {}
        for child in row:
            val = child.get("value")
            stock[child.tag] = val.strip() if val is not None else (child.text or "").strip()
        if stock:
            stocks.append(stock)

    logger.info(f"파싱 완료: 총 {len(stocks)}개 종목")
    if stocks:
        logger.debug(f"첫 번째 종목 필드: {list(stocks[0].keys())}")
    return stocks


# ============================================================
#  ETF / ETN 판별
# ============================================================
def get_product_type(stock: dict):
    """
    종목이 ETF 또는 ETN인지 판별합니다.
    반환값: 'ETF', 'ETN', 또는 None (해당 없음)
    """
    # 종목명 후보 필드 (KOR_SECN_NM 우선, 하위 호환 필드 포함)
    name_fields = [
        "KOR_SECN_NM",
        "KR_NM", "ISIN_NM", "STK_NM", "ITEM_NM", "PRDT_NM",
        "kr_nm", "isin_nm", "stk_nm", "item_nm",
    ]
    name = ""
    for field in name_fields:
        val = stock.get(field, "")
        if val:
            name = val
            break

    name_upper = name.upper()
    # 공백을 제거한 버전으로도 체크 (예: "상장지수 투자신탁"처럼 띄어쓰기 편차 대응)
    name_nospace = re.sub(r"\s+", "", name)

    # ETF 판별: "ETF" 또는 한국어 정식명칭 "상장지수투자신탁"
    if "ETF" in name_upper or "상장지수투자신탁" in name_nospace:
        return "ETF"

    # ETN 판별: "ETN" 또는 한국어 정식명칭 "상장지수증권"
    if "ETN" in name_upper or "상장지수증권" in name_nospace:
        return "ETN"

    return None


# ============================================================
#  단일종목형 판별
# ============================================================
def is_single_stock_type(stock: dict, product_type: str) -> bool:
    """
    단일종목형 ETF/ETN 여부를 판별합니다.
    KOR_SECN_NM 필드 값에 '단일' 문자열이 포함되면 단일종목형으로 판별합니다.
    """
    kor_secn_nm = stock.get("KOR_SECN_NM", "")
    result = "단일" in kor_secn_nm
    if result:
        logger.info(f"단일종목형 ETF/ETN 판별: KOR_SECN_NM='{kor_secn_nm}' → 단일종목형")
    else:
        logger.debug(f"단일종목형 아님: KOR_SECN_NM='{kor_secn_nm}'")
    return result


# ============================================================
#  이메일 발송
# ============================================================
def build_email_html(stocks: list[dict], date_str: str) -> str:
    """HTML 이메일 본문 생성"""
    date_formatted = f"{date_str[:4]}년 {date_str[4:6]}월 {date_str[6:]}일"

    rows_html = ""
    for s in stocks:
        # 종목명 (KOR_SECN_NM 우선, 하위 호환 필드 포함)
        name = next(
            (s.get(f, "") for f in ["KOR_SECN_NM", "KR_NM", "ISIN_NM", "STK_NM", "ITEM_NM", "PRDT_NM"] if s.get(f)),
            "이름 없음",
        )
        # ISIN 코드
        isin = next(
            (s.get(f, "") for f in ["ISIN", "ISIN_CD", "isin_cd"] if s.get(f)),
            "-",
        )
        # 단축코드
        short_cd = next(
            (s.get(f, "") for f in ["SHOTN_ISIN", "SHRT_ISIN", "SHRT_CD", "STK_CD"] if s.get(f)),
            "-",
        )
        # 상장일 (APLI_DT: YYYYMMDD → YYYY.MM.DD)
        apli_dt_raw = s.get("APLI_DT", "")
        list_date = (
            f"{apli_dt_raw[:4]}.{apli_dt_raw[4:6]}.{apli_dt_raw[6:]}"
            if len(apli_dt_raw) == 8 else "-"
        )
        # 상품유형
        ptype = get_product_type(s) or "-"

        rows_html += f"""
        <tr>
            <td style="padding:10px;border-bottom:1px solid #eee;">{name}</td>
            <td style="padding:10px;border-bottom:1px solid #eee;text-align:center;">{ptype}</td>
            <td style="padding:10px;border-bottom:1px solid #eee;text-align:center;">{list_date}</td>
            <td style="padding:10px;border-bottom:1px solid #eee;text-align:center;font-family:monospace;">{isin}</td>
            <td style="padding:10px;border-bottom:1px solid #eee;text-align:center;">{short_cd}</td>
        </tr>"""

    count = len(stocks)

    html = f"""
<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"></head>
<body style="font-family:'Malgun Gothic',Arial,sans-serif;background:#f5f5f5;margin:0;padding:20px;">
  <div style="max-width:700px;margin:0 auto;background:#fff;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">

    <!-- 헤더 -->
    <div style="background:#1a3c6e;padding:24px 30px;">
      <h1 style="color:#fff;margin:0;font-size:20px;">📢 단일종목형 ETF/ETN 신규상장 알림</h1>
      <p style="color:#aac4e8;margin:6px 0 0;font-size:14px;">{date_formatted} 신규상장</p>
    </div>

    <!-- 요약 -->
    <div style="padding:20px 30px;background:#eaf1fb;border-bottom:1px solid #d0e0f0;">
      <p style="margin:0;font-size:16px;color:#1a3c6e;">
        오늘 <strong>단일종목형 ETF/ETN {count}개</strong>가 신규상장되었습니다.
      </p>
    </div>

    <!-- 테이블 -->
    <div style="padding:20px 30px;">
      <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <thead>
          <tr style="background:#f0f0f0;">
            <th style="padding:10px;text-align:left;border-bottom:2px solid #ccc;">종목명</th>
            <th style="padding:10px;text-align:center;border-bottom:2px solid #ccc;">유형</th>
            <th style="padding:10px;text-align:center;border-bottom:2px solid #ccc;">상장일</th>
            <th style="padding:10px;text-align:center;border-bottom:2px solid #ccc;">ISIN</th>
            <th style="padding:10px;text-align:center;border-bottom:2px solid #ccc;">단축코드</th>
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
    </div>

    <!-- 주석 -->
    <div style="padding:16px 30px;background:#fffbf0;border-top:1px solid #f0e0a0;">
      <p style="margin:0;font-size:12px;color:#888;">
        ⚠️ 단일종목형 판별은 종목명 분석 기반입니다. 실제 운용 전략은 투자설명서를 확인하세요.<br>
        본 알림은 Seibro Open API를 활용하여 자동 생성된 정보입니다.
      </p>
    </div>

    <!-- 푸터 -->
    <div style="padding:16px 30px;text-align:center;font-size:12px;color:#aaa;">
      KSD Seibro 신규상장 모니터링 에이전트 • {date_formatted}
    </div>

  </div>
</body>
</html>
"""
    return html


def send_gmail(subject: str, html_body: str) -> bool:
    """Gmail SMTP(SSL)로 이메일 발송 (다중 수신자 지원)"""
    if "여기에" in GMAIL_APP_PASSWORD:
        logger.error("Gmail 앱 비밀번호가 설정되지 않았습니다. admin.html에서 설정 후 config.json을 내보내세요.")
        return False
    if not EMAIL_TO_LIST:
        logger.error("수신 이메일 목록이 비어 있습니다.")
        return False

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = GMAIL_USER
        msg["To"] = ", ".join(EMAIL_TO_LIST)
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, EMAIL_TO_LIST, msg.as_string())

        logger.info(f"✅ 이메일 발송 완료 → {', '.join(EMAIL_TO_LIST)}")
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error("Gmail 인증 실패. 앱 비밀번호를 확인하세요.")
    except smtplib.SMTPException as e:
        logger.error(f"SMTP 오류: {e}")
    except Exception as e:
        logger.error(f"이메일 발송 중 예외 발생: {e}")
    return False


# ============================================================
#  Slack 알림 발송
# ============================================================
# ============================================================
#  메인 실행
# ============================================================
def main():
    # 날짜 결정 (인자 있으면 해당 날짜, 없으면 오늘)
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
        if not re.match(r"^\d{8}$", date_str):
            print("날짜 형식 오류. YYYYMMDD 형식으로 입력하세요.")
            sys.exit(1)
    else:
        date_str = datetime.now().strftime("%Y%m%d")

    logger.info(f"========== ETF/ETN 모니터링 시작: {date_str} ==========")
    logger.info(f"설정: 기간={SEARCH_PERIOD}, 발송={GMAIL_USER}, 수신={EMAIL_TO_LIST}")

    # 주말 체크 (당일 기준)
    dt = datetime.strptime(date_str, "%Y%m%d")
    if dt.weekday() >= 5:
        logger.info(f"주말({['월','화','수','목','금','토','일'][dt.weekday()]})이므로 건너뜁니다.")
        return

    # 검색 날짜 범위 계산
    begin_str, end_str = calc_date_range(date_str)
    logger.info(f"조회 기간: {begin_str} ~ {end_str}")

    # 1. API 호출
    xml_text = fetch_new_listings(begin_str, end_str)
    if xml_text is None:
        logger.error("API 호출 실패로 종료합니다.")
        sys.exit(1)

    # 2. 파싱
    all_stocks = parse_listings(xml_text)
    if not all_stocks:
        logger.info("신규상장 종목이 없거나 데이터를 파싱할 수 없습니다.")
        # 디버그: 원본 응답 출력
        logger.info(f"원본 응답:\n{xml_text[:1000]}")
        return

    logger.info(f"전체 신규상장: {len(all_stocks)}개")

    # 3. ETF/ETN 필터
    etf_etn_list = []
    for s in all_stocks:
        ptype = get_product_type(s)
        if ptype:
            s["_detected_type"] = ptype
            etf_etn_list.append(s)

    logger.info(f"ETF/ETN: {len(etf_etn_list)}개")

    # 4. 단일종목형 필터
    single_stock_list = []
    for s in etf_etn_list:
        ptype = s["_detected_type"]
        if is_single_stock_type(s, ptype):
            single_stock_list.append(s)

    logger.info(f"단일종목형 ETF/ETN: {len(single_stock_list)}개")

    # 5. 알림 발송
    if single_stock_list:
        date_fmt = f"{date_str[:4]}/{date_str[4:6]}/{date_str[6:]}"
        subject = f"[Seibro 알림] 단일종목형 ETF/ETN {len(single_stock_list)}개 신규상장 ({date_fmt})"
        html_body = build_email_html(single_stock_list, date_str)
        send_gmail(subject, html_body)
    else:
        logger.info("단일종목형 ETF/ETN 신규상장 없음. 이메일 미발송.")

    logger.info("========== 모니터링 완료 ==========\n")


if __name__ == "__main__":
    main()
