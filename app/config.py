from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Settings:
    root: Path
    database_path: Path
    storage_path: Path
    require_auth: bool = True
    environment: str = "development"
    agent_mode: str = "disabled"
    agent_provider: str = "deepseek"
    agent_model: str = "deepseek-chat"
    # 按任务分级：结构与判断类用推理档，图像类只能用带视觉的那一档，高频轻任务用快档。
    # 留空表示沿用 agent_model，因此既有部署不受影响。
    agent_model_reasoning: str = ""
    agent_model_vision: str = ""
    agent_model_fast: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str = ""
    agent_prompt_version: str = "finwise-agent-prompt-v1"
    agent_max_tokens: int = 1200
    gateway_timeout_seconds: float = 45.0
    gateway_max_retries: int = 0

    @classmethod
    def from_env(cls, root: Optional[Path] = None) -> "Settings":
        project_root = root or Path(__file__).resolve().parents[1]
        database_path = Path(os.getenv("FINWISE_DATABASE_PATH", str(project_root / "data" / "finwise.db")))
        storage_path = Path(os.getenv("FINWISE_STORAGE_PATH", str(project_root / "data" / "artifacts")))
        if not database_path.is_absolute():
            database_path = project_root / database_path
        if not storage_path.is_absolute():
            storage_path = project_root / storage_path
        def env_int(name: str, default: int) -> int:
            try:
                return int(os.getenv(name, str(default)))
            except ValueError as exc:
                raise ValueError(f"{name} 必须是整数") from exc

        def env_float(name: str, default: float) -> float:
            try:
                return float(os.getenv(name, str(default)))
            except ValueError as exc:
                raise ValueError(f"{name} 必须是数字") from exc

        return cls(
            root=project_root,
            database_path=database_path,
            storage_path=storage_path,
            require_auth=os.getenv("FINWISE_REQUIRE_AUTH", "true").lower() not in {"0", "false", "no"},
            environment=os.getenv("FINWISE_ENVIRONMENT", "development").lower(),
            agent_mode=os.getenv("FINWISE_AGENT_MODE", "disabled").lower(),
            agent_provider=os.getenv("FINWISE_AGENT_PROVIDER", "deepseek").lower(),
            agent_model=os.getenv("FINWISE_AGENT_MODEL", "deepseek-chat"),
            agent_model_reasoning=os.getenv("FINWISE_AGENT_MODEL_REASONING", ""),
            agent_model_vision=os.getenv("FINWISE_AGENT_MODEL_VISION", ""),
            agent_model_fast=os.getenv("FINWISE_AGENT_MODEL_FAST", ""),
            deepseek_base_url=os.getenv("FINWISE_DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            deepseek_api_key=os.getenv("FINWISE_DEEPSEEK_API_KEY", ""),
            agent_prompt_version=os.getenv("FINWISE_AGENT_PROMPT_VERSION", "finwise-agent-prompt-v1"),
            agent_max_tokens=env_int("FINWISE_AGENT_MAX_TOKENS", 1200),
            gateway_timeout_seconds=env_float("FINWISE_GATEWAY_TIMEOUT_SECONDS", 45.0),
            gateway_max_retries=env_int("FINWISE_GATEWAY_MAX_RETRIES", 0),
        )

    # 各 stage 该用哪一档模型。未列出的 stage 用默认档。
    REASONING_STAGES = frozenset({"STRUCTURE_PLAN", "PROBLEM_REVIEW", "PAYROLL_MAPPING"})
    VISION_STAGES = frozenset({"SCANNED_DOCUMENT"})
    FAST_STAGES = frozenset({"MATERIAL_GUIDANCE"})

    def model_for(self, stage: str) -> str:
        """按任务选模型。只有配置了对应档位才切换，否则沿用默认模型。

        图像类是唯一的硬约束：不是所有模型都支持图像理解，没配就在真正用到时
        明确报错，而不是让不带视觉的模型去读扫描件、悄悄返回一堆幻觉。
        """
        if stage in self.VISION_STAGES:
            if not self.agent_model_vision:
                raise ValueError(
                    "处理扫描件需要具备图像理解的模型，请配置 FINWISE_AGENT_MODEL_VISION"
                )
            return self.agent_model_vision
        if stage in self.REASONING_STAGES and self.agent_model_reasoning:
            return self.agent_model_reasoning
        if stage in self.FAST_STAGES and self.agent_model_fast:
            return self.agent_model_fast
        return self.agent_model

    def validate_runtime(self) -> None:
        if self.environment in {"staging", "production"} and not self.require_auth:
            raise ValueError("Staging/生产环境必须开启认证")
        if self.environment in {"staging", "production"} and self.agent_mode != "gateway":
            raise ValueError("Staging/生产环境必须启用真实 Agent Gateway")
        if self.agent_mode not in {"disabled", "gateway"}:
            raise ValueError("FINWISE_AGENT_MODE 只能是 disabled 或 gateway")
        if self.agent_mode == "gateway":
            if self.agent_provider != "deepseek":
                raise ValueError("当前仅支持 DeepSeek Gateway Provider")
            if not self.deepseek_api_key.strip():
                raise ValueError("Gateway 模式必须配置 FINWISE_DEEPSEEK_API_KEY")
            if not self.agent_model.strip():
                raise ValueError("Gateway 模式必须配置 FINWISE_AGENT_MODEL")
            if not self.deepseek_base_url.startswith(("https://", "http://127.0.0.1", "http://localhost")):
                raise ValueError("DeepSeek Base URL 必须使用 HTTPS，或仅允许本机测试地址")
            if self.environment == "production" and not self.deepseek_base_url.startswith("https://"):
                raise ValueError("生产环境 DeepSeek Base URL 必须使用 HTTPS")
        if self.agent_max_tokens < 128 or self.agent_max_tokens > 32768:
            raise ValueError("FINWISE_AGENT_MAX_TOKENS 超出允许范围")
        if self.gateway_timeout_seconds <= 0 or self.gateway_timeout_seconds > 300:
            raise ValueError("FINWISE_GATEWAY_TIMEOUT_SECONDS 超出允许范围")
        if self.gateway_max_retries < 0 or self.gateway_max_retries > 3:
            raise ValueError("FINWISE_GATEWAY_MAX_RETRIES 超出允许范围")
