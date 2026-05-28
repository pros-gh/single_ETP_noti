"""
GitHub Actions에서 Secrets → config.json 변환 스크립트
"""
import json
import os

cfg = {
    "_info": "GitHub Actions에서 자동 생성",
    "searchPeriod": "biz5",
    "senderEmail": os.environ["SENDER_EMAIL"],
    "appPassword": os.environ["APP_PASSWORD"],
    "recipients": [r.strip() for r in os.environ["RECIPIENTS"].split(",")],
}

with open("config.json", "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)

print(f"config.json 생성 완료 - 수신자: {cfg['recipients']}")
