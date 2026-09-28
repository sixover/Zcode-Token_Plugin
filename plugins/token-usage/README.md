# token-usage

ZCode 插件：本地统计会话 token 用量。**零 token 开销**——分析与统计全部由本地脚本完成，不经过模型、不注入会话上下文。

## 提供什么

- **每轮自动更新**：`SessionStart`（startup/resume）与 `Stop` 钩子运行本地分析脚本（`type: "process"`，不经模型），把报告写到本地文件。
- **`/usage` 命令**：随时向模型要一份用量汇报（模型只负责读报告文件并转述）。
  - `/usage` —— 当前会话
  - `/usage all` —— 全部会话汇总
- **`/usage-dashboard` 命令**：在浏览器打开本地可视化面板 `dashboard.html`：
  - 时间维度筛选：近 7 天 / 近 30 天 / 全部
  - 每日 token 堆叠图：细分缓存命中输入、非缓存输入（含缓存写入）、输出
  - 每日消费金额与按模型金额（需先在 `prices.json` 配置单价，单位：元/百万 token）
  - 按模型汇总表：请求次数、各类 token、缓存命中率
  - 数据每轮由 Stop 钩子本地重算；浏览器中按 F5 或勾选"30秒自动刷新"查看最新
- **报告文件**（可直接打开查看，模型不参与）：
  - `~/.zcode/token-usage/<会话ID>.md` —— 单会话报告
  - `~/.zcode/token-usage/dashboard.html` —— 可视化面板（浏览器打开）
  - `~/.zcode/token-usage/prices.json` —— 单价配置（已预置 GLM-5.3-Flash 与 GLM-5.3 定价，可自行修改）
  - `~/.zcode/token-usage/sessions.md` —— 跨会话汇总（运行过 `/usage all` 后生成）
  - `~/.zcode/token-usage/latest.json` —— 最新报告指针

> 说明：应用内置的统计面板没有插件 UI 扩展点，无法注入图表；本插件的可视化面板是同数据源的本地网页替代方案。金额为按单价的估算值，不代表账单。

## 统计口径

| 指标 | 来源字段 |
|---|---|
| 输入（含缓存） | `usage.inputTokens` |
| 缓存命中 | `usage.cacheReadTokens` |
| 缓存写入 / 未命中 | `usage.cacheWriteTokens` |
| 输出 | `usage.outputTokens` |
| 推理 token | `usage.reasoningTokens`（仅当模型在 usage 中上报时显示） |
| 来源占比 | `querySource`：main_turn / subagent / compact / web_search_tool / web_fetch_processing |
| 模型占比 | `model.modelId` |

数据源：`~/.zcode/cli/rollout/model-io-*.jsonl`（ZCode 每次模型调用一行）。

## 依赖

- 本机 `python`（3.9+，仅标准库）在 PATH 中。钩子以 `process` 方式调用 `python`；若缺失，钩子会在日志中记录失败但不影响会话。
- 插件钩子自动启用 hook runner，无需在配置中手动开启。

## 报告写到哪个盘

默认写在 `~/.zcode/token-usage/`（即 C 盘用户目录）。每个会话只新增一个约 1.5KB 的报告文件、每轮原地覆写，占用可忽略；但如需完全避开 C 盘，设置用户级环境变量后重启 ZCode 即可重定向：

```bat
setx ZCODE_TOKEN_USAGE_DIR "F:\zcode-token-usage"
```

- 对 `/usage all` 生成的跨会话汇总 `sessions.md`、指针文件 `latest.json` 一并生效。
- 注意两点：① 需重启 ZCode 才会让钩子进程拿到新环境变量；② 改向后如想清掉 C 盘旧报告，直接删除 `~/.zcode/token-usage/` 整个文件夹即可，不影响任何功能。
- 另请知悉：C 盘上 `~/.zcode/cli/rollout/`（34MB 量级）是 ZCode 本体记录的每次模型调用数据，是本插件的**数据源**，由 ZCode 自己管理，不属于本插件的占用。

## 成本说明

- 钩子与统计脚本：0 token。
- `/usage`：仅调用那一次花费少量 token（读文件 + 转述，约千级）；平时放着不用则完全无开销。
