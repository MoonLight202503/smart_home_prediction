"""
기상청 ASOS 기간조회 API → CSV 저장 스크립트 (v2)

기존 kma_fetch_to_csv.py(v1)는 kma_sfctm2.php를 시간당 1번씩 호출했지만,
이 버전은 kma_sfctm3.php의 tm1~tm2 기간조회 기능을 사용해
긴 기간을 한 번(또는 몇 번)의 요청으로 가져옵니다.

- API 호출 횟수가 "시간 수"만큼이 아니라 "청크(chunk) 수"만큼만 발생합니다.
  예: 1년치(8760시간)도 --chunk-days 30 이면 약 12번 요청으로 끝남.
- 응답이 너무 길어지는 걸 막기 위해 --chunk-days로 기간을 나눠 요청합니다
  (필요시 --chunk-days 0 으로 전체 기간을 한 번에 요청 가능).
- 컬럼 위치는 kma_sfctm2.php와 동일합니다 (TA=12번째, HM=14번째, SI=35번째 → 0-index 11,13,34).

사용법:
    KMA_API_KEY=your_key python kma_fetch_to_csv.py \
        --start 2025-01-01 --end 2025-12-31 --stn 108 --out weather_2025.csv

    # 청크 크기 조절 (기본 30일). 응답이 너무 크면 줄이세요.
    KMA_API_KEY=your_key python kma_fetch_to_csv.py \
        --start 2022-01-01 --end 2024-12-31 --stn 108 --out weather_full.csv --chunk-days 30
"""

import argparse
import csv
import os
import time
from datetime import datetime, timedelta

import requests

KMA_API_KEY = os.environ.get("KMA_API_KEY")
CSV_COLUMNS = ["r_timestamp", "r_temperature", "r_humidity", "r_insolation"]


def fetch_range(tm1: datetime, tm2: datetime, stn: int, timeout: int = 60, retries: int = 3) -> list[dict]:
    """tm1~tm2 기간의 데이터를 한 번의 요청으로 가져온다 (kma_sfctm3.php)."""
    TM1 = tm1.strftime("%Y%m%d%H%M")
    TM2 = tm2.strftime("%Y%m%d%H%M")
    URL = (
        f"https://apihub.kma.go.kr/api/typ01/url/kma_sfctm3.php"
        f"?tm1={TM1}&tm2={TM2}&stn={stn}&authKey={KMA_API_KEY}"
    )

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(URL, timeout=timeout)
            resp.raise_for_status()
            # 응답이 EUC-KR 인코딩일 수 있어 명시적으로 디코딩
            resp.encoding = resp.apparent_encoding or "euc-kr"
            text = resp.text

            if "ERROR" in text and "#START7777" not in text:
                print(f"  ⚠️ {TM1}~{TM2} API 응답 오류: {text[:150]}")
                return []

            rows = []
            for line in text.split("\n"):
                parts = line.strip().split()
                if len(parts) < 36 or not parts[0].isdigit() or len(parts[0]) != 12:
                    continue
                if int(parts[1]) != stn:
                    continue
                rows.append({
                    "r_timestamp": datetime.strptime(parts[0], "%Y%m%d%H%M").strftime("%Y-%m-%d %H:%M:00"),
                    "r_temperature": float(parts[11]),
                    "r_humidity": float(parts[13]),
                    "r_insolation": float(parts[34]),
                })
            return rows

        except requests.exceptions.Timeout:
            last_err = "timeout"
            print(f"  ⏱ {TM1}~{TM2} 타임아웃 (시도 {attempt}/{retries})")
            time.sleep(2 * attempt)
        except requests.exceptions.RequestException as e:
            last_err = str(e)
            print(f"  ⚠️ {TM1}~{TM2} 요청 실패: {e} (시도 {attempt}/{retries})")
            time.sleep(2 * attempt)

    print(f"  ❌ {TM1}~{TM2} 최종 실패 ({last_err}) — IP 화이트리스트 등록 여부를 확인하세요.")
    return []


def load_already_fetched(csv_path: str) -> set[str]:
    if not os.path.exists(csv_path):
        return set()
    done = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            done.add(row["r_timestamp"])
    return done


def main():
    parser = argparse.ArgumentParser(description="KMA ASOS 기간조회 API로 CSV 저장")
    parser.add_argument("--start", required=True, help="시작일 2024-02-25")
    parser.add_argument("--end", required=True, help="종료일 2025-12-31 (포함)")
    parser.add_argument("--stn", type=int, default=108, help="108 (기본 108 = 서울)")
    parser.add_argument("--out", required=True, help="출력 CSV 경로")
    parser.add_argument("--chunk-days", type=int, default=30,
                         help="한 번의 요청으로 가져올 기간(일). 0이면 전체를 한 번에 요청 (기본 30)")
    parser.add_argument("--sleep", type=float, default=0.5, help="청크 요청 간 대기 시간(초)")
    parser.add_argument("--resume", action="store_true", help="이미 CSV에 있는 시각은 건너뜀")
    args = parser.parse_args()

    if not KMA_API_KEY:
        raise SystemExit("❌ 환경변수 KMA_API_KEY가 설정되지 않았습니다.")

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(hour=23, minute=0)

    already = load_already_fetched(args.out) if args.resume else set()
    if already:
        print(f"📄 기존 CSV에서 {len(already):,}건 발견 — 이어받기 모드")

    write_header = not (args.resume and os.path.exists(args.out))
    mode = "a" if args.resume and os.path.exists(args.out) else "w"

    chunk = timedelta(days=args.chunk_days) if args.chunk_days > 0 else (end - start)
    total_hours = int((end - start).total_seconds() / 3600) + 1
    n_chunks = max(1, -(-int((end - start) / chunk) // 1) + 1) if args.chunk_days > 0 else 1

    print(f"📅 수집 기간: {start} ~ {end} (관측소 {args.stn})")
    print(f"📊 총 {total_hours:,}시간 — 약 {n_chunks}번의 API 요청으로 가져옵니다 (청크: {args.chunk_days or '전체'}일)\n")

    total_written, total_skipped_existing = 0, 0
    cursor = start

    with open(args.out, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if write_header:
            writer.writeheader()

        while cursor <= end:
            chunk_end = min(cursor + chunk - timedelta(hours=1), end)
            print(f"➡️  요청 중: {cursor:%Y-%m-%d %H:%M} ~ {chunk_end:%Y-%m-%d %H:%M}")

            rows = fetch_range(cursor, chunk_end, args.stn)
            new_rows = [r for r in rows if r["r_timestamp"] not in already]

            for r in new_rows:
                writer.writerow(r)
                already.add(r["r_timestamp"])
            f.flush()

            total_written += len(new_rows)
            total_skipped_existing += (len(rows) - len(new_rows))
            print(f"  ✅ {len(rows)}건 수신 (신규 {len(new_rows)}건 저장, 누적 {total_written:,}건)")

            cursor = chunk_end + timedelta(hours=1)
            time.sleep(args.sleep)

    print(f"\n🎉 완료! 신규 저장: {total_written:,}건 | 기존과 중복: {total_skipped_existing:,}건 | 파일: {args.out}")


if __name__ == "__main__":
    main()
