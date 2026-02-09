"""Base strategy classes."""
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any
import pandas as pd


class Action(Enum):
    """Trading action."""
    LONG = "LONG"
    SHORT = "SHORT"
    HOLD = "HOLD"


class Bias(Enum):
    """Market bias."""
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class Signal:
    """Trading signal."""
    timestamp: pd.Timestamp
    action: Action
    reason: str
    price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    trailing: Optional[dict] = None
    indicators_info: Optional[dict] = None
