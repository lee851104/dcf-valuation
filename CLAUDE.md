# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 專案概述

美股 DCF（折現現金流）估值工具。使用者輸入股票代碼，系統從 Yahoo Finance 抓取財務數據與成長率預估、從 GuruFocus 抓取 WACC，透過**引導式六步驟流程**逐步計算合理股價。

---

## 執行方式

```bash
pip install -r requirements.txt
py app.py
# 開啟 http://localhost:5001
```

需要 `yfinance >= 1.2.0`、`curl_cffi >= 0.15`。

## 部署

已部署至 Render（`render.yaml` 已設定）：
- Build: `pip install -r requirements.txt`
- Start: `gunicorn app:app`
- 網址：https://dcf-valuation.onrender.com
- 推送到 GitHub `main` 分支即自動重新部署

---

## 架構：Flask API + 純前端 JS

**後端（app.py）只有兩支 API：**
- `POST /api/fetch` — 一次完成：yfinance 財務數據 + GuruFocus WACC + Yahoo 成長率預估，全部回傳
- `POST /api/wacc` — 使用者手動重新抓取 WACC 用

**所有 DCF 計算在前端 JS 完成**，`dcf.py` 僅備用未使用。`templates/index.html` 是單頁應用，無外部框架，JS/CSS 全部 inline。

---

## 資料來源細節

| 欄位 | 來源 |
|------|------|
| FCF TTM | `ticker.cashflow["Free Cash Flow"]`，失敗則 `op_cf + capex` |
| 現金／負債／股數／股價 | `ticker.info`（各有備用 key） |
| WACC | GuruFocus，**必須用 `curl_cffi` impersonate `chrome124`**，普通 `requests` 會收到 Cloudflare 403；yfinance Ticker 也使用同一 `curl_cffi` session 避免雲端 IP 被 Yahoo rate-limit |
| 年成長率 | `ticker.growth_estimates.loc["+1y", "stockTrend"]` × 100（Yahoo Finance Next Year 預估） |

- ticker 中 `.` 自動換成 `-`（BRK.B → BRK-B）
- WACC 抓取失敗時前端預設填 10%

---

## 六步驟流程與計算邏輯

| 步驟 | 內容 |
|------|------|
| 1 | 輸入 ticker，抓取所有數據，WACC 自動填入（即折現率） |
| 2 | 設定年成長率 g1（預設帶入 Yahoo 預估），預覽 N 年 FCF 長條圖 |
| 3 | 設定折現率 r（預設帶入 WACC）、永久成長率 gT（預設 4%），計算終值 TV |
| 4 | 計算 EV = Σ PV(FCF_n) + PV(TV) |
| 5 | 股權價值 E = EV + 現金 − 負債 |
| 6 | 合理股價 = E / 流通股數 |

**計算年數 = 使用者選擇的 years（3／5／7）**，不額外加五年。

```
FCF_n   = FCF_0 × (1+g1)^n          # n = 1..years
TV      = FCF_years × (1+gT) / (r-gT)
PV(TV)  = TV / (1+r)^years
EV      = Σ [FCF_n/(1+r)^n] + PV(TV)
E       = EV + 現金 - 負債
合理股價 = E / 流通股數
```

所有數值單位：`state.fcfM`、`state.cashM`、`state.debtM`、`state.sharesM` 均為**百萬**，計算時乘 `1e6`。

---

## 前端狀態管理

- 全域 `state` 物件存所有數值與計算結果
- **卡片切換**：`.step-overlay`（摘要，completed 時顯示）和 `.card-body`（表單，completed 時隱藏）並存，`goToStep(n)` 只切換 CSS class，不動 innerHTML，確保返回修改時表單值保留
- **事件冒泡陷阱**：返回功能的 onclick 掛在 `.step-overlay` 上而非整張卡片，避免卡片內按鈕 click 冒泡觸發返回（曾經導致「下一步」按了沒反應的 bug）
- Step 2 FCF 用水平長條圖呈現，最大值撐滿，顏色隨年份漸變（藍→青），第 0 年為灰色
