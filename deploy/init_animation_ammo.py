#!/usr/bin/env python3
"""动画产品弹药库初始化 - 在服务器容器内执行

注意：执行体必须留在 main() 里、不能放在模块顶层。
原来「连库 + 建游标 + 插入数据」整段都在顶层，于是 `import deploy.init_animation_ammo`
会真的去连库写数据——导入一个脚本不该有这种副作用，质量门的导入检查也正是卡在这里
（sql_compat 的游标接口在导入期直接抛 NotImplementedError）。

用法：
    python deploy/init_animation_ammo.py
"""
from __future__ import annotations
import os
from datetime import datetime

from core import sql_compat as sqlite3  # SQL 统一指向 DATABASE_URL，避免与 ORM 分叉


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main() -> int:
    DB_PATH = "/app/data/customers.db"
    if os.path.exists(DB_PATH):
        print(f"检测到本地库文件 {DB_PATH}（开发环境）；正式环境连接串以 DATABASE_URL 为准")
    else:
        print("未发现本地库文件，按 DATABASE_URL 连接（正式环境属正常）")

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # ===== 产品知识 =====
    products = [
        ("动画视频制作", "自媒体创作者、品牌方、教育机构、电商商家",
         "帮助客户用动画视频做内容引流、品牌宣传、产品展示，降低真人出镜门槛",
         "风格多样（二维/三维/MG动画）| 专业团队制作 | 可定制IP角色 | 适合短视频平台分发",
         "待定（按风格、时长、复杂度报价）",
         "免费修改2次 | 交付源文件 | 30天售后答疑",
         "不含真人拍摄 | 不含平台投流 | 修改超限另计费",
         "案例展示、客户好评截图、平台数据", 1),
        ("IP角色设计", "品牌方、个人IP、教育机构、亲子博主",
         "帮客户打造专属卡通形象，用于品牌辨识、内容创作、周边衍生",
         "原创设计 | 多场景适配（头像/表情包/视频）| 可做动态表情 | 源文件交付",
         "待定",
         "免费修改2次 | 源文件交付 | 后续衍生制作优惠",
         "不含商标注册 | 不含周边生产",
         "作品集展示", 1),
    ]

    for p in products:
        now = _now()
        cur.execute("""INSERT INTO product_knowledge
            (product_name, target_customer, solves, selling_points, price, after_sales, risk_limits, proof, active, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""", tuple(p) + (now, now))

    # ===== 异议应答 =====
    objections = [
        ("价格太贵",
         "动画制作的价格确实比图文高一些，但一条好的动画视频可以反复用、多平台分发，算下来单次成本其实很低。您主要想用在哪个平台呢？我帮您算一下性价比。",
         "一条1分钟MG动画，在抖音/快手/视频号都能用，按3个月使用期算，单次成本不到几块钱",
         "了解客户用途和预算，给出针对性报价方案", 1, 1),
        ("效果不确定",
         "完全理解，第一次做动画确实会担心效果。我们可以先做一个15秒的试做小样，您满意了再做完整版，不满意不收费。",
         "试做案例、客户好评截图",
         "提供试做机会，降低决策门槛", 1, 2),
        ("周期太长",
         "标准MG动画7-10个工作日就能交付，如果赶时间我们也有加急通道。您大概什么时候要用呢？",
         "加急案例、交付时间表",
         "确认时间需求，匹配对应方案", 1, 3),
        ("自己能做吗",
         "现在确实有不少工具可以自己做简单动画，但专业动画在角色动作、节奏感、配音配乐上的效果差别还是挺大的。您是想做品牌宣传还是日常内容引流呢？",
         "自做vs专业制作对比案例",
         "根据用途判断是否需要专业制作", 1, 4),
    ]

    for o in objections:
        cur.execute("""INSERT INTO objection_responses
            (trigger_scene, standard_reply, evidence, next_step, active, sort, created_at)
            VALUES (?,?,?,?,?,?,?)""", tuple(o) + (_now(),))

    # ===== 竞品应对 =====
    competitors = [
        ("剪映/其他工具自制", "我用剪映自己做就行了",
         "专业动画有原创角色和动作设计，模板做不出来",
         "省时间：自己做一条可能要3天，专业团队3天出3条",
         "效果差距：专业动画在平台上完播率和转发率更高",
         "剪映确实方便，适合日常简单内容。但如果您想做品牌IP或者内容差异化，专业动画的效果会好很多。我们可以先做一个试做，您对比看看。", 1),
        ("其他动画工作室", "别家报价更便宜",
         "我们有完整的IP角色设计能力，不只是做视频",
         "交付源文件，后续修改不依赖我们",
         "提供短视频平台分发建议，不只是做动画",
         "价格确实重要，但更重要的是做完能不能用、效果好不好。我们可以先做一个试做小样，您对比一下品质再决定。", 1),
    ]

    for c in competitors:
        cur.execute("""INSERT INTO competitor_responses
            (competitor, customer_saying, differentiator_1, differentiator_2, differentiator_3, standard_reply, active, created_at)
            VALUES (?,?,?,?,?,?,?,?)""", tuple(c) + (_now(),))

    # ===== 跟进话术 =====
    scripts = [
        ("动画首次跟进", "客户咨询动画产品后24小时未回复",
         "发一个动画案例视频，展示实际效果",
         "给您看一个我们最近做的动画案例，客户用在抖音上效果挺好的，播放量比之前翻了好几倍。您想做哪种风格的呢？",
         "客户回复并表达具体需求", 24, 1),
        ("动画犹豫跟进", "客户表示要考虑一下",
         "提供试做机会，降低决策门槛",
         "考虑是应该的，毕竟动画做好了能用很久。我们可以先做一个15秒的试做小样，您看看效果再决定，不满意不收费。您看方便发一下想做的主题吗？",
         "客户同意试做或给出具体需求", 48, 1),
        ("动画报价后跟进", "报价后客户未回复",
         "强调性价比和试做保障",
         "上次报的价格您看了吗？如果有预算顾虑，我们可以先做一个小样试试效果，满意了再做完整版。您觉得怎么样？",
         "客户回应价格或同意试做", 72, 1),
    ]

    for s in scripts:
        cur.execute("""INSERT INTO followup_scripts
            (followup_scene, trigger_condition, value_point, script_example, next_goal, delay_hours, active, created_at)
            VALUES (?,?,?,?,?,?,?,?)""", tuple(s) + (_now(),))

    # ===== 销售案例 =====
    cur.execute("""INSERT INTO sales_cases
        (title, case_type, source, channel, content, key_turns, objections, winning_points, mistakes, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        ("自媒体博主用动画视频引流案例", "general", "manual", "抖音",
         "某亲子博主想做差异化内容，我们帮她设计了一个卡通IP角色，用MG动画做了一系列亲子教育短视频。上线一个月，单条最高播放量50万，涨粉2万+。",
         "客户一开始只想做一条试试，看到效果后连续做了10条系列",
         "觉得动画制作周期长，实际7天就交付了",
         "试做小样打消顾虑 + 平台数据说话",
         "应该一开始就建议做系列，而不是单条") + (_now(), _now()))

    conn.commit()
    conn.close()

    print("Animation ammo initialized:")
    print(f"  Products: {len(products)}")
    print(f"  Objections: {len(objections)}")
    print(f"  Competitors: {len(competitors)}")
    print(f"  Scripts: {len(scripts)}")
    print(f"  Cases: 1")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
