#!/usr/bin/env python3
"""
Investment Research Center · Phase 3 company data collector (FREE · SEC EDGAR)

- 표준 라이브러리만 사용, API 키 없음 (SEC는 연락처가 포함된 User-Agent만 요구)
- SEC_USER_AGENT 환경변수(GitHub Secret)가 없으면 SEC에 요청하지 않는다
- 숫자는 SEC 원문(XBRL)에 보고된 값만 저장한다. 추정·보간 없음.
- 실패 시 이전 값을 이어 쓰지 않는다
출력: data/companies.json
"""
import json, os, re, sys, time, urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timezone

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "data", "companies.json")
CONFIG = os.path.join(ROOT, "config", "companies.json")
UA = os.environ.get("SEC_USER_AGENT", "").strip()
NOW = datetime.now(timezone.utc)
FORMS_MAIN = ("10-Q", "10-K")
FORMS_LIST = ("10-Q", "10-K", "8-K", "20-F", "6-K", "10-Q/A", "10-K/A")

# ------------------------------------------------------------ http (SEC fair access: ≤10 req/s)
_last = [0.0]
def http_get(url, timeout=40, retries=3):
    err = None
    for i in range(retries):
        wait = 0.15 - (time.time() - _last[0])
        if wait > 0: time.sleep(wait)
        _last[0] = time.time()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="replace")
        except Exception as e:  # noqa
            err = e; time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url} → {err}")

def get_json(url): return json.loads(http_get(url))
def d(s): return date.fromisoformat(s[:10])

# ------------------------------------------------------------ XBRL companyfacts
CONCEPTS = {
    "revenue":   [("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"), ("us-gaap", "Revenues"),
                  ("us-gaap", "SalesRevenueNet"), ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax"),
                  ("ifrs-full", "Revenue")],
    "operatingIncome": [("us-gaap", "OperatingIncomeLoss"), ("ifrs-full", "ProfitLossFromOperatingActivities")],
    "netIncome": [("us-gaap", "NetIncomeLoss"), ("ifrs-full", "ProfitLossAttributableToOwnersOfParent"), ("ifrs-full", "ProfitLoss")],
    "epsDiluted": [("us-gaap", "EarningsPerShareDiluted"), ("ifrs-full", "DilutedEarningsPerShare")],
    # V20 FREE FINAL+ (추가 항목 · 기존 키 변경 없음)
    "grossProfit": [("us-gaap", "GrossProfit"), ("ifrs-full", "GrossProfit")],
    "rnd": [("us-gaap", "ResearchAndDevelopmentExpense"), ("us-gaap", "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost")],
    "ocf": [("us-gaap", "NetCashProvidedByUsedInOperatingActivities"), ("ifrs-full", "CashFlowsFromUsedInOperatingActivities")],
    "capex": [("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"),
              ("ifrs-full", "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities")],
}
INSTANTS = {
    "equity": [("us-gaap", "StockholdersEquity"), ("ifrs-full", "EquityAttributableToOwnersOfParent")],
    "cash": [("us-gaap", "CashAndCashEquivalentsAtCarryingValue"), ("ifrs-full", "CashAndCashEquivalents")],
    "sharesOutstanding": [("dei", "EntityCommonStockSharesOutstanding")],
}
OK_FORMS = ("10-Q", "10-K", "20-F", "10-Q/A", "10-K/A", "20-F/A", "6-K")

def latest_instant(facts, cands):
    """재무상태표·표지 항목(시점 값) 중 가장 최근 보고값."""
    for tax, name in cands:
        units = facts.get(tax, {}).get(name, {}).get("units")
        if not units: continue
        unit = "shares" if "shares" in units else ("USD" if "USD" in units else next(iter(units)))
        rows = [e for e in units[unit] if "start" not in e and e.get("form", "") in OK_FORMS and e.get("val") is not None]
        if not rows: continue
        e = max(rows, key=lambda e: (e["end"], e.get("filed", "")))
        return {"value": e["val"], "end": e["end"][:10], "form": e.get("form"), "filed": e.get("filed"),
                "unit": unit, "concept": f"{tax}:{name}"}
    return None

