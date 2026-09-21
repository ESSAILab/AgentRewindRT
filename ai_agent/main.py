from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys

import uvicorn
from dotenv import load_dotenv

from agent_guard.config import AgentGuardConfig
from agent_guard.llm import OpenAICompletionLLM
from agent_guard.runtime import AgentGuardRuntime
from agent_guard.sql_repository import SqlAlchemyAgentSessionRepositoryProvider
from api_server import create_app
from shared.database.bootstrap import init_database
from shared.database.connection import init_db_manager
from shared.utils.config import ConfigError, load_config
from shared.utils.logger import setup_logging


logger = logging.getLogger(__name__)


class AgentGuardSystem:
    def __init__(self):
        self.config = load_config()
        setup_logging(self.config.log_level, self.config.log_format, self.config.log_file)
        self.database_manager = None
        self.agent_guard_runtime = None
        self.api_app = None

    async def initialize(self) -> None:
        await init_database(self.config.database_url)
        self.database_manager = init_db_manager(self.config.database_url)
        await self.database_manager.initialize()

        guard_config = AgentGuardConfig.from_env()
        guard_llm = OpenAICompletionLLM(
            api_key=self.config.openai_api_key,
            base_url=self.config.openai_base_url,
            model=self.config.openai_model,
        )
        self.agent_guard_runtime = AgentGuardRuntime(
            bootstrap_servers=self.config.kafka_bootstrap_servers,
            config=guard_config,
            llm=guard_llm,
            session_topic=os.getenv("KAFKA_AGENT_SESSION_TOPIC", "agent.session.finished"),
            rollback_requested_topic=os.getenv(
                "KAFKA_AGENT_ROLLBACK_REQUESTED_TOPIC",
                "agent.rollback.requested",
            ),
            rollback_completed_topic=os.getenv(
                "KAFKA_AGENT_ROLLBACK_COMPLETED_TOPIC",
                "agent.rollback.completed",
            ),
        )
        await self.agent_guard_runtime.start()
        self.api_app = create_app(
            SqlAlchemyAgentSessionRepositoryProvider(),
            self.agent_guard_runtime.rollback_publisher(),
        )

    async def start(self) -> None:
        await self.initialize()
        server = uvicorn.Server(
            uvicorn.Config(
                self.api_app,
                host="0.0.0.0",
                port=self.config.api_port,
                log_level=self.config.log_level.lower(),
                access_log=False,
            )
        )
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._signal_handler)
        logger.info("AgentGuard API started on port %s", self.config.api_port)
        await server.serve()

    async def shutdown(self) -> None:
        if self.agent_guard_runtime:
            await self.agent_guard_runtime.stop()
            self.agent_guard_runtime = None
        if self.database_manager:
            await self.database_manager.close()
            self.database_manager = None

    def _signal_handler(self, signum, _frame) -> None:
        logger.info("Received signal %s; shutting down AgentGuard", signum)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.shutdown())
            else:
                asyncio.run(self.shutdown())
        finally:
            raise SystemExit(0)


async def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="AgentGuard")
    parser.add_argument("--debug", action="store_true", help="启用调试模式")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default=None,
        help="设置日志级别",
    )
    args = parser.parse_args()
    if args.debug:
        os.environ["DEBUG_MODE"] = "true"
        os.environ["LOG_LEVEL"] = "DEBUG"
    if args.log_level:
        os.environ["LOG_LEVEL"] = args.log_level

    system = None
    try:
        system = AgentGuardSystem()
        await system.start()
    except ConfigError as exc:
        print(str(exc), file=sys.stderr)
    finally:
        if system:
            await system.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
