#!/usr/bin/env python3
"""同步“天赋家”当前产品信息：赵焱AI赋能实战课，1980原价骨折价198，转发海报3天参加活动。"""
import datetime
import os
import shutil
from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉
import sys

PAY_LINK = "https://7rp4r.xetslk.com/s/2iAzMg"


def now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def find_db():
    candidates = [
        os.environ.get("SALES_DB"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "customers.db"),
        os.path.join(os.getcwd(), "data", "customers.db"),
        "/app/data/customers.db",
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def main():
    db = find_db()
    if not db:
        print("未找到 customers.db，请用 SALES_DB 环境变量指定路径")
        sys.exit(1)

    bak = db + ".bak-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    shutil.copy2(db, bak)
    print("已备份:", bak)

    conn = sqlite3.connect(db)
    cur = conn.cursor()
    ts = now()

    product = {
        "product_name": "赵焱AI赋能实战课（无社群）",
        "target_customer": "零基础可学的普通人，想学AI编程开发、AI副业变现、AI育儿提效",
        "solves": "一站式解决AI编程开发、AI商业变现、AI家庭育儿提效；零基础可学，不用魔法、不用搭梯子，学完直接用、直接变现、直接提效",
        "selling_points": "课程内容与1980元版本一致：①AI智能编程·全项目落地：四大AI智能体工具教学，可独立制作小程序、网页、自媒体工作台，涵盖文生图、图生视频、数字人生成、爆款文案/短视频/小红书图文、AI短剧、动画片制作；②AI商业变现·全自动增收：英文动画/爆款视频制作分销低价知识课程赚取佣金，数字人分身、AI智能代理分销接单变现，已有学员稳定变现；③AI工作提效·育儿减负：针对看图写话、数理难题、英语背单词等痛点，PPT一键制作、日报周报一键生成。现在骨折价198元，不带社群答疑，课程内容不变",
        "price": "原价1980元（含售后一对一服务）；现在骨折价198元，内容一模一样，就是不带社群答疑；把海报转到朋友圈3天即可参加这个活动；付款链接：" + PAY_LINK,
        "after_sales": "不带社群答疑（无社群、无答疑、无一对一售后），课程为图文讲解+视频详解，下单前请确认",
        "risk_limits": "不承诺百分之百变现，不夸大收益",
        "proof": "AI商业变现赛道①已有学员稳定变现；具体学员案例待补充",
        "active": 1,
    }

    cur.execute("SELECT id FROM product_knowledge WHERE id = 1")
    if cur.fetchone():
        fields = list(product.keys())
        sql = 'UPDATE product_knowledge SET %s, updated_at = ? WHERE id = 1' % (
            ", ".join('"%s"=?' % k for k in fields),
        )
        cur.execute(sql, list(product.values()) + [ts])
        print("已更新产品知识档案")
    else:
        fields = list(product.keys()) + ["created_at", "updated_at"]
        placeholders = ", ".join("?" for _ in fields)
        sql = 'INSERT INTO product_knowledge (%s) VALUES (%s)' % (
            ", ".join('"%s"' % k for k in fields),
            placeholders,
        )
        cur.execute(sql, list(product.values()) + [ts, ts])
        print("已新建产品知识档案")

    price_items = [
        ("赵焱AI赋能实战课（无社群）", "AI-FU-198", 198.0, "原价1980元，现骨折价198元，不带社群答疑；转发海报到朋友圈3天即可参加活动"),
    ]
    cur.execute("DELETE FROM price_items")
    for name, sku, price, desc in price_items:
        cur.execute(
            'INSERT INTO price_items (product_name, sku, price, currency, active, description, created_at, updated_at) '
            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
            (name, sku, price, "CNY", 1, desc, ts, ts),
        )
    print("已更新价目表:", len(price_items), "条")

    cur.execute("DELETE FROM payment_links")
    cur.execute(
        'INSERT INTO payment_links (order_id, title, amount, pay_method, link, status, expires_at, created_at) '
        'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        (0, "赵焱AI赋能实战课（无社群）", 198.0, "wechat", PAY_LINK, "active", "", ts),
    )
    print("已更新支付链接")

    conn.commit()
    conn.close()
    print("产品信息同步完成")


if __name__ == "__main__":
    main()
