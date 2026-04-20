# Paper 전략: `scalp_rsi_flag_hf_v1` / `intraday_rsi_flag_hf_v1`

## 목적

- **일중 다회** 완료 거래(페이퍼)를 현실적으로 늘리되, 킬 스위치·일손실·롤링 손실·중복 주문 방지 등 **기존 안전장치를 유지**한다.
- 백테스트 최적화가 아니라 **실행 가능한 필터·진단**을 우선한다.

`intraday_rsi_flag_hf_v1`은 동일 구현(`ScalpRsiFlagHfV1Strategy`)에 **다른 paper strategy_id**만 부여한 별칭이다. 주문·진단의 `strategy_profile` / `strategy_name`은 선택한 ID를 따른다.

## 로직 요약

- **봉**: 백엔드에서 1분봉을 **3분봉으로 리샘플** (`universe_as_timeframe(..., 3)`).
- **매수 (두 경로 중 하나)**  
  1. **반전(reversal)**: `rsi_red_flag_buy` (= `evaluate_rsi_red_flag_buy`) — 서브 경로 3개(과매도 반전, VWAP/EMA 재탈환, 플러시 후 양봉) 중 **최소 점수** `PAPER_RSI_HF_MIN_ENTRY_SCORE` (기본 2).  
  2. **모멘텀 연속(momentum continuation)**: `evaluate_momentum_continuation_entry` — VWAP·EMA 스택·근접 고점·RSI 연속 구간·저점 구조 등 **구조 히트** + 적응형 거래량 + blow-off / late vertical 스파이크 차단.  
  - 장세·시간대·대형 유동성(리더) 프로필에 따라 **거래량 z/ratio 바닥이 달라짐**(진단: `adaptive_volume_*_detail`, `volume_confirmation_*`).  
  - 유동성·스프레드·추격 캔들 필터는 공통. 모멘텀 진입은 **손절 폭을 약간 타이트**(`PAPER_RSI_HF_MOMENTUM_STOP_TIGHTEN_MULT`).  
  - 횡보(`sideways`)에서는 **수량 스케일**(`PAPER_RSI_HF_SIDEWAYS_*_QTY_MULT`)만 줄이고, 강한 단일명은 여전히 후보가 될 수 있음.
- **매도 (blue flag 우선)**  
  - `rsi_blue_flag_sell` (= `evaluate_rsi_blue_flag_sell`): RSI 과매수 꺾임, MACD 히스토그램 약화, VWAP 위 확장 후 실패 캔들 등.  
  - 그 다음 고정 **손절/익절/트레일/시간** 및 **장마감 강제청산**.

## 진단 필드 (전략·헬퍼)

| 필드 | 의미 |
|------|------|
| `rsi_red_flag_buy` | red 플래그 통과 여부 |
| `rsi_red_flag_reason` | 세부 이유(세미콜론 구분) |
| `rsi_blue_flag_sell` | blue 플래그 |
| `rsi_blue_flag_reason` | 세부 이유 |
| `rsi_red_path_hits` | red 서브 경로 충족 개수(0~3) |
| `entry_mode_selected` | `reversal_entry_mode` / `momentum_continuation` / 빈 문자열 |
| `momentum_path_hits` / `momentum_paths_detail` | 모멘텀 경로 히트 및 세부 |
| `min_required_reversal_hits` / `min_required_momentum_hits` | 각 모드별 최소 히트 |
| `volume_confirmation_value` / `volume_confirmation_threshold` / `volume_confirmation_detail` | 적응형 거래량 판정 |
| `strong_override_used` | 대형·고품질 추세에서 거래량 완화가 적용됐는지 |
| `trend_strength_score` / `continuation_quality_score` | 모멘텀 품질 진단(0–100 스케일) |

## 환경 변수 (주요)

| 변수 | 기본 | 설명 |
|------|------|------|
| `PAPER_INTRADAY_MAX_TRADES_PER_DAY` | 48 | 일일 매수 체결 상한(전 인트라데이 공통) |
| `PAPER_RSI_HF_MAX_OPEN_POSITIONS` | 4 | 동시 보유 종목 상한 |
| `PAPER_RSI_HF_MAX_TRADES_PER_SYMBOL_DAY` | 4 | 종목별 일 매수 체결 상한 |
| `PAPER_RSI_HF_MIN_ENTRY_SCORE` | 2 | red 서브조건 최소 개수 |
| `PAPER_RSI_HF_MOMENTUM_MIN_HITS` | 3 | 모멘텀 구조 히트 최소 |
| `PAPER_RSI_HF_MOMENTUM_MIN_HITS_LATE` | 4 | 후반(개장 후 분) 모멘텀 최소 히트 |
| `PAPER_RSI_HF_LEADER_SYMBOLS_CSV` | 005930,000660,005380 | 리더 유동 프로필(거래량 완화 참고) |
| `PAPER_RSI_HF_SIDEWAYS_MOMENTUM_QTY_MULT` | 0.65 | 횡보 시 모멘텀 진입 수량 배율 |
| `PAPER_RSI_HF_SIDEWAYS_REVERSAL_QTY_MULT` | 0.85 | 횡보 시 반전 진입 수량 배율 |
| `PAPER_RSI_HF_MOMENTUM_STOP_TIGHTEN_MULT` | 0.92 | 모멘텀 진입 손절(%) 타이트닝 |
| `PAPER_RSI_HF_LATE_SESSION_OPEN_MINUTES` | 330 | 후반 구간 기준(개장 후 분) |
| `PAPER_INTRADAY_POST_EXIT_COOLDOWN_MINUTES` | 4 | 청산 후 동일 종목 재진입 지연(`final_betting_v1` 제외) |
| `PAPER_INTRADAY_STOP_EXIT_EXTRA_MINUTES` | 6 | **손절** 청산 시 쿨다운 가산 |
| `PAPER_RISK_PER_TRADE_PCT` | 0.45 | 계좌 대비 1회 허용 손실(수량 산출) |

## 알려진 리스크

- **5회/일 평균**은 시장 유동성·필터·모의 계좌 크기에 따라 달라지며 **보장되지 않는다**.
- RSI·MACD는 **지표 지연**이 있으며, 휩소·갭에 취약할 수 있다.
- `OrderRequest.signal_reason`이 청산 후 쿨다운 가산에 사용된다(손절 구분).

## final_betting_v1 최소 배분 (연동)

- `PAPER_FINAL_BETTING_MIN_ALLOCATION_PCT` (기본 **20**)  
- `PAPER_FINAL_BETTING_MAX_CAPITAL_PER_POSITION_PCT` (기본 **25**, 최소 배분보다 커야 함)  
- 리스크 수량이 최소 주수보다 작으면 진입은 **`insufficient_budget_for_min_allocation`** 으로 차단된다.

추가 가드(종가·오버나잇):

| 변수 | 기본 | 설명 |
|------|------|------|
| `PAPER_FINAL_BETTING_MAX_OVERNIGHT_EQUITY_PCT` | 65 | `final_betting_carry`로 추적 중인 포지션 노셔널 합이 평가금 대비 이 비율 이상이면 신규 진입 차단. `0`이면 비활성. |
| `PAPER_FINAL_BETTING_WEAK_CLOSE_RSI_MAX` | 74 | 당일 막바 RSI(14)가 이 값 이상이면 **`weak_close_rsi_high`** 로 진입 차단. |

진단에 `final_betting_overnight_exposure_pct`가 포함될 수 있다.
