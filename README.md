# Zcode-Token_Plugin

ZCode 插件：**Token 用量统计（token-usage）**。纯本地统计 ZCode 会话的 token 消耗与费用估算，统计过程本身**零 token 消耗**。

当前版本：v0.3.0

## 功能

| 入口 | 说明 |
|---|---|
| 自动（钩子） | 每轮对话结束自动更新本地用量报告，无需任何操作 |
| `/usage` | 在会话里查看当前（或全部）会话的用量报告：输入 / 缓存命中 / 缓存写入 / 输出，按来源（主对话 / 子代理 / 搜索…）与按模型分列 |
| `/usage-dashboard` | 在浏览器打开本地用量仪表盘 |

仪表盘（Apple 简约白风格，纯静态单文件 HTML）：

- 近 7 天 / 近 30 天 / 全部 时间范围切换
- 金额估算（单价可在 `prices.json` 中按模型修改）
- 分模型 API 请求次数、token 消耗堆叠图（输入缓存命中 / 输入未命中 / 输出）
- 鼠标悬停图表查看每日具体数量，30 秒自动刷新

## 数据来源与隐私

- 数据来自本地记录 `~/.zcode/cli/rollout/model-io-*.jsonl`，全部统计在本地完成，不联网、不上传、不消耗 token
- 输出目录默认 `~/.zcode/token-usage/`，可通过环境变量 `ZCODE_TOKEN_USAGE_DIR` 重定向到其他盘

## 安装

克隆本仓库，在 ZCode 的插件市场中把仓库内的 `plugins` 目录添加为本地市场源，即可安装 `token-usage` 插件。

详细说明见 [plugins/token-usage/README.md](plugins/token-usage/README.md)。
