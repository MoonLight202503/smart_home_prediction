# 🌤 태양광 일사량 예측 및 전력 소비량 계산 시스템

기상청 ASOS API로 서울 기상 데이터를 수집하고, LSTM 모델로 다음날 24시간 일사량과 전력 소비량을 예측합니다.

---

## 📁 프로젝트 구조

```
├── autoweatherrecordtosupabase.py   # 매시간 기상 데이터 수집
├── power_prediction.py              # 매일 07시 LSTM 예측 + 전력 계산
├── bulk_insert_historical.py        # 최초 1회 과거 데이터 bulk insert
├── requirements.txt
└── .github/
    └── workflows/
        ├── collect_weather.yml      # 매시간 수집 자동화
        └── predict_daily.yml        # 매일 07시 예측 자동화
```

---

## ⚙️ 동작 흐름

```
[매시간] 기상청 API → r_weather_data (Supabase)
                              ↓
[매일 07시] LSTM 학습 → 24시간 예측 → prediction (Supabase)
```

---

## 🗄️ Supabase 테이블

### r_weather_data
| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL | PK |
| r_timestamp | TIMESTAMP (UNIQUE) | 관측 시각 |
| r_temperature | FLOAT | 기온 (°C) |
| r_humidity | FLOAT | 습도 (%) |
| r_insolation | FLOAT | 일사량 (MJ/m²) |

### prediction
| 컬럼 | 타입 | 설명 |
|------|------|------|
| prediction_id | BIGSERIAL | PK |
| predicted_time | TIMESTAMP | 예측 시각 |
| pred_insolation | FLOAT | 예측 일사량 (W/m²) |
| pred_power | FLOAT | 예측 소비전력 (W) |
| timestamp | TIMESTAMP | 예측 실행 시각 |

SQL:
```sql
CREATE TABLE r_weather_data (
    id            BIGSERIAL PRIMARY KEY,
    r_timestamp   TIMESTAMP UNIQUE,
    r_temperature FLOAT,
    r_humidity    FLOAT,
    r_insolation  FLOAT
);

CREATE TABLE prediction (
    prediction_id   BIGSERIAL PRIMARY KEY,
    predicted_time  TIMESTAMP,
    pred_insolation FLOAT,
    pred_power      FLOAT,
    timestamp       TIMESTAMP
);
```

---

## 🔐 GitHub Secrets 설정

저장소 → Settings → Secrets and variables → Actions → New repository secret

| Secret 이름 | 값 |
|------------|-----|
| SUPABASE_URL | Supabase 프로젝트 URL |
| SUPABASE_KEY | Supabase anon key |
| KMA_API_KEY | 기상청 API 인증키 |

---

## 🚀 시작하기

### 1. 최초 1회 — 과거 데이터 적재 (로컬 실행)
```bash
pip install requests supabase
KMA_API_KEY=your_key SUPABASE_KEY=your_key python bulk_insert_historical.py
```
Windows:
```bash
set KMA_API_KEY=your_key
set SUPABASE_KEY=your_key
python bulk_insert_historical.py
```

### 2. GitHub에 push
GitHub Actions가 자동으로:
- 매시간 정각 → 기상 데이터 수집
- 매일 KST 07:00 → 예측 실행

---

## ⚡ 전력 소비량 계산 공식

```
총 소비전력 = 기본(0.6W)
            + LED 5개 × 0.53W × (일사량 / 1000)  ← 일사량 비례
            + RGB 4개 × 0.53W                     ← 고정
            + 서보모터 2개 × 1.53W / 50            ← 고정
            + 센서류 0.3W                           ← 고정
```
