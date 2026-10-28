# -*- coding: utf-8 -*-
"""
样稿制作数据周报
- 每周一上午 10:00 推送到飞书群
- 内容：上周（周一~周日）+ 本月累计
- 维度：制作人 / 制作类型 / 商家（只统计样稿数量）
"""
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
import calendar

BEIJING_TZ = timezone(timedelta(hours=8))

# ==================== 配置 ====================
FEISHU_WEBHOOK = os.environ.get(
    "FEISHU_WEBHOOK",
    "https://open.feishu.cn/open-apis/bot/v2/hook/e28f339a-d9ff-416f-b82b-6a6d1821a22b"
)
FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "cli_a94135e7057b9bef")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
BITABLE_APP_TOKEN = os.environ.get("BITABLE_APP_TOKEN", "JWV3bVG68aZSN0sr8VecH48Tnqh")
BITABLE_TABLE_ID = os.environ.get("BITABLE_TABLE_ID", "tblKajqwSWLVr3bh")

DATA_FILE = os.environ.get("DATA_FILE", "")
# 商家列表最多显示多少个，其余合并为「其他N家」
MERCHANT_TOP_N = int(os.environ.get("MERCHANT_TOP_N", "8"))
# 详情链接（多维表）
DETAIL_URL = os.environ.get(
    "DETAIL_URL",
    "https://zibfgih0a9y.feishu.cn/base/JWV3bVG68aZSN0sr8VecH48Tnqh?table=blkHTtEnHM1Rm8Fm"
)


