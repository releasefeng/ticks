from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.lottery_spider import LotterySpider
import logging

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_scheduler(app):
    """初始化定时任务"""
    with app.app_context():
        scheduler = BackgroundScheduler()
        spider = LotterySpider()

        def update_lottery_data():
            """更新彩票数据的任务"""
            logger.info("开始更新彩票数据...")
            success, message = spider.update_database()
            if success:
                logger.info("彩票数据更新成功")
            else:
                logger.error(f"彩票数据更新失败: {message}")

        # 每周一、三、六的21:30更新数据（大乐透开奖时间）
        scheduler.add_job(
            update_lottery_data,
            trigger=CronTrigger(
                day_of_week='mon,wed,sat',
                hour=21,
                minute=30
            ),
            id='update_lottery_data',
            name='Update lottery data',
            replace_existing=True
        )

        # 添加一个每天早上的检查，以防之前的更新失败
        scheduler.add_job(
            update_lottery_data,
            trigger=CronTrigger(
                hour=9,
                minute=0
            ),
            id='check_lottery_data',
            name='Check lottery data',
            replace_existing=True
        )

        scheduler.start()
        logger.info("定时任务已启动") 