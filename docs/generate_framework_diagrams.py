from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT_DIR = Path(__file__).resolve().parent
FONT = "C:/Windows/Fonts/msyh.ttc"
FONT_BOLD = "C:/Windows/Fonts/msyhbd.ttc"

# 企业级配色：避免单一色系，分域区分
INK = "#172033"
MUTED = "#F4F7FB"
GRID = "#DCE5F0"
ACCESS = "#2563EB"
CONTROL = "#0F9F9F"
ENGINE = "#16A34A"
MODULE = "#6D28D9"
DATA = "#D97706"
FLOW = "#334155"

font = font_manager.FontProperties(fname=FONT)
font_bold = font_manager.FontProperties(fname=FONT_BOLD)


def new_ax(fig):
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis("off")
    return ax


def rounded_box(ax, x, y, w, h, fc, ec, lw=1.4, alpha=0.96):
    box = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.35,rounding_size=1.4",
        linewidth=lw,
        edgecolor=ec,
        facecolor=fc,
        alpha=alpha,
        zorder=2,
    )
    ax.add_patch(box)
    return box


def title_text(ax, text, x=50, y=96, size=21, color=INK):
    ax.text(x, y, text, ha="center", va="center", fontproperties=font_bold,
            fontsize=size, color=color, zorder=5)


def layer_label(ax, text, x=1.5, y=80, size=11, color="#475569", bold=True):
    fp = font_bold if bold else font
    ax.text(x, y, text, ha="left", va="center", fontproperties=fp,
            fontsize=size, color=color, zorder=5)


def box_text(ax, cx, cy, lines, title_fs=10.5, body_fs=8.3, title_color=INK, body_color="#334155"):
    if not lines:
        return
    first = lines[0]
    ax.text(cx, cy + 0.12, first, ha="center", va="center", fontproperties=font_bold,
            fontsize=title_fs, color=title_color, zorder=6)
    if len(lines) > 1:
        body = "\n".join(lines[1:])
        ax.text(cx, cy - 0.12, body, ha="center", va="center", fontproperties=font,
                fontsize=body_fs, color=body_color, zorder=6, linespacing=1.35)


def arrow(ax, x1, y1, x2, y2, color=FLOW, lw=1.6, style="-|>"):
    ax.add_patch(FancyArrowPatch(
        (x1, y1), (x2, y2), arrowstyle=style, mutation_scale=12,
        linewidth=lw, color=color, zorder=3, shrinkA=1, shrinkB=1,
    ))


