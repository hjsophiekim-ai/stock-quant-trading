# Trading Rules

## 문서 목적

자동매매 의사결정을 "수익 최대화"보다 "손실 최소화"에 우선순위를 두고 일관되게 수행하기 위한 규칙을 정의합니다.

## 시장 국면별 운영 원칙

- `bullish_trend`
  - 추세추종 중심으로 진입 기회를 확대
  - 손절 규칙은 유지하되 목표 수익 구간은 상대적으로 넓게 운용
- `bearish_trend`
  - 계좌 방어 최우선
  - 신규 진입 종목 수/종목 비중/손절폭/보유기간을 모두 보수적으로 축소
  - 반등 매매는 짧고 작게만 허용
- `sideways`
  - 평균회귀형 대응만 제한적으로 허용
  - 과매매 방지를 위해 신규 진입 빈도와 크기 축소
- `high_volatility_risk`
  - 신규 진입 원칙적 차단
  - 기존 포지션 리스크 축소/정리 주문만 허용

## 하락장 강화 리스크 규칙

`app/risk/rules.py` 기준:

- 일일 신규 진입 제한
  - `bearish_max_new_entries_per_day` 초과 시 신규 매수 차단
  - reason code: `BLOCK_REGIME_BEARISH_NEW_ENTRY_LIMIT`
- 보유 종목 수 상한 축소
  - `bearish_max_positions` 적용
  - reason code: `BLOCK_REGIME_BEARISH_MAX_POSITIONS`
- 종목당 최대 비중 상한 축소
  - `bearish_max_position_weight` 적용
  - reason code: `BLOCK_REGIME_BEARISH_POSITION_WEIGHT`
- 손절폭 상한 강화
  - `bearish_max_stop_loss_pct` 초과 주문 차단
  - reason code: `BLOCK_REGIME_BEARISH_STOP_LOSS_TOO_WIDE`
- 하락장 승인 주문 추적
  - 보수 규칙 통과 시 reason code: `OK_REGIME_BEARISH_BUY_CONSERVATIVE`

## 고변동성 위험장 규칙

- 신규 매수 차단
  - reason code: `BLOCK_REGIME_HIGH_VOLATILITY_NEW_ENTRY`
- 기존 포지션 리스크 축소용 매도는 허용
  - reason code: `OK_SELL`

## 국면별 포지션 사이징 설정

`app/risk/position_sizing.py` 기준:

- 국면별 설정 객체: `RegimeSizingConfig`
- `bearish_trend` 기본값
  - `max_weight=0.06`, `prefer_weight=0.04`
  - `max_new_entries=1`
  - `max_hold_days=2`
- `high_volatility_risk`
  - `max_weight=0.0`
  - `max_new_entries=0`
  - 신규 진입 수량 0

## 전략 엔진 하락장 강화

`app/strategy/bear_strategy.py` 기준:

- 신규 진입 임계값 강화
  - `rebound_entry_drop_3d_pct=-6.0`
  - `rebound_entry_rsi_max=28.0`
- 보유기간 단축
  - `time_exit_days=1`
- 손절/익절을 짧고 빠르게 운용
  - `stop_loss_pct=1.8`
  - `first_take_profit_pct=2.0`
  - `second_take_profit_pct=3.2`

## 상승장 Trailing Exit 규칙

`app/strategy/bull_strategy.py` 기준:

- 고정 익절 규칙 개선
  - +6% 구간에서 1차 부분익절(잔여 물량 유지)
  - 기존 +10% 도달 즉시 전량 익절 대신, 추세가 유지되면 보유 연장
- 잔여 물량 트레일링 청산
  - 1차 부분익절 완료(`first_take_profit_done`) 이후에만 트레일링 활성화
  - `trailing_mode` 선택 가능
    - `atr`: `highest_price_since_entry - ATR * trailing_atr_multiplier` 하향 이탈 시 청산
    - `n_day_low`: 최근 `trailing_n_day_low_window` 저점 하향 이탈 시 청산
- 추세 약화 시 추가 청산
  - +10% 이상 수익 구간에서 종가가 MA20 아래로 내려오면 전량 청산
- 목적
  - 강한 상승 추세 구간에서 러너 물량을 길게 가져가 수익 확장
  - 급락 전환 시 확보한 이익을 트레일링 스탑으로 보호
