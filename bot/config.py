"""Configuration for Tinkoff trading bot."""
from dataclasses import dataclass, field
from typing import Optional, List, Dict
import os
import json
import logging
from pathlib import Path
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@dataclass
class ApiSettings:
    """API settings for Tinkoff Invest."""
    token: str = ""
    sandbox: bool = False
    
    def __post_init__(self):
        """Load values from environment."""
        if not self.token:
            self.token = os.getenv("TINKOFF_TOKEN", "").strip()
        if not self.sandbox:
            self.sandbox = os.getenv("TINKOFF_SANDBOX", "false").lower() in ("true", "1", "yes")


@dataclass
class StrategyParams:
    """ML strategy parameters."""
    confidence_threshold: float = 0.35
    min_signal_strength: str = "слабое"
    stability_filter: bool = True
    target_profit_pct_margin: float = 18.0
    max_loss_pct_margin: float = 10.0
    min_signals_per_day: int = 1
    max_signals_per_day: int = 20
    model_type: Optional[str] = None
    mtf_enabled: bool = False
    feature_engineering_enabled: bool = True
    retrain_days: int = 7
    retrain_interval_hours: int = 24
    
    # Параметры комбинированной MTF стратегии (1h + 15m)
    # ВАЖНО: По умолчанию False для безопасности. Включите через конфигурацию после настройки моделей.
    use_mtf_strategy: bool = False  # Использовать комбинированную стратегию (1h фильтр + 15m вход)
    mtf_confidence_threshold_1h: float = 0.50  # Порог уверенности для 1h модели (фильтр)
    mtf_confidence_threshold_15m: float = 0.35  # Порог уверенности для 15m модели (вход)
    mtf_alignment_mode: str = "strict"  # Режим выравнивания: "strict" или "weighted"
    mtf_require_alignment: bool = True  # Требовать совпадение направлений обеих моделей
    
    def __post_init__(self):
        """Validate values."""
        if not 0 <= self.confidence_threshold <= 1:
            self.confidence_threshold = 0.75
        valid_strengths = ["слабое", "умеренное", "среднее", "сильное", "очень_сильное"]
        if self.min_signal_strength not in valid_strengths:
            self.min_signal_strength = "слабое"
        
        # Валидация параметров MTF стратегии
        if not 0 <= self.mtf_confidence_threshold_1h <= 1:
            self.mtf_confidence_threshold_1h = 0.50
        if not 0 <= self.mtf_confidence_threshold_15m <= 1:
            self.mtf_confidence_threshold_15m = 0.35
        if self.mtf_alignment_mode not in ["strict", "weighted"]:
            self.mtf_alignment_mode = "strict"


@dataclass
class RiskParams:
    """Risk management parameters."""
    max_position_usd: float = 200.0
    base_order_usd: float = 10000.0  # Минимальная сумма для открытия позиции (в рублях)
    add_order_usd: float = 50.0
    margin_pct_balance: float = 0.20
    stop_loss_pct: float = 0.01
    take_profit_pct: float = 0.02
    enable_trailing_stop: bool = True
    trailing_stop_activation_pct: float = 0.003
    trailing_stop_distance_pct: float = 0.002
    enable_partial_close: bool = True
    partial_close_pct: float = 0.5
    enable_loss_cooldown: bool = True
    loss_cooldown_minutes: int = 120
    max_consecutive_losses: int = 3
    enable_profit_protection: bool = True
    profit_protection_activation_pct: float = 0.01
    profit_protection_retreat_pct: float = 0.003
    enable_breakeven: bool = True
    breakeven_activation_pct: float = 0.005
    fee_rate: float = 0.0006
    mid_term_tp_pct: float = 0.025
    long_term_tp_pct: float = 0.04
    long_term_sl_pct: float = 0.02
    long_term_ignore_reverse: bool = True
    dca_enabled: bool = True
    dca_drawdown_pct: float = 0.003
    dca_max_adds: int = 2
    dca_min_confidence: float = 0.6
    reverse_on_strong_signal: bool = True
    reverse_min_confidence: float = 0.75
    reverse_min_strength: str = "сильное"
    enable_dynamic_position_sizing: bool = True
    volatility_reduction_factor: float = 0.5
    high_volatility_atr_multiplier: float = 1.5
    
    # Circuit Breaker (Daily Limits)
    max_daily_loss_pct: float = 2.0      # Stop trading if daily loss > 2%
    max_daily_drawdown_usd: float = 5000.0 # Safety net in absolute value
    reset_daily_stats_hour: int = 10     # Hour to reset daily stats (MOEX open)
    
    def __post_init__(self):
        """Validate risk parameters."""
        # Convert percentages if needed
        for attr in ['stop_loss_pct', 'take_profit_pct', 'trailing_stop_activation_pct',
                     'trailing_stop_distance_pct', 'profit_protection_activation_pct',
                     'profit_protection_retreat_pct', 'breakeven_activation_pct',
                     'fee_rate', 'mid_term_tp_pct', 'long_term_tp_pct', 'long_term_sl_pct',
                     'dca_drawdown_pct', 'reverse_min_confidence']:
            value = getattr(self, attr)
            if value >= 1:
                setattr(self, attr, value / 100.0)