# ==================== HTTP ====================
def _http_post(url, payload):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get(url, token, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ==================== 数据 ====================
def _to_int(v):
    if v is None:
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    if not s:
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def _text(v):
    """飞书文本 / 单选 / 多选 / 人员字段统一转字符串"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, list):
        parts = []
        for it in v:
            if isinstance(it, dict):
                parts.append(it.get("text") or it.get("name") or "")
            else:
                parts.append(str(it))
        return "、".join(p for p in parts if p)
    if isinstance(v, dict):
        return v.get("text") or v.get("name") or ""
    return str(v)


def _date(v):
    """日期字段 → YYYY-MM-DD（北京时间）"""
    if not v:
        return None
    if isinstance(v, (int, float)):
        try:
            return datetime.fromtimestamp(v / 1000, tz=BEIJING_TZ).strftime("%Y-%m-%d")
        except Exception:
            return None
    s = str(v)[:10]
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except Exception:
        return None


def normalize(fields):
    return {
        "maker": _text(fields.get("制作人")) or "未填",
        "mtype": _text(fields.get("制作类型")) or "未填",
        "merchant": _text(fields.get("商家")) or "未填",
        "count": _to_int(fields.get("样稿数量")),
        "date": _date(fields.get("交付时间")),
    }


def fetch_from_bitable():
    if not FEISHU_APP_SECRET:
        raise RuntimeError("缺少 FEISHU_APP_SECRET 环境变量")

    tk = _http_post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        {"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
    )
    if tk.get("code") != 0:
        raise RuntimeError(f"获取飞书令牌失败: {tk}")
    token = tk["tenant_access_token"]

    url = (f"https://open.feishu.cn/open-apis/bitable/v1/apps/"
           f"{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/records")
    items, page_token, page = [], None, 0
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        res = _http_get(url, token, params)
        if res.get("code") != 0:
            raise RuntimeError(f"读取多维表失败: {res}")
        data = res.get("data", {})
        page += 1
        batch = data.get("items", [])
        items.extend(batch)
        print(f"  第{page}页 +{len(batch)} 条")
        if not data.get("has_more"):
            break
        page_token = data.get("page_token")

    return [normalize(r.get("fields", {})) for r in items]


def load_from_file(path):
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    out = []
    for r in raw:
        sc = r.get("sampleCount")
        if sc is None:
            sc = r.get("样稿数量")
        out.append({
            "maker": r.get("maker") or r.get("制作人") or "未填",
            "mtype": r.get("mtype") or r.get("制作类型") or "未填",
            "merchant": r.get("merchant") or r.get("商家") or "未填",
            "count": _to_int(sc),
            "date": _date(r.get("deliverDate") or r.get("交付时间")),
        })
    return out


def load_records():
    if DATA_FILE and os.path.exists(DATA_FILE):
        try:
            recs = load_from_file(DATA_FILE)
            print(f"从本地文件加载 {len(recs)} 条：{DATA_FILE}")
            return recs
        except Exception as e:
            print(f"本地文件读取失败({e})，改为直连多维表")
    recs = fetch_from_bitable()
    print(f"从多维表拉取 {len(recs)} 条")
    return recs


# ==================== 统计 ====================
def date_range():
    now = datetime.now(BEIJING_TZ)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    this_monday = today - timedelta(days=today.weekday())
    last_monday = this_monday - timedelta(days=7)
    last_sunday = this_monday - timedelta(days=1)
    month_start = today.replace(day=1)
    month_end = today.replace(day=calendar.monthrange(now.year, now.month)[1])
    return {
        "last_monday": last_monday, "last_sunday": last_sunday,
        "month_start": month_start, "month_end": month_end,
        "now": now, "today": today,
    }


def aggregate(records, start, end):
    by_maker, by_type, by_merchant = {}, {}, {}
    total = 0
    s, e = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    for r in records:
        d = r["date"]
        if not d or not (s <= d <= e):
            continue
        c = r["count"]
        total += c
        by_maker[r["maker"]] = by_maker.get(r["maker"], 0) + c
        by_type[r["mtype"]] = by_type.get(r["mtype"], 0) + c
        by_merchant[r["merchant"]] = by_merchant.get(r["merchant"], 0) + c
    return {"total": total, "maker": by_maker, "type": by_type, "merchant": by_merchant}


def _join(items, limit=None):
    items = [(k, v) for k, v in items if v > 0]
    if not items:
        return "（无数据）"
    items.sort(key=lambda x: -x[1])
    head = items[:limit] if limit else items
    txt = " · ".join(f"{k} {v}" for k, v in head)
    if limit and len(items) > limit:
        rest = sum(v for _, v in items[limit:])
        txt += f" · 其他{len(items) - limit}家 {rest}"
    return txt


def build_section(title, stats):
    return [
        f"【{title}】",
        f"合计 {stats['total']} 个样稿",
        f"👤 制作人：{_join(stats['maker'].items())}",
        f"🧩 制作类型：{_join(stats['type'].items())}",
        f"🏪 商家：{_join(stats['merchant'].items(), MERCHANT_TOP_N)}",
    ]


def build_report(records):
    r = date_range()
    last = aggregate(records, r["last_monday"], r["last_sunday"])
    month = aggregate(records, r["month_start"], r["today"])

    lines = [
        "📊 样稿制作数据周报",
        f"统计时间：{r['now'].strftime('%Y-%m-%d %H:%M')}",
        "",
    ]
    lines += build_section(
        f"上周 {r['last_monday'].strftime('%m.%d')}-{r['last_sunday'].strftime('%m.%d')}", last)
    lines += [""]
    lines += build_section(
        f"本月 {r['month_start'].strftime('%m.%d')}-{r['today'].strftime('%m.%d')}", month)
    lines += [
        "",
        f"详细数据可点击链接查看：{DETAIL_URL}",
    ]
    return "\n".join(lines), last, month


# ==================== 发送 ====================
def send_feishu(message):
    payload = json.dumps({
        "msg_type": "text",
        "content": {"text": message},
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        FEISHU_WEBHOOK, data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        if result.get("code") == 0 or result.get("StatusCode") == 0:
            print("✅ 已推送到飞书群")
            return True
        print(f"❌ 飞书返回异常: {result}")
        return False
    except Exception as e:
        print(f"❌ 发送失败: {e}")
        return False


def main():
    mode = os.environ.get("REPORT_MODE", "weekly").strip().lower()
    dry_run = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "yes")

    print(f"[{datetime.now(BEIJING_TZ).strftime('%Y-%m-%d %H:%M:%S')}] 生成样稿周报（mode={mode}）")
    records = load_records()
    print(f"总记录 {len(records)} 条，有交付日期 {sum(1 for x in records if x['date'])} 条")

    report, last, month = build_report(records)

    if os.environ.get("TEST_MODE", "").strip() in ("1", "true", "yes"):
        report = "【测试】以下为周一自动周报的预览内容\n\n" + report

    print("\n================ 消息预览 ================")
    print(report)
    print("=========================================\n")

    if dry_run:
        print("DRY_RUN=1，仅预览不发送")
        return 0
    return 0 if send_feishu(report) else 1


if __name__ == "__main__":
    sys.exit(main())