def balance(facts):
    return {k: latest_instant(facts, c) for k, c in INSTANTS.items()}

def classify(e):
    if "start" not in e: return None
    days = (d(e["end"]) - d(e["start"])).days
    return "q" if 80 <= days <= 100 else ("fy" if 350 <= days <= 380 else None)

def pick_units(units, per_share):
    keys = [k for k in units if ("/shares" in k) == per_share]
    if not keys: return None, None
    k = "USD/shares" if per_share and "USD/shares" in keys else ("USD" if "USD" in keys else keys[0])
    return k, units[k]

def concept_series(facts, cands, per_share=False):
    for tax, name in cands:
        units = facts.get(tax, {}).get(name, {}).get("units")
        if not units: continue
        unit, rows = pick_units(units, per_share)
        if not rows: continue
        best = {}
        for e in rows:
            k = classify(e)
            if not k or e.get("form", "") not in ("10-Q", "10-K", "20-F", "10-Q/A", "10-K/A", "20-F/A", "6-K"): continue
            key = (k, e["start"][:10], e["end"][:10])
            if key not in best or e.get("filed", "") > best[key].get("filed", ""):
                best[key] = e
        if best:
            return f"{tax}:{name}", unit, best
    return None, None, {}

def latest_with_yoy(best, kind):
    rows = sorted((v for (k, _, _), v in best.items() if k == kind), key=lambda e: e["end"])
    if not rows: return None
    cur = rows[-1]
    target = d(cur["end"]).toordinal() - 365
    prev = next((r for r in reversed(rows[:-1]) if abs(d(r["end"]).toordinal() - target) <= 15), None)
    out = {"value": cur["val"], "start": cur["start"][:10], "end": cur["end"][:10], "form": cur.get("form"),
           "filed": cur.get("filed"), "accn": cur.get("accn"), "fy": cur.get("fy"), "fp": cur.get("fp")}
    if prev is not None and prev["val"] not in (0, None):
        out["prevValue"] = prev["val"]; out["prevEnd"] = prev["end"][:10]
        out["yoyPct"] = round((cur["val"] - prev["val"]) / abs(prev["val"]) * 100, 2)
    return out

def fundamentals(facts):
    m = {}
    for key, cands in CONCEPTS.items():
        concept, unit, best = concept_series(facts, cands, per_share=(key == "epsDiluted"))
        if not best: m[key] = None; continue
        m[key] = {"concept": concept, "unit": unit, "q": latest_with_yoy(best, "q"), "fy": latest_with_yoy(best, "fy")}
    return m

# ------------------------------------------------------------ segments (XBRL instance of latest 10-Q / 10-K)
NS_XBRLI = "{http://www.xbrl.org/2003/instance}"
NS_DI = "{http://xbrl.org/2006/xbrldi}"
REV_NAMES = ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "RevenueFromContractWithCustomerIncludingAssessedTax"]
PROFIT_NAMES = ["OperatingIncomeLoss"]
SEG_AXIS = "StatementBusinessSegmentsAxis"

def member_label(qname):
    s = qname.split(":")[-1]
    s = re.sub(r"(Segment)?Member$", "", s)
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s).strip() or qname

