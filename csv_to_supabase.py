"""
CSV → Supabase r_weather_data 업로드 스크립트

kma_fetch_to_csv.py로 받은 CSV 파일을 읽어서 Supabase에 batch insert 합니다.
r_timestamp가 UNIQUE 컬럼이므로, 이미 존재하는 시각은 upsert로 덮어씁니다
(중복 insert 에러 없이 안전하게 재실행 가능).

사용법:
    SUPABASE_KEY=your_key python csv_to_supabase.py --csv weather_2025_01.csv
"""

import argparse
import csv
import os
import time

from supabase import create_client, Client

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

BATCH_SIZE = 200
SLEEP_SEC = 0.2


def load_csv(path: str) -> list[dict]:
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                "r_timestamp": row["r_timestamp"],
                "r_temperature": float(row["r_temperature"]),
                "r_humidity": float(row["r_humidity"]),
                "r_insolation": float(row["r_insolation"]),
            })
    return rows


def upload(rows: list[dict], supabase: Client):
    total = len(rows)
    print(f"📤 총 {total:,}건 업로드 시작 (배치 {BATCH_SIZE}건씩, upsert)")

    success = 0
    for i in range(0, total, BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        try:
            # r_timestamp가 UNIQUE이므로 on_conflict로 같은 시각은 덮어씀
            supabase.table("r_weather_data").upsert(batch, on_conflict="r_timestamp").execute()
            success += len(batch)
            print(f"  ✅ {success:,}/{total:,}건 업로드 완료")
        except Exception as e:
            print(f"  ❌ 배치 실패 (rows {i}~{i+len(batch)}): {e}")
        time.sleep(SLEEP_SEC)

    print(f"\n🎉 업로드 완료: {success:,}/{total:,}건")


def main():
    parser = argparse.ArgumentParser(description="CSV 기상 데이터를 Supabase에 업로드")
    parser.add_argument("--csv", required=True, help="kma_fetch_to_csv.py로 생성한 CSV 경로")
    args = parser.parse_args()

    if not SUPABASE_KEY:
        raise SystemExit("❌ 환경변수 SUPABASE_KEY가 설정되지 않았습니다.")

    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    rows = load_csv(args.csv)
    print(f"📄 {args.csv}에서 {len(rows):,}건 로드")

    if not rows:
        print("⚠️ 업로드할 데이터가 없습니다.")
        return

    upload(rows, supabase)


if __name__ == "__main__":
    main()
