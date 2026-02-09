"""Main entry point for Tinkoff trading bot."""
import asyncio
import logging
import signal
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler

from bot.config import load_settings
from bot.state import BotState
from trading.client import TinkoffClient
from bot.model_manager import ModelManager
from bot.telegram_bot import TelegramBot
from bot.trading_loop import TradingLoop
from utils.logger import logger

# Flag to prevent duplicate logging setup
_logging_configured = False

def setup_logging():
    """Setup logging (called once)."""
    global _logging_configured
    
    if _logging_configured:
        return logging.getLogger("main")
    
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
    # Main log with rotation
    main_handler = RotatingFileHandler(
        'logs/bot.log',
        maxBytes=10*1024*1024,  # 10 MB
        backupCount=5,
        encoding='utf-8'
    )
    main_handler.setLevel(logging.DEBUG)
    
    # Error log
    error_handler = RotatingFileHandler(
        'logs/errors.log',
        maxBytes=10*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    main_handler.setFormatter(formatter)
    error_handler.setFormatter(formatter)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.handlers.clear()
    root_logger.addHandler(main_handler)
    root_logger.addHandler(error_handler)
    
    # Suppress noisy library logs
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    
    _logging_configured = True
    return logging.getLogger("main")

async def main():
    """Main async function."""
    try:
        # Setup logging
        logger = setup_logging()
        logger.info("Initializing Tinkoff Trading Bot...")
        
        # Load settings
        try:
            settings = load_settings()
        except Exception as e:
            logger.error(f"Failed to load settings: {e}", exc_info=True)
            raise
        
        if not settings.telegram_token:
            logger.warning("⚠️ TELEGRAM_TOKEN not found in .env file!")
            logger.warning("💡 Telegram bot will not start. Add to .env:")
            logger.warning("   TELEGRAM_TOKEN=your_bot_token_here")
            logger.warning("   ALLOWED_USER_ID=your_telegram_user_id")
        else:
            logger.info(f"✅ Telegram token loaded: {settings.telegram_token[:10]}...{settings.telegram_token[-5:]}")
            if settings.allowed_user_id:
                logger.info(f"✅ Allowed user ID: {settings.allowed_user_id}")
            else:
                logger.warning("⚠️ ALLOWED_USER_ID not set - bot will accept commands from any user")
        
        # Initialize state
        try:
            state = BotState()
            
            # Sync instruments: prioritize settings, but keep state if settings is empty
            if settings.active_instruments:
                state.active_instruments = settings.active_instruments
                state.save()
                logger.info(f"✅ Loaded {len(settings.active_instruments)} active instruments from settings: {settings.active_instruments}")
            elif state.active_instruments:
                logger.info(f"✅ Using {len(state.active_instruments)} active instruments from saved state: {state.active_instruments}")
            else:
                logger.warning("⚠️ No active instruments found! Add instruments via:")
                logger.warning("   1. .env file: TRADING_INSTRUMENTS=VBH6,SRH6,GLDRUBF")
                logger.warning("   2. Telegram bot: /start -> ⚙️ ИНСТРУМЕНТЫ -> ➕ Добавить")
                logger.warning("   3. Or edit runtime_state.json manually")
        except Exception as e:
            logger.error(f"Failed to initialize BotState: {e}", exc_info=True)
            raise
        
        # Initialize Tinkoff client
        try:
            tinkoff = TinkoffClient(
                token=settings.api.token,
                sandbox=settings.api.sandbox
            )
        except Exception as e:
            logger.error(f"Failed to initialize TinkoffClient: {e}", exc_info=True)
            raise
        
        # Initialize model manager
        try:
            model_manager = ModelManager(settings, state)
        except Exception as e:
            logger.error(f"Failed to initialize ModelManager: {e}", exc_info=True)
            raise
        
        # Initialize Telegram bot
        try:
            tg_bot = TelegramBot(settings, state, model_manager, tinkoff)
        except Exception as e:
            logger.error(f"Failed to initialize TelegramBot: {e}", exc_info=True)
            raise
        
        # Initialize trading loop
        try:
            trading_loop = TradingLoop(settings, state, tinkoff, tg_bot)
            tg_bot.trading_loop = trading_loop
        except Exception as e:
            logger.error(f"Failed to initialize TradingLoop: {e}", exc_info=True)
            raise
        
        # Run components
        try:
            await asyncio.gather(
                tg_bot.start(),
                trading_loop.run()
            )
        except asyncio.CancelledError:
            logger.info("Bot execution cancelled.")
        except Exception as e:
            logger.error(f"Fatal error during execution: {e}", exc_info=True)
            raise
        finally:
            logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Fatal error during initialization: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Manual shutdown.")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Unhandled exception in main: {e}", exc_info=True)
        sys.exit(1)
