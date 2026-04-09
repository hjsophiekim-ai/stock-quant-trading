# 초보자용: 오늘 바로 실행 체크리스트 (Windows · Python 3.11)

저장소 루트에서 백엔드를 띄우고 Swagger로 주요 API까지 확인하는 **최소 순서**입니다.  
**Google Drive·OneDrive 동기화 폴더**에서는 `pip`/`npm` 설치가 실패할 수 있으므로, 가능하면 **`C:\dev\...` 등 로컬 디스크**에 클론하세요.

---

## 0. 선행 조건

| 항목 | 확인 |
|------|------|
| OS | Windows 10/11 |
| Python | **3.11 이상** (`python --version`) |
| Git | 저장소 클론 완료 |
| 한국투자 | 모의투자 앱키·앱시크릿·모의계좌(선택, KIS API 호출 시 필요) |

---

## 1. 가상환경 · 의존성 (저장소 루트)

PowerShell 예시:

```powershell
cd C:\dev\stock-quant-trading
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip setuptools wheel
python -m pip install -e .
```

---

## 2. `.env.paper` → `.env`

1. `env.paper.example` 을 복사해 **`.env.paper`** 를 만듭니다.  
2. 아래를 채웁니다(모의 기준).  
   - `APP_SECRET_KEY` — 16자 이상 임의 문자열 권장  
   - `KIS_APP_KEY`, `KIS_APP_SECRET`  
   - `KIS_ACCOUNT_NO`, `KIS_ACCOUNT_PRODUCT_CODE` (예: `01`)  
   - `TRADING_MODE=paper`, `LIVE_TRADING*` 는 `false` 유지  
3. 검토 후 **`.env`** 로 복사합니다 (백엔드는 **`.env`만** 자동 로드).

```powershell
copy /Y .env.paper .env
# 또는: Copy-Item .env.paper .env
```

**`package.json` 을 찾을 수 없다**는 오류는 보통 **작업 폴더가 저장소 루트가 아닐 때** 납니다.

```powershell
Get-Location
Test-Path .\pyproject.toml
Test-Path .\scripts\check_env.py
```

---

## 3. 점검 스크립트 (저장소 루트에서)

```powershell
python scripts\check_env.py
python scripts\check_runtime_safety.py
```

- `[PASS]` 가 나오면 다음으로 진행합니다.  
- `[BLOCKERS]` 가 있으면 메시지대로 `pip install -e .` 또는 `.env` 를 수정합니다.

---

## 4. 백엔드 기동

```powershell
scripts\run_backend.bat
```

- 콘솔에 `http://127.0.0.1:8000` · `/docs` 안내가 나옵니다.  
- 브라우저에서 **http://127.0.0.1:8000/docs** (Swagger) 를 엽니다.

**빌드/테스트 중 이전 Electron·앱이 `dist` 를 잠그지 않았는지** 데스크톱 빌드와는 별개로, 백엔드만 쓸 때는 보통 문제 없습니다.

---

## 5. Swagger에서 API 순서 (인증 필요한 경로는 Authorize)

아래 경로는 모두 **`/api` 접두사**가 붙습니다. Swagger 상단 **Authorize**에 `Bearer <access_token>` 을 넣은 뒤 호출하세요.

| 순서 | 메서드 | 경로 | 비고 |
|------|--------|------|------|
| 1 | POST | `/api/auth/register` | Body: email, password 등 |
| 2 | POST | `/api/auth/login` | 응답의 `access_token` 복사 → Authorize |
| 3 | POST | `/api/broker-accounts/me` | JWT 필요. 모의 계좌 정보 |
| 4 | POST | `/api/broker-accounts/me/test-connection` | 연결 성공 시 paper trading 조건 충족 |
| 5 | POST | `/api/screening/refresh` | 스크리너 갱신(서버 `.env` KIS 키 필요) |
| 6 | POST | `/api/strategy-signals/evaluate` | 유니버스·KIS 일봉 필요. 비어 있으면 `SCREENER_UNIVERSE_SYMBOLS` 또는 기본 종목 문자열 확인 |
| 7 | POST | `/api/paper-trading/start` | JWT, Body: `{"strategy_id":"swing_v1","link_runtime_engine":true}` 등 |
| 8 | POST | `/api/portfolio/sync` | 서버 `.env` 의 KIS 계좌 기준 동기화 |
| 9 | GET | `/api/dashboard/summary` | 선택적으로 Authorization 헤더(브로커 스냅샷) |
| 10 | GET | `/api/performance/metrics` | 스냅샷·이력 기반 |

- **`/api/health`** 는 인증 없이 200 이면 서버 정상입니다.

---

## 6. 산출물 확인

- 백엔드 로그에 오류가 없고, Swagger에서 위 순서가 **4xx/5xx 없이** 이어지면 성공에 가깝습니다.  
- `POST /api/portfolio/sync` 이후 `GET /api/portfolio/summary` 로 스냅샷 존재를 확인할 수 있습니다.

---

## 자주 막히는 지점 (요약)

1. **`.env` 없음** → `copy /Y .env.paper .env` 후 서버 재시작.  
2. **Python 3.10 이하** → 3.11+ 설치 후 venv 재생성.  
3. **모듈 없음** → 저장소 루트에서 `pip install -e .`.  
4. **KIS 토큰/종목 오류** → `.env` 키·계좌·모의 호스트, 방화벽, 장 운영 시간대 확인.  
5. **401 on paper-trading** → Swagger **Authorize**에 로그인 토큰 넣었는지 확인.

더 상세한 단계는 **[Docs/quickstart_real_mock_trading.md](./quickstart_real_mock_trading.md)** 를 참고하세요.
