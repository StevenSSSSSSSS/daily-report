# Daily Report — PROGRESS.md

> 最後更新：2026-06-11
> 當前階段：Phase 3A — AI 決策品質與可追蹤性規劃

## 總覽

| Phase | 狀態 | 開始日期 | 完成日期 |
|-------|------|----------|----------|
| Phase 1：文件與工作流基礎 | 完成 | 2026-06-09 | 2026-06-09 |
| Phase 2：Prompt 可維護性 | 完成 | 2026-06-09 | 2026-06-09 |
| Phase 3：Portfolio Review | 進行中 | 2026-06-09 | — |
| Phase 3A：AI 決策品質與可追蹤性 | 規劃中 | 2026-06-11 | — |
| Phase 4：報告與資料穩定性 | 未開始 | — | — |

## 當前系統摘要

- 入口：`main_new.py`
- 自動化：`.github/workflows/daily.yml`
- 狀態資料：`daily-data/`
- Portfolio book：`daily-data/xai_portfolio_book.json`
- 輸出頁：`portfolio_book.html`

## Phase 1：文件與工作流基礎

### 目標

建立專案專用文件，讓之後每次修改都有清楚記錄、設計目的和開發規範。

### 進度

| # | 任務 | 狀態 | 備註 |
|---|------|------|------|
| 1.1 | 建立 `AGENTS.md` | 完成 | 定義 Codex 工作規範、prompt、portfolio、secret 限制 |
| 1.2 | 建立 `GOAL.md` | 完成 | 定義專案願景、設計原則、路線圖 |
| 1.3 | 建立 `PROGRESS.md` | 完成 | 建立進度與修改記錄格式 |
| 1.4 | 建立每階段 code review / debug / 記錄流程 | 完成 | Phase 完成後必須 review、驗證、記錄；需要人工測試時提醒 Steven |
| 1.5 | 形成每次修改後更新記錄的習慣 | 進行中 | 之後每次階段性修改都要更新本檔 |

## Phase 2：Prompt 可維護性

### 目標

把固定 AI system prompt 從 `main_new.py` 拆到獨立檔案，方便人工 review，同時保持現有 JSON schema 和呼叫流程不變。

### 進度

| # | 任務 | 狀態 | 備註 |
|---|------|------|------|
| 2.1 | 評估固定 prompt 分拆範圍 | 完成 | 只拆 `SYSTEM_PROMPT` 和 `PORTFOLIO_SYSTEM_PROMPT` |
| 2.2 | 新增 `prompts.py` | 完成 | 固定 prompt 集中存放 |
| 2.3 | 更新 `main_new.py` import | 完成 | 原呼叫點不變 |
| 2.4 | Code review / debug | 完成 | `py_compile` 通過，引用檢查通過 |

## Phase 3：Portfolio Review

### 目標

新增獨立 portfolio review，讓 AI 在看到壓縮市況、今日 orders、目前持倉和最近交易後，檢討策略問題和下次優化方向；review 不直接下單。

### 進度

| # | 任務 | 狀態 | 備註 |
|---|------|------|------|
| 3.1 | 新增 `PORTFOLIO_REVIEW_SYSTEM_PROMPT` | 完成 | 放在 `prompts.py`，只輸出 `portfolio_review` JSON |
| 3.2 | 新增 review prompt builder | 完成 | 使用壓縮市況、orders、持倉、最近 trade log / closed trades |
| 3.3 | 新增第三次 AI review 呼叫 | 完成 | 交易執行後呼叫，不回頭改 orders |
| 3.4 | Email 顯示 review | 完成 | 加在 portfolio / stock cards 後 |
| 3.5 | Review 寫入 portfolio book | 完成 | `latest_review` + 最近 20 筆 `review_history` |
| 3.6 | 視效果決定是否餵回下次 portfolio prompt | 未開始 | 先人工觀察 review 質素 |
| 3.7 | Code review / debug | 完成 | `py_compile` 通過；本機 import 測試因缺少 `xai_sdk` 無法執行 |

## Phase 3A：AI 決策品質與可追蹤性

### 目標

參考 `ai_ml_trading/PROJECT_ARCHITECTURE.md` 的 thesis discipline，但保持 daily-report 最小改動：先讓 AI buy 決策更可驗證，再逐步形成 review feedback loop。

