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
    # 1200 是早期留下的额度，实测对这套系统里的任何一档都不够：DeepSeek 会先花
    # 一截额度在推理上，答案还没开始写就到顶，返回空内容加 finish_reason=length。
    # 同一条建议请求 1200 必然截断、8000 正常返回。
    agent_max_tokens: int = 4000
    # 逐行抄录整份对账单的输出远大于普通判断任务：35 行就已经超出 1200。
    # 截断的表现是"输出不是合法 JSON"，很容易被误判成模型不会用 JSON。
    agent_vision_max_tokens: int = 16000
    # 推理档会先花掉一大截额度在推理上，答案还没开始写就到顶了 ——
    # 实测 1200 的默认额度下 PROBLEM_REVIEW 每次都返回空内容加 finish_reason=length，
    # 界面上表现成"分析失败"，看不出是被截断。
    agent_reasoning_max_tokens: int = 8000
    gateway_timeout_seconds: float = 45.0
    # 图像识别要逐行抄录，比判断类调用慢得多；切条重读还要一次发多张图。
    gateway_vision_timeout_seconds: float = 180.0
    # 推理档要先想再写，45 秒常常不够 —— 实测复核会以 read timeout 失败，
    # 表现和模型答不上来一模一样。
    gateway_reasoning_timeout_seconds: float = 180.0
    gateway_max_retries: int = 0

    @staticmethod
    def load_env_file(root: Path) -> None:
        """读取项目根的 .env，但不覆盖已存在的环境变量。

        没有这一步的话 .env 只是一个看着像配置、实际不生效的文件 ——
        真实环境变量优先，便于部署与临时覆盖。
        """
        path = root / ".env"
        if not path.is_file():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())

    @classmethod
    def from_env(cls, root: Optional[Path] = None) -> "Settings":
        project_root = root or Path(__file__).resolve().parents[1]
        cls.load_env_file(project_root)
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
            agent_max_tokens=env_int("FINWISE_AGENT_MAX_TOKENS", 4000),
            agent_vision_max_tokens=env_int("FINWISE_AGENT_VISION_MAX_TOKENS", 16000),
            agent_reasoning_max_tokens=env_int("FINWISE_AGENT_REASONING_MAX_TOKENS", 8000),
            gateway_reasoning_timeout_seconds=env_float("FINWISE_GATEWAY_REASONING_TIMEOUT_SECONDS", 180.0),
            gateway_timeout_seconds=env_float("FINWISE_GATEWAY_TIMEOUT_SECONDS", 45.0),
            gateway_vision_timeout_seconds=env_float("FINWISE_GATEWAY_VISION_TIMEOUT_SECONDS", 180.0),
            gateway_max_retries=env_int("FINWISE_GATEWAY_MAX_RETRIES", 0),
        )

    # 各 stage 该用哪一档模型。未列出的 stage 用默认档。
    REASONING_STAGES = frozenset({"STRUCTURE_PLAN", "PROBLEM_REVIEW", "PAYROLL_MAPPING"})
    VISION_STAGES = frozenset({"SCANNED_DOCUMENT"})
    FAST_STAGES = frozenset({"MATERIAL_GUIDANCE"})

    def timeout_for(self, stage: str) -> float:
        """这一档任务等多久。和 model_for / tokens_for 同一套分档。"""
        if stage in self.VISION_STAGES:
            return self.gateway_vision_timeout_seconds
        if stage in self.REASONING_STAGES:
            return max(self.gateway_reasoning_timeout_seconds, self.gateway_timeout_seconds)
        return self.gateway_timeout_seconds

    def tokens_for(self, stage: str) -> int:
        """这一档任务给多少输出额度。和 model_for 同一套分档，别处不再各调各的。"""
        if stage in self.VISION_STAGES:
            return self.agent_vision_max_tokens
        if stage in self.REASONING_STAGES:
            return max(self.agent_reasoning_max_tokens, self.agent_max_tokens)
        return self.agent_max_tokens

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
