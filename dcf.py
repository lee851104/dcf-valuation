"""
DCF 純計算模組 — 不含 Flask，可獨立測試

模型：單段成長 + 終值
  - 使用者選 N 年（3/5/7），期間以 g1 成長
  - 第 N 年後以 gT 永久成長（終值）
"""


def project_fcf(fcf0, g1, years):
    """
    單段式 FCF 預測：前 years 年以 g1 成長。
    回傳 years 筆 {year, fcf, growth_rate}
    """
    rows = []
    fcf = fcf0
    for n in range(1, years + 1):
        fcf = fcf * (1 + g1)
        rows.append({"year": n, "fcf": fcf, "growth_rate": g1})
    return rows


def discount_cashflows(rows, r):
    """
    對每筆 FCF 加上折現因子與現值。
    回傳新 list，每筆多 discount_factor、pv 兩個欄位。
    """
    result = []
    for row in rows:
        n = row["year"]
        df = 1 / (1 + r) ** n
        pv = row["fcf"] * df
        result.append({**row, "discount_factor": df, "pv": pv})
    return result


def terminal_value(fcf_n, gt, r, years):
    """
    Gordon Growth Model 終值，折現到今天。
    - fcf_n：第 years 年的 FCF
    - 終值 TV = fcf_n × (1+gT) / (r - gT)
    - 終值現值 PV(TV) = TV / (1+r)^years
    r 必須 > gt，否則 raise ValueError。
    回傳 (tv, pv_tv)。
    """
    if r <= gt:
        raise ValueError(f"折現率 r ({r:.1%}) 必須大於永續成長率 gT ({gt:.1%})")
    tv = fcf_n * (1 + gt) / (r - gt)
    pv_tv = tv / (1 + r) ** years
    return tv, pv_tv


def calc_intrinsic_value(fcf0, g1, years, r, gt, cash, debt, shares):
    """
    完整 DCF 計算。
    回傳 dict：
      - fcf_rows: 含折現資訊的 FCF（years 筆）
      - sum_pv_fcf: FCF 現值合計
      - tv: 終值
      - pv_tv: 終值現值
      - equity_value: 股東權益（加現金減負債）
      - intrinsic_per_share: 每股內在價值
    """
    rows = project_fcf(fcf0, g1, years)
    discounted = discount_cashflows(rows, r)

    sum_pv_fcf = sum(row["pv"] for row in discounted)
    fcf_n = rows[-1]["fcf"]
    tv, pv_tv = terminal_value(fcf_n, gt, r, years)

    equity_value = sum_pv_fcf + pv_tv + cash - debt
    intrinsic_per_share = equity_value / shares if shares > 0 else 0

    return {
        "fcf_rows": discounted,
        "sum_pv_fcf": sum_pv_fcf,
        "tv": tv,
        "pv_tv": pv_tv,
        "equity_value": equity_value,
        "intrinsic_per_share": intrinsic_per_share,
    }


def calc_sensitivity(fcf0, years, gt, cash, debt, shares, g1_values, r_values):
    """
    敏感度分析：對所有 (r, g1) 組合計算每股內在價值。
    回傳 2D list，row=r_values，col=g1_values。
    每格為 intrinsic_per_share（r<=gt 時為 None）。
    """
    result = []
    for r in r_values:
        row = []
        for g1 in g1_values:
            try:
                res = calc_intrinsic_value(fcf0, g1, years, r, gt, cash, debt, shares)
                row.append(res["intrinsic_per_share"])
            except ValueError:
                row.append(None)
        result.append(row)
    return result
