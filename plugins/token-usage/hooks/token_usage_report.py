#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ZCode plugin "token-usage": local session token usage analyzer.

Reads per-call usage records from ~/.zcode/cli/rollout/model-io-sess_*.jsonl
and writes a markdown report plus a latest.json pointer under
~/.zcode/token-usage/.

Hook usage (SessionStart / Stop):
    python token_usage_report.py --session <sessionId>
Optional:
    --all   also (re)write the cross-session summary sessions.md

Prints nothing on success and always exits 0 so hooks stay quiet; errors go
to stderr. Requires only the Python 3 standard library (3.9+).
"""
import argparse
import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

HOME = os.path.expanduser("~")
ROLLOUT_DIR = os.path.join(HOME, ".zcode", "cli", "rollout")
# Output directory: override with the ZCODE_TOKEN_USAGE_DIR environment variable
# (set it at user level and restart ZCode so hook processes inherit it).
_out_dir_env = os.environ.get("ZCODE_TOKEN_USAGE_DIR", "").strip()
OUT_DIR = os.path.abspath(os.path.expanduser(_out_dir_env)) if _out_dir_env else os.path.join(HOME, ".zcode", "token-usage")

SOURCE_LABELS = {
    "main_turn": "main_turn（主对话）",
    "subagent": "subagent（子代理）",
    "compact": "compact（上下文压缩）",
    "web_search_tool": "web_search_tool（联网搜索）",
    "web_fetch_processing": "web_fetch_processing（网页抓取）",
    "session_title": "session_title（会话标题生成）",
}


def num(*vals):
    """First value that is a real number (ints only; bools/None/strings skipped)."""
    for v in vals:
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            return int(v)
    return 0


def dig(d, *path):
    cur = d
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def extract_call(d):
    """Normalize one model_io record into a flat dict, or None if it has no usage."""
    resp = d.get("response") or {}
    u = resp.get("usage") if isinstance(resp.get("usage"), dict) else {}
    body = resp.get("body")
    ru = body.get("usage") if isinstance(body, dict) and isinstance(body.get("usage"), dict) else {}
    inp = num(u.get("inputTokens"), u.get("input_tokens"), ru.get("input_tokens"))
    out = num(u.get("outputTokens"), u.get("output_tokens"), ru.get("output_tokens"))
    cache_read = num(u.get("cacheReadTokens"), u.get("cache_read_input_tokens"), ru.get("cache_read_input_tokens"))
    cache_write = num(u.get("cacheWriteTokens"), u.get("cache_creation_input_tokens"), ru.get("cache_creation_input_tokens"))
    reasoning = num(
        u.get("reasoningTokens"),
        dig(ru, "completion_tokens_details", "reasoning_tokens"),
        dig(ru, "output_tokens_details", "reasoning_tokens"),
    )
    searches = num(dig(ru, "server_tool_use", "web_search_requests"))
    if not (inp or out or cache_read or cache_write or reasoning or searches):
        return None
    model = (d.get("model") or {}).get("modelId") or "unknown"
    return {
        "src": d.get("querySource") or "unknown",
        "model": model,
        "in": inp,
        "out": out,
        "cr": cache_read,
        "cw": cache_write,
        "reasoning": reasoning,
        "searches": searches,
        "ts": d.get("completedAt") or d.get("startedAt"),
        "dur": num(d.get("durationMs")),
    }


def read_calls(paths):
    calls = []
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    call = extract_call(record)
                    if call:
                        calls.append(call)
        except OSError:
            continue
    return calls


class Stats(object):
    def __init__(self):
        self.calls = 0
        self.totals = {"in": 0, "out": 0, "cr": 0, "cw": 0, "reasoning": 0, "searches": 0}
        self.by_src = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "cr": 0, "cw": 0})
        self.by_model = defaultdict(lambda: {"calls": 0, "in": 0, "out": 0, "cr": 0, "cw": 0})
        self.first_ts = None
        self.last_ts = None
        self.duration_ms = 0
        self.latest_in = 0
        self.latest_model = "unknown"

    def add(self, call):
        self.calls += 1
        for key in self.totals:
            self.totals[key] += call[key]
        for bucket in (self.by_src[call["src"]], self.by_model[call["model"]]):
            bucket["calls"] += 1
            bucket["in"] += call["in"]
            bucket["out"] += call["out"]
            bucket["cr"] += call["cr"]
            bucket["cw"] += call["cw"]
        if call["ts"]:
            if self.first_ts is None:
                self.first_ts = call["ts"]
            self.last_ts = call["ts"]
        self.duration_ms += call["dur"]
        self.latest_in = call["in"]
        self.latest_model = call["model"]


def aggregate(paths):
    stats = Stats()
    for call in read_calls(paths):
        stats.add(call)
    return stats


def rollout_paths(session_id):
    sid = (session_id or "").strip()
    if not sid:
        return []
    bare = sid[5:] if sid.startswith("sess_") else sid
    candidates = []
    for stem in (sid, bare, "sess_" + bare):
        path = os.path.join(ROLLOUT_DIR, "model-io-%s.jsonl" % stem)
        if os.path.isfile(path) and path not in candidates:
            candidates.append(path)
    if not candidates:
        pattern = os.path.join(ROLLOUT_DIR, "model-io-*%s*.jsonl" % bare)
        candidates = sorted(glob.glob(pattern), key=os.path.getmtime)
    return candidates


def newest_session_file():
    files = glob.glob(os.path.join(ROLLOUT_DIR, "model-io-sess_*.jsonl"))
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def session_id_from_path(path):
    name = os.path.basename(path)
    if name.startswith("model-io-") and name.endswith(".jsonl"):
        return name[len("model-io-"):-len(".jsonl")]
    return name


def fmt(n):
    return "{:,}".format(int(n))


def safe_name(s):
    return re.sub(r"[^A-Za-z0-9._-]", "_", s or "") or "unknown"


def fmt_ts(ts):
    if not ts:
        return "-"
    text = str(ts).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return str(ts)


def rate(part, whole):
    return (float(part) / whole * 100.0) if whole else 0.0


def totals_table(stats, title):
    t = stats.totals
    lines = [
        "## %s" % title,
        "",
        "| 指标 | 数量 |",
        "|---|---:|",
        "| 输入 token（含缓存读取） | %s |" % fmt(t["in"]),
        "| ├─ 缓存命中 | %s（%.1f%%） |" % (fmt(t["cr"]), rate(t["cr"], t["in"])),
        "| ├─ 缓存写入 / 未命中 | %s |" % fmt(t["cw"]),
        "| └─ 非缓存输入 | %s |" % fmt(t["in"] - t["cr"]),
        "| 输出 token | %s |" % fmt(t["out"]),
        "| 合计（输入 + 输出） | %s |" % fmt(t["in"] + t["out"]),
    ]
    if t["reasoning"]:
        lines.append("| 其中推理 token（如模型上报） | %s |" % fmt(t["reasoning"]))
    if t["searches"]:
        lines.append("| 联网搜索次数 | %s |" % fmt(t["searches"]))
    lines += [
        "",
        "当前上下文规模（最近一次调用的输入）：**%s** token（模型 %s）" % (fmt(stats.latest_in), stats.latest_model),
    ]
    return lines


def breakdown_table(stats, key, title):
    lines = [
        "## %s" % title,
        "",
        "| 来源 | 调用次数 | 输入 | 输出 | 缓存命中 | 缓存写入 |" if key == "src"
        else "| 模型 | 调用次数 | 输入 | 输出 | 缓存命中 | 缓存写入 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    buckets = stats.by_src if key == "src" else stats.by_model
    ordered = sorted(buckets.items(), key=lambda kv: -(kv[1]["in"] + kv[1]["out"]))
    for name, b in ordered:
        label = SOURCE_LABELS.get(name, name) if key == "src" else name
        lines.append(
            "| %s | %s | %s | %s | %s | %s |"
            % (label, fmt(b["calls"]), fmt(b["in"]), fmt(b["out"]), fmt(b["cr"]), fmt(b["cw"]))
        )
    if len(ordered) == 1:
        lines.append("")
        lines.append("（本次统计只有一种取值；其他来源/模型出现后会自动分行显示。）")
    return lines


def render_report(session_id, stats, found_paths):
    t = stats.totals
    header = [
        "# 会话 Token 用量报告",
        "",
        "- 会话：`%s`" % (session_id or "unknown"),
        "- 统计时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "- 模型调用次数：%s 次" % fmt(stats.calls),
        "- 调用时间范围：%s ~ %s" % (fmt_ts(stats.first_ts), fmt_ts(stats.last_ts)),
        "- 累计模型耗时：%.1f 秒" % (stats.duration_ms / 1000.0),
    ]
    if not stats.calls:
        return header + [
            "",
            "暂无模型调用记录（报告文件 %s 未找到或为空）。" % ("、".join(found_paths) if found_paths else "rollout 目录"),
            "发一条消息让模型响应一次后，报告会随 Stop 钩子自动更新。",
        ]
    lines = header + [""] + totals_table(stats, "总量") + [""]
    lines += breakdown_table(stats, "src", "按来源") + [""]
    lines += breakdown_table(stats, "model", "按模型") + [""]
    lines += [
        "---",
        "",
        "说明：输入 token 含缓存读取部分；缓存命中率 = 缓存命中 / 输入总量。"
        "推理 token 仅在模型于 usage 中上报时才会显示。数据来自本地记录文件"
        " `~/.zcode/cli/rollout/model-io-*.jsonl`，由本地脚本统计，统计过程不消耗 token。",
    ]
    return lines


def write_sessions_report(latest_extra):
    files = sorted(
        glob.glob(os.path.join(ROLLOUT_DIR, "model-io-sess_*.jsonl")),
        key=os.path.getmtime,
    )
    rows = []
    grand = {"calls": 0, "in": 0, "out": 0, "cr": 0, "cw": 0}
    for path in files:
        sid = session_id_from_path(path)
        stats = aggregate([path])
        if not stats.calls:
            continue
        rows.append((sid, os.path.getmtime(path), stats))
        grand["calls"] += stats.calls
        grand["in"] += stats.totals["in"]
        grand["out"] += stats.totals["out"]
        grand["cr"] += stats.totals["cr"]
        grand["cw"] += stats.totals["cw"]
    lines = [
        "# 全部会话 Token 用量汇总",
        "",
        "统计时间：%s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "",
        "| 会话 | 最近活动 | 调用 | 输入（含缓存） | 缓存命中 | 输出 | 合计（输入+输出） |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for sid, mtime, stats in sorted(rows, key=lambda r: -r[1]):
        lines.append(
            "| `%s` | %s | %s | %s | %s | %s | %s |"
            % (
                sid,
                datetime.fromtimestamp(mtime).strftime("%m-%d %H:%M"),
                fmt(stats.calls),
                fmt(stats.totals["in"]),
                fmt(stats.totals["cr"]),
                fmt(stats.totals["out"]),
                fmt(stats.totals["in"] + stats.totals["out"]),
            )
        )
    lines += [
        "| **合计** | - | **%s** | **%s** | **%s** | **%s** | **%s** |"
        % (fmt(grand["calls"]), fmt(grand["in"]), fmt(grand["cr"]), fmt(grand["out"]), fmt(grand["in"] + grand["out"])),
        "",
        "缓存总命中率：%.1f%%" % rate(grand["cr"], grand["in"]),
    ]
    path = os.path.join(OUT_DIR, "sessions.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    latest_extra["sessionsReportPath"] = path
    return path


def update_latest(session_id, report_path, stats, dashboard_path=None):
    latest_path = os.path.join(OUT_DIR, "latest.json")
    data = {}
    if os.path.isfile(latest_path):
        try:
            with open(latest_path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                data = loaded
        except (ValueError, OSError):
            data = {}
    data["sessionId"] = session_id
    data["reportPath"] = report_path
    data["updatedAt"] = datetime.now().isoformat(timespec="seconds")
    data["totals"] = dict(stats.totals) if stats else {"calls": 0}
    data["calls"] = stats.calls if stats else 0
    if dashboard_path:
        data["dashboardPath"] = dashboard_path
    with open(latest_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


PRICES_TEMPLATE = {
    "_说明": "单价单位：元/百万 token，按模型 ID 填写。input_cache_read=缓存命中输入；input_cache_write=缓存写入；"
             "input_miss=非缓存输入；output=输出。全部字段为 0 的模型不计入金额（面板显示 —）。",
    "GLM-5.3-Flash": {"input_cache_read": 0.23, "input_cache_write": 0.8, "input_miss": 0.8, "output": 2.8},
    "GLM-5.3": {"input_cache_read": 2, "input_cache_write": 8, "input_miss": 8, "output": 28},
}

# The dashboard UI lives in dashboard_template.html next to this script.


def price_val(v):
    """Prices are decimal (e.g. 0.23 元/M); unlike token counts they must not be int-truncated."""
    if isinstance(v, bool):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    return 0.0


def load_prices():
    """Read OUT_DIR/prices.json (per-model unit prices). Write a template on first run."""
    path = os.path.join(OUT_DIR, "prices.json")
    if not os.path.isfile(path):
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(PRICES_TEMPLATE, fh, ensure_ascii=False, indent=2)
        except OSError:
            pass
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (ValueError, OSError):
        return {}
    prices = {}
    if isinstance(raw, dict):
        for model, cfg in raw.items():
            if model.startswith("_") or not isinstance(cfg, dict):
                continue
            prices[model] = {
                "cr": price_val(cfg.get("input_cache_read")),
                "cw": price_val(cfg.get("input_cache_write")),
                "miss": price_val(cfg.get("input_miss")),
                "out": price_val(cfg.get("output")),
            }
    return prices


def local_date(ts):
    if not ts:
        return None
    text = str(ts).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).astimezone().date().isoformat()
    except ValueError:
        return None


def price_for(prices, model):
    """Case-insensitive price lookup so 'glm-5.3' and 'GLM-5.3' both match."""
    p = prices.get(model)
    if p is None:
        low = model.lower()
        for key, val in prices.items():
            if key.lower() == low:
                return val
    return p


def build_dashboard():
    """Aggregate every rollout file into daily per-model buckets and render dashboard.html."""
    prices = load_prices()
    days = {}
    for call in read_calls(glob.glob(os.path.join(ROLLOUT_DIR, "model-io-*.jsonl"))):
        date = local_date(call["ts"]) or "未知"
        bucket = days.setdefault(date, {})
        agg = bucket.setdefault(call["model"], {"calls": 0, "in": 0, "cr": 0, "cw": 0, "out": 0, "cost": 0.0, "priced": False})
        agg["calls"] += 1
        for key in ("in", "cr", "cw", "out"):
            agg[key] += call[key]
        price = price_for(prices, call["model"])
        if price and any(price.values()):
            cr, cw = call["cr"], call["cw"]
            miss = max(call["in"] - cr - cw, 0)
            cost = (cr * price["cr"] + cw * price["cw"] + miss * price["miss"] + call["out"] * price["out"]) / 1e6
            agg["cost"] += cost
            agg["priced"] = True
    payload = {
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "today": datetime.now().date().isoformat(),
        "days": [{"date": date, "models": models} for date, models in sorted(days.items())],
        "unpricedModels": sorted({m for models in days.values() for m, v in models.items() if not v["priced"]}),
    }
    data_json = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard_template.html")
    with open(template_path, "r", encoding="utf-8") as fh:
        template = fh.read()
    path = os.path.join(OUT_DIR, "dashboard.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(template.replace("__DATA__", data_json))
    return path


def main():
    parser = argparse.ArgumentParser(description="ZCode session token usage report (local, no model involved).")
    parser.add_argument("--session", help="session id (with or without the sess_ prefix)")
    parser.add_argument("--all", action="store_true", help="also write the cross-session summary sessions.md")
    parser.add_argument("--dashboard", action="store_true", help="rebuild the local HTML dashboard")
    args = parser.parse_args()

    try:
        os.makedirs(OUT_DIR, exist_ok=True)
        latest_extra = {}

        if args.all:
            write_sessions_report(latest_extra)

        dashboard_path = build_dashboard() if args.dashboard else None

        session_id = (args.session or "").strip()
        if not session_id:
            newest = newest_session_file()
            if newest:
                session_id = session_id_from_path(newest)
        paths = rollout_paths(session_id)
        stats = aggregate(paths)

        report_path = os.path.join(OUT_DIR, safe_name(session_id) + ".md")
        with open(report_path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(render_report(session_id, stats, paths)) + "\n")
        update_latest(session_id, report_path, stats, dashboard_path)

        # keep any sessionsReportPath from a previous --all run in latest.json
        if latest_extra:
            update_latest(session_id, report_path, stats, dashboard_path)
            with open(os.path.join(OUT_DIR, "latest.json"), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            data.update(latest_extra)
            with open(os.path.join(OUT_DIR, "latest.json"), "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
    except Exception as exc:  # hooks must never fail loudly
        sys.stderr.write("token-usage: %r\n" % (exc,))
    return 0


if __name__ == "__main__":
    sys.exit(main())
