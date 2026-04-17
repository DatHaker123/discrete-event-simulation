import math
import os
import random
from abc import ABC, abstractmethod
from dotenv import load_dotenv

load_dotenv()

_seed = os.getenv("RANDOM_SEED")
if _seed is not None:
    random.seed(int(_seed))


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


class PoissonDistribution(Distribution):
    """
    Poisson with mean ``mu`` (Knuth's algorithm). ``sample()`` returns a float
    holding a non-negative integer count, consistent with other distributions here.
    """

    def __init__(self, mu: float):
        super().__init__("Poisson")
        if mu < 0:
            raise ValueError("Poisson mean mu must be non-negative")
        self.mu = mu

    def sample(self) -> float:
        mu = self.mu
        if mu == 0:
            return 0.0
        limit = math.exp(-mu)
        k = 0
        p = 1.0
        while p > limit:
            k += 1
            p *= random.random()
        return float(k - 1)
