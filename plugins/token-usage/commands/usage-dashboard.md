---
description: 在浏览器打开本地 token 用量可视化面板（时间筛选、金额估算、图表）
---

打开 token 用量可视化面板（一个本地 HTML 文件，零 token 消耗）：

1. 用 Bash 运行 `echo "${ZCODE_TOKEN_USAGE_DIR:-$HOME/.zcode/token-usage}"` 得到报告目录 `<DIR>`。
2. 若 `<DIR>/latest.json` 存在，读取其中 `dashboardPath`；否则直接用 `<DIR>/dashboard.html`。
3. 若该 HTML 文件不存在，用 Bash 运行 `python "<插件报告目录同级的已安装插件路径>/hooks/token_usage_report.py" --dashboard` 重新生成（找不到脚本时，直接提示用户"面板尚未生成，等本轮结束后 Stop 钩子会自动生成"并结束）。
4. 用 Bash 在默认浏览器中打开它（Windows）：`cmd /c start "" "<dashboard.html 的完整路径>"`。
5. 告诉用户：面板支持"近7天 / 近30天 / 全部"筛选；数据在每轮会话结束后由本地钩子自动重算，浏览器里按 F5 即可看到最新；消费金额需要在 `<DIR>/prices.json` 中配置单价后才会显示。