### 建議順序

| # | 任務 | 狀態 | 備註 |
|---|------|------|------|
| 3A.1 | 修改 portfolio prompt schema | 完成 | buy order 加 `thesis`、`evidence`、`falsification_points`、`review_trigger` |
| 3A.2 | 保存 thesis 欄位 | 完成 | 寫入 position / trade log，方便日後復盤 |
| 3A.3 | Review 摘要餵回下次決策 | 完成 | 只帶最近 1-3 次壓縮摘要，控制 token |
| 3A.4 | 輕量 AI output validation | 完成 | 檢查 `orders`、`action`、ticker、allocation、stop / target |
| 3A.5 | 決策紀錄加強 | 暫緩 | 先使用現有 trade_log / review_history；待 GitHub 實測後再決定是否追加 append-only decision log |

## 修改記錄

| 日期 | 修改檔案 | 內容 | Code Review / Debug |
|------|----------|------|---------------------|
| 2026-06-09 | `AGENTS.md`, `GOAL.md`, `PROGRESS.md` | 參考 Claire 專案文件，建立 daily-report 專用規範、目標和進度追蹤 | `git status --short` 確認只有三個新文件 |
| 2026-06-09 | `GOAL.md`, `PROGRESS.md` | 補充每階段完成後必須自動 code review、debug / 驗證、記錄；需要人工測試時提醒 Steven | `git status --short` 確認只有三個文件變更 |
| 2026-06-09 | `main_new.py`, `prompts.py`, `GOAL.md`, `PROGRESS.md` | Phase 2：固定 system prompts 拆到 `prompts.py`，`main_new.py` 改為 import | `python3 -m py_compile main_new.py prompts.py` 通過；`rg` 確認 prompt 定義和引用正常 |
| 2026-06-09 | `main_new.py`, `prompts.py`, `GOAL.md`, `PROGRESS.md` | Phase 3：新增 portfolio strategy review，不直接下單；review 顯示在 email 並寫入 portfolio book | `python3 -m py_compile main_new.py prompts.py` 通過；本機 import 測試因缺少 `xai_sdk` 無法執行 |
| 2026-06-09 | `prompts.py`, `PROGRESS.md` | 修正 portfolio review prompt：明確 portfolio mandate 是美股 AI 產業鏈，避免把 AI / 半導體集中本身誤判為策略錯誤 | `python3 -m py_compile main_new.py prompts.py` 通過 |
| 2026-06-09 | `main_new.py`, `PROGRESS.md` | 將 email 內完整 stock ideas / watchlist 卡片改為三欄 table：Ticker、Company Name、Price，沿用 portfolio table 風格 | `python3 -m py_compile main_new.py prompts.py` 通過 |
| 2026-06-11 | `AGENTS.md`, `GOAL.md`, `PROGRESS.md` | 記錄 AI 決策優化建議：可驗證 thesis、review feedback loop、輕量 validation、決策紀錄加強 | 文件修改；未改程式碼 |
| 2026-06-11 | `AGENTS.md`, `GOAL.md`, `PROGRESS.md` | 從 `soul.md` 精簡抽取控制迴路、降級、安全模式和抗干擾指引，加入專案文件 | 文件修改；未改程式碼 |
| 2026-06-11 | `prompts.py`, `PROGRESS.md` | Phase 3A.1：portfolio buy prompt schema 加入可驗證 thesis 欄位 | Code review：diff 只影響 `PORTFOLIO_SYSTEM_PROMPT`；Debug：`python3 -m py_compile main_new.py prompts.py` 通過 |
| 2026-06-11 | `AGENTS.md`, `PROGRESS.md` | 補充測試邊界：本專案主要在 GitHub Actions 實際運行，AI / email / Actions 實測需 Steven 人工確認或執行 | 文件修改；未改程式碼 |
| 2026-06-11 | `main_new.py`, `PROGRESS.md` | Phase 3A.2：buy 成交時保存 `thesis`、`evidence`、`falsification_points`、`review_trigger` 到 position / trade log | Code review：diff 只影響 buy 欄位保存與文字 list 正規化；Debug：`python3 -m py_compile main_new.py prompts.py` 通過 |
| 2026-06-11 | `main_new.py`, `PROGRESS.md` | Phase 3A.3：portfolio prompt 加入最近 1-3 次 review 壓縮摘要，形成下次決策 feedback loop | Code review：diff 只影響 prompt builder 與 review 摘要 helper；Debug：`python3 -m py_compile main_new.py prompts.py` 通過 |
| 2026-06-11 | `main_new.py`, `PROGRESS.md` | Phase 3A.4：加入輕量 portfolio order validation，過濾不合法 action / ticker / reason，以及缺少 allocation、stop、target、thesis 欄位的 buy | Code review：diff 只影響 order 過濾流程；Debug：`python3 -m py_compile main_new.py prompts.py` 通過 |
| 2026-06-11 | `PROGRESS.md` | Phase 3A.5 評估：暫不新增 append-only AI decision log，避免狀態檔膨脹與 GitHub Actions commit 噪音 | 文件修改；未改程式碼 |
| 2026-06-11 | `prompts.py`, `main_new.py`, `portfolio_book.html`, `PROGRESS.md` | 修正現金部署 prompt，避免 AI 誤解每檔固定 20%；行情表加入 NaN 防護；portfolio page 顯示 latest review 與 thesis / review trigger / falsification points | Code review：diff 只影響 prompt、行情顯示防護、portfolio page 顯示；Debug：`python3 -m py_compile main_new.py prompts.py` 通過，抽出 `portfolio_book.html` script 後 `node --check` 通過 |
| 2026-06-11 | `main_new.py`, `PROGRESS.md` | 緊急修正快速市場行情：yfinance 最後一行可能是 NaN，改為取最後兩個有效 Close，避免 email 顯示 `--` 或 `nan` | Code review：diff 只影響 `fetch_quotes`；Debug：`python3 -m py_compile main_new.py prompts.py` 通過，模擬最後一筆 NaN 時可取前面有效價格 |
| 2026-06-11 | `scripts/push-code.sh`, `AGENTS.md`, `GOAL.md`, `PROGRESS.md` | 新增專用 push 流程，解決 GitHub Actions 先 commit `daily-data` 狀態檔導致本機 push 被拒絕的問題 | 文件/腳本修改；腳本會 fetch、確認遠端只含 `daily-data/` 更新、rebase、py_compile、push |
| 2026-06-11 | `portfolio_book.html`, `PROGRESS.md` | 修正 Portfolio Strategy Review 版面：改為 full-width summary + 四欄 review cards，對齊現有 portfolio page 深色卡片設計 | Code review：diff 只影響 review 區塊 CSS/HTML render；Debug：抽出 `portfolio_book.html` script 後 `node --check` 通過，`python3 -m py_compile main_new.py prompts.py` 通過 |

