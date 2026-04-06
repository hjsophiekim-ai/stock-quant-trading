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
