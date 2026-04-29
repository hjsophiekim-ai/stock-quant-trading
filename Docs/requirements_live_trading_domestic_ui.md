# 국내 Live 화면 요구사항

이 문서는 데스크톱 국내 Live 화면의 사용자 요구 UI/동작을 정의합니다.

## 1) 목표

- 메인 화면은 “콘솔/Raw JSON” 중심이 아니라 **전략 탭 + 후보/주문 표 + 계좌 표** 중심이어야 합니다.
- Auto Run(자동매매)은 사용자 선택 전략이 실제 평가/결정 경로에 반영되어야 합니다.
- Raw/진단 정보는 기본 숨김이며, 상세보기에서만 확인합니다.

## 2) 용어

- 후보만 보기 = live_shadow
- 자동매매 = live_auto_guarded
- 지금 한 번 판단 = tick
- 실주문 가능 = can_place_auto_order / can_place_live_order (UI는 “실주문 가능”으로 표시)

## 3) 메인 화면 구조

### 3.1 상단 요약 바

한 줄 카드/배지로 표시:

- LIVE 주문 가능 / 차단
- 자동매매 실행중 / 정지
- 선택 전략
- Market Mode
- 최근 Tick
- 오늘 매수/매도 수
- Emergency Stop
- 검증 우회 중이면 “검증 우회 중” 배지

### 3.2 전략 탭

탭:

- final_betting
- RSI 고빈도
- MACD RSI 3m
- Swing
- Multi

각 탭은 동일한 레이아웃을 사용합니다.

### 3.3 전략 컨트롤 카드

각 탭 내부:

- 전략명
- 추천 시간
- 모드 선택: aggressive / auto / passive
- 후보만 보기 버튼
- 자동매매 시작 버튼
- 자동매매 중지 버튼
- 지금 한 번 판단 버튼
- 자동 루프 ON/OFF 표시

### 3.4 Shadow 후보 표

컬럼:

- 상태
- 순위
- 종목
- 방향
- 수량
- 기준가
- 점수
- 이유
- 갱신시간

후보가 없으면 빈 표 대신:

- “현재 조건을 만족한 후보가 없습니다.”
- 가능하면 이유:
  - 시간대 아님
  - 시장 모드 neutral/passive
  - 조건 미충족
  - 데이터 부족
  - KIS 조회 실패

### 3.5 Auto Run 후보/주문 판단 표

Auto Guarded의 마지막 평가 결과를 표로 표시합니다.

컬럼:

- 상태: 후보 / 주문됨 / 거절 / 차단
- 순위
- 전략
- 종목
- 방향
- 수량
- 예상금액
- 점수
- 이유
- 주문 ID
- 시간

중요:

- Raw JSON에 last_eval_candidates가 있으면 메인 표는 비어 있으면 안 됩니다.
- state.enabled=false여도 마지막 평가 결과는 “마지막 판단 결과”로 유지해 보여줍니다.

### 3.6 주문/계좌 현황 카드

표 3개:

- 보유 포지션
- 미체결 주문
- 최근 체결

보유 포지션 컬럼:

- 종목
- 수량
- 평균단가
- 현재가
- 평가금액
- 손익률

미체결 주문 컬럼:

- 주문번호
- 종목
- 매수/매도
- 남은수량
- 가격
- 시간

최근 체결 컬럼:

- 종목
- 매수/매도
- 수량
- 가격
- 주문번호
- 체결시간

### 3.7 상세보기 / 진단 로그

아래 항목은 모두 `<details>` 안에 넣고 기본 닫힘 상태:

- Live 실행 콘솔
- Raw status JSON
- Auto Guarded Raw JSON
- Runtime Safety JSON
- Paper Readiness JSON
- Readiness Builder JSON
- Readiness 데이터 상태
- Market Mode Raw JSON
- final_betting fetch_summary
- last_diagnostics
- rejection_reasons_by_symbol
- Sell-Only Arm
- 전체 청산
- Liquidation Raw

## 4) Auto Run(자동매매) 전략 선택 규칙

- Start/Save Strategy 시 선택 전략을 state.selected_strategy에 저장합니다.
- Tick 전략 선택 우선순위:
  1) UI에서 저장된 state.selected_strategy
  2) LIVE_AUTO_STRATEGY env
  3) 기본값 final_betting_v1

지원 전략:

- final_betting_v1
- scalp_rsi_flag_hf_v1
- scalp_macd_rsi_3m_v1
- swing_relaxed_v2
- multi

## 5) 성공 조건

- selected_strategy가 저장되면 tick 결과에 반영되어야 합니다.
- final_betting 시간이 아니어도 scalp 전략은 평가되어야 합니다.
- 후보가 있으면 last_eval_candidates에 표시되어야 합니다.
- 실주문 가능 상태에서 후보가 있으면 submitted.buys / submitted.sells에 제출 결과가 표시되어야 합니다.