## 暫停 / 恢復記錄

| 日期 | 狀態 | 下一步 |
|------|------|--------|
| 2026-06-09 | 文件基礎建立 | 後續若修改 prompt 或 portfolio review，先按 `GOAL.md` 路線圖小步執行 |
| 2026-06-09 | Phase 2 完成 | 下一步可開始 Phase 3：Portfolio Review；需先確認是否新增第三次 AI 呼叫 |
| 2026-06-09 | Phase 3 第一版完成 | 下一步人工觀察 GitHub Actions 實際報告中的 review 質素和 token 成本 |
| 2026-06-11 | Phase 3A.5 暫緩 | 下一步建議由 Steven 在 GitHub Actions 實測一次 AI / email 流程，再按輸出質素決定是否調整 validation 或 log |
| 2026-06-11 | Push 流程補強 | 後續功能 commit 用 `scripts/push-code.sh`，避免被遠端 Actions 狀態檔更新卡住 |

## 決策記錄

| 日期 | 決策 | 原因 |
|------|------|------|
| 2026-06-09 | 建立三份根目錄專案文件 | 方便 Codex 後續遵守專案規範，並追蹤每次修改 |
| 2026-06-09 | `daily-data/xai_portfolio_book.json` 暫時保持 Git 追蹤 | GitHub Actions 會自動更新，本機測試前後用 `git status` 控制風險 |
| 2026-06-11 | AI 決策優化先走 thesis discipline | 先提高決策可驗證性，不一次改交易執行規則或引入新 dependency |