def draw_architecture(path: Path) -> None:
    fig = plt.figure(figsize=(23, 15), dpi=160)
    fig.patch.set_facecolor(MUTED)
    ax = new_ax(fig)
    ax.set_facecolor(MUTED)

    title_text(ax, "销售智能体 SaaS 商业版 · 总体框架图", y=97.3, size=23)
    ax.text(50, 94.2, "从获客、会话、成交到经营，所有渠道统一进入消息中枢",
            ha="center", va="center", fontproperties=font, fontsize=11, color="#64748B")

    # 访问层
    layer_label(ax, "01 访问层", y=90.5)
    access = [
        ("企业主 / 运营", "经营总览 · 线索看板 · 待办告警", ACCESS),
        ("销售 / 客服", "统一会话 · 人工接管 · 跟进客户", ACCESS),
        ("实施管理员", "渠道配置 · 知识库 · 权限管理", ACCESS),
        ("最终客户", "企业微信 / 微信 / 公众号 / 网页咨询", ACCESS),
        ("平台运营", "租户管理 · 套餐 · 审计", ACCESS),
    ]
    aw, gap = 18.0, 1.35
    for i, (t, d, c) in enumerate(access):
        x = 2 + i * (aw + gap)
        rounded_box(ax, x, 86.5, aw, 5.5, "#EFF6FF", c, lw=1.2)
        box_text(ax, x + aw / 2, 89.25, [t, d], title_fs=10, body_fs=7.4, title_color=c)

    # 控制与安全层
    layer_label(ax, "02 控制与安全层", y=82.2)
    controls = [
        ("登录与认证", "账号 / API Key / Token 吊销"),
        ("多租户隔离", "tenant_id 全链路过滤"),
        ("权限 RBAC", "角色 / 数据范围 / 字段权限"),
        ("审计合规", "配置 / 发送 / 导出 / 删除留痕"),
    ]
    cw, cgap = 23.2, 0.9
    for i, (t, d) in enumerate(controls):
        x = 2 + i * (cw + cgap)
        rounded_box(ax, x, 77.2, cw, 6.2, "#ECFDFD", CONTROL, lw=1.2)
        box_text(ax, x + cw / 2, 80.3, [t, d], title_fs=10, body_fs=7.7, title_color=CONTROL)

    # 统一消息中枢
    layer_label(ax, "03 统一消息中枢", y=74.0)
    engine_steps = ["渠道归一化", "幂等去重", "身份识别", "路由策略", "用户串行锁", "AI 生成", "合规分条", "审计回执"]
    ew, egap = 11.35, 0.35
    for i, t in enumerate(engine_steps):
        x = 2 + i * (ew + egap)
        rounded_box(ax, x, 67.7, ew, 7.4, "#ECFDF5", ENGINE, lw=1.3)
        ax.text(x + ew / 2, 71.4, t, ha="center", va="center", fontproperties=font_bold,
                fontsize=8.2, color=ENGINE)
        if i:
            arrow(ax, x - egap, 71.4, x, 71.4, color=ENGINE, lw=1.8)

    # 功能模块层 5x2
    layer_label(ax, "04 功能模块层", y=46.0)
    modules = [
        ("会话与智能体", ["统一会话工作台", "销售 Agent + RAG", "转人工与上下文一致"], MODULE),
        ("渠道接入", ["企业微信 / 微信客服", "公众号 / 网页客服", "个人微信群 + 视觉执行器"], MODULE),
        ("客户经营", ["客户档案 / 客户 360", "线索管理 / 公海池", "商机与销售阶段"], MODULE),
        ("成交履约", ["商品与订单", "报价 / 合同", "回款 / 开票 / 交付"], MODULE),
        ("营销增长", ["自动跟进计划", "营销活动 / 培育", "话术与内容资产"], MODULE),
        ("服务质量", ["客服工作台", "质检中心", "工单 / SLA / 满意度"], MODULE),
        ("经营与数据", ["经营首页", "BI 报表", "统一指标口径"], MODULE),
        ("系统管理（仅管理员）", ["企业信息 / 成员 / 角色", "API Key / IP 白名单", "审计 / 系统设置 / 备份"], MODULE),
        ("商业化", ["套餐 / 许可证", "用量统计", "账单与续费"], MODULE),
        ("桌面客户端", ["账号登录", "本租户中台", "视觉执行器开关 / 更新"], MODULE),
    ]
    mx0, my_top = 2.0, 34.0
    mw, mh, mgx, mgy = 18.0, 9.0, 1.0, 1.1
    for idx, (t, desc, c) in enumerate(modules):
        row = idx // 5
        col = idx % 5
        x = mx0 + col * (mw + mgx)
        y = my_top + row * (mh + mgy)
        rounded_box(ax, x, y, mw, mh, "#F4F1FF", c, lw=1.2)
        cx = x + mw / 2
        ax.text(cx, y + mh / 2 + 2.15, t, ha="center", va="center", fontproperties=font_bold,
                fontsize=9.2, color=c)
        ax.text(cx, y + mh / 2 - 1.0, "\n".join(desc), ha="center", va="center",
                fontproperties=font, fontsize=6.8, color="#475569", linespacing=1.25)

    # 数据与运行底座
    layer_label(ax, "05 数据与运行底座", y=20.2)
    data_items = [
        ("PostgreSQL", "业务数据 · 租户隔离 · 事务"),
        ("Redis", "会话 / 队列 / 锁 / 限流"),
        ("对象存储", "知识库 / 语音 / 图片 / 导出"),
        ("消息队列", "Celery 异步任务 / 定时任务"),
        ("部署运维", "Docker Compose / 备份 / 监控"),
    ]
    dw, dgap = 18.0, 1.35
    for i, (t, d) in enumerate(data_items):
        x = 2 + i * (dw + dgap)
        rounded_box(ax, x, 13.0, dw, 5.8, "#FFF7ED", DATA, lw=1.2)
        box_text(ax, x + dw / 2, 15.9, [t, d], title_fs=9.2, body_fs=7.0, title_color=DATA)

    # 路线图
    layer_label(ax, "06 版本路线", y=10.4)
    roadmap = [
        ("P0 内部商用闭环", "统一会话 / 渠道收敛 / CRM / 视觉执行器 / 审计"),
        ("P1 对外交付", "官网 / 桌面安装包 / 套餐许可证 / 自动更新"),
        ("P2 规模化", "多租户增强 / 白标私有化 / 开放平台"),
    ]
    rw, rgap = 30.4, 2.7
    for i, (t, d) in enumerate(roadmap):
        x = 2 + i * (rw + rgap)
        rounded_box(ax, x, 2.0, rw, 5.2, "#F1F5F9", "#475569", lw=1.1)
        box_text(ax, x + rw / 2, 4.6, [t, d], title_fs=9.3, body_fs=7.1, title_color=INK)

    ax.text(97.5, 1.2, "颜色仅用于区分层级，不改变模块归属", ha="right", va="center",
            fontproperties=font, fontsize=7, color="#94A3B8")
    fig.savefig(path, facecolor=MUTED, bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)


