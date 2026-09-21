from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    database_url: str
    kafka_bootstrap_servers: str
    log_level: str
    log_format: str
    log_file: str
    debug_mode: bool
    api_port: int
    backend_api_key: str
    openai_api_key: str
    openai_base_url: str
    openai_model: str


class ConfigError(ValueError):
    """Raised when required AgentGuard configuration is missing or invalid."""


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _required_env(name: str, missing: list[str]) -> str:
    value = _env(name)
    if value is None:
        missing.append(name)
        return ""
    return value


def _parse_bool(name: str, default: bool, errors: list[str]) -> bool:
    raw_value = _env(name)
    if raw_value is None:
        return default
    normalized = raw_value.lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    errors.append(f"{name}={raw_value!r} 不是有效布尔值，请使用 true/false")
    return default


def _parse_int(
    name: str,
    default: int,
    errors: list[str],
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    raw_value = _env(name)
    if raw_value is None:
        value = default
    else:
        try:
            value = int(raw_value)
        except ValueError:
            errors.append(f"{name}={raw_value!r} 不是有效整数")
            return default
    if minimum is not None and value < minimum:
        errors.append(f"{name}={value} 小于最小值 {minimum}")
    if maximum is not None and value > maximum:
        errors.append(f"{name}={value} 大于最大值 {maximum}")
    return value


def _raise_if_invalid(missing: list[str], errors: list[str]) -> None:
    if not missing and not errors:
        return
    message_lines = ["配置校验失败，请修正环境变量后重启。"]
    if missing:
        message_lines.append("缺失必填环境变量:")
        message_lines.extend(f"  - {name}" for name in sorted(missing))
    if errors:
        message_lines.append("非法环境变量:")
        message_lines.extend(f"  - {error}" for error in errors)
    raise ConfigError("\n".join(message_lines))


def load_config() -> Config:
    missing: list[str] = []
    errors: list[str] = []
    log_level = str(_env("LOG_LEVEL", "INFO")).upper()
    valid_log_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if log_level not in valid_log_levels:
        errors.append(f"LOG_LEVEL={log_level!r} 无效，可选值: {', '.join(sorted(valid_log_levels))}")

    config = Config(
        database_url=_required_env("DATABASE_URL", missing),
        kafka_bootstrap_servers=_required_env("KAFKA_BOOTSTRAP_SERVERS", missing),
        log_level=log_level,
        log_format=str(_env("LOG_FORMAT", "%(asctime)s - %(name)s - %(levelname)s - %(message)s")),
        log_file=str(_env("LOG_FILE", "/app/logs/agent_guard.log")),
        debug_mode=_parse_bool("DEBUG_MODE", False, errors),
        api_port=_parse_int("API_PORT", 8000, errors, minimum=1, maximum=65535),
        backend_api_key=_required_env("BACKEND_API_KEY", missing),
        openai_api_key=_required_env("OPENAI_API_KEY", missing),
        openai_base_url=str(_env("OPENAI_BASE_URL", "")),
        openai_model=str(_env("OPENAI_MODEL", "deepseek-v3-2-251201")),
    )
    _raise_if_invalid(missing, errors)
    return config
