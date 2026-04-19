# 국내 Paper 전략 정리 (2026-04)

## 기본 노출 전략 (UI 5종)

1. `swing_relaxed_v2` — 메인 스윙  
2. `final_betting_v1` — 메인 종가베팅  
3. `scalp_macd_rsi_3m_v1` — 메인 장중 3분봉 MACD/RSI  
4. `scalp_momentum_v2` — 실험(보조)  
5. `scalp_momentum_v3` — 실험·고빈도(보조)  

레거시 ID(`swing_v1`, `swing_relaxed_v1`, `bull_focus_v1`, `defensive_v1`, `scalp_momentum_v1`)는 `backend/app/engine/paper_strategy.py` registry에 유지됩니다.

## 추가한 전략

- `app/strategy/scalp_macd_rsi_3m_v1_strategy.py` — `scalp_macd_rsi_3m_v1`  
- 3분 OHLC는 Paper 루프에서 `universe_as_timeframe(..., 3)` 로 생성 (기존 1m 수집 재사용, 추가 preload 없음).

## swing_relaxed_v2 보강

- 당일 거래량 vs 20일 평균 비율로 유동성 하한.  
- 약한 반등·추격 위험 구간 차단.  
- 진단에 `v2_score_breakdown` 필드 추가.

## final_betting_v1 보강

- 14:25~15:20 구간 고점 대비 급락(`late_session_plunge_from_intraday_high`) 차단.  
- 오전 약세·급락 시 빠른 손절 `weak_morning_flush_fast_stop`.  
- 기존 진단에 `score_breakdown`/`late_plunge_pct_from_high` 등 유지·확장.

## scalp_momentum_v2 / v3

- 역할: 실험 축 (`strategy_role`, 한글 `label_ko` in `last_intraday_signal_breakdown`).  
- 동시 포지션 상한: `PAPER_EXPERIMENTAL_SCALP_MAX_OPEN_POSITIONS`.  
- 자본 배분: `PAPER_EXPERIMENTAL_SCALP_ENABLED`, `PAPER_EXPERIMENTAL_SCALP_CAPITAL_PCT` → `resolved_intraday_entry_quantity` 버킷 스케일.

## 리스크·설정

- `effective_intraday_max_open_positions()` 로 전략별 상한 교차.  
- 실험 스캘프만 `_experimental_capital_scale` 적용.  
- MACD 전용: `PAPER_SCALP_MACD_MAX_OPEN_POSITIONS`, 장 시작/종료 진입 금지 분.

## Render / 성능

- 전략 모듈은 요청 시 import, 네트워크 호출 없음.  
- 분봉 집계는 기존 틱 경로와 동일.

## 테스트

- `tests/test_scalp_macd_rsi_3m_v1_smoke.py` — 합성 데이터 스모크.  
- Paper 로그 기반 성과 비교는 운영 데이터 필요 시 별도 노트북/백테스트 권장.

## 재배포

- 백엔드(Python) 변경 포함 → 서버 재배포 필요.  
- 데스크톱/모바일 클라이언트는 전략 목록 UI만 변경 → 앱 재빌드 시 반영.

## 사용자 다음 액션 (1개)

- Render(또는 백엔드 호스트)에 본 커밋 배포 후, 앱에서 **기본 전략 `swing_relaxed_v2` 또는 `scalp_macd_rsi_3m_v1`** 로 Paper 세션을 한 번 시작해 `tick_report.last_intraday_signal_breakdown` 에 `strategy_role` / 진단 필드가 오는지 확인하세요.
