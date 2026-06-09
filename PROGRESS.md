# Daily Report — PROGRESS.md

> 最後更新：2026-06-09
> 當前階段：Phase 3 — Portfolio Review 完成第一版

## 總覽

| Phase | 狀態 | 開始日期 | 完成日期 |
|-------|------|----------|----------|
| Phase 1：文件與工作流基礎 | 完成 | 2026-06-09 | 2026-06-09 |
| Phase 2：Prompt 可維護性 | 完成 | 2026-06-09 | 2026-06-09 |
| Phase 3：Portfolio Review | 進行中 | 2026-06-09 | — |
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

## 修改記錄

| 日期 | 修改檔案 | 內容 | Code Review / Debug |
|------|----------|------|---------------------|
| 2026-06-09 | `AGENTS.md`, `GOAL.md`, `PROGRESS.md` | 參考 Claire 專案文件，建立 daily-report 專用規範、目標和進度追蹤 | `git status --short` 確認只有三個新文件 |
| 2026-06-09 | `GOAL.md`, `PROGRESS.md` | 補充每階段完成後必須自動 code review、debug / 驗證、記錄；需要人工測試時提醒 Steven | `git status --short` 確認只有三個文件變更 |
| 2026-06-09 | `main_new.py`, `prompts.py`, `GOAL.md`, `PROGRESS.md` | Phase 2：固定 system prompts 拆到 `prompts.py`，`main_new.py` 改為 import | `python3 -m py_compile main_new.py prompts.py` 通過；`rg` 確認 prompt 定義和引用正常 |
| 2026-06-09 | `main_new.py`, `prompts.py`, `GOAL.md`, `PROGRESS.md` | Phase 3：新增 portfolio strategy review，不直接下單；review 顯示在 email 並寫入 portfolio book | `python3 -m py_compile main_new.py prompts.py` 通過；本機 import 測試因缺少 `xai_sdk` 無法執行 |

## 暫停 / 恢復記錄

| 日期 | 狀態 | 下一步 |
|------|------|--------|
| 2026-06-09 | 文件基礎建立 | 後續若修改 prompt 或 portfolio review，先按 `GOAL.md` 路線圖小步執行 |
| 2026-06-09 | Phase 2 完成 | 下一步可開始 Phase 3：Portfolio Review；需先確認是否新增第三次 AI 呼叫 |
| 2026-06-09 | Phase 3 第一版完成 | 下一步人工觀察 GitHub Actions 實際報告中的 review 質素和 token 成本 |

## 決策記錄

| 日期 | 決策 | 原因 |
|------|------|------|
| 2026-06-09 | 建立三份根目錄專案文件 | 方便 Codex 後續遵守專案規範，並追蹤每次修改 |
| 2026-06-09 | `daily-data/xai_portfolio_book.json` 暫時保持 Git 追蹤 | GitHub Actions 會自動更新，本機測試前後用 `git status` 控制風險 |
