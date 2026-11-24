from abc import ABC, abstractmethod

class AIProvider(ABC):
    """Provider-neutral interface. Implementations must never execute repository code."""
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError
    @abstractmethod
    async def generate(self, *, system: str, prompt: str) -> str:
        raise NotImplementedError
