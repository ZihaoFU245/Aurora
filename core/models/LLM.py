"""
Model configurations
"""
import sys
from typing import Optional
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from ..Config import Config


class Models:
    """
    A Model class that gather all the models
    """

    def __init__(self, config: Config):
        # Raw env values (maybe None)
        self.key: Optional[str] = config.OPENROUTER_API_KEY
        self.url: Optional[str] = config.OPENAI_BASE_URL

        # Validate required API configs
        missing = []
        if not self.key:
            missing.append("OPENROUTER_API_KEY")
        if not self.url:
            missing.append("OPENAI_BASE_URL")
        if not config.ROUTER_MODEL:
            missing.append("ROUTER_MODEL")
        if not config.PLANNER_MODEL:
            missing.append("PLANNER_MODEL")
        if not config.EXECUTOR_MODEL:
            missing.append("EXECUTOR_MODEL")
        if not config.CRITIC_MODEL:
            missing.append("CRITIC_MODEL")
        if missing:
            sys.exit(f"Missing required API config: {', '.join(missing)}")

        # Parse temperature safely (default 0.0)
        def _t(v: Optional[str]) -> float:
            try:
                return float(v) if v is not None else 0.0
            except ValueError:
                return 0.0

        router_temp = _t(config.ROUTER_TEMP)
        planner_temp = _t(config.PLANNER_TEMP)
        executor_temp = _t(config.EXECUTOR_TEMP)
        critic_temp = _t(config.CRITIC_TEMP)

        # Create models
        self.routerModel = ChatOpenAI(
            model=config.ROUTER_MODEL,
            api_key=SecretStr(self.key),
            base_url=self.url,
            temperature=router_temp,
        )
        self.plannerModel = ChatOpenAI(
            model=config.PLANNER_MODEL,
            api_key=SecretStr(self.key),
            base_url=self.url,
            temperature=planner_temp,
        )
        self.executorModel = ChatOpenAI(
            model=config.EXECUTOR_MODEL,
            api_key=SecretStr(self.key),
            base_url=self.url,
            temperature=executor_temp,
        )
        self.criticModel = ChatOpenAI(
            model=config.CRITIC_MODEL,
            api_key=SecretStr(self.key),
            base_url=self.url,
            temperature=critic_temp,
        )

    # Instance getters
    def getRouterModel(self):
        return self.routerModel

    def getPlannerModel(self):
        return self.plannerModel

    def getExecutorModel(self):
        return self.executorModel

    def getCriticModel(self):
        return self.criticModel
