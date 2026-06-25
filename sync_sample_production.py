# -*- coding: utf-8 -*-
"""
样稿制作记录同步脚本
从飞书多维表拉取数据，输出 sample_production.json
"""
import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta


# ==================== 配置 ====================
FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "cli_a94135e7057b9bef")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
BITABLE_APP_TOKEN = "JWV3bVG68aZSN0sr8VecH48Tnqh"
BITABLE_TABLE_ID = "tblKajqwSWLVr3bh"
OUTPUT_PATH = os.environ.get("OUTPUT_PATH", "sample_production.json")

# 飞书字段名 → JSON 输出字段名
FIELD_MAP = {
    "制作人": "maker",
    "交付时间": "deliverDate",
    "样稿数量": "sampleCount",
    "商家": "merchant",
    "系列|科目": "series",
    "制作月份": "productionMonth",
    "要求沉淀时间": "沉淀日期",
    "备注": "note",
    "制作价格": "productionPrice",
    "沉淀价格": "沉淀价格",
}

# ==================== HTTP 工具 ====================
def http_post(url, data=None, headers=None):
    req = urllib.request.Request(url, method='POST')
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    if data:
        if isinstance(data, dict):
            data = json.dumps(data).encode('utf-8')
            req.add_header('Content-Type', 'application/json')
        req.data = data
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode('utf-8'))


def http_get(url, headers=None, params=None):
    if params:
        url += '?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, method='GET')
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode('utf-8'))


# ==================== 飞书 API ====================
def get_feishu_token():
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    result = http_post(url, {"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET})
    if result.get("code") != 0:
        raise Exception(f"获取飞书令牌失败: {result}")
    return result.get("tenant_access_token")


def get_bitable_records(token):
    """分页拉取多维表所有记录"""
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{BITABLE_APP_TOKEN}/tables/{BITABLE_TABLE_ID}/records"
    headers = {"Authorization": f"Bearer {token}"}
    all_records = []
    page_token = None
    page_count = 0

    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token

        result = http_get(url, headers, params)
        page_count += 1
        print(f"[{datetime.now().strftime('%H:%M:%S')}] 获取第{page_count}页数据...")

        if result.get("code") == 0:
            items = result.get("data", {}).get("items", [])
            print(f"  本页获取到 {len(items)} 条记录")
            all_records.extend(items)

            has_more = result.get("data", {}).get("has_more", False)
            page_token = result.get("data", {}).get("page_token")

            if not has_more or not page_token:
                break
        else:
            print(f"获取记录失败: {result}")
            break

    print(f"共获取 {len(all_records)} 条原始记录")
    return all_records


# ==================== 数据解析 ====================
def parse_text_field(value):
    """解析文本类字段（支持多选等复杂格式）"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        # 飞书多选/人员字段格式: [{"text": "xxx"}]
        texts = []
        for item in value:
            if isinstance(item, dict):
                text = item.get("text", "")
                if text:
                    texts.append(text)
            else:
                texts.append(str(item))
        return "、".join(texts) if texts else ""
    return str(value)


def parse_number(value):
    """解析数值字段（飞书数字字段可能返回字符串）"""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return 0
        try:
            return int(float(value))
        except:
            pass
    return 0


def parse_float(value):
    """解析价格等需要保留小数的数值字段"""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return 0.0
        try:
            return float(value)
        except:
            pass
    return 0.0


def parse_date(value):
    """解析日期字段，返回 YYYY-MM-DD 字符串或 None"""
    if not value:
        return None
    try:
        if isinstance(value, str):
            # 字符串格式：2026-04-05
            date_str = value[:10]
            datetime.strptime(date_str, "%Y-%m-%d")
            return date_str
        elif isinstance(value, (int, float)):
            # 毫秒时间戳（飞书返回 UTC 时间）→ 转北京时间 UTC+8
            dt = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
            dt_cn = dt.astimezone(timezone(timedelta(hours=8)))
            return dt_cn.strftime("%Y-%m-%d")
    except Exception as e:
        print(f"  日期解析失败: {repr(value)} → {e}")
    return None


def transform_record(record):
    """将单条飞书记录转换为 JSON 输出格式"""
    fields = record.get("fields", {})
    out = {
        "_record_id": record.get("record_id", ""),
    }
    for feishu_name, json_name in FIELD_MAP.items():
        raw = fields.get(feishu_name)
        if json_name == "maker":
            out[json_name] = parse_text_field(raw)
        elif json_name in ("sampleCount",):
            out[json_name] = parse_number(raw)
        elif json_name in ("productionPrice", "沉淀价格"):
            out[json_name] = parse_float(raw)
        elif json_name in ("deliverDate", "productionMonth"):
            out[json_name] = parse_date(raw)
        else:
            out[json_name] = parse_text_field(raw)
    return out


# ==================== 主流程 ====================
def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始同步样稿制作记录...")

    token = get_feishu_token()
    print(f"✓ 飞书令牌获取成功")

    records = get_bitable_records(token)

    data = [transform_record(r) for r in records]

    # 写入 JSON
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✓ 写入 {OUTPUT_PATH}，共 {len(data)} 条记录")

    # 简单统计摘要
    makers = {}
    for item in data:
        m = item.get("maker", "未知") or "未知"
        cnt = item.get("sampleCount", 1) or 1
        makers[m] = makers.get(m, 0) + cnt
    print(f"  制作人统计: {makers}")


if __name__ == "__main__":
    main()
