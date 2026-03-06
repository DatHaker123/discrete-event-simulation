import random
from abc import ABC, abstractmethod

class Distribution(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def sample(self) -> float:
        pass

class UniformDistribution(Distribution):
    def __init__(self, min: float, max: float):
        super().__init__("Uniform")
        self.min = min
        self.max = max

    def sample(self) -> float:
        return random.uniform(self.min, self.max)

class ExponentialDistribution(Distribution):
    def __init__(self, rate: float):
        super().__init__("Exponential")
        self.rate = rate

    def sample(self) -> float:
        return random.expovariate(self.rate)

class ConstantDistribution(Distribution):
    def __init__(self, value: float):
        super().__init__("Constant")
        self.value = value

    def sample(self) -> float:
        return self.value