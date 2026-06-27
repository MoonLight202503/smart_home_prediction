"""
기상청 ASOS (kma_sfctm2) 실시간 수집기
- 매시간 정각 실행 (GitHub Actions)
- 서울(STN=108) 기온, 습도, 일사량 → Supabase r_weather_data 저장
"""

import requests
import os
from datetime import datetime
import pytz
from supabase import create_client, Client

# ── 설정 ──────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
KMA_API_KEY  = os.environ.get("KMA_API_KEY")
STN          = 108  # 서울
# ──────────────────────────────────────────────────────

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

kst     = pytz.timezone('Asia/Seoul')
now     = datetime.now(kst)
END_TIME = now.replace(minute=0, second=0, microsecond=0)

print(f"📅 기준 시각: {END_TIME.strftime('%Y-%m-%d %H:%M')} (KST)")


def fetch_data(target_time: datetime) -> dict | None:
    TM  = target_time.strftime("%Y%m%d%H%M")
    URL = (
        f"https://apihub.kma.go.kr/api/typ01/url/kma_sfctm2.php"
        f"?tm={TM}&stn={STN}&authKey={KMA_API_KEY}"
    )
    print(f"⏳ Requesting {TM} ...")

    try:
        resp = requests.get(URL, timeout=30)
        resp.raise_for_status()
        text = resp.text.strip()

        if "ERROR" in text or "help" in text.lower():
            print(f"🚨 API 오류 응답")
            return None

        for line in text.split("\n"):
            parts = line.strip().split()
            if len(parts) < 36 or not parts[0].isdigit() or len(parts[0]) != 12:
                continue
            if int(parts[1]) != STN:
                continue

            return {
                "r_timestamp":   datetime.strptime(parts[0], "%Y%m%d%H%M").strftime("%Y-%m-%d %H:%M:00"),
                "r_temperature": float(parts[11]),
                "r_humidity":    float(parts[13]),
                "r_insolation":  float(parts[34]),
            }

    except Exception as e:
        print(f"⚠️ 요청 실패: {e}")

    return None


def main():
    record = fetch_data(END_TIME)

    if record:
        supabase.table("r_weather_data").insert(record).execute()
        print(f"✅ 저장 완료: {record}")
    else:
        print("❌ 데이터 없음 — 빈 레코드 저장")
        supabase.table("r_weather_data").insert({
            "r_timestamp":   END_TIME.strftime("%Y-%m-%d %H:%M:00"),
            "r_temperature": None,
            "r_humidity":    None,
            "r_insolation":  None,
        }).execute()


if __name__ == "__main__":
    main()
