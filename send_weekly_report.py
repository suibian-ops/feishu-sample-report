# -*- coding: utf-8 -*-
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

"""
样稿制作周报 & 月报推送脚本
- 每周一早上 9:00 自动推送上周数据到飞书群
- 每月末（最后一天）推送本月完整数据到飞书群
"""
import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
import calendar

BEIJING_TZ = timezone(timedelta(hours=8))

# ==================== 配置 ====================
FEISHU_WEBHOOK = os.environ.get(
    "FEISHU_WEBHOOK",
    "https://open.feishu.cn/open-apis/bot/v2/hook/e28f339a-d9ff-416f-b82b-6a6d1821a22b"
)
DATA_URL = os.environ.get(
    "DATA_URL",
    "https://raw.githubusercontent.com/suibian-ops/feishu-data/main/sample_production.json"
)
# 优先读本地文件（GitHub Actions 同步后直接用），否则从远程 URL 拉
DATA_FILE = os.environ.get("DATA_FILE", "")

# 通过环境变量控制模式：weekly（默认）或 monthly
REPORT_MODE = os.environ.get("REPORT_MODE", "weekly")


def get_date_range():
    """计算日期范围（北京时间）"""
    now = datetime.now(BEIJING_TZ)

    # 本周一（时间清零）
    this_monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    # 上周区间：上周一 ~ 上周日
    last_monday = this_monday - timedelta(days=7)
    last_sunday = this_monday - timedelta(days=1)

    # 本月区间：本月1号 ~ 本月末
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_day_of_month = calendar.monthrange(now.year, now.month)[1]
    month_end = now.replace(
        day=last_day_of_month, hour=23, minute=59, second=59, microsecond=0
    )

    return {
        "last_monday": last_monday.strftime("%Y-%m-%d"),
        "last_sunday": last_sunday.strftime("%Y-%m-%d"),
        "month_start": month_start.strftime("%Y-%m-%d"),
        "month_end": month_end.strftime("%Y-%m-%d"),
        "year_month": now.strftime("%Y年%m月"),
        "last_monday_dt": last_monday,
        "last_sunday_dt": last_sunday,
        "month_start_dt": month_start,
        "month_end_dt": month_end,
        "now_dt": now,
    }


def parse_date(date_str):
    """解析日期字符串为 datetime 对象（北京时间）"""
    if not date_str:
        return None
    try:
        return datetime.strptime(str(date_str)[:10], "%Y-%m-%d").replace(
            tzinfo=BEIJING_TZ
        )
    except Exception:
        return None


def load_data():
    """加载 JSON 数据：优先本地文件，否则从远程 URL 拉取"""
    # 优先读本地文件（sync 步骤刚生成的）
    if DATA_FILE and os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            print(f"从本地文件加载: {DATA_FILE} ({len(data)} 条)")
            return data
        except Exception as e:
            print(f"本地文件读取失败: {e}")

    # 否则从远程 URL 拉取
    try:
        req = urllib.request.Request(DATA_URL, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"加载数据失败: {e}")
        return []


def calculate_stats(data, start_dt, end_dt):
    """按制作人统计指定日期范围内的样稿数量"""
    stats = {}
    for record in data:
        date_str = record.get("deliverDate") or record.get("交付时间") or ""
        record_date = parse_date(date_str)
        if not record_date:
            continue
        if start_dt <= record_date <= end_dt:
            maker = record.get("maker") or record.get("制作人") or "未知"
            sample_count = record.get("sampleCount") or record.get("样稿数量") or 0
            if isinstance(sample_count, str):
                try:
                    sample_count = int(sample_count)
                except ValueError:
                    sample_count = 0
            stats[maker] = stats.get(maker, 0) + sample_count
    return stats


