"""
기상청 ASOS 과거 데이터 bulk insert
- 기간: 2022-01-01 ~ 2024-12-31 (3년치)
- 관측소: 서울 (STN=108)
- 최초 1회만 로컬에서 실행
"""

import requests
import time
import os
from datetime import datetime, timedelta
from supabase import create_client, Client

# ── 설정 ──────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://vcqqokmyyjsvxyvuzgmv.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
KMA_API_KEY  = os.environ.get("KMA_API_KEY")

STN        = 108
START_TIME = datetime(2022, 1, 1, 0, 0)
END_TIME   = datetime(2024, 12, 31, 23, 0)
BATCH_SIZE = 100
SLEEP_SEC  = 0.3
# ──────────────────────────────────────────────────────

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def fetch_one_hour(target_time: datetime) -> dict | None:
    TM  = target_time.strftime("%Y%m%d%H%M")
    URL = (
        f"https://apihub.kma.go.kr/api/typ01/url/kma_sfctm2.php"
        f"?tm={TM}&stn={STN}&authKey={KMA_API_KEY}"
    )
    try:
        resp = requests.get(URL, timeout=30)
        resp.raise_for_status()
        text = resp.text.strip()

        if "ERROR" in text or "help" in text.lower():
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
        print(f"  ⚠️ {target_time.strftime('%Y-%m-%d %H:%M')} 실패: {e}")

    return None


def insert_batch(batch: list[dict]):
    try:
        supabase.table("r_weather_data").insert(batch).execute()
    except Exception as e:
        print(f"  ❌ insert 실패 ({len(batch)}건): {e}")


def main():
    total_hours = int((END_TIME - START_TIME).total_seconds() / 3600) + 1
    print(f"📅 수집 기간: {START_TIME} ~ {END_TIME}")
    print(f"📊 총 {total_hours:,}시간치 수집 예정 (서울 STN={STN})")
    print(f"⏱  예상 소요: 약 {total_hours * SLEEP_SEC / 60:.0f}분\n")

    batch, success, skipped = [], 0, 0
    current = START_TIME

    while current <= END_TIME:
        record = fetch_one_hour(current)

        if record:
            batch.append(record)
            success += 1
        else:
            skipped += 1

        if len(batch) >= BATCH_SIZE:
            insert_batch(batch)
            print(f"  ✅ insert {success:,}건 완료 | 현재: {current.strftime('%Y-%m-%d %H:%M')} | 누락: {skipped}건")
            batch = []

        current += timedelta(hours=1)
        time.sleep(SLEEP_SEC)

    if batch:
        insert_batch(batch)

    print(f"\n🎉 완료! 총 성공: {success:,}건 | 누락(결측/오류): {skipped}건")


if __name__ == "__main__":
    main()