def parse_instance(xml_text, want="q"):
    root = ET.fromstring(xml_text)
    ctx = {}
    for c in root.iter(NS_XBRLI + "context"):
        p = c.find(NS_XBRLI + "period")
        st, en = p.find(NS_XBRLI + "startDate"), p.find(NS_XBRLI + "endDate")
        if st is None or en is None: continue
        dims = [(m.get("dimension", ""), (m.text or "").strip()) for m in c.iter(NS_DI + "explicitMember")]
        typed = list(c.iter(NS_DI + "typedMember"))
        ctx[c.get("id")] = {"start": st.text.strip(), "end": en.text.strip(), "dims": dims, "typed": bool(typed)}
    facts = {}  # (name, ctxid) -> value
    for el in root.iter():
        tag = el.tag
        if not tag.startswith("{http://fasb.org/us-gaap/"): continue
        name = tag.split("}")[1]
        if name not in REV_NAMES and name not in PROFIT_NAMES: continue
        cid = el.get("contextRef")
        if cid not in ctx or el.text is None: continue
        try: facts.setdefault((name, cid), float(el.text.strip()))
        except ValueError: pass
    def dur(c): return (d(c["end"]) - d(c["start"])).days
    ok = (lambda c: 80 <= dur(c) <= 100) if want == "q" else (lambda c: 350 <= dur(c) <= 380)
    def collect(names):
        for name in names:
            segs = {}
            for (n, cid), v in facts.items():
                c = ctx[cid]
                if n != name or c["typed"] or not ok(c): continue
                if len(c["dims"]) == 1 and c["dims"][0][0].endswith(SEG_AXIS):
                    segs.setdefault(c["end"], {})[c["dims"][0][1]] = (v, c["start"])
            if not segs: continue
            end = max(segs)
            if len(segs[end]) < 2: continue
            total = next((v for (n, cid), v in facts.items() if n == name and not ctx[cid]["dims"] and not ctx[cid]["typed"]
                          and ctx[cid]["end"] == end and ok(ctx[cid])), None)
            rows = [{"member": m, "name": member_label(m), "value": v,
                     "share": round(v / total * 100, 1) if total else None} for m, (v, _) in segs[end].items()]
            rows.sort(key=lambda r: -abs(r["value"]))
            start = next(iter(segs[end].values()))[1]
            return {"concept": "us-gaap:" + name, "start": start, "end": end, "total": total, "rows": rows}
        return None
    return collect(REV_NAMES), collect(PROFIT_NAMES)

def segments(cik, filing):
    if not filing:
        return {"status": "CHECK", "reason": "최근 10-Q/10-K 없음 (해외기업 20-F/6-K는 분기 세그먼트 XBRL이 없을 수 있음)"}
    accn = filing["accn"].replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn}/"
    idx = get_json(base + "index.json")
    names = [i["name"] for i in idx.get("directory", {}).get("item", [])]
    inst = next((n for n in names if n.endswith("_htm.xml")), None)
    meta = {"form": filing["form"], "filed": filing["date"], "accn": filing["accn"], "url": filing["url"]}
    if not inst:
        return {"status": "CHECK", "reason": "XBRL 인스턴스 파일을 찾지 못함", "filing": meta}
    rev, prof = parse_instance(http_get(base + inst), "q" if filing["form"].startswith("10-Q") else "fy")
    if not rev:
        return {"status": "CHECK", "reason": "사업부 매출이 XBRL 세그먼트로 태그되지 않음 — 공시 원문 확인 필요", "filing": meta}
    return {"status": "OK", "filing": meta, "revenue": rev, "profit": prof,
            "profitStatus": "OK" if prof else "NOT_TAGGED"}