def build_weekly_report(last_stats, month_stats, date_range):
    """生成周报消息文本"""
    last_total = sum(last_stats.values())
    month_total = sum(month_stats.values())

    last_lines = [
        f"• {maker}：{count} 个"
        for maker, count in sorted(last_stats.items(), key=lambda x: -x[1])
    ]
    month_lines = [
        f"• {maker}：{count} 个"
        for maker, count in sorted(month_stats.items(), key=lambda x: -x[1])
    ]

    lines = [
        "🌿 样稿制作周报",
        "",
        f"📅 上周统计（{date_range['last_monday']} ~ {date_range['last_sunday']}）",
        f"合计：{last_total} 个",
    ]
    if last_lines:
        lines.extend(last_lines)
    else:
        lines.append("（暂无记录）")

    lines.extend([
        "",
        f"📈 本月累计（{date_range['month_start']} 至今）",
        f"合计：{month_total} 个",
    ])
    if month_lines:
        lines.extend(month_lines)
    else:
        lines.append("（暂无记录）")

    return "\n".join(lines)


def build_monthly_report(month_stats, date_range):
    """生成月报消息文本"""
    month_total = sum(month_stats.values())

    month_lines = [
        f"• {maker}：{count} 个"
        for maker, count in sorted(month_stats.items(), key=lambda x: -x[1])
    ]

    lines = [
        f"📋 样稿制作月报 · {date_range['year_month']}",
        "",
        f"📊 本月统计（{date_range['month_start']} ~ {date_range['month_end']}）",
        f"月度合计：{month_total} 个",
        "",
    ]
    if month_lines:
        lines.extend(month_lines)
    else:
        lines.append("（本月暂无记录）")

    lines.extend([
        "",
        "本月工作圆满完成，辛苦大家了！🎉",
    ])

    return "\n".join(lines)


def send_feishu(message):
    """发送消息到飞书群（自定义机器人 Webhook）"""
    payload = json.dumps({
        "msg_type": "text",
        "content": {
            "text": message
        }
    }, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        FEISHU_WEBHOOK,
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            if result.get("code") == 0:
                print("✅ 飞书消息发送成功！")
                return True
            else:
                print(f"❌ 飞书返回错误: {result}")
                return False
    except Exception as e:
        print(f"❌ 发送失败: {e}")
        return False


def main():
    mode = REPORT_MODE.strip().lower()
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始生成{'月报' if mode == 'monthly' else '周报'}...")
    print(f"  运行模式: {mode}")

    date_range = get_date_range()
    print(f"  上周区间：{date_range['last_monday']} ~ {date_range['last_sunday']}")
    print(f"  本月区间：{date_range['month_start']} ~ {date_range['month_end']}")

    data = load_data()
    print(f"  共加载 {len(data)} 条记录")

    if not data:
        print("❌ 没有数据，退出")
        return

    if mode == "monthly":
        # 月报：统计整月数据
        month_stats = calculate_stats(
            data,
            date_range["month_start_dt"],
            date_range["month_end_dt"]
        )
        print(f"  本月：{sum(month_stats.values())} 个，制作人 {len(month_stats)} 人")
        report = build_monthly_report(month_stats, date_range)
    else:
        # 周报：上周 + 本月累计
        last_stats = calculate_stats(
            data,
            date_range["last_monday_dt"],
            date_range["last_sunday_dt"].replace(hour=23, minute=59, second=59)
        )
        month_stats = calculate_stats(
            data,
            date_range["month_start_dt"],
            date_range["now_dt"]
        )
        print(f"  上周：{sum(last_stats.values())} 个，制作人 {len(last_stats)} 人")
        print(f"  本月累计：{sum(month_stats.values())} 个，制作人 {len(month_stats)} 人")
        report = build_weekly_report(last_stats, month_stats, date_range)

    print("\n--- 报告内容 ---")
    try:
        print(report)
    except UnicodeEncodeError:
        print(report.encode("utf-8", errors="replace").decode("utf-8"))
    print("--- 报告结束 ---\n")

    send_feishu(report)


if __name__ == "__main__":
    main()
