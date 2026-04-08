# 빠른 시작: 한국투자 모의계좌 + 백엔드 + Paper Trading (초보자)

이 문서는 **git clone 후 최소 단계**로 로컬 백엔드를 띄우고, **모의투자 API**와 **앱 계정·브로커 설정**까지 연결하는 순서를 정리합니다.

> **실거래(live) 주문은 이 프로젝트에서 기본 금지입니다.**  
> `TRADING_MODE=live` 와 여러 `LIVE_TRADING*` 확인 플래그가 동시에 켜지지 않으면 실주문 경로는 열리지 않습니다. 초보자는 **paper만** 사용하세요.

---

## 사전 준비

| 항목 | 설명 |
|------|------|
| OS | Windows 10/11, macOS, Linux |
| Python | **3.11 이상** (`pyproject.toml` 기준) |
| 한국투자 | [KIS 개발자센터](https://apiportal.koreainvestment.com/)에서 **모의투자** 앱키·앱시크릿·모의계좌 |

---

## 1. `.env.paper` 만들기

저장소 루트에 있는 **`env.paper.example`** 을 복사해 **`.env.paper`** 파일을 만듭니다.

**Windows (PowerShell, 저장소 루트에서)**

```powershell
Copy-Item env.paper.example .env.paper
```

**macOS / Linux**

```bash
cp env.paper.example .env.paper
```

메모장/VS Code로 `.env.paper` 를 열고 아래를 채웁니다.

- `APP_SECRET_KEY` — 16자 이상 임의 문자열 (JWT·브로커 암호화에 사용)
- `KIS_APP_KEY`, `KIS_APP_SECRET` — 모의투자용 앱키
- `KIS_ACCOUNT_NO` — 모의 계좌번호(CANO, 보통 8자리)
- `KIS_ACCOUNT_PRODUCT_CODE` — 예: `01`

`TRADING_MODE=paper` 와 모든 `LIVE_TRADING*` 가 `false` 인지 다시 확인합니다.

---

## 2. `.env` 로 복사

백엔드(`BackendSettings` / `Settings`)는 기본적으로 **루트의 `.env`만** 읽습니다.

**Windows**

```powershell
Copy-Item .env.paper .env
```

**macOS / Linux**

```bash
cp .env.paper .env
```

> `.env`, `.env.paper` 는 **절대 Git에 커밋하지 마세요.** (`.gitignore`에 포함됨)

---

## 3. 가상환경 만들기·활성화

**Windows (PowerShell)**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

---

## 4. 필요한 패키지 설치

저장소 **루트**에서 (가상환경 활성화 후):

```bash
python -m pip install -U pip setuptools wheel
python -m pip install -e .
```

- `pytest` 로 테스트까지 돌릴 때: `python -m pip install -e ".[dev]"`
- 의존성 목록만 파일로 보고 싶으면: `requirements/backend.txt` (단, **editable 없이** `pip install -r` 만 하면 `app`/`backend` 패키지는 설치되지 않으므로, 일반적으로는 **`pip install -e .`** 권장)

---

## 5. 환경·안전 점검

```bash
python scripts/check_env.py
python scripts/check_runtime_safety.py
```

둘 다 `[PASS]` 가 나오면 다음 단계로 갑니다.

---

## 6. Backend 실행

**Windows**

```bat
scripts\run_backend.bat
```

**macOS / Linux**

```bash
bash scripts/run_backend.sh
```

브라우저에서 **http://127.0.0.1:8000/docs** (Swagger UI) 가 열리면 성공입니다.

---

## 7. Swagger에서 회원가입·로그인

Swagger (`/docs`)에서 순서대로 호출합니다.

1. **`POST /api/auth/register`**  
   - Body 예:  
     `{ "email": "you@example.com", "password": "yourpassword8+", "display_name": "홍길동", "role": "user" }`
2. **`POST /api/auth/login`**  
   - 같은 이메일·비밀번호로 로그인  
   - 응답의 **`access_token`** 을 복사합니다.

이후 브로커 API 호출 시 Swagger 상단 **Authorize** 에 `Bearer <access_token>` 형식으로 넣습니다.

---

## 8. Broker account 등록

Swagger에서 **`POST /api/broker-accounts/me`** (Authorize 필요)

Body 예 (모의 계좌 기준):

```json
{
  "kis_app_key": "<모의 앱키>",
  "kis_app_secret": "<모의 앱시크릿>",
  "kis_account_no": "<모의 CANO>",
  "kis_account_product_code": "01",
  "trading_mode": "paper"
}
```

서버에 암호화 저장됩니다. 키는 앱에 직접 넣지 않고 **서버에만** 등록하는 흐름이 안전합니다.

---

## 9. Connection test (연결 테스트)

Swagger **`POST /api/broker-accounts/me/test-connection`** (Authorize 필요)

또는 런타임용 키 검증만 할 때:

**`POST /api/broker-accounts/runtime/test-connection`** (인증 없음, `.env` 의 KIS 키 기준)

`ok: true` 가 나오면 토큰 발급까지 통과한 것입니다.

---

## 10. Paper trading 시작 (앱·KIS 모의 세션)

Paper 자동매매는 **인메모리 데모가 아니라**, 앱에 등록한 **사용자 KIS 모의 계정**으로 백그라운드 틱이 돌고 **모의 주문 API**를 사용합니다. 기본값으로 `POST /api/paper-trading/start` 호출 시 전역 런타임 엔진도 함께 시작됩니다(`link_runtime_engine=true`).

### 필수 조건

- `POST /api/broker-accounts/me` 로 **모의** 계정 등록, **`trading_mode`: `"paper"`**
- `POST /api/broker-accounts/me/test-connection` → `ok: true`
- 서버가 브로커에 대해 **openapivts(모의 호스트)** 만 허용하는지 검증함 — 실전 호스트면 시작 거부

### API (JWT 필요: start / stop / risk-reset)

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/api/paper-trading/start` | Body: `{ "strategy_id": "swing_v1" \| "bull_focus_v1" \| "defensive_v1", "link_runtime_engine": true }` (`live` 등은 거부) |
| POST | `/api/paper-trading/stop` | 세션 중지(시작한 사용자만) |
| POST | `/api/paper-trading/risk-reset` | `risk_off` 해제 후 루프 재개(시작한 사용자만) |
| GET | `/api/paper-trading/status` | `running` / `stopped` / `risk_off`, 전략, 마지막 틱, 실패 연속 등 |
| GET | `/api/paper-trading/positions` | 마지막 틱 이후 스냅샷 포지션 |
| GET | `/api/paper-trading/pnl` | 마지막 틱 리포트 기준 손익 요약 |
| GET | `/api/paper-trading/logs` | 최근 로그 |

**동시 세션:** 서버당 **한 명**만 Paper 세션 가능. 다른 사용자가 이미 켜 두었으면 `409`.

**오류·안전:** 틱이 연속으로 실패하면 `risk_off` 로 전환. 원인 확인 후 `risk-reset` 또는 중지.

### 앱에서

모바일·데스크톱 **Paper Trading** 화면: 연결 테스트 통과 후 **시작 / 중지 / risk 해제**, 전략 선택, 로그·포지션·손익 표시. 앱은 약 15초마다 상태를 다시 불러옵니다.

### CLI로 빠르게 점검

백엔드가 켜진 상태에서 (로그인 또는 토큰 필요):

```bash
python scripts/start_paper_trading_demo.py --email you@example.com --password '***'
# 또는 --access-token 'eyJ...'
# 기본 strategy_id 는 swing_v1
```

옵션 `--sync-portfolio` 는 시작 후 **`POST /api/portfolio/sync`** 를 호출합니다. 이 동기화는 **서버 `.env` 의 KIS** 를 사용하므로, 앱에 저장한 모의 계정과 **다르면** 스냅샷이 Paper 주문과 맞지 않을 수 있습니다. 가능하면 **`.env` 와 앱 브로커를 동일 모의 계정**으로 맞추세요.

### 전역 런타임 엔진(선택/수동)

`.env` 기반 자동 루프·리스크는 Swagger **`POST /api/runtime-engine/start`** 로도 수동 시작할 수 있습니다. 실패 누적 시 `risk_off` 로 전환되며 `POST /api/runtime-engine/risk-reset` 후 재개합니다.

---

## 10-B. Swagger 11단계 E2E (회원가입 -> 주문 -> 결과)

아래 순서대로 호출하면 end-to-end를 검증할 수 있습니다.

1) `POST /api/auth/register`  
2) `POST /api/auth/login` (Bearer 토큰 획득)  
3) `POST /api/broker-accounts/me` (JWT, `trading_mode=paper`)  
4) `POST /api/broker-accounts/me/test-connection` (JWT)  
5) `POST /api/screening/refresh`  
6) `POST /api/strategy-signals/evaluate`  
7) `POST /api/order-engine/execute-signal` (내부 리스크 승인 포함)  
8) Step 7 응답에서 KIS mock 주문 호출/결과 확인  
9) `GET /api/order-engine/tracked` + `POST /api/order-engine/sync`  
10) `POST /api/portfolio/sync` -> `GET /api/portfolio/summary`  
11) `GET /api/dashboard/summary` + `GET /api/performance/metrics`

상세 계약/예시 요청 바디는 `docs/e2e_mock_trading.md` 참고.

---

## 초보자용 단계별 체크리스트

인쇄하거나 메모장에 복사해 순서대로 체크하세요.

- [ ] Python 3.11+ 설치됨 (`python --version`)
- [ ] `git clone` 후 저장소 루트로 이동함
- [ ] `env.paper.example` → `.env.paper` 복사 후 값 입력
- [ ] `.env.paper` → `.env` 복사 완료
- [ ] `python -m venv .venv` 후 가상환경 활성화
- [ ] `pip install -e .` 성공
- [ ] `python scripts/check_env.py` → PASS
- [ ] `python scripts/check_runtime_safety.py` → PASS
- [ ] `scripts/run_backend.bat` 또는 `bash scripts/run_backend.sh` 로 서버 기동
- [ ] http://127.0.0.1:8000/docs 접속됨
- [ ] `POST /api/auth/register` → `POST /api/auth/login` → `access_token` 확보
- [ ] Swagger Authorize 에 Bearer 토큰 입력
- [ ] `POST /api/broker-accounts/me` 로 계좌 등록
- [ ] `POST /api/broker-accounts/me/test-connection` → ok
- [ ] 앱 Paper Trading 또는 Swagger `POST /api/paper-trading/start` (JWT·paper·연결 성공) / 필요 시 `risk-reset`
- [ ] `POST /api/portfolio/sync` 후 `GET /api/portfolio/summary` 로 손익 확인
- [ ] 실거래는 시도하지 않음 (`TRADING_MODE=paper` 유지)

---

## 흔한 오류와 해결법

| 증상 | 원인 | 조치 |
|------|------|------|
| `ModuleNotFoundError` | 패키지 미설치 | 가상환경 활성화 후 `pip install -e .` |
| `uvicorn` 를 찾을 수 없음 | venv 밖에서 실행 | `run_backend` 스크립트는 `.venv` 의 python 우선 사용 |
| `.env` 없음 경고 | 파일 누락 | `.env.paper` 를 `.env` 로 복사 |
| KIS 토큰 실패 / `401` | 앱키·시크릿·모의/실전 URL 불일치 | `TRADING_MODE=paper` 이면 **모의** 키 + `openapivts` URL 사용 |
| `KIS_ACCOUNT_NO` 오류 | 계좌번호 자릿수·하이픈 | CANO 숫자만 (보통 8자리), 상품코드 `01` 등 |
| `register` 실패 | 비밀번호 짧음 | 8자 이상, `display_name` 필수 |
| `broker-accounts` 401 | 토큰 없음 | Swagger Authorize 에 Bearer 입력 |
| Paper start 409 | 다른 사용자 세션 실행 중 | 해당 세션 중지 후 재시도 |
| Paper start 403 (paper/trading_mode) | live 브로커 또는 모의 호스트 아님 | 브로커를 paper·openapivts 로 저장 |
| `portfolio/sync` 503 | 토큰·계좌·네트워크 | `.env` 키·계좌 확인, 한투 API 점검 시간대 확인 |
| 포트 8000 사용 중 | 다른 프로세스 | `--port 8001` 로 uvicorn 실행 또는 프로세스 종료 |

---

## live trading 관련 (읽기만)

- **실주문은 기본 잠금**입니다. 실전 전용 체크리스트는 `docs/live_trading_checklist.md` 를 따르세요.
- 이 quickstart는 **모의(paper)** 만 대상으로 합니다.

---

## 다음에 읽을 문서

- `README.md` — 모노레포 개요  
- `AGENTS.md` — 안전·API 경계 정책  
- `docs/system_design.md` — 시스템 설계  