# ------------------------------------------------------------ company
def collect_company(ticker, tmap):
    if ticker not in tmap:
        return {"status": "FAILED", "error": "SEC 티커 목록에서 찾을 수 없음"}
    cik, ent_name, exch = tmap[ticker]
    cik10 = str(cik).zfill(10)
    out = {"status": "OK", "cik": cik10, "name": ent_name, "exchange": exch, "errors": []}
    try:
        sub = get_json(f"https://data.sec.gov/submissions/CIK{cik10}.json")
        out.update({"name": sub.get("name") or ent_name, "sic": sub.get("sic"), "sicDescription": sub.get("sicDescription"),
                    "fiscalYearEnd": sub.get("fiscalYearEnd"), "exchange": ", ".join(sub.get("exchanges") or []) or exch})
        r = sub.get("filings", {}).get("recent", {})
        filings = []
        for i, form in enumerate(r.get("form", [])):
            if form not in FORMS_LIST: continue
            accn = r["accessionNumber"][i]; doc = r.get("primaryDocument", [""] * (i + 1))[i]
            items = (r.get("items") or [""] * (i + 1))[i] if i < len(r.get("items") or []) else ""
            filings.append({"form": form, "date": r["filingDate"][i], "reportDate": (r.get("reportDate") or [""] * (i + 1))[i],
                            "accn": accn, "desc": (r.get("primaryDocDescription") or [""] * (i + 1))[i], "items": items,
                            "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accn.replace('-', '')}/{doc}"})
            if len(filings) >= 15: break
        out["filings"] = filings
        main = next((f for f in filings if f["form"] in FORMS_MAIN), None)
    except Exception as e:  # noqa
        out["errors"].append(f"submissions: {e}"); out["filings"] = None; main = None
    try:
        facts = get_json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json").get("facts", {})
        out["metrics"] = fundamentals(facts)
        out["balance"] = balance(facts)
    except Exception as e:  # noqa
        out["errors"].append(f"companyfacts: {e}"); out["metrics"] = None
    try:
        out["segments"] = segments(cik10, main)
    except Exception as e:  # noqa
        out["errors"].append(f"segments: {e}"); out["segments"] = {"status": "FAILED", "reason": str(e)[:200]}
    if out["errors"]:
        out["status"] = "FAILED" if out.get("metrics") is None and out.get("filings") is None else "PARTIAL"
        for e in out["errors"]: print(f"::warning::{ticker} {e}")
    return out

def ticker_map():
    j = get_json("https://www.sec.gov/files/company_tickers_exchange.json")
    f = j["fields"]; ic, it, iname, iex = f.index("cik"), f.index("ticker"), f.index("name"), f.index("exchange")
    return {row[it].upper(): (row[ic], row[iname], row[iex]) for row in j["data"]}

def build():
    tickers = json.load(open(CONFIG, encoding="utf-8")).get("us", [])
    res = {"schemaVersion": 1, "generatedAt": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"), "source": "SEC EDGAR (data.sec.gov)",
           "companies": {}}
    if not UA or "@" not in UA:
        print("::error::SEC_USER_AGENT secret이 없거나 이메일이 없습니다. SEC에 요청하지 않습니다.")
        res.update(runStatus="FAILED", error="SEC_USER_AGENT 미설정")
        for t in tickers: res["companies"][t] = {"status": "FAILED", "error": "SEC_USER_AGENT 미설정"}
        return res
    try:
        tmap = ticker_map()
    except Exception as e:  # noqa
        print(f"::error::티커 목록 실패: {e}")
        res.update(runStatus="FAILED", error=f"티커 목록 실패: {e}")
        for t in tickers: res["companies"][t] = {"status": "FAILED", "error": "SEC 티커 목록 수집 실패"}
        return res
    for t in tickers:
        try: res["companies"][t] = collect_company(t.upper(), tmap)
        except Exception as e:  # noqa
            res["companies"][t] = {"status": "FAILED", "error": str(e)[:200]}
    sts = [c["status"] for c in res["companies"].values()]
    res["runStatus"] = "OK" if all(s == "OK" for s in sts) else ("FAILED" if all(s == "FAILED" for s in sts) else "PARTIAL")
    return res

if __name__ == "__main__":
    data = build()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print("runStatus=" + data["runStatus"])
    for t, c in data["companies"].items():
        m = c.get("metrics") or {}
        rq = ((m.get("revenue") or {}).get("q") or {})
        print(f"  {t:6s} {c['status']:8s} rev_q={rq.get('value')} end={rq.get('end')} seg={(c.get('segments') or {}).get('status')}")
    sys.exit(0)