@dataclass
class SymbolMLSettings:
    """ML settings for specific trading pair."""
    enabled: bool = True
    model_type: Optional[str] = None
    mtf_enabled: Optional[bool] = None
    model_path: Optional[str] = None
    confidence_threshold: Optional[float] = None
    min_signal_strength: Optional[str] = None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        result = {"enabled": self.enabled}
        if self.model_type is not None:
            result["model_type"] = self.model_type
        if self.mtf_enabled is not None:
            result["mtf_enabled"] = self.mtf_enabled
        if self.model_path is not None:
            result["model_path"] = self.model_path
        if self.confidence_threshold is not None:
            result["confidence_threshold"] = self.confidence_threshold
        if self.min_signal_strength is not None:
            result["min_signal_strength"] = self.min_signal_strength
        return result
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'SymbolMLSettings':
        """Create from dictionary."""
        return cls(
            enabled=data.get("enabled", True),
            model_type=data.get("model_type", None),
            mtf_enabled=data.get("mtf_enabled", None),
            model_path=data.get("model_path", None),
            confidence_threshold=data.get("confidence_threshold", None),
            min_signal_strength=data.get("min_signal_strength", None),
        )


@dataclass
class AppSettings:
    """Main application settings."""
    telegram_token: str = ""
    allowed_user_id: Optional[int] = None
    notification_level: str = "HIGH"
    
    # Trading instruments (FIGI or tickers)
    instruments: List[str] = field(default_factory=lambda: [])
    active_instruments: List[str] = field(default_factory=lambda: [])
    primary_instrument: str = ""
    
    # API settings
    api: ApiSettings = field(default_factory=ApiSettings)
    
    # ML strategy
    ml_strategy: StrategyParams = field(default_factory=StrategyParams)
    
    # Risk management
    risk: RiskParams = field(default_factory=RiskParams)
    
    # General settings
    timeframe: str = "15min"  # Trading timeframe
    leverage: int = 1  # Leverage (1 for spot, >1 for futures)
    live_poll_seconds: int = 120
    kline_limit: int = 1000
    
    # Health monitoring
    health_check_interval_seconds: int = 300
    memory_threshold_mb: float = 1000.0
    memory_critical_mb: float = 2000.0
    
    # Per-instrument ML settings
    instrument_ml_settings: Dict[str, SymbolMLSettings] = field(default_factory=dict)
    
    def get_ml_settings_for_instrument(self, instrument: str) -> SymbolMLSettings:
        """Get ML settings for specific instrument."""
        instrument = instrument.upper()
        if instrument in self.instrument_ml_settings:
            return self.instrument_ml_settings[instrument]
        
        return SymbolMLSettings(
            enabled=True,
            model_type=self.ml_strategy.model_type,
            mtf_enabled=self.ml_strategy.mtf_enabled,
            confidence_threshold=self.ml_strategy.confidence_threshold,
            min_signal_strength=self.ml_strategy.min_signal_strength,
        )
    
    def set_ml_settings_for_instrument(self, instrument: str, settings: SymbolMLSettings) -> None:
        """Set ML settings for specific instrument."""
        instrument = instrument.upper()
        self.instrument_ml_settings[instrument] = settings


