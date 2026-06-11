# Daily Report — GOAL.md

## 願景

建立一個自動化美股市場快報系統，定時整合市場行情、AI / 半導體產業訊號、X 市場共識和模擬 portfolio 狀態，產出可執行、可追蹤、可持續優化的每日投資簡報。

## 核心用途

- 每個交易日自動產生美股 / AI 產業鏈市場摘要。
- 追蹤 watchlist、removelist、portfolio 狀態和交易紀錄。
- 使用 xAI 協助產生市場分析、候選股和 portfolio buy / hold / sell 決策。
- 透過 GitHub Actions 自動執行並更新 `daily-data/` 狀態檔。
- 以 HTML email 和 portfolio 頁面呈現結果。

## 主要設計原則

1. **穩定優先**：自動化報告不能因小改動中斷。
2. **最小控制**：每次只改最必要的部分，避免一次改多個交易邏輯。
3. **反饋驅動**：根據報告結果、portfolio 表現和測試回饋逐步修正。
4. **可追蹤**：重要策略、prompt、portfolio 格式和 workflow 變更必須記錄在 `PROGRESS.md`。
5. **資料保守**：`daily-data/` 是系統狀態來源，不能隨意清除。
6. **人工可 review**：Prompt 和策略規則應使用繁體中文描述，JSON key 保持英文。
7. **可降級**：外部 API、AI、email 或測試不可用時，系統應保留最小可用輸出並清楚標記限制。
8. **抗干擾**：避免無關檔案、無關重構和過度設計影響每日報告主流程。

## 當前系統範圍

- 市場資料：S&P 500、NASDAQ、DJI、美債 10 年、VIX。
- AI 分析範圍：美股、美國上市 ETF、NASDAQ、DJI。
- Portfolio 限制：
  - 初始資金：`5000`
  - 每次買入金額：`1000`
  - 最多持倉：`5`
  - 只允許美股普通股與美國上市 ETF

## 路線圖

每個 Phase 都是分拆修改的單位。Phase 完成時必須先自動執行 code review、debug / 最小可行驗證，然後更新 `PROGRESS.md`，最後才回報完成。

### 每階段完成流程

1. **Code Review**：檢查是否有 bug、regression、無關重構、secret 外洩、資料格式破壞。
2. **Debug / 驗證**：按改動範圍執行最小可行測試，例如 `python3 -m py_compile main_new.py`、本機 dry run、或檢查 GitHub Actions YAML。
3. **人工測試提醒**：如果涉及實際寄信、GitHub Actions、AI token 消耗、portfolio 狀態檔、HTML 顯示或外部 API，必須提醒 Steven 需要人工確認。
4. **記錄**：更新 `PROGRESS.md` 的修改記錄、review 結果、debug 結果、下一步 / 暫停點。
5. **校正**：如驗證失敗或改動超出目標，先縮小修改範圍，回到最小可行方案。
6. **Push**：功能 commit 不包含 `daily-data/*.json`；用 `scripts/push-code.sh` 處理遠端 Actions 狀態檔更新後再 push。

### Phase 1：文件與工作流基礎

- [x] 建立 `AGENTS.md`
- [x] 建立 `GOAL.md`
- [x] 建立 `PROGRESS.md`
- [ ] 建立穩定的修改記錄習慣

### Phase 2：Prompt 可維護性

- [x] 評估是否把固定 prompt 拆到獨立檔案
- [x] 保持 prompt 繁體中文可 review
- [x] 保持 JSON schema 與現有程式相容

### Phase 3：Portfolio Review

- [x] 新增 portfolio review prompt
- [x] Review 使用壓縮市況、現有持倉和最近交易
- [x] Review 只輸出策略檢討，不直接下單
- [ ] 視效果決定是否把 review 摘要餵回下一次 portfolio prompt

### Phase 3A：AI 決策品質與可追蹤性

- [ ] Portfolio buy prompt 加入可驗證 thesis 欄位：`thesis`、`evidence`、`falsification_points`、`review_trigger`
- [ ] 將最近 1-3 次 portfolio review 壓縮餵回 portfolio manager prompt，形成低 token 閉環
- [ ] 加入輕量 AI output validation，檢查 `orders`、`action`、ticker、allocation、stop / target 合理性
- [ ] 保存 buy thesis 到 portfolio position / trade log，方便日後復盤
- [ ] 視需要追加 append-only AI decision log，保存 prompt 摘要與 AI output

### Phase 4：報告與資料穩定性

- [ ] 檢查 GitHub Actions 自動更新狀態檔流程
- [ ] 避免本機測試資料誤 push
- [ ] 改善錯誤處理和 fallback 報告品質

## 成功指標

- GitHub Actions 可穩定定時執行。
- 每次報告都能產生清楚、可讀、可執行的市場摘要。
- 外部資料或 AI 失效時，fallback 報告不誤導、不假裝完整分析。
- Portfolio 狀態、交易紀錄和策略變更可追蹤。
- AI buy 決策包含可驗證 thesis，後續 review 可根據證據檢討，而不是只看敘述理由。
- Prompt 修改容易人工 review，不需要每次在大型 `main_new.py` 裡搜尋。
- 本機測試不會污染自動更新資料。
