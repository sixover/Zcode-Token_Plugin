---
description: 查看会话 token 用量统计（总量、缓存命中/未命中、输出、来源与模型占比）
---

向用户呈现 token 用量报告，步骤如下：

1. 先确定报告目录：用 Bash 运行 `echo "${ZCODE_TOKEN_USAGE_DIR:-$HOME/.zcode/token-usage}"` 得到目录 `<DIR>`，然后用 Read 读取 `<DIR>/latest.json`。
2. 若参数为 "all"：读取其中 `sessionsReportPath` 指向的跨会话汇总并完整呈现；若该字段或文件不存在，提示用户"尚无跨会话汇总，稍后重试"并结束。
3. 否则（默认）：读取 `reportPath` 字段指向的报告文件，**完整转述**其中的数字——保留表格结构，特别是"按来源"和"按模型"两个表格，不要省略行。
4. 若 latest.json 或报告文件不存在（插件刚安装、钩子尚未运行过），改用 Bash 运行下面这段与插件分析器等价的内联脚本，并把它打印的内容转述给用户：

```bash
python - <<'PY'
import json, glob, os
fs = sorted(glob.glob(os.path.expanduser('~/.zcode/cli/rollout/model-io-sess_*.jsonl')), key=os.path.getmtime)
p = fs[-1] if fs else None
t = {'i': 0, 'o': 0, 'c': 0, 'w': 0}
src = {}
if p:
    for ln in open(p, encoding='utf-8', errors='replace'):
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        u = (d.get('response') or {}).get('usage') or {}
        i = u.get('inputTokens', 0); o = u.get('outputTokens', 0)
        c = u.get('cacheReadTokens', 0); w = u.get('cacheWriteTokens', 0)
        if not (i or o):
            continue
        t['i'] += i; t['o'] += o; t['c'] += c; t['w'] += w
        s = src.setdefault(d.get('querySource') or 'unknown', [0, 0, 0])
        s[0] += 1; s[1] += i; s[2] += o
print('报告文件:', os.path.basename(p) if p else '(无)')
print('调用次数:', sum(s[0] for s in src.values()))
if t['i']:
    print('输入(含缓存): {:,}  命中: {:,} ({:.1f}%)  写入/未命中: {:,}  非缓存输入: {:,}'.format(
        t['i'], t['c'], t['c'] * 100.0 / t['i'], t['w'], t['i'] - t['c']))
print('输出: {:,}  合计(输入+输出): {:,}'.format(t['o'], t['i'] + t['o']))
for k, s in sorted(src.items(), key=lambda x: -(x[1][1] + x[1][2])):
    print('  来源 {:24s} 次数 {:<4d} 输入 {:>12,} 输出 {:>9,}'.format(k, s[0], s[1], s[2]))
PY
```

5. 提醒用户：报告由本地 Stop 钩子每轮自动更新，也可随时打开 `<DIR>` 下的报告文件直接查看。
