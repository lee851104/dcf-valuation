from flask import Flask, request, jsonify, render_template
import yfinance as yf
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import re

app = Flask(__name__)

# yfinance 用的 session，帶 browser User-Agent 避免被識別為爬蟲
# 注意：不對 429 重試，重試只會讓 rate-limit 更嚴重
def _make_session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    })
    # 只對網路錯誤重試，不對 429 重試
    retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[500, 502, 503])
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


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
        t = yf.Ticker(ticker_symbol)
        info = t.info
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
