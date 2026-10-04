#!/usr/bin/env python3
"""
Investment Research Center · Phase 2 market data collector (FREE)

- 표준 라이브러리만 사용 (pip 설치 불필요)
- API 키 / 유료 API 사용 안 함
- 수집 실패 시 이전 값을 이어 쓰지 않는다 → status=FAILED, value=null
- 저작권상 공개 재게시가 제한된 지수는 수치를 저장하지 않는다 → status=RESTRICTED
출력: data/market.json
"""
import csv, io, json, os, sys, time, urllib.request, urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

UA = "InvestmentResearchCenter/1.0 (personal research dashboard; GitHub Actions; no redistribution of restricted series)"
OUT = os.path.join(os.path.dirname(__file__), "..", "data", "market.json")
NOW = datetime.now(timezone.utc)

# ---------------------------------------------------------------- http
def http_get(url, timeout=30, retries=3):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:  # noqa
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url} → {last}")

def to_float(s):
    try:
        s = str(s).strip()
        if s in ("", ".", "NA", "NaN"):
            return None
        return float(s)
    except ValueError:
        return None

# ---------------------------------------------------------------- parsers
def parse_fred_csv(text):
    """FRED graph CSV: 첫 열 날짜, 둘째 열 값. '.'은 결측."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or len(rows[0]) < 2:
        raise ValueError("FRED CSV 형식 아님")
    out = []
    for r in rows[1:]:
        if len(r) >= 2:
            v = to_float(r[1])
            if v is not None:
                out.append((r[0][:10], v))
    return sorted(out)

NS = {"a": "http://www.w3.org/2005/Atom",
      "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
      "d": "http://schemas.microsoft.com/ado/2007/08/dataservices"}

def parse_treasury_xml(text, field="BC_10YEAR"):
    root = ET.fromstring(text)
    out = []
    for p in root.iter(f"{{{NS['m']}}}properties"):
        d = p.find(f"d:NEW_DATE", NS)
        v = p.find(f"d:{field}", NS)
        if d is not None and v is not None:
            fv = to_float(v.text)
            if fv is not None:
                out.append((d.text[:10], fv))
    return sorted(out)

def parse_ecb_csv(text):
    """ECB csvdata → {currency: [(date, value)]}"""
    out = {}
    for r in csv.DictReader(io.StringIO(text)):
        cur, d, v = r.get("CURRENCY"), r.get("TIME_PERIOD"), to_float(r.get("OBS_VALUE"))
        if cur and d and v is not None:
            out.setdefault(cur, []).append((d[:10], v))
    for k in out:
        out[k].sort()
    return out

# ---------------------------------------------------------------- fetchers
def fred(series_id, days=60):
    cosd = (NOW - timedelta(days=days)).strftime("%Y-%m-%d")
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={cosd}"
    return parse_fred_csv(http_get(url)), url

def treasury_10y():
    obs = []
    for dt in (NOW.replace(day=1) - timedelta(days=1), NOW):  # 전월 + 당월
        ym = dt.strftime("%Y%m")
        url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
               f"?data=daily_treasury_yield_curve&field_tdr_date_value_month={ym}")
        obs += parse_treasury_xml(http_get(url))
    return sorted(set(obs)), "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/TextView?type=daily_treasury_yield_curve"

def ecb_usdkrw():
    url = "https://data-api.ecb.europa.eu/service/data/EXR/D.USD+KRW.EUR.SP00.A?lastNObservations=10&format=csvdata"
    data = parse_ecb_csv(http_get(url))
    usd, krw = dict(data.get("USD", [])), dict(data.get("KRW", []))
    obs = sorted((d, krw[d] / usd[d]) for d in set(usd) & set(krw) if usd[d])
    return obs, "https://data.ecb.europa.eu/data/datasets/EXR"

# ---------------------------------------------------------------- build
def series_entry(key, label, unit, fn, source, max_age_days, valid, note="", fallback=None):
    attempts = [(fn, source)] + ([fallback] if fallback else [])
    errors = []
    for f, src in attempts:
        try:
            obs, url = f()
            if len(obs) < 1:
                raise ValueError("관측값 없음")
            d, v = obs[-1]
            if not (valid[0] <= v <= valid[1]):
                raise ValueError(f"값 검증 실패: {v}")
            prev = obs[-2] if len(obs) >= 2 else (None, None)
            return {"label": label, "status": "OK", "value": round(v, 4), "unit": unit,
                    "asOf": d, "prev": None if prev[1] is None else round(prev[1], 4), "prevDate": prev[0],
                    "source": src, "sourceUrl": url, "maxAgeDays": max_age_days, "note": note,
                    "fallbackUsed": f is not fn}
        except Exception as e:  # noqa
            errors.append(f"{src}: {e}")
            print(f"::warning::{key} 수집 실패 — {src}: {e}")
    return {"label": label, "status": "FAILED", "value": None, "unit": unit, "asOf": None,
            "source": source, "sourceUrl": None, "maxAgeDays": max_age_days, "note": note,
            "error": " | ".join(errors)}

def restricted(label, owner, url):
    return {"label": label, "status": "RESTRICTED", "value": None,
            "note": f"{owner} 저작권 데이터 — 공개 저장소에 수치를 재게시하지 않습니다.", "sourceUrl": url}

def key_required(label, note):
    return {"label": label, "status": "KEY_REQUIRED", "value": None, "note": note, "sourceUrl": None}

def build():
    s = {}
    s["spx"] = restricted("S&P 500", "S&P Dow Jones Indices", "https://fred.stlouisfed.org/series/SP500")
    s["ndx"] = restricted("Nasdaq", "Nasdaq, Inc.", "https://fred.stlouisfed.org/series/NASDAQCOM")
    s["dji"] = restricted("Dow", "S&P Dow Jones Indices", "https://fred.stlouisfed.org/series/DJIA")
    s["kospi"] = key_required("KOSPI", "키 없이 사용할 수 있는 공식 무료 소스 없음 · 공공데이터포털(무료 키) 연결 여부 결정 필요")
    s["kosdaq"] = key_required("KOSDAQ", "키 없이 사용할 수 있는 공식 무료 소스 없음 · 공공데이터포털(무료 키) 연결 여부 결정 필요")
    s["us10y"] = series_entry("us10y", "미국 10년 국채금리", "%", treasury_10y,
                              "U.S. Treasury · Daily Par Yield Curve", 6, (0, 20),
                              fallback=(lambda: fred("DGS10"), "FRED DGS10 (Federal Reserve H.15)"))
    s["dxy"] = series_entry("dxy", "Dollar Index", "index", lambda: fred("DTWEXBGS"),
                            "Federal Reserve H.10 · Nominal Broad U.S. Dollar Index (FRED DTWEXBGS)", 14, (50, 250),
                            note="Fed Broad 지수 · ICE DXY와 다른 지수 · 주 1회 발표")
    s["wti"] = series_entry("wti", "WTI", "USD/bbl", lambda: fred("DCOILWTICO"),
                            "U.S. EIA · WTI Cushing Spot (FRED DCOILWTICO)", 14, (-100, 500),
                            note="EIA 현물가격 · 주 단위 갱신")
    s["usdkrw"] = series_entry("usdkrw", "USD/KRW", "KRW", ecb_usdkrw,
                               "ECB 기준환율 교차계산 (EUR/KRW ÷ EUR/USD)", 6, (500, 3000),
                               note="ECB 14:15 CET 기준환율로 계산한 참고 환율",
                               fallback=(lambda: fred("DEXKOUS"), "Federal Reserve H.10 (FRED DEXKOUS)"))
    collected = [v for v in s.values() if v["status"] in ("OK", "FAILED")]
    ok = sum(v["status"] == "OK" for v in collected)
    run = "OK" if ok == len(collected) else ("FAILED" if ok == 0 else "PARTIAL")
    return {"schemaVersion": 1, "generatedAt": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "runStatus": run, "collected": ok, "expected": len(collected), "series": s}

if __name__ == "__main__":
    data = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"runStatus={data['runStatus']} collected={data['collected']}/{data['expected']}")
    for k, v in data["series"].items():
        print(f"  {k:7s} {v['status']:12s} {v.get('value')} asOf={v.get('asOf')}")
    sys.exit(0)  # 실패도 JSON에 기록해 앱이 '업데이트 실패'를 표시하도록 한다
