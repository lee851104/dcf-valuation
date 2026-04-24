from flask import Flask, request, jsonify, render_template
import yfinance as yf
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import re
import time
from curl_cffi import requests as cffi_requests

app = Flask(__name__)

# 用 curl_cffi 建立 session 給 yfinance，模擬瀏覽器 TLS 繞過雲端 IP 封鎖
def _make_session(profile="chrome124"):
    s = cffi_requests.Session(impersonate=profile)
    return s


def _fetch_ticker_with_retry(ticker_symbol, max_attempts=3):
    """嘗試多種 session 組合，每次失敗後稍等再試。"""
    profiles = ["chrome124", "chrome110", "safari17_0"]
    last_exc = None
    for attempt in range(max_attempts):
        profile = profiles[attempt % len(profiles)]
        try:
            session = _make_session(profile)
            t = yf.Ticker(ticker_symbol, session=session)
            info = t.info
            # 確認拿到有效資料
            if info and (info.get("currentPrice") or info.get("regularMarketPrice")):
                return t, info
            # info 空但沒例外 — 視為找不到代碼，不重試
            return t, info
        except Exception as e:
            last_exc = e
            err_str = str(e).lower()
            if "too many requests" in err_str or "rate limit" in err_str:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
            else:
                raise  # 非 rate-limit 錯誤直接往上拋
    raise last_exc


def _get_fcf(ticker_obj):
    """嘗試從 cashflow 取 Free Cash Flow，失敗則用 op_cf + capex 推算。"""
    try:
        cf = ticker_obj.cashflow
        if "Free Cash Flow" in cf.index:
            val = cf.loc["Free Cash Flow"].iloc[0]
            if val is not None and not (hasattr(val, '__float__') and val != val):
                return float(val)
    except Exception:
        pass

    try:
        cf = ticker_obj.cashflow
        op_cf = float(cf.loc["Operating Cash Flow"].iloc[0])
        capex = float(cf.loc["Capital Expenditure"].iloc[0])  # yfinance 回傳負數
        return op_cf + capex
    except Exception:
        pass

    return None


def _get_wacc(ticker):
    """從 GuruFocus 抓取 WACC %。使用 curl_cffi 模擬瀏覽器 TLS 繞過 Cloudflare。失敗時回傳 None。"""
    try:
        from curl_cffi import requests as cffi_requests
        url = f"https://www.gurufocus.com/term/wacc/{ticker}"
        resp = cffi_requests.get(url, impersonate="chrome124", timeout=15)
        if resp.status_code != 200:
            return None

        text = resp.text

        patterns = [
            r'"currentValue"\s*:\s*"([\d.]+)"',
            r'"currentValue"\s*:\s*([\d.]+)',
            r'WACC\s*%?\s*[:\-]?\s*([\d]+\.[\d]+)',
            r'>([\d]+\.[\d]+)\s*%?\s*</.*?[Ww][Aa][Cc][Cc]',
        ]

        for pattern in patterns:
            m = re.search(pattern, text, re.DOTALL)
            if m:
                val = float(m.group(1))
                if 1 < val < 50:
                    return round(val, 2)

        return None
    except Exception:
        return None


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/fetch", methods=["POST"])
def api_fetch():
    data = request.get_json(force=True)
    raw_ticker = data.get("ticker", "").strip().upper()
    if not raw_ticker:
        return jsonify({"error": "請輸入股票代碼"}), 400

    ticker_symbol = raw_ticker.replace(".", "-")

    try:
        t, info = _fetch_ticker_with_retry(ticker_symbol)
    except Exception as e:
        return jsonify({"error": f"無法取得數據：{e}"}), 400

    if info.get("currentPrice") is None and info.get("regularMarketPrice") is None:
        return jsonify({"error": f"找不到股票代碼「{raw_ticker}」，請確認是否正確"}), 400

    name = info.get("longName") or info.get("shortName") or ticker_symbol
    price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
    cash = info.get("totalCash") or 0
    debt = info.get("totalDebt") or 0
    shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding") or 0
    currency = info.get("currency", "USD")

    fcf = _get_fcf(t)
    wacc = _get_wacc(ticker_symbol)

    # Growth Estimates — Next Year (+1y)
    growth_next_year = None
    try:
        ge = t.growth_estimates
        val = ge.loc["+1y", "stockTrend"]
        if val is not None and val == val:  # not NaN
            growth_next_year = round(float(val) * 100, 2)
    except Exception:
        pass

    return jsonify({
        "ticker": ticker_symbol,
        "name": name,
        "price": price,
        "fcf": fcf,
        "cash": cash,
        "debt": debt,
        "shares": shares,
        "currency": currency,
        "wacc": wacc,
        "growthNextYear": growth_next_year,
    })


@app.route("/api/wacc", methods=["POST"])
def api_wacc():
    """獨立抓取 WACC，與 yfinance 分開避免互相影響。"""
    data = request.get_json(force=True)
    ticker = data.get("ticker", "").strip().upper()
    if not ticker:
        return jsonify({"error": "請輸入股票代碼"}), 400
    wacc = _get_wacc(ticker)
    if wacc is None:
        return jsonify({"error": "無法從 GuruFocus 取得 WACC，請手動輸入"}), 404
    return jsonify({"wacc": wacc})


if __name__ == "__main__":
    app.run(port=5001, debug=True)
