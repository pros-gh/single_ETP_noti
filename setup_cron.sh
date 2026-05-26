#!/bin/bash
# ============================================================
#  ETF/ETN 모니터링 에이전트 - Mac cron 자동 실행 설정
# ============================================================
#
#  이 스크립트는 아래 두 가지를 자동으로 설정합니다:
#    1. requests 라이브러리 설치 (없는 경우)
#    2. 평일 오전 8시 자동 실행 cron 등록
#
#  실행 방법:
#    chmod +x setup_cron.sh
#    ./setup_cron.sh
#
#  주의:
#    - Mac이 오전 8시에 켜져 있어야 합니다.
#    - 잠자기(sleep) 상태에서는 실행되지 않습니다.
#      → 항상 실행하려면 Mac의 '에너지 절약' 설정에서
#        "전원 어댑터: 시스템 잠자기 없음" 또는
#        launchd 방식(아래 참고)을 사용하세요.
# ============================================================

set -e

# 스크립트 디렉토리 (이 sh 파일이 있는 폴더 기준)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/etf_etn_monitor.py"
LOG_FILE="$SCRIPT_DIR/cron_run.log"

echo "============================================"
echo "  ETF/ETN 모니터링 에이전트 cron 설정"
echo "============================================"
echo ""

# Python3 확인
if ! command -v python3 &>/dev/null; then
    echo "❌ python3가 설치되지 않았습니다."
    echo "   https://www.python.org 에서 설치 후 다시 실행하세요."
    exit 1
fi

PYTHON_PATH=$(command -v python3)
echo "✅ Python3: $PYTHON_PATH"

# requests 라이브러리 설치
echo ""
echo "📦 requests 라이브러리 설치 확인 중..."
if ! python3 -c "import requests" 2>/dev/null; then
    echo "   설치 중..."
    pip3 install requests --quiet
    echo "✅ requests 설치 완료"
else
    echo "✅ requests 이미 설치됨"
fi

# 스크립트 존재 확인
if [ ! -f "$PYTHON_SCRIPT" ]; then
    echo ""
    echo "❌ 스크립트를 찾을 수 없습니다: $PYTHON_SCRIPT"
    echo "   etf_etn_monitor.py 와 같은 폴더에 이 sh 파일을 놓으세요."
    exit 1
fi

echo ""
echo "📅 cron 작업 등록 중..."
echo "   → 평일(월~금) 오전 8:00 자동 실행"
echo "   → 로그: $LOG_FILE"
echo ""

# cron 항목 생성
# 형식: 분 시 일 월 요일(0=일,1=월,...,5=금,6=토) 명령
# 1-5 = 월요일~금요일
CRON_JOB="0 8 * * 1-5 $PYTHON_PATH $PYTHON_SCRIPT >> $LOG_FILE 2>&1"

# 기존 cron에 동일 항목이 있으면 제거 후 재등록
(crontab -l 2>/dev/null | grep -v "etf_etn_monitor.py"; echo "$CRON_JOB") | crontab -

echo "✅ cron 등록 완료!"
echo ""
echo "--------------------------------------------"
echo "  등록된 cron 목록:"
crontab -l | grep etf_etn_monitor
echo "--------------------------------------------"
echo ""
echo "📌 유용한 명령어:"
echo "   crontab -l                    # 현재 cron 목록 확인"
echo "   crontab -r                    # 모든 cron 제거 (주의!)"
echo "   python3 $PYTHON_SCRIPT        # 수동 즉시 실행"
echo "   python3 $PYTHON_SCRIPT 20260520  # 특정 날짜로 테스트"
echo ""
echo "============================================"
echo "  설정 완료! Gmail 앱 비밀번호 설정을 잊지 마세요."
echo "  etf_etn_monitor.py 상단 CONFIG 섹션을 확인하세요."
echo "============================================"
