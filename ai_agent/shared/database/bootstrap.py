"""Database bootstrap helpers."""
import logging
import os

from dotenv import load_dotenv

from .connection import init_db_manager

logger = logging.getLogger(__name__)

load_dotenv()


async def init_database(database_url: str | None = None) -> None:
    """Initialize database connections and create missing tables."""
    database_url = database_url or os.getenv("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL is required")

    db_manager = init_db_manager(database_url)
    try:
        await db_manager.initialize()

        logger.info("开始创建数据库表...")
        await db_manager.create_tables()
        logger.info("数据库初始化完成")
    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        raise
    finally:
        await db_manager.close()
