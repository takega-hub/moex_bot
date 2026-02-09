"""Model manager for ML models."""
import os
import subprocess
import sys
import pandas as pd
import json
from pathlib import Path
from typing import Dict, Any, Optional
from bot.config import AppSettings
from bot.state import BotState

class ModelManager:
    """Manages ML models for trading."""
    
    def __init__(self, settings: AppSettings, state: BotState):
        self.settings = settings
        self.state = state
        self.models_dir = Path("ml_models")
        self.models_dir.mkdir(exist_ok=True)
    
    def find_models_for_instrument(self, instrument: str) -> list:
        """Find all available models for instrument."""
        instrument = instrument.upper()
        models = []
        
        patterns = [
            f"*_{instrument}_*.pkl",
            f"*{instrument}*.pkl"
        ]
        
        for pattern in patterns:
            for model_file in self.models_dir.glob(pattern):
                if model_file.is_file() and model_file not in models:
                    models.append(model_file)
        
        models.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return models
    
    def test_model(self, model_path: str, instrument: str, days: int = 14) -> Optional[Dict[str, Any]]:
        """Test model on historical data."""
        # Placeholder for model testing
        return None
    
    def apply_model(self, instrument: str, model_path: str):
        """Apply model to instrument."""
        with self.state.lock:
            self.state.instrument_models[instrument] = model_path
        self.state.save()
        print(f"[model_manager] Applied model {model_path} for {instrument}")