def load_settings() -> AppSettings:
    """Load settings from .env file and environment variables."""
    project_root = Path(__file__).parent.parent
    env_path = project_root / ".env"
    
    logger.info(f"Loading settings from: {env_path}")
    
    if env_path.exists():
        logger.info(f"✅ .env file found at {env_path}")
        result = load_dotenv(dotenv_path=env_path, override=True)
        if result:
            logger.info("✅ Environment variables loaded from .env")
        else:
            logger.warning("⚠️ No environment variables loaded from .env (file might be empty or invalid)")
    else:
        logger.warning(f"⚠️ .env file not found at {env_path}")
        logger.warning("   Trying to load from environment variables only...")
        # Try to load from current directory as fallback
        load_dotenv(override=True)
    
    settings = AppSettings()
    
    # Load API settings
    token = os.getenv("TINKOFF_TOKEN", "").strip()
    sandbox = os.getenv("TINKOFF_SANDBOX", "false").lower() in ("true", "1", "yes")
    
    if token:
        settings.api.token = token
        logger.debug(f"✅ TINKOFF_TOKEN loaded (length: {len(token)})")
    else:
        logger.warning("⚠️ TINKOFF_TOKEN not found in environment")
    
    if sandbox:
        settings.api.sandbox = sandbox
        logger.info(f"✅ Sandbox mode: {sandbox}")
    
    # Load trading instruments
    instruments_env = os.getenv("TRADING_INSTRUMENTS", "").strip()
    if instruments_env:
        instruments_list = [s.strip().upper() for s in instruments_env.split(",") if s.strip()]
        settings.instruments = instruments_list
        # Если active_instruments пуст, загружаем ВСЕ инструменты из .env (до максимума 5)
        if not settings.active_instruments:
            # Загружаем все инструменты, но не более max_active_instruments
            max_instruments = min(len(instruments_list), 5)  # Лимит 5 инструментов
            settings.active_instruments = instruments_list[:max_instruments]
            settings.primary_instrument = instruments_list[0] if instruments_list else ""
            logger.info(f"✅ Loaded {len(settings.active_instruments)} active instruments from .env: {settings.active_instruments}")
        else:
            logger.info(f"ℹ️ Using existing active_instruments from state: {settings.active_instruments}")
        logger.info(f"✅ Total instruments in config: {len(instruments_list)}: {instruments_list}")
    
    # Load ML strategy settings
    ml_conf_threshold = os.getenv("ML_CONFIDENCE_THRESHOLD", "").strip()
    if ml_conf_threshold:
        try:
            settings.ml_strategy.confidence_threshold = float(ml_conf_threshold)
            logger.debug(f"✅ ML_CONFIDENCE_THRESHOLD: {settings.ml_strategy.confidence_threshold}")
        except ValueError:
            pass
    
    # Load ML settings from ml_settings.json if exists
    ml_settings_file = project_root / "ml_settings.json"
    if ml_settings_file.exists():
        try:
            with open(ml_settings_file, 'r', encoding='utf-8') as f:
                ml_dict = json.load(f)
                if "confidence_threshold" in ml_dict:
                    settings.ml_strategy.confidence_threshold = float(ml_dict["confidence_threshold"])
                if "min_signal_strength" in ml_dict:
                    settings.ml_strategy.min_signal_strength = ml_dict["min_signal_strength"]
                if "mtf_enabled" in ml_dict:
                    settings.ml_strategy.mtf_enabled = bool(ml_dict["mtf_enabled"])
                if "use_mtf_strategy" in ml_dict:
                    settings.ml_strategy.use_mtf_strategy = bool(ml_dict["use_mtf_strategy"])
                    logger.info(f"Loaded use_mtf_strategy from ml_settings.json: {settings.ml_strategy.use_mtf_strategy}")
                if "mtf_confidence_threshold_1h" in ml_dict:
                    settings.ml_strategy.mtf_confidence_threshold_1h = float(ml_dict["mtf_confidence_threshold_1h"])
                if "mtf_confidence_threshold_15m" in ml_dict:
                    settings.ml_strategy.mtf_confidence_threshold_15m = float(ml_dict["mtf_confidence_threshold_15m"])
                if "mtf_alignment_mode" in ml_dict:
                    settings.ml_strategy.mtf_alignment_mode = ml_dict["mtf_alignment_mode"]
                if "mtf_require_alignment" in ml_dict:
                    settings.ml_strategy.mtf_require_alignment = bool(ml_dict["mtf_require_alignment"])
                logger.info(f"✅ ML settings loaded from ml_settings.json")
        except Exception as e:
            logger.warning(f"⚠️ Error loading ml_settings.json: {e}")
    
    # Load MTF strategy from environment
    ml_mtf_strategy = os.getenv("ML_MTF_STRATEGY_ENABLED", "").strip()
    if ml_mtf_strategy:
        settings.ml_strategy.use_mtf_strategy = ml_mtf_strategy.lower() not in ("0", "false", "no", "off")
        logger.info(f"✅ ML_MTF_STRATEGY_ENABLED: {settings.ml_strategy.use_mtf_strategy}")
    
    # Load Telegram settings
    telegram_token = os.getenv("TELEGRAM_TOKEN", "").strip()
    if telegram_token:
        settings.telegram_token = telegram_token
        logger.info(f"✅ TELEGRAM_TOKEN loaded (length: {len(telegram_token)}, starts with: {telegram_token[:10]}...)")
    else:
        logger.warning("⚠️ TELEGRAM_TOKEN not found in environment variables")
        logger.warning("   Check .env file for: TELEGRAM_TOKEN=your_bot_token_here")
        logger.warning("   Get token from @BotFather in Telegram")
        settings.telegram_token = ""
    
    tg_user_id = os.getenv("ALLOWED_USER_ID", "").strip()
    if tg_user_id:
        try:
            settings.allowed_user_id = int(tg_user_id)
            logger.info(f"✅ ALLOWED_USER_ID loaded: {settings.allowed_user_id}")
        except ValueError:
            logger.warning(f"⚠️ Invalid ALLOWED_USER_ID format: {tg_user_id}")
    else:
        logger.warning("⚠️ ALLOWED_USER_ID not set - bot will accept commands from any user")
    
    # Load timeframe
    timeframe = os.getenv("TIMEFRAME", "").strip()
    if timeframe:
        settings.timeframe = timeframe
        logger.debug(f"✅ TIMEFRAME: {timeframe}")
    
    return settings
