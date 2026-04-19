# Paper 전략: `scalp_rsi_flag_hf_v1`

## 목적

- **일중 다회** 완료 거래(페이퍼)를 현실적으로 늘리되, 킬 스위치·일손실·롤링 손실·중복 주문 방지 등 **기존 안전장치를 유지**한다.
- 백테스트 최적화가 아니라 **실행 가능한 필터·진단**을 우선한다.

## 로직 요약

- **봉**: 백엔드에서 1분봉을 **3분봉으로 리샘플** (`universe_as_timeframe(..., 3)`).
- **매수 (red flag)**  
  - `app/strategy/rsi_flag_helpers.evaluate_rsi_red_flag_buy`  
  - 서브 경로 3개(과매도 반전, VWAP/EMA 재탈환, 플러시 후 양봉) 중 **최소 점수** `PAPER_RSI_HF_MIN_ENTRY_SCORE` (기본 2).  
  - 유동성·스프레드·추격 캔들 필터. (VWAP/EMA 연속성은 진단 필드 `optional_vwap_ema_score` 로만 기록.)
- **매도 (blue flag 우선)**  
  - `evaluate_rsi_blue_flag_sell`: RSI 과매수 꺾임, MACD 히스토그램 약화, VWAP 위 확장 후 실패 캔들 등.  
  - 그 다음 고정 **손절/익절/트레일/시간** 및 **장마감 강제청산**.

## 진단 필드 (전략·헬퍼)

| 필드 | 의미 |
|------|------|
| `rsi_red_flag_buy` | red 플래그 통과 여부 |
| `rsi_red_flag_reason` | 세부 이유(세미콜론 구분) |
| `rsi_blue_flag_sell` | blue 플래그 |
| `rsi_blue_flag_reason` | 세부 이유 |
| `rsi_red_path_hits` | red 서브 경로 충족 개수(0~3) |

## 환경 변수 (주요)

| 변수 | 기본 | 설명 |
|------|------|------|
| `PAPER_INTRADAY_MAX_TRADES_PER_DAY` | 48 | 일일 매수 체결 상한(전 인트라데이 공통) |
| `PAPER_RSI_HF_MAX_OPEN_POSITIONS` | 4 | 동시 보유 종목 상한 |
| `PAPER_RSI_HF_MAX_TRADES_PER_SYMBOL_DAY` | 4 | 종목별 일 매수 체결 상한 |
| `PAPER_RSI_HF_MIN_ENTRY_SCORE` | 2 | red 서브조건 최소 개수 |
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
