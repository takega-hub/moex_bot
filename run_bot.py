"""Main entry point for Tinkoff trading bot."""
import asyncio
import logging
import signal
import sys
import multiprocessing
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
    
    # Проверяем, что это главный процесс (для multiprocessing)
    try:
        import multiprocessing
        current_process = multiprocessing.current_process()
        is_main_process = current_process.name == 'MainProcess'
    except (AttributeError, RuntimeError):
        is_main_process = True
    
    # Main log with rotation - только в главном процессе
    if is_main_process:
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
    else:
        # В дочерних процессах используем только консольный вывод
        main_handler = logging.StreamHandler(sys.stdout)
        main_handler.setLevel(logging.DEBUG)
        error_handler = logging.StreamHandler(sys.stderr)
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
    if is_main_process:
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
            
            # Sync instruments: prioritize state (runtime_state.json), fallback to settings (.env)
            # This allows Telegram bot to manage active instruments without being overwritten
            if state.active_instruments:
                logger.info(f"✅ Using {len(state.active_instruments)} active instruments from saved state: {state.active_instruments}")
            elif settings.active_instruments:
                # Only use .env if runtime_state.json is empty (first run)
                state.active_instruments = settings.active_instruments
                state.save()
                logger.info(f"✅ Loaded {len(settings.active_instruments)} active instruments from settings (first run): {state.active_instruments}")
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
        
        # Обновляем словарь ГО из API для всех активных инструментов
        if state.active_instruments:
            try:
                from data.storage import DataStorage
                from bot.margin_rates import update_margins_from_api
                from bot.margin_calculator import calculate_margins_for_instruments
                
                storage = DataStorage()
                logger.info(f"📊 Обновление словаря ГО из API для {len(state.active_instruments)} активных инструментов...")
                
                # Обновляем словарь MARGIN_PER_LOT из API (с таймаутом 120 секунд)
                try:
                    updated_margins = await asyncio.wait_for(
                        update_margins_from_api(
                            tinkoff_client=tinkoff,
                            instruments=state.active_instruments,
                            storage=storage
                        ),
                        timeout=120.0  # 2 минуты на обновление всех инструментов
                    )
                    
                    if updated_margins:
                        logger.info(f"✅ Словарь ГО обновлен для {len(updated_margins)} инструментов: {updated_margins}")
                    else:
                        logger.warning("⚠️ Не удалось обновить словарь ГО из API")
                except asyncio.TimeoutError:
                    logger.error("⏱️ Timeout updating margins from API (120s exceeded) - continuing without update")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to update margins from API: {e}", exc_info=True)
                
                # Также сохраняем рассчитанные значения маржи в state (для совместимости)
                logger.info("📊 Calculating margins for active instruments at startup...")
                try:
                    margins = await asyncio.wait_for(
                        calculate_margins_for_instruments(
                            tinkoff=tinkoff,
                            storage=storage,
                            instruments=state.active_instruments
                        ),
                        timeout=60.0  # 1 минута на расчет маржи
                    )
                    
                    # Сохраняем рассчитанные значения маржи в state
                    state.instrument_margins = margins
                    state.save()
                    
                    logger.info(f"✅ Margins calculated and saved for {len(margins)} instruments")
                except asyncio.TimeoutError:
                    logger.error("⏱️ Timeout calculating margins (60s exceeded) - continuing without calculation")
                except Exception as e:
                    logger.warning(f"⚠️ Failed to calculate margins: {e}", exc_info=True)
            except Exception as e:
                logger.warning(f"⚠️ Failed to update margins at startup: {e}", exc_info=True)
                logger.warning("⚠️ Bot will continue without margin update - margins will be calculated on demand")
        
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
