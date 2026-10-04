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
