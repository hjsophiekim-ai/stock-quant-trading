# Live Trading Checklist

실거래 전 아래 항목을 모두 통과해야 합니다.

## 1) 필수 안전 플래그

- [ ] `TRADING_MODE=live`
- [ ] `LIVE_TRADING=true`
- [ ] `LIVE_TRADING_CONFIRM=true`
- [ ] `LIVE_TRADING_EXTRA_CONFIRM=true` (추가 확인 플래그)
- [ ] `LIVE_ORDER_DRY_RUN_LOG=true` (초기 운영 권장)
- [ ] (옵션) `LIVE_AUTO_STRATEGY=<strategy_id>` 설정 시 기본 자동매매 전략 힌트로 사용됨(사용자 선택 전략이 우선)

## 2) 계좌/경로 검증

- [ ] `KIS_ACCOUNT_NO` 설정 완료
- [ ] `KIS_ACCOUNT_PRODUCT_CODE` 설정 완료
- [ ] 모의투자(`PaperBroker`)와 실거래(`LiveBroker`) 경로가 혼합되지 않음
- [ ] startup safety validation 통과 상태 확인

## 3) 런타임 안전 점검

- [ ] `python scripts/check_runtime_safety.py` 실행
- [ ] blocker 없이 PASS 확인
- [ ] live 모드에서 미충족 항목이 있으면 주문이 차단되는지 확인

## 4) 주문 전 검증/로그

- [ ] live 주문 전 dry-run 로그 출력 확인
- [ ] 로그에 계좌 전체번호/비밀정보가 출력되지 않음
- [ ] 주문 차단 메시지가 원인(`reason`)을 명확히 포함

## 5) 장애 대응

- [ ] 운영 장애 시 즉시 주문 중지 절차(킬스위치) 확인
- [ ] 일일/총손실/rolling loss/cooldown 동작 확인
- [ ] API 장애 시 신규 주문 차단 경로 확인

## 6) Auto Guarded(전략별 자동매매) 점검

- [ ] 최초 운영은 `passive`로 시작해 후보/차단 사유/시간대가 기대대로 표시되는지 확인
- [ ] `auto/aggressive`에서 제출이 발생하는 경우, 1틱당 제출 상한/중복가드/보유가드가 의도대로 동작하는지 확인
- [ ] 마지막 판단 결과가 enabled=false 상태에서도 유지되어 표시되는지 확인

## 핵심 원칙

- 기본값은 항상 `paper` 유지
- 다중 플래그 + 앱 승인 + 런타임 안전검증 미충족이면 실주문은 반드시 차단
- 손실 제한 위반 시 즉시 거래 중단/종료
