"""
销售客服智能体 - 主入口
支持多通道启动：个人微信 / 公众号 / 全部
"""
from __future__ import annotations
import argparse
import logging
import sys
import threading

def setup_logging():
    log_format = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler("sales_agent.log", encoding="utf-8"),
        ],
    )

logger = logging.getLogger(__name__)


def run_personal_wechat(msg_handler):
    from connectors.wechat import WeChatConnector
    connector = WeChatConnector(msg_handler=msg_handler)
    logger.info("个人微信：请扫描二维码登录...")
    connector.login()
    logger.info("个人微信：登录成功，开始监听消息")
    connector.start()


def run_official_account(msg_handler):
    try:
        import anyio
        anyio.to_thread.current_default_thread_limiter().total_tokens = 100
    except Exception as e:
        logger.debug("run_official_account 异常已忽略: %s", e)
    from connectors.wechat_official import create_app, run_server
    app = create_app(msg_handler=msg_handler)
    logger.info("公众号：Web 服务启动中...")
    run_server(app)


def create_msg_handler(agent, source: str = "wechat"):
    def handle(msg: str, from_user: str) -> str:
        try:
            return agent.chat(msg, session_id=from_user, source=source)
        except Exception as e:
            logger.error(f"处理消息出错: {e}")
            return "抱歉，我暂时无法处理您的问题，请稍后再试。"
    return handle


def main():
    parser = argparse.ArgumentParser(description="销售客服智能体")
    parser.add_argument(
        "--channel", "-c",
        choices=["personal", "official", "all", "console"],
        default="console",
        help="启动通道: personal(个人微信) / official(公众号) / all(全部) / console(控制台)",
    )
    args = parser.parse_args()

    setup_logging()
    logger.info("=" * 50)
    logger.info(f"销售客服智能体启动中... 通道={args.channel}")
    logger.info("=" * 50)

    from config.settings import settings
    if not settings.DEEPSEEK_API_KEY:
        logger.warning("未设置 DEEPSEEK_API_KEY，请在 .env 中配置")

    logger.info("正在初始化销售 Agent ...")
    from core.agent import sales_agent
    logger.info("Agent 初始化完成")

    wechat_handler = create_msg_handler(sales_agent, source="wechat")
    official_handler = create_msg_handler(sales_agent, source="official")

    if args.channel == "console":
        logger.info("进入控制台对话模式（输入 exit 退出）")
        print()
        print("=== 销售客服智能体 - 控制台模式 ===")
        print("输入消息开始对话，输入 exit 退出")
        while True:
            try:
                user_input = input("客户: ")
                if user_input.lower() in ("exit", "quit", "q"):
                    break
                reply = sales_agent.chat(user_input, session_id="console_user", source="console")
                print(f"客服: {reply}")
            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"错误: {e}")

    elif args.channel == "personal":
        run_personal_wechat(wechat_handler)

    elif args.channel == "official":
        run_official_account(official_handler)

    elif args.channel == "all":
        logger.info("双通道模式：同时启动个人微信 + 公众号")
        threads = []
        t1 = threading.Thread(target=run_personal_wechat, args=(wechat_handler,), daemon=True)
        t1.name = "personal-wechat"
        threads.append(t1)
        t2 = threading.Thread(target=run_official_account, args=(official_handler,), daemon=True)
        t2.name = "official-account"
        threads.append(t2)
        for t in threads:
            t.start()
        try:
            for t in threads:
                t.join()
        except KeyboardInterrupt:
            logger.info("收到退出信号，正在关闭...")

    logger.info("销售客服智能体已停止")


if __name__ == "__main__":
    main()
