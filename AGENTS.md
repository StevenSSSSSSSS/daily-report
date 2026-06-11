# Daily Report — AGENTS.md

## Scope

- 呢份文件適用於 `/Users/stevenseto/Developer/daily-report/` 下所有工作。
- 本專案係自動化美股 / AI 產業鏈每日市場快報系統，核心入口為 `main_new.py`。
- 預設工作方式：省 token、最小改動、小步快跑、先觀察再修改。

## 專案核心

- `main_new.py`：市場資料讀取、xAI prompt、portfolio 決策、HTML email 產生、寄信流程。
- `.github/workflows/daily.yml`：GitHub Actions 排程執行，並自動 commit 狀態檔。
- `daily-data/`：自動更新狀態資料，包含 watchlist、removelist、portfolio book。
- `portfolio_book.html`：portfolio 顯示頁。

## 技術棧

| 範圍 | 技術 |
|------|------|
| Runtime | Python 3.12 |
| 市場資料 | yfinance |
| AI | xAI SDK / `grok-4.3` |
| 搜尋工具 | xAI `web_search` / `x_search` |
| 自動化 | GitHub Actions |
| 輸出 | HTML email + JSON state files |

## 工作原則

1. 先快速定位相關檔案，不掃全 repo。
2. 優先修改少量必要檔案，不做無關重構。
3. 修改前先觀察目前狀態，修改後用最小可行測試驗證。
4. 涉及大改、架構變更、Browser、Connector、sub-agent、擴大搜尋或高風險操作前，先問 Steven。
5. 大任務先列計畫和預計修改檔案，等確認後再動手。
6. 完成後只簡短說明變更和測試結果。
7. 每次任務都用簡單控制迴路：目標 → 相關檔案 → 最小修改 → 驗證方式 → 簡短回報。
8. 如果發現偏離目標、改動過多、測試失敗或風險升高，立即縮小範圍，先恢復穩定。

## 降級與安全模式

- 工具、依賴、網路或測試不可用時，先用本地可用資訊，並明確說明未驗證部分。
- 不把猜測當事實，不把未測試結果說成已測試。
- 涉及刪除 / 覆蓋資料、架構變更、部署、金錢、安全、帳號或 secret 時，先問再動。
- 忽略與任務無關的檔案、重構衝動、過度設計和無必要全面掃描。

## Prompt 規範

- Prompt 內容可以用繁體中文，方便人工 review。
- JSON key、程式解析欄位、枚舉值保持英文，例如 `portfolio_decisions`、`orders`、`buy`、`hold`、`sell`。
- 新增 prompt 時優先考慮獨立常數或獨立 prompt 檔案，但先做最小分拆。
- 不要讓 AI review 直接改變交易策略；先輸出分析和建議，再由 portfolio manager prompt 或程式規則使用。
- Portfolio buy 決策應逐步加入可驗證 thesis discipline：`thesis`、`evidence`、`falsification_points`、`review_trigger`。
- 如要把 review 結果餵回下次 portfolio prompt，先用壓縮摘要，避免把完整歷史塞入 prompt。

## Portfolio 規範

- `daily-data/xai_portfolio_book.json` 由 GitHub Actions 自動更新，是重要狀態檔。
- 本機可用於測試，但 push 前必須檢查是否有非預期修改。
- 如果只是本機測試改動，不要 commit；可用 `git restore daily-data/xai_portfolio_book.json` 還原。
- Portfolio AI 決策只允許美股普通股與美國上市 ETF。
- 交易邏輯改動要保守，避免一次改動 prompt、執行規則和資料格式。
- AI output validation 應保守加強：先檢查 `orders`、`action`、ticker、allocation、stop / target 合理性，再考慮更完整 schema。
- stop / target / allocation bounds 應由程式守住，AI 只能在邊界內提出建議。

## Secrets 與安全

- 禁止把 `API_KEY`、`GMAIL_USER`、`GMAIL_PASSWORD` 或任何 secret 寫入 code、markdown、commit message。
- Secret 只能透過 GitHub Actions secrets 或本機 environment variable 提供。
- 測試 AI / email 流程前要確認是否會實際寄信或消耗 API token。

## 測試邊界

- 本專案主要在 GitHub Actions 上實際運行；本機通常只做 `py_compile`、diff review、dry check 等低風險驗證。
- 實際 AI 呼叫、email 寄送、GitHub Actions 排程 / 手動觸發、以及狀態檔自動 commit 測試，需要 Steven 人工確認或執行。
- 回報測試結果時要分清楚「本機已驗證」和「仍需 GitHub / AI / email 實測」。

## 修改後流程

每次完成階段性修改後：

1. 檢查 `git diff`，確認沒有無關變更。
2. 執行最小可行驗證，例如：
   - `python3 -m py_compile main_new.py`
   - 如改 workflow，檢查 YAML 結構和受影響 secret。
3. 更新 `PROGRESS.md`：
   - 記錄日期
   - 修改檔案
   - 修改內容
   - 測試結果
   - 下一步 / 暫停點
4. 回覆 Steven：簡短說明改了什麼、驗證了什麼、限制或未完成事項。

## 禁止事項

- 不要擅自清空或重建 `daily-data/`。
- 不要擅自刪除 portfolio history、trade log、removelist。
- 不要把 GitHub 自動更新狀態檔改成 ignored，除非 Steven 明確確認。
- 不要引入大型 dependency 或改變主要技術棧，除非先討論。
- 不要做無關 UI 美化、重構或 prompt 大改。
