# Security Design

## 목적

설치형 앱(모바일/데스크톱) 기반 자동매매 플랫폼에서, 민감정보 보호와 실주문 오작동 방지를 위한 보안 설계를 정의합니다.

## 핵심 원칙

- 기본 모드는 `paper trading`
- `live trading`은 기본 잠금
- 민감정보는 서버에서만 암호화 저장
- 주문 경로는 반드시 서버를 통해서만 접근
- **월 15%는 연구 목표이며, 보장 수익이 아님**

## 왜 앱에서 직접 한투 API를 호출하지 않는가

- 앱에 키를 포함하면 추출/복제 리스크가 매우 높습니다.
- 리스크 승인 로직을 우회하는 주문 경로가 생길 수 있습니다.
- 사용자/관리자 권한 통제와 감사 로그를 일관되게 유지하기 어렵습니다.

## 왜 서버 저장/암호화 구조가 필요한가

- 사용자별 브로커 계정을 분리 관리할 수 있습니다.
- 키/시크릿/계좌정보를 암호화 저장해 평문 노출을 줄입니다.
- 토큰 발급/연결 테스트/주문 허용 여부 검증을 서버 단에서 통합합니다.

## 계층별 보안 책임

- Mobile/Desktop:
  - JWT 기반 접근
  - 민감정보 장기 저장 금지
  - 서버 API만 호출
- Backend:
  - 인증/권한 확인
  - 브로커 비밀정보 암호화 저장
  - 리스크 엔진/kill switch 강제
  - live unlock 다단계 검증

## live trading 안전장치

실주문 허용 조건(모두 충족):

1. `TRADING_MODE=live`
2. `LIVE_TRADING=true`
3. `LIVE_TRADING_CONFIRM=true`
4. 앱 live enable flag
5. 앱 secondary confirmation
6. 앱 extra approval
7. 계좌/손실 한도 검증 통과

하나라도 불충족 시 live 주문 차단.

## 운영 보안 체크

- 설정 변경 이력(log/history) 저장
- 손실 제한 초과 시 경고 + 차단 유지
- runtime safety validation API로 차단 사유 노출
- 비밀정보 로그 출력 금지
