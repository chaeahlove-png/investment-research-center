# Investment Research Center (FREE)

개인 투자 리서치 대시보드. 유료 API 없이 공개 데이터만 사용합니다.

## 자동 업데이트 구조
GitHub Actions(`.github/workflows/update-market-data.yml`) → `scripts/fetch_market.py` 실행
→ `data/market.json` 저장 → GitHub Pages의 `index.html`이 JSON을 읽어 표시

- 실행 시각: 평일 07:30 KST, 18:30 KST (GitHub 사정으로 수 분~수십 분 지연될 수 있음)
- 수동 실행: Actions 탭 → Update market data → Run workflow

## 데이터 소스 (키 불필요 · 공공 데이터)
| 항목 | 소스 |
|---|---|
| 미국 10년 국채금리 | U.S. Treasury Daily Par Yield Curve (대체: FRED DGS10) |
| USD/KRW | ECB 기준환율 교차계산 (대체: Fed H.10 / FRED DEXKOUS) |
| WTI | U.S. EIA via FRED DCOILWTICO |
| Dollar Index | Fed Nominal Broad Dollar Index (FRED DTWEXBGS) — ICE DXY 아님 |

S&P 500 · Nasdaq · Dow는 지수사 저작권 데이터라 공개 저장소에 수치를 저장하지 않습니다.
KOSPI · KOSDAQ은 키 없는 공식 무료 소스가 없어 보류 중입니다.

## 실패 처리
수집 실패 시 이전 값을 이어 쓰지 않고 `FAILED`로 기록 → 앱에 `업데이트 실패` 표시.
기준일이 허용 기간을 넘으면 값을 숨기고 `업데이트 필요` 표시.

## 기업 데이터 (Phase 3 · SEC EDGAR)
GitHub Actions(`.github/workflows/update-company-data.yml`, 평일 08:10 KST) → `scripts/fetch_companies.py`
→ `data/companies.json` 저장 → Company Research 화면에 표시

- 대상: `config/companies.json`의 미국 상장사 티커 (관심기업 추가 시 여기에도 티커 추가)
- 항목: 기업명·거래소·SEC 산업분류, 매출·영업이익·순이익·희석 EPS(분기/연간, YoY), XBRL로 태그된 사업부 매출·이익, 최근 공시
- SEC 요청에는 연락처가 담긴 User-Agent가 필요 → 저장소 Secret `SEC_USER_AGENT`
- 주가·시가총액·PER·PBR: 거래소 라이선스 데이터 → 무료버전 미제공
- 한국 기업: OpenDART(무료 키) 연결 결정 전까지 미제공
