"""
전력 소비량 예측 시스템
- Supabase r_weather_data에서 과거 데이터 로드
- LSTM으로 내일 24시간 일사량 예측 (롤링 예측)
- 일사량 기반 전력 소비량 계산
- 결과를 Supabase prediction 테이블에 저장
- 매일 KST 07:00 실행 (GitHub Actions)
"""

import torch
import torch.nn as nn
import torch.optim as optim
import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta
from supabase import create_client, Client

# ── 설정 ──────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://vcqqokmyyjsvxyvuzgmv.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

SEQ_LENGTH  = 24
EPOCHS      = 100
LR          = 0.001
HIDDEN_SIZE = 64
# ──────────────────────────────────────────────────────

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ── 1. 데이터 로드 ─────────────────────────────────────
def load_data() -> pd.DataFrame:
    print("📥 Supabase에서 데이터 로드 중...")
    resp = supabase.table("r_weather_data").select("*").order("r_timestamp").execute()
    df   = pd.DataFrame(resp.data)

    if df.empty:
        raise ValueError("❌ r_weather_data 테이블에 데이터가 없습니다.")

    df['datetime']    = pd.to_datetime(df['r_timestamp'])
    df['insolation']  = pd.to_numeric(df['r_insolation'], errors='coerce').replace(-9, 0).fillna(0)
    df['temperature'] = pd.to_numeric(df['r_temperature'], errors='coerce').replace(-9, np.nan).ffill()
    df['humidity']    = pd.to_numeric(df['r_humidity'], errors='coerce').replace(-9, np.nan).ffill()

    df = df.sort_values('datetime').reset_index(drop=True)
    print(f"✅ {len(df):,}건 로드 완료 ({df['datetime'].min()} ~ {df['datetime'].max()})")
    return df


# ── 2. 시퀀스 생성 ─────────────────────────────────────
def create_sequences(series: np.ndarray, seq_length: int):
    X, y = [], []
    for i in range(len(series) - seq_length):
        X.append(series[i:i + seq_length])
        y.append(series[i + seq_length])
    return np.array(X), np.array(y)


# ── 3. LSTM 모델 ───────────────────────────────────────
class LSTMModel(nn.Module):
    def __init__(self, input_size=1, hidden_size=64, num_layers=2):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers,
                            batch_first=True, dropout=0.2)
        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 32),
            nn.ReLU(),
            nn.Linear(32, 1)
        )

    def forward(self, x):
        out, _ = self.lstm(x)
        return self.fc(out[:, -1, :])


# ── 4. 학습 ───────────────────────────────────────────
def train_model(df: pd.DataFrame):
    print("\n🧠 LSTM 모델 학습 중...")
    series   = df['insolation'].values.astype(np.float32)
    max_val  = series.max() if series.max() > 0 else 1.0
    series_n = series / max_val

    X, y = create_sequences(series_n, SEQ_LENGTH)
    X_t  = torch.tensor(X, dtype=torch.float32).unsqueeze(-1)
    y_t  = torch.tensor(y, dtype=torch.float32).unsqueeze(-1)

    model     = LSTMModel(hidden_size=HIDDEN_SIZE)
    optimizer = optim.Adam(model.parameters(), lr=LR)
    criterion = nn.MSELoss()

    model.train()
    for epoch in range(EPOCHS):
        optimizer.zero_grad()
        loss = criterion(model(X_t), y_t)
        loss.backward()
        optimizer.step()
        if (epoch + 1) % 20 == 0:
            print(f"  Epoch {epoch+1}/{EPOCHS} | Loss: {loss.item():.6f}")

    print("✅ 학습 완료")
    return model, X_t, max_val


# ── 5. 24시간 롤링 예측 ────────────────────────────────
def predict_24h(model: LSTMModel, df: pd.DataFrame, X_t: torch.Tensor, max_val: float):
    print("\n🔮 24시간 일사량 예측 중...")
    model.eval()

    last_time = df['datetime'].max().replace(minute=0, second=0, microsecond=0)
    window    = X_t[-1].squeeze(-1).tolist()
    predictions = []

    with torch.no_grad():
        for hour in range(24):
            pred_time = last_time + timedelta(hours=hour + 1)
            x_input   = torch.tensor(window[-SEQ_LENGTH:],
                                     dtype=torch.float32).unsqueeze(0).unsqueeze(-1)
            pred_norm = model(x_input).item()
            pred      = max(pred_norm * max_val, 0.0)

            if pred_time.hour < 6 or pred_time.hour > 18:
                pred = 0.0

            predictions.append((pred_time, pred))
            window.append(pred_norm)

    return predictions


# ── 6. 전력 소비량 계산 ────────────────────────────────
def calculate_power(irradiance: float) -> float:
    """
    기존 공식 기반 전력 소비량 계산
    - 기본(라즈베리파이 등): 0.6W
    - LED 5개 × 0.53W (일사량 비례)
    - RGB 4개 × 0.53W (고정)
    - 서보모터 2개 × 1.53W / 50 (고정)
    - 센서류: 0.3W (고정)
    """
    return round(
        0.6
        + 5 * 0.53 * (irradiance / 1000)
        + 4 * 0.53
        + (2 * 1.53) / 50
        + 0.3,
        4
    )


# ── 7. Supabase 저장 ───────────────────────────────────
def save_to_supabase(predictions: list) -> list:
    print("\n💾 Supabase prediction 테이블에 저장 중...")

    records = [
        {
            "predicted_time":  pred_time.isoformat(),
            "pred_insolation": round(float(insolation), 4),
            "pred_power":      float(calculate_power(insolation)),
            "timestamp":       datetime.now().isoformat(),
        }
        for pred_time, insolation in predictions
    ]

    try:
        supabase.table("prediction").delete().not_.is_("prediction_id", None).execute()
        print("🗑️  기존 prediction 데이터 삭제 완료")
        supabase.table("prediction").insert(records).execute()
        print(f"✅ {len(records)}건 저장 완료")
    except Exception as e:
        print(f"❌ Supabase 저장 실패: {e}")

    return records


# ── 8. 콘솔 출력 ──────────────────────────────────────
def print_results(records: list):
    print("\n" + "=" * 60)
    print(f"{'시각':<20} {'일사량(W/m²)':>12} {'소비전력(W)':>12}")
    print("=" * 60)
    for r in records:
        t   = r["predicted_time"][:16]
        i   = r["pred_insolation"]
        p   = r["pred_power"]
        ico = "☀️ " if i > 0 else "🌙"
        print(f"{ico} {t}   {i:>10.3f}   {p:>10.3f}")
    print("=" * 60)
    print(f"📊 24시간 총 소비 에너지: {sum(r['pred_power'] for r in records):.3f} Wh")
    print(f"☀️  최대 일사량 예측값:    {max(r['pred_insolation'] for r in records):.3f} W/m²")


# ── 메인 ──────────────────────────────────────────────
def main():
    print("🌤 전력 소비량 예측 시스템 시작\n")
    df          = load_data()
    model, X_t, max_val = train_model(df)
    predictions = predict_24h(model, df, X_t, max_val)
    records     = save_to_supabase(predictions)
    print_results(records)
    print("\n✅ 전체 프로세스 완료")


if __name__ == "__main__":
    main()
