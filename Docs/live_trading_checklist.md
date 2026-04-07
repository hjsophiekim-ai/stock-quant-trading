# Live Trading Checklist

실거래 전 아래 항목을 모두 통과해야 합니다.

## 1) 필수 안전 플래그

- [ ] `TRADING_MODE=live`
- [ ] `LIVE_TRADING=true`
- [ ] `LIVE_TRADING_CONFIRM=true`
- [ ] `LIVE_TRADING_EXTRA_CONFIRM=true` (추가 확인 플래그)
- [ ] `LIVE_ORDER_DRY_RUN_LOG=true` (초기 운영 권장)

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
# Live Trading Checklist

실거래 전 아래 항목을 모두 통과해야 합니다.

## 1) 설정 확인

- [ ] `TRADING_MODE=live`
- [ ] `LIVE_TRADING=true`
- [ ] `LIVE_TRADING_CONFIRM=true` (추가 확인 플래그)
- [ ] `KIS_ACCOUNT_NO` 설정 완료
- [ ] `KIS_ACCOUNT_PRODUCT_CODE` 설정 완료
- [ ] `LIVE_ORDER_DRY_RUN_LOG=true` 유지(초기 운영 권장)

## 2) 안전 점검 스크립트

- [ ] `python scripts/check_runtime_safety.py` 실행
- [ ] blocker 없이 PASS 확인

## 3) API 연결 점검

- [ ] `python scripts/check_kis_connection.py` 성공
- [ ] `python scripts/check_kis_quotes.py` 성공
- [ ] 조회 API 응답 필드 검증 완료

## 4) 리스크 엔진 점검

- [ ] 일일 손실 제한(-3%) 동작 확인
- [ ] 총 손실 제한(-10%) 동작 확인
- [ ] rolling loss limit/cooldown 동작 확인
- [ ] 손절 우선 규칙 동작 확인

## 5) 운영 중단 경로

- [ ] 계좌 손실 제한 초과 시 자동 shutdown 경로 확인
- [ ] 긴급 중단(킬스위치) 수동 절차 문서화
- [ ] 로그/알림 경로 정상 동작 확인

## 6) 보안

- [ ] 비밀키/토큰을 코드/로그에 출력하지 않음
- [ ] `.env` 외 민감정보 저장 금지
- [ ] 저장소 커밋 전 민감정보 누락 점검

## 핵심 원칙

- 기본값은 항상 `paper` 유지
- 이중 확인(`LIVE_TRADING` + `LIVE_TRADING_CONFIRM`) 없이는 실주문 금지
- 손실 제한 위반 시 즉시 거래 중단/종료