def draw_logic_flow(path: Path) -> None:
    fig = plt.figure(figsize=(20, 12), dpi=160)
    fig.patch.set_facecolor(MUTED)
    ax = new_ax(fig)
    ax.set_facecolor(MUTED)

    title_text(ax, "销售智能体 · 核心逻辑流程图", y=96.5, size=22)
    ax.text(50, 93.8, "一条消息从进入系统到形成客户资产，统一按以下链路执行",
            ha="center", va="center", fontproperties=font, fontsize=10.5, color="#64748B")

    # 顶部渠道来源
    sources = ["企业微信", "微信客服", "公众号", "网页客服", "个人微信群", "视觉执行器"]
    sw, sgap = 14.6, 0.9
    for i, t in enumerate(sources):
        x = 3 + i * (sw + sgap)
        rounded_box(ax, x, 84.0, sw, 5.5, "#EFF6FF", ACCESS, lw=1.3)
        ax.text(x + sw / 2, 86.75, t, ha="center", va="center", fontproperties=font_bold,
                fontsize=9.2, color=ACCESS)
        arrow(ax, x + sw / 2, 83.8, x + sw / 2, 79.5, color=ACCESS, lw=1.6)

    # 统一消息中枢容器
    rounded_box(ax, 3.0, 55.5, 94.0, 22.0, "#ECFDF5", ENGINE, lw=1.8)
    ax.text(50, 75.5, "统一消息中枢", ha="center", va="center", fontproperties=font_bold,
            fontsize=12, color=ENGINE)

    steps = [
        "事件归一化", "幂等去重", "身份识别", "路由策略", "用户串行锁", "AI + RAG + 画像", "合规检查", "分条发送"
    ]
    descriptions = [
        "渠道事件统一结构", "msg_id / 指纹去重", "统一客户身份", "自动 / 仅@ / 人工", "同用户上下文一致", "生成销售回复", "敏感词 / 话术", "自然延迟 + 审计"
    ]
    bw, bgap = 10.9, 0.7
    for i, (t, d) in enumerate(zip(steps, descriptions)):
        x = 5 + i * (bw + bgap)
        rounded_box(ax, x, 61.0, bw, 10.0, "#FFFFFF", ENGINE, lw=1.1)
        ax.text(x + bw / 2, 67.4, t, ha="center", va="center", fontproperties=font_bold,
                fontsize=8.0, color=ENGINE)
        ax.text(x + bw / 2, 64.2, d, ha="center", va="center", fontproperties=font,
                fontsize=6.6, color="#475569")
        if i:
            arrow(ax, x - bgap, 66.0, x, 66.0, color=ENGINE, lw=1.5)

    # 输出侧
    outputs = ["自动回复客户", "转人工接管", "写入 CRM", "审计日志", "触发跟进任务"]
    ow, ogap = 16.5, 1.6
    for i, t in enumerate(outputs):
        x = 4 + i * (ow + ogap)
        rounded_box(ax, x, 46.0, ow, 5.0, "#FFF7ED", DATA, lw=1.2)
        ax.text(x + ow / 2, 48.5, t, ha="center", va="center", fontproperties=font_bold,
                fontsize=8.8, color=DATA)
        arrow(ax, 50, 55.3, x + ow / 2, 51.2, color=DATA, lw=1.3)

    # 底部业务闭环
    rounded_box(ax, 3.0, 27.5, 94.0, 14.5, "#F4F1FF", MODULE, lw=1.5)
    ax.text(50, 39.0, "业务闭环", ha="center", va="center", fontproperties=font_bold,
            fontsize=11.5, color=MODULE)
    closed_items = [
        ("客户与线索", "身份统一 / 建档 / 评分 / 公海"),
        ("商机与成交", "阶段 / 赢率 / 订单 / 回款"),
        ("服务与增长", "转人工 / 质检 / 跟进 / 复购"),
        ("数据与经营", "看板 / BI / 报表"),
    ]
    cw, cgap = 21.5, 1.2
    for i, (t, d) in enumerate(closed_items):
        x = 5 + i * (cw + cgap)
        rounded_box(ax, x, 31.0, cw, 5.0, "#FFFFFF", MODULE, lw=1.0)
        box_text(ax, x + cw / 2, 33.5, [t, d], title_fs=8.6, body_fs=6.9, title_color=MODULE)

    # 风险与决策提示
    rounded_box(ax, 3.0, 14.0, 94.0, 9.0, "#F1F5F9", "#475569", lw=1.3)
    ax.text(50, 20.4, "关键决策点", ha="center", va="center", fontproperties=font_bold,
            fontsize=10, color=INK)
    ax.text(50, 16.8, "消息先进入中枢，不允许多渠道各自调用 AI；转人工 / 非目标群 / 未授权视觉执行器必须中途停止；系统管理仅管理员可见；发送必须带审计。",
            ha="center", va="center", fontproperties=font, fontsize=8.4, color="#475569")

    ax.text(97.5, 5.0, "官方通道：公众号 / 企业微信 / 微信客服   非官方通道：个人微信 / 视觉执行器",
            ha="right", va="center", fontproperties=font, fontsize=7.4, color="#94A3B8")
    fig.savefig(path, facecolor=MUTED, bbox_inches="tight", pad_inches=0.25)
    plt.close(fig)


def main() -> None:
    draw_architecture(OUT_DIR / "销售智能体-总体框架图.png")
    draw_logic_flow(OUT_DIR / "销售智能体-核心逻辑图.png")
    print("ok")


if __name__ == "__main__":
    main()
