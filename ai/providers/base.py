from abc import ABC, abstractmethod

from ai.planner_models import AnalysisPlanResponse


class AIProvider(ABC):

    @abstractmethod
    def create_analysis_plan(
        self,
        user_question: str,
        metadata: dict,
    ) -> AnalysisPlanResponse:
        pass