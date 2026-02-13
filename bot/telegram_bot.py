"""Telegram bot for Tinkoff trading bot control."""
import logging
import asyncio
import json
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

try:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
    from telegram.error import BadRequest
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    print("[telegram] ⚠️ WARNING: python-telegram-bot not installed")

from bot.config import AppSettings, RiskParams, StrategyParams, SymbolMLSettings
from bot.state import BotState
from bot.model_manager import ModelManager
from trading.client import TinkoffClient
from data.storage import DataStorage
from utils.logger import logger


def safe_float(value, default=0.0):
    """Безопасное преобразование в float."""
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


class TelegramBot:
    """Telegram bot for Tinkoff trading bot control."""
    
    def __init__(self, settings: AppSettings, state: BotState, model_manager: ModelManager, tinkoff_client: Optional[TinkoffClient] = None):
        self.settings = settings
        self.state = state
        self.model_manager = model_manager
        self.tinkoff = tinkoff_client
        self.storage = DataStorage()
        self.app = None
        self.trading_loop = None
        
        # Состояния ожидания ввода
        self.waiting_for_ticker = {}  # user_id -> True если ждем ввод тикера
        self.waiting_for_risk_setting = {}  # user_id -> setting_name
        self.waiting_for_ml_setting = {}  # user_id -> setting_name
        self.waiting_for_strategy_setting = {}  # user_id -> setting_name

    async def start(self):
        """Start Telegram bot."""
        if not TELEGRAM_AVAILABLE:
            logger.warning("Telegram bot not available (python-telegram-bot not installed)")
            logger.warning("Install with: pip install python-telegram-bot")
            return
        
        if not self.settings.telegram_token:
            logger.error("❌ No Telegram token found in settings!")
            logger.error("💡 Add TELEGRAM_TOKEN to .env file:")
            logger.error("   TELEGRAM_TOKEN=your_bot_token_here")
            logger.error("   Get token from @BotFather in Telegram")
            return
        
        if not self.settings.allowed_user_id:
            logger.warning("⚠️ ALLOWED_USER_ID not set - bot will accept commands from any user")
            logger.warning("💡 Add ALLOWED_USER_ID to .env file for security:")
            logger.warning("   ALLOWED_USER_ID=your_telegram_user_id")
            logger.warning("   Get your ID from @userinfobot in Telegram")
        
        try:
            self.app = Application.builder().token(self.settings.telegram_token).build()
            
            # Handlers
            self.app.add_handler(CommandHandler("start", self.cmd_start))
            self.app.add_handler(CommandHandler("status", self.cmd_status))
            self.app.add_handler(CommandHandler("dashboard", self.cmd_dashboard))
            self.app.add_handler(CallbackQueryHandler(self.handle_callback))
            self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
            
            logger.info("✅ Starting Telegram bot...")
            logger.info(f"   Token: {self.settings.telegram_token[:10]}...{self.settings.telegram_token[-5:]}")
            logger.info(f"   Allowed user ID: {self.settings.allowed_user_id or 'ANY (not secure!)'}")
            
            await self.app.initialize()
            await self.app.start()
            await self.app.updater.start_polling()
            
            logger.info("✅ Telegram bot started successfully! Send /start to your bot.")
        except Exception as e:
            logger.error(f"❌ Failed to start Telegram bot: {e}", exc_info=True)
            logger.error("💡 Check:")
            logger.error("   1. TELEGRAM_TOKEN is correct in .env file")
            logger.error("   2. Token is valid (get new one from @BotFather if needed)")
            logger.error("   3. Internet connection is working")
            raise

    async def check_auth(self, update: Update) -> bool:
        """Check user authorization."""
        user_id = update.effective_user.id
        if self.settings.allowed_user_id and user_id != self.settings.allowed_user_id:
            await update.message.reply_text("⛔ Доступ запрещен. Ваш ID не в вайтлисте.")
            return False
        return True
    
    async def safe_edit_message(self, query, text: str, reply_markup=None):
        """Безопасное редактирование сообщения."""
        try:
            await query.edit_message_text(text, reply_markup=reply_markup)
        except BadRequest as e:
            if "Message is not modified" in str(e):
                logger.debug(f"Message not modified (non-critical): {e}")
            else:
                raise

    async def cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command."""
        try:
            logger.info(f"Received /start command from user {update.effective_user.id}")
            if not await self.check_auth(update):
                logger.warning(f"User {update.effective_user.id} not authorized")
                return
            
            await update.message.reply_text(
                "🤖 Tinkoff Trading Bot Terminal",
                reply_markup=self.get_main_keyboard()
            )
            logger.info(f"✅ Sent start menu to user {update.effective_user.id}")
        except Exception as e:
            logger.error(f"Error in cmd_start: {e}", exc_info=True)
            try:
                await update.message.reply_text(f"❌ Ошибка: {str(e)}")
            except:
                pass

    async def cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command."""
        if not await self.check_auth(update):
            return
        await self.show_status(update)
    
    async def cmd_dashboard(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /dashboard command."""
        if not await self.check_auth(update):
            return
        class FakeQuery:
            def __init__(self, message):
                self.message = message
            async def edit_message_text(self, text, reply_markup=None):
                await self.message.reply_text(text, reply_markup=reply_markup)
        await self.show_dashboard(FakeQuery(update.message))

    def get_main_keyboard(self):
        """Главное меню."""
        keyboard = [
            [InlineKeyboardButton("🟢 СТАРТ", callback_data="bot_start"),
             InlineKeyboardButton("🔴 СТОП", callback_data="bot_stop")],
            [InlineKeyboardButton("📊 СТАТУС", callback_data="status_info"),
             InlineKeyboardButton("📈 СТАТИСТИКА", callback_data="stats")],
            [InlineKeyboardButton("⚙️ ИНСТРУМЕНТЫ", callback_data="settings_instruments"),
             InlineKeyboardButton("🤖 МОДЕЛИ", callback_data="settings_models")],
            [InlineKeyboardButton("⚙️ НАСТРОЙКИ РИСКА", callback_data="settings_risk"),
             InlineKeyboardButton("🧠 ML НАСТРОЙКИ", callback_data="settings_ml")],
            [InlineKeyboardButton("🔧 НАСТРОЙКИ СТРАТЕГИИ", callback_data="settings_strategy"),
             InlineKeyboardButton("🌐 РЕЖИМ API", callback_data="settings_api")],
            [InlineKeyboardButton("📝 ИСТОРИЯ", callback_data="history_menu"),
             InlineKeyboardButton("🚨 ЭКСТРЕННЫЕ", callback_data="emergency_menu")]
        ]
        return InlineKeyboardMarkup(keyboard)

    async def show_status(self, update_or_query):
        """Показывает статус бота."""
        status_text = f"🤖 СТАТУС ТЕРМИНАЛА: {'🟢 РАБОТАЕТ' if self.state.is_running else '🔴 ОСТАНОВЛЕН'}\n\n"
        
        # Режим API (Sandbox/Real)
        api_mode = "🧪 ПЕСОЧНИЦА" if self.settings.api.sandbox else "💰 РЕАЛЬНЫЙ РЕЖИМ"
        status_text += f"🌐 РЕЖИМ API: {api_mode}\n\n"
        
        # Account Info
        wallet_balance = 0.0
        available_balance = 0.0  # Initialize - will be set from API
        open_positions = []
        total_margin = 0.0
        
        if self.tinkoff:
            try:
                # Добавляем таймаут для получения баланса (30 секунд)
                balance_info = await asyncio.wait_for(
                    asyncio.to_thread(self.tinkoff.get_wallet_balance),
                    timeout=30.0
                )
                if balance_info.get("retCode") == 0:
                    result = balance_info.get("result", {})
                    list_data = result.get("list", [])
                    if list_data:
                        wallet = list_data[0].get("coin", [])
                        rub_coin = next((c for c in wallet if c.get("coin") == "RUB"), None)
                        if rub_coin:
                            wallet_balance = safe_float(rub_coin.get("walletBalance"), 0)
                            # Use availableBalance from API directly - exchange knows best
                            available_balance = safe_float(rub_coin.get("availableBalance"), wallet_balance)
            except asyncio.TimeoutError:
                logger.error("Timeout getting balance in show_status (30s exceeded)")
            except Exception as e:
                logger.error(f"Error getting balance: {e}")
            
            # Open Positions
            total_blocked_margin_from_api = 0.0  # Общая замороженная маржа из API
            try:
                # Сначала синхронизируем позиции с биржей (если есть trading_loop)
                if hasattr(self, 'trading_loop') and self.trading_loop:
                    try:
                        await self.trading_loop.sync_positions_with_exchange()
                    except Exception as e:
                        logger.debug(f"Error syncing positions in status: {e}")
                
                # Получаем общую замороженную маржу из API (из валютной позиции)
                try:
                    all_pos_info = await asyncio.wait_for(
                        asyncio.to_thread(self.tinkoff.get_position_info),
                        timeout=30.0
                    )
                    if all_pos_info and all_pos_info.get("retCode") == 0:
                        result = all_pos_info.get("result", {})
                        total_blocked_margin_from_api = result.get("total_blocked_margin", 0.0)
                        if total_blocked_margin_from_api > 0:
                            logger.debug(f"Got total blocked margin from API: {total_blocked_margin_from_api:.2f} руб")
                except Exception as e:
                    logger.debug(f"Error getting total blocked margin: {e}")
                
                # Проверяем позиции на бирже ПЕРВОЙ (источник истины)
                for ticker in self.state.active_instruments:
                    # Получаем FIGI для тикера
                    instrument_info = self.storage.get_instrument_by_ticker(ticker)
                    if not instrument_info:
                        continue
                    figi = instrument_info["figi"]
                    
                    # Проверяем позицию на бирже (с таймаутом 30 секунд)
                    try:
                        pos_info = await asyncio.wait_for(
                            asyncio.to_thread(self.tinkoff.get_position_info, figi=figi),
                            timeout=30.0
                        )
                    except asyncio.TimeoutError:
                        logger.error(f"Timeout getting position info in show_status (30s exceeded)")
                        pos_info = None
                    except Exception as e:
                        logger.error(f"Error getting position info in show_status: {e}")
                        pos_info = None
                    exchange_has_position = False
                    exchange_pos = None
                    
                    if pos_info.get("retCode") == 0:
                        list_data = pos_info.get("result", {}).get("list", [])
                        for p in list_data:
                            quantity = safe_float(p.get("quantity"), 0)
                            if abs(quantity) > 0:
                                exchange_has_position = True
                                exchange_pos = p
                                break
                    
                    # Если на бирже есть позиция - показываем её
                    if exchange_has_position and exchange_pos:
                        quantity = safe_float(exchange_pos.get("quantity"), 0)
                        side = "Buy" if quantity > 0 else "Sell"
                        entry_price = safe_float(exchange_pos.get("average_price"), 0)
                        current_price = safe_float(exchange_pos.get("current_price"), 0)
                        
                        # Get lot size for accurate calculations
                        lot_size = 1.0
                        try:
                            lot_size = await asyncio.wait_for(
                                asyncio.to_thread(self.tinkoff.get_qty_step, figi),
                                timeout=10.0
                            )
                            if lot_size <= 0:
                                lot_size = 1.0
                        except Exception as e:
                            logger.debug(f"Error getting lot size for {ticker}: {e}, using default 1.0")
                            lot_size = 1.0
                        
                        # Рассчитываем PnL с учетом размера лота
                        abs_quantity = abs(quantity)
                        if side == "Buy":
                            pnl_rub = (current_price - entry_price) * abs_quantity * lot_size
                            pnl_pct = ((current_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
                        else:  # Sell (SHORT)
                            pnl_rub = (entry_price - current_price) * abs_quantity * lot_size
                            pnl_pct = ((entry_price - current_price) / entry_price * 100) if entry_price > 0 else 0
                        
                        # Маржа: используем реальное гарантийное обеспечение из API, если доступно
                        # Иначе используем справочник реальных коэффициентов маржи
                        margin = None
                        margin_source = "none"
                        if "current_margin" in exchange_pos:
                            margin = safe_float(exchange_pos.get("current_margin"), 0)
                            if margin > 0:
                                margin_source = "current_margin"
                        elif "initial_margin" in exchange_pos:
                            margin = safe_float(exchange_pos.get("initial_margin"), 0)
                            if margin > 0:
                                margin_source = "initial_margin"
                        elif "blocked" in exchange_pos:
                            margin = safe_float(exchange_pos.get("blocked"), 0)
                            if margin > 0:
                                margin_source = "blocked"
                        
                        # Fallback: используем справочник реальных коэффициентов маржи
                        if margin is None or margin == 0:
                            from bot.margin_rates import get_margin_for_position
                            margin = get_margin_for_position(
                                ticker=ticker,
                                quantity=abs_quantity,
                                entry_price=entry_price,
                                lot_size=lot_size
                            )
                            margin_source = "margin_rates_dict"
                        
                        logger.debug(
                            f"[show_status] Position {ticker} margin: {margin:.2f} руб "
                            f"(source: {margin_source}, entry={entry_price:.2f}, "
                            f"qty={abs_quantity}, lot_size={lot_size})"
                        )
                        
                        # Получаем вариационную маржу из API, если доступна
                        variation_margin = None
                        if "expected_yield" in exchange_pos:
                            variation_margin = safe_float(exchange_pos.get("expected_yield"), 0)
                        
                        open_positions.append({
                            "ticker": ticker,
                            "side": side,
                            "quantity": abs(quantity),
                            "entry": entry_price,
                            "current": current_price,
                            "pnl": pnl_rub,
                            "pnl_pct": pnl_pct,
                            "margin": margin,
                            "variation_margin": variation_margin,  # Вариационная маржа (текущий PnL)
                            "lot_size": lot_size
                        })
                        total_margin += margin
                        
                        logger.debug(
                            f"[show_status] Position {ticker}: margin={margin:.2f}, "
                            f"total_margin={total_margin:.2f}"
                        )
                        continue  # Позиция уже добавлена, пропускаем проверку локального состояния
                    
                    # Если на бирже позиции нет, но в локальном состоянии есть - синхронизируем
                    # (позиция была закрыта вручную, не показываем её)
                    local_pos = await asyncio.to_thread(self.state.get_open_position, ticker)
                    if local_pos and local_pos.status == "open" and not exchange_has_position:
                        # Позиция закрыта вручную на бирже, но локальное состояние не обновлено
                        # Синхронизируем через trading_loop если доступен
                        if hasattr(self, 'trading_loop') and self.trading_loop:
                            try:
                                await self.trading_loop.handle_position_closed(
                                    figi, local_pos, "external_manual"
                                )
                                logger.info(f"[{ticker}] Synced: Position closed manually, updated local state")
                            except Exception as e:
                                logger.debug(f"Error syncing position for {ticker}: {e}")
                        # Не показываем эту позицию, так как она закрыта на бирже
            except Exception as e:
                logger.error(f"Error getting positions: {e}", exc_info=True)
        
        # Доступный баланс - используем total_blocked_margin из API (из валютной позиции)
        # Это самый точный способ получить реальную замороженную маржу
        if total_blocked_margin_from_api > 0:
            # Используем замороженную маржу из API
            available_balance = wallet_balance - total_blocked_margin_from_api
            if available_balance < 0:
                available_balance = 0.0
            logger.debug(
                f"[show_status] Using API blocked margin: "
                f"wallet={wallet_balance:.2f}, blocked={total_blocked_margin_from_api:.2f}, "
                f"available={available_balance:.2f}"
            )
        elif open_positions and total_margin > 0:
            # Fallback: используем расчетную маржу из позиций
            calculated_available = wallet_balance - total_margin
            if calculated_available < 0:
                calculated_available = 0.0
            available_balance = calculated_available
            logger.debug(
                f"[show_status] Using calculated margin: "
                f"wallet={wallet_balance:.2f}, margin={total_margin:.2f}, "
                f"available={available_balance:.2f}"
            )
        elif available_balance == 0.0 and wallet_balance > 0:
            # Если нет позиций, используем баланс как доступный
            available_balance = wallet_balance
        
        if wallet_balance > 0:
            status_text += f"💰 ACCOUNT INFO:\n"
            status_text += f"Баланс: {wallet_balance:.2f} руб | Доступно: {available_balance:.2f} руб\n\n"
        
        if open_positions:
            status_text += "📊 OPEN POSITIONS:\n"
            for pos in open_positions:
                side_emoji = "📈" if pos["side"] == "Buy" else "📉"
                pnl_sign = "+" if pos["pnl"] >= 0 else ""
                status_text += f"{side_emoji} {pos['ticker']} | {pos['side']}\n"
                status_text += f"   Лотов: {pos['quantity']:.0f} (лот: {pos.get('lot_size', 1.0):.0f})\n"
                status_text += f"   💰 Гарантийное обеспечение: {pos['margin']:.2f} руб\n"
                if pos.get('variation_margin') is not None:
                    vm_sign = "+" if pos['variation_margin'] >= 0 else ""
                    status_text += f"   📈 Вариационная маржа: {vm_sign}{pos['variation_margin']:.2f} руб\n"
                status_text += f"   Вход: {pos['entry']:.2f} руб | Тек: {pos['current']:.2f} руб\n"
                status_text += f"   PnL: {pnl_sign}{pos['pnl']:.2f} руб ({pnl_sign}{pos['pnl_pct']:.2f}%)\n\n"
        else:
            status_text += "📊 OPEN POSITIONS:\n(нет открытых позиций)\n\n"
        
        # Active Strategy
        status_text += "📈 ACTIVE STRATEGY:\n"
        if not self.state.active_instruments:
            status_text += "  (нет активных инструментов)\n"
        else:
            for ticker in self.state.active_instruments:
                # Проверяем, используется ли MTF стратегия
                use_mtf = self.settings.ml_strategy.use_mtf_strategy
                is_mtf = False
                
                if use_mtf and hasattr(self, 'trading_loop') and self.trading_loop:
                    strategy = self.trading_loop.strategies.get(ticker)
                    if strategy and hasattr(strategy, 'predict_combined'):
                        is_mtf = True
                        # Загружаем MTF модели
                        mtf_models = self.load_mtf_models_for_instrument(ticker)
                        if mtf_models.get("model_1h") and mtf_models.get("model_15m"):
                            status_text += f"Инструмент: {ticker} | MTF: {mtf_models['model_1h']} + {mtf_models['model_15m']}\n"
                            status_text += f"   🎯 Уверенность: 1h≥{self.settings.ml_strategy.mtf_confidence_threshold_1h*100:.0f}%, 15m≥{self.settings.ml_strategy.mtf_confidence_threshold_15m*100:.0f}%\n"
                        else:
                            status_text += f"Инструмент: {ticker} | MTF: ⚠️ Модели не выбраны\n"
                    else:
                        # MTF включена, но стратегия не загружена
                        mtf_models = self.load_mtf_models_for_instrument(ticker)
                        if mtf_models.get("model_1h") and mtf_models.get("model_15m"):
                            status_text += f"Инструмент: {ticker} | MTF: {mtf_models['model_1h']} + {mtf_models['model_15m']} (ожидание загрузки)\n"
                        else:
                            status_text += f"Инструмент: {ticker} | MTF: ⚠️ Модели не выбраны\n"
                
                if not is_mtf:
                    # Обычная стратегия
                    model_path = self.state.instrument_models.get(ticker)
                    if model_path and Path(model_path).exists():
                        model_name = Path(model_path).stem
                        ml_settings = self.settings.get_ml_settings_for_instrument(ticker)
                        status_text += f"Инструмент: {ticker} | Модель: {model_name}\n"
                        status_text += f"   🎯 Уверенность: ≥{ml_settings.confidence_threshold*100:.0f}%\n"
                    else:
                        models = self.model_manager.find_models_for_instrument(ticker)
                        if models:
                            model_path = str(models[0])
                            self.model_manager.apply_model(ticker, model_path)
                            model_name = models[0].stem
                            ml_settings = self.settings.get_ml_settings_for_instrument(ticker)
                            status_text += f"Инструмент: {ticker} | Модель: {model_name} (авто)\n"
                            status_text += f"   🎯 Уверенность: ≥{ml_settings.confidence_threshold*100:.0f}%\n"
                        else:
                            status_text += f"Инструмент: {ticker} | Модель: ❌ Не найдена\n"
                
                # Cooldown
                cooldown_info = self.state.get_cooldown_info(ticker) if hasattr(self.state, 'get_cooldown_info') else None
                if cooldown_info and cooldown_info.get("active"):
                    hours_left = cooldown_info.get("hours_left", 0)
                    if hours_left < 1:
                        minutes_left = int(hours_left * 60)
                        status_text += f"   ❄️ Cooldown: {cooldown_info['reason']} | Разморозка через {minutes_left} мин\n"
                    else:
                        status_text += f"   ❄️ Cooldown: {cooldown_info['reason']} | Разморозка через {hours_left:.1f} ч\n"
        
        # Overall Stats
        stats = self.state.get_stats()
        status_text += f"\n💰 ОБЩИЙ PnL: {stats['total_pnl']:.2f} руб ({stats['win_rate']:.1f}% WR, {stats['total_trades']} сделок)"
        
        if hasattr(update_or_query, 'message'):
            await update_or_query.message.reply_text(status_text, reply_markup=self.get_main_keyboard())
        else:
            await self.safe_edit_message(update_or_query, status_text, reply_markup=self.get_main_keyboard())

    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback queries."""
        query = update.callback_query
        try:
            await query.answer()
        except Exception as e:
            logger.debug(f"Could not answer callback query (non-critical): {e}")

        try:
            logger.debug(f"Callback query: {query.data} from user {query.from_user.id}")
            
            if query.data == "bot_start":
                self.state.set_running(True)
                await self.safe_edit_message(query, "✅ Бот запущен!", reply_markup=self.get_main_keyboard())
            elif query.data == "bot_stop":
                self.state.set_running(False)
                await self.safe_edit_message(query, "🛑 Бот остановлен!", reply_markup=self.get_main_keyboard())
            elif query.data == "status_info":
                await self.show_status(query)
            elif query.data == "settings_instruments":
                await self.show_instruments_settings(query)
            elif query.data.startswith("toggle_ml_"):
                # Обрабатываем ML настройки ПЕРЕД общим toggle_
                setting_name = query.data.replace("toggle_ml_", "")
                await self.toggle_ml_setting(query, setting_name)
            elif query.data.startswith("toggle_risk_"):
                # Обрабатываем Risk настройки ПЕРЕД общим toggle_
                setting_name = query.data.replace("toggle_risk_", "")
                await self.toggle_risk_setting(query, setting_name)
            elif query.data.startswith("toggle_strategy_"):
                # Обрабатываем Strategy настройки ПЕРЕД общим toggle_
                setting_name = query.data.replace("toggle_strategy_", "")
                await self.toggle_strategy_setting(query, setting_name)
            elif query.data.startswith("toggle_"):
                ticker = query.data.replace("toggle_", "")
                logger.info(f"🔄 Toggling instrument {ticker}...")
                logger.info(f"   Current active instruments before toggle: {self.state.active_instruments}")
                
                try:
                    # Выполняем toggle с таймаутом (5 секунд должно быть достаточно для простой операции)
                    res = await asyncio.wait_for(
                        asyncio.to_thread(
                            self.state.toggle_instrument if hasattr(self.state, 'toggle_instrument') else lambda x: None,
                            ticker
                        ),
                        timeout=5.0
                    )
                    logger.info(f"✅ Toggle instrument {ticker} completed: {res}")
                    logger.info(f"   Active instruments after toggle: {self.state.active_instruments}")
                    
                    # Проверяем, что файл действительно обновился
                    if self.state.state_file.exists():
                        import json
                        try:
                            with open(self.state.state_file, 'r', encoding='utf-8') as f:
                                saved_data = json.load(f)
                                saved_instruments = saved_data.get("active_instruments", [])
                                logger.info(f"   Verified: Saved active instruments in file: {saved_instruments}")
                                if saved_instruments != self.state.active_instruments:
                                    logger.warning(f"   ⚠️ Mismatch! Memory: {self.state.active_instruments}, File: {saved_instruments}")
                        except Exception as e:
                            logger.error(f"   ❌ Error verifying saved state: {e}")
                    else:
                        logger.error(f"   ❌ State file {self.state.state_file} does not exist!")
                        
                except asyncio.TimeoutError:
                    logger.error(f"❌ Timeout toggling instrument {ticker} (5s exceeded)")
                    await query.answer("❌ Таймаут при переключении инструмента. Попробуйте еще раз.", show_alert=True)
                    return
                except Exception as e:
                    logger.error(f"❌ Error toggling instrument {ticker}: {e}", exc_info=True)
                    await query.answer(f"❌ Ошибка при переключении: {str(e)[:100]}", show_alert=True)
                    return
                
                if res is None:
                    await query.answer("⚠️ Достигнут лимит в 5 инструментов!", show_alert=True)
                
                logger.info(f"📋 Showing instruments settings after toggle {ticker}...")
                await self.show_instruments_settings(query)
            elif query.data == "add_ticker":
                user_id = query.from_user.id
                # Очищаем другие состояния ожидания, чтобы избежать конфликтов
                self.waiting_for_risk_setting.pop(user_id, None)
                self.waiting_for_ml_setting.pop(user_id, None)
                self.waiting_for_strategy_setting.pop(user_id, None)
                self.waiting_for_ticker[user_id] = True
                await query.edit_message_text(
                    "➕ ДОБАВЛЕНИЕ НОВОГО ИНСТРУМЕНТА\n\n"
                    "Введите тикер инструмента (например: VBH6, SRH6, GLDRUBF)\n\n"
                    "Тикер должен быть в формате: TICKER\n"
                    "Примеры: VBH6, SRH6, GLDRUBF, Si-3.25",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Отмена", callback_data="cancel_add_ticker")]])
                )
            elif query.data == "cancel_add_ticker":
                user_id = query.from_user.id
                self.waiting_for_ticker.pop(user_id, None)
                await self.show_instruments_settings(query)
            elif query.data == "history_menu":
                await self.show_history_menu(query)
            elif query.data == "history_signals":
                await self.show_signals(query)
            elif query.data == "history_trades":
                await self.show_trades(query)
            elif query.data == "stats":
                await self.show_stats(query)
            elif query.data == "settings_models":
                await self.show_models_settings(query)
            elif query.data.startswith("select_model_"):
                ticker = query.data.replace("select_model_", "")
                await self.show_model_selection(query, ticker)
            elif query.data.startswith("apply_model_"):
                parts = query.data.replace("apply_model_", "").split("_", 1)
                if len(parts) == 2:
                    ticker = parts[0]
                    model_index = int(parts[1])
                    await self.apply_selected_model(query, ticker, model_index)
            elif query.data.startswith("test_all_"):
                ticker = query.data.replace("test_all_", "")
                user_id = query.from_user.id
                await query.answer("🧪 Начато тестирование моделей...")
                asyncio.create_task(self.test_all_models_async(ticker, user_id))
            elif query.data.startswith("retrain_"):
                ticker = query.data.replace("retrain_", "")
                user_id = query.from_user.id
                await query.answer("🎓 Начато обучение моделей...")
                asyncio.create_task(self.retrain_models_async(ticker, user_id))
            elif query.data == "settings_risk":
                await self.show_risk_settings(query)
            elif query.data.startswith("edit_risk_"):
                setting_name = query.data.replace("edit_risk_", "")
                await self.start_edit_risk_setting(query, setting_name)
            elif query.data.startswith("toggle_risk_"):
                setting_name = query.data.replace("toggle_risk_", "")
                await self.toggle_risk_setting(query, setting_name)
            elif query.data == "settings_ml":
                await self.show_ml_settings(query)
            elif query.data.startswith("edit_ml_"):
                setting_name = query.data.replace("edit_ml_", "")
                await self.start_edit_ml_setting(query, setting_name)
            # toggle_ml_ обрабатывается выше (строка 383), перед общим toggle_
            elif query.data.startswith("select_mtf_models_"):
                ticker = query.data.replace("select_mtf_models_", "")
                await self.show_mtf_model_selection(query, ticker)
            elif query.data.startswith("select_mtf_1h_"):
                ticker = query.data.replace("select_mtf_1h_", "")
                await self.show_mtf_timeframe_selection(query, ticker, "1h")
            elif query.data.startswith("select_mtf_15m_"):
                ticker = query.data.replace("select_mtf_15m_", "")
                await self.show_mtf_timeframe_selection(query, ticker, "15m")
            elif query.data.startswith("apply_mtf_model_"):
                parts = query.data.replace("apply_mtf_model_", "").split("_")
                if len(parts) >= 3:
                    ticker = parts[0]
                    timeframe = parts[1]
                    model_index = int(parts[2]) if len(parts) > 2 else 0
                    await self.select_mtf_model(query, ticker, timeframe, model_index)
            elif query.data.startswith("apply_mtf_strategy_"):
                ticker = query.data.replace("apply_mtf_strategy_", "")
                await self.apply_mtf_strategy(query, ticker)
            elif query.data == "settings_strategy":
                await self.show_strategy_settings(query)
            elif query.data.startswith("edit_strategy_"):
                setting_name = query.data.replace("edit_strategy_", "")
                await self.start_edit_strategy_setting(query, setting_name)
            elif query.data.startswith("toggle_strategy_"):
                setting_name = query.data.replace("toggle_strategy_", "")
                await self.toggle_strategy_setting(query, setting_name)
            elif query.data == "settings_api":
                await self.show_api_settings(query)
            elif query.data == "toggle_sandbox":
                await self.toggle_sandbox_mode(query)
            elif query.data == "main_menu":
                await self.safe_edit_message(query, "🤖 Tinkoff Trading Bot Terminal", reply_markup=self.get_main_keyboard())
            elif query.data == "emergency_menu":
                await self.show_emergency_menu(query)
            elif query.data == "emergency_stop_all":
                await self.emergency_stop_all(query)
            elif query.data == "sync_positions":
                await self.sync_positions(query)
            elif query.data == "dashboard":
                await self.show_dashboard(query)
            elif query.data.startswith("remove_cooldown_"):
                ticker = query.data.replace("remove_cooldown_", "")
                if hasattr(self.state, 'remove_cooldown'):
                    self.state.remove_cooldown(ticker)
                await query.answer(f"✅ Разморозка снята для {ticker}", show_alert=True)
                await self.show_instruments_settings(query)
            else:
                logger.warning(f"Unknown callback query: {query.data}")
                await query.answer("❌ Неизвестная команда", show_alert=True)
        except Exception as e:
            logger.error(f"Error handling callback {query.data if query else 'unknown'}: {e}", exc_info=True)
            try:
                await query.answer("❌ Ошибка при обработке команды", show_alert=True)
            except:
                pass

    async def show_instruments_settings(self, query):
        """Показывает настройки инструментов."""
        try:
            logger.debug("show_instruments_settings: Starting...")
            # Получаем все известные инструменты
            all_possible = list(set(self.state.known_instruments + self.state.active_instruments))
            all_possible = sorted(all_possible)
            logger.debug(f"show_instruments_settings: Found {len(all_possible)} instruments")
            
            keyboard = []
            for ticker in all_possible:
                status = "✅" if ticker in self.state.active_instruments else "❌"
                button_text = f"{status} {ticker}"
                
                # Проверяем cooldown
                if hasattr(self.state, 'get_cooldown_info'):
                    cooldown_info = self.state.get_cooldown_info(ticker)
                    if cooldown_info and cooldown_info.get("active"):
                        hours_left = cooldown_info.get("hours_left", 0)
                        if hours_left < 1:
                            minutes_left = int(hours_left * 60)
                            button_text += f" ❄️({minutes_left}м)"
                        else:
                            button_text += f" ❄️({hours_left:.1f}ч)"
                
                keyboard.append([InlineKeyboardButton(button_text, callback_data=f"toggle_{ticker}")])
                
                # Кнопка снятия cooldown
                if hasattr(self.state, 'get_cooldown_info'):
                    cooldown_info = self.state.get_cooldown_info(ticker)
                    if cooldown_info and cooldown_info.get("active"):
                        keyboard.append([InlineKeyboardButton(
                            f"🔥 Снять разморозку {ticker}",
                            callback_data=f"remove_cooldown_{ticker}"
                        )])
            
            keyboard.append([InlineKeyboardButton("➕ Добавить новый инструмент", callback_data="add_ticker")])
            keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="status_info")])
            keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
            
            logger.debug(f"show_instruments_settings: Sending message with {len(keyboard)} buttons")
            await self.safe_edit_message(query, "⚙️ Настройка активных инструментов (макс 5):", reply_markup=InlineKeyboardMarkup(keyboard))
            logger.debug("show_instruments_settings: Completed successfully")
        except Exception as e:
            logger.error(f"Error in show_instruments_settings: {e}", exc_info=True)
            try:
                await query.answer("❌ Ошибка при отображении настроек инструментов", show_alert=True)
            except:
                pass

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages."""
        if not await self.check_auth(update):
            return
        
        user_id = update.effective_user.id
        text = update.message.text.strip()
        
        # Проверяем, ждем ли мы ввод тикера (проверяем первым, так как это специфичный ввод)
        if self.waiting_for_ticker.get(user_id, False):
            self.waiting_for_ticker.pop(user_id, None)
            
            ticker = text.upper().strip()
            
            # Проверяем, не добавлен ли уже
            if ticker in self.state.active_instruments:
                await update.message.reply_text(
                    f"ℹ️ Инструмент {ticker} уже активен.",
                    reply_markup=self.get_main_keyboard()
                )
                return
            
            # Валидируем тикер через Tinkoff API
            await update.message.reply_text(f"🔍 Проверка инструмента {ticker} на бирже...")
            
            try:
                if not self.tinkoff:
                    await update.message.reply_text(
                        "❌ Tinkoff клиент не инициализирован.",
                        reply_markup=self.get_main_keyboard()
                    )
                    return
                
                # Пытаемся найти инструмент (с таймаутом 30 секунд)
                logger.info(f"Searching for instrument {ticker} via Tinkoff API...")
                try:
                    instrument_info = await asyncio.wait_for(
                        asyncio.to_thread(
                            self.tinkoff.find_instrument,
                            ticker,
                            instrument_type="futures",
                            prefer_perpetual=False
                        ),
                        timeout=30.0
                    )
                    logger.info(f"Instrument {ticker} search completed: found={instrument_info is not None}")
                except asyncio.TimeoutError:
                    logger.error(f"Timeout searching for instrument {ticker} (30s exceeded)")
                    await update.message.reply_text(
                        f"❌ Таймаут при поиске инструмента {ticker}.\n"
                        "Попробуйте позже или проверьте подключение к интернету.",
                        reply_markup=self.get_main_keyboard()
                    )
                    return
                
                if not instrument_info:
                    await update.message.reply_text(
                        f"❌ Инструмент {ticker} не найден на бирже Tinkoff.\n"
                        "Проверьте правильность написания.",
                        reply_markup=self.get_main_keyboard()
                    )
                    return
                
                # Сохраняем информацию об инструменте (с таймаутом 10 секунд)
                logger.info(f"Saving instrument {ticker} to storage...")
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(
                            self.storage.save_instrument,
                            figi=instrument_info["figi"],
                            ticker=ticker,
                            name=instrument_info["name"],
                            instrument_type=instrument_info.get("instrument_type", "futures")
                        ),
                        timeout=10.0
                    )
                    logger.info(f"Instrument {ticker} saved successfully")
                except asyncio.TimeoutError:
                    logger.error(f"Timeout saving instrument {ticker} (10s exceeded)")
                    await update.message.reply_text(
                        f"⚠️ Инструмент {ticker} найден, но произошла ошибка при сохранении.\n"
                        "Попробуйте еще раз.",
                        reply_markup=self.get_main_keyboard()
                    )
                    return
                
                # Добавляем в известные
                if ticker not in self.state.known_instruments:
                    self.state.known_instruments.append(ticker)
                    logger.info(f"Added {ticker} to known_instruments")
                
                # Включаем инструмент
                if hasattr(self.state, 'enable_instrument'):
                    enable_result = self.state.enable_instrument(ticker)
                    logger.info(f"enable_instrument({ticker}) returned: {enable_result}")
                    if enable_result is None:
                        await update.message.reply_text(
                            f"⚠️ Инструмент {ticker} сохранен, но лимит активных инструментов достигнут.\n"
                            "Отключите один из активных инструментов и включите этот из списка.",
                            reply_markup=self.get_main_keyboard()
                        )
                        return
                    elif enable_result:
                        logger.info(f"✅ Instrument {ticker} successfully enabled via enable_instrument()")
                else:
                    # Простое добавление
                    if len(self.state.active_instruments) < self.state.max_active_instruments:
                        if ticker not in self.state.active_instruments:
                            self.state.active_instruments.append(ticker)
                            logger.info(f"✅ Added {ticker} to active_instruments (simple method)")
                        else:
                            logger.info(f"ℹ️ {ticker} already in active_instruments")
                    else:
                        await update.message.reply_text(
                            f"⚠️ Достигнут лимит активных инструментов ({self.state.max_active_instruments}).",
                            reply_markup=self.get_main_keyboard()
                        )
                        return
                
                # Сохраняем состояние после всех изменений
                self.state.save()
                logger.info(f"✅ State saved. Active instruments: {self.state.active_instruments}, Known: {self.state.known_instruments}")
                
                # Проверяем, есть ли модели
                existing_models = self.model_manager.find_models_for_instrument(ticker)
                has_models = bool(existing_models)
                
                logger.info(f"Adding instrument {ticker}: has_models={has_models}, models_count={len(existing_models)}")
                
                if has_models:
                    await update.message.reply_text(
                        f"✅ Инструмент {ticker} включен.\n"
                        "Модели уже существуют — обучение не требуется.",
                        reply_markup=self.get_main_keyboard()
                    )
                else:
                    await update.message.reply_text(
                        f"✅ Инструмент {ticker} добавлен!\n\n"
                        "🔄 Автоматически запущено обучение моделей...\n"
                        "Вы получите уведомление по завершении.",
                        reply_markup=self.get_main_keyboard()
                    )
                    
                    # Автоматически запускаем обучение моделей только если их нет
                    user_id = update.message.from_user.id
                    logger.info(f"Starting model training for {ticker}, user_id={user_id}")
                    training_task = asyncio.create_task(self.retrain_models_async(ticker, user_id))
                    logger.info(f"Model training task created for {ticker}: {training_task}")
                
            except Exception as e:
                logger.error(f"Error validating/adding ticker {ticker}: {e}")
                await update.message.reply_text(
                    f"❌ Ошибка при добавлении инструмента {ticker}:\n{str(e)}",
                    reply_markup=self.get_main_keyboard()
                )
            return
        
        # Проверяем, ждем ли мы ввод настройки риска
        if user_id in self.waiting_for_risk_setting:
            setting_name = self.waiting_for_risk_setting.pop(user_id)
            await self.process_risk_setting_input(update, setting_name, text)
            return
        
        # Проверяем, ждем ли мы ввод ML настройки
        if user_id in self.waiting_for_ml_setting:
            setting_name = self.waiting_for_ml_setting.pop(user_id)
            await self.process_ml_setting_input(update, setting_name, text)
            return
        
        # Проверяем, ждем ли мы ввод настройки стратегии
        if user_id in self.waiting_for_strategy_setting:
            setting_name = self.waiting_for_strategy_setting.pop(user_id)
            await self.process_strategy_setting_input(update, setting_name, text)
            return

    async def show_history_menu(self, query):
        """Показывает меню истории."""
        keyboard = [
            [InlineKeyboardButton("🔍 ИСТОРИЯ СИГНАЛОВ", callback_data="history_signals")],
            [InlineKeyboardButton("📈 ИСТОРИЯ СДЕЛОК", callback_data="history_trades")],
            [InlineKeyboardButton("🔙 Назад", callback_data="status_info")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        await self.safe_edit_message(query, "📝 Меню истории:", reply_markup=InlineKeyboardMarkup(keyboard))

    async def show_signals(self, query):
        """Показывает историю сигналов."""
        signals = self.state.signals[-10:] if hasattr(self.state, 'signals') else []
        if not signals:
            text = "История сигналов пуста."
        else:
            text = "🔍 ПОСЛЕДНИЕ СИГНАЛЫ:\n\n"
            for s in reversed(signals):
                timestamp_str = s.timestamp[11:19] if len(s.timestamp) > 19 else s.timestamp[:8]
                text += f"🕒 {timestamp_str} | {s.instrument} | {s.action} ({int(s.confidence*100)}%)\n"
        
        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="history_menu")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        await self.safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def show_stats(self, query):
        """Показывает статистику."""
        stats = self.state.get_stats()
        all_trades = self.state.trades if hasattr(self.state, 'trades') else []
        closed_trades = [t for t in all_trades if t.status == "closed"]
        open_trades = [t for t in all_trades if t.status == "open"]
        
        text = "📈 СТАТИСТИКА ТОРГОВЛИ:\n\n"
        text += f"💰 Общий PnL: {stats['total_pnl']:.2f} руб\n"
        text += f"📊 Винрейт: {stats['win_rate']:.1f}%\n"
        text += f"🔢 Всего сделок: {len(all_trades)}\n"
        text += f"   • Закрыто: {len(closed_trades)}\n"
        text += f"   • Открыто: {len(open_trades)}\n\n"
        
        if closed_trades:
            wins = [t for t in closed_trades if t.pnl_usd > 0]
            losses = [t for t in closed_trades if t.pnl_usd < 0]
            text += f"✅ Прибыльных: {len(wins)}\n"
            text += f"❌ Убыточных: {len(losses)}\n"
            if wins:
                avg_win = sum(t.pnl_usd for t in wins) / len(wins)
                text += f"📈 Средний выигрыш: {avg_win:.2f} руб\n"
            if losses:
                avg_loss = sum(t.pnl_usd for t in losses) / len(losses)
                text += f"📉 Средний проигрыш: {avg_loss:.2f} руб\n"
        
        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="status_info")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        await self.safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def show_trades(self, query):
        """Показывает историю сделок."""
        all_trades = self.state.trades if hasattr(self.state, 'trades') else []
        closed_trades = [t for t in all_trades if t.status == "closed"][-10:]
        if not closed_trades:
            text = "История сделок пуста."
        else:
            text = "📈 ПОСЛЕДНИЕ СДЕЛКИ:\n\n"
            for idx, t in enumerate(reversed(closed_trades)):
                pnl_sign = "+" if t.pnl_usd >= 0 else ""
                trade_idx = len(all_trades) - len(closed_trades) + idx
                
                exit_time_str = t.exit_time[11:19] if t.exit_time and len(t.exit_time) > 19 else (t.exit_time[:8] if t.exit_time else "N/A")
                entry_time_str = t.entry_time[11:19] if len(t.entry_time) > 19 else t.entry_time[:8]
                
                pnl_emoji = "✅" if t.pnl_usd > 0 else "❌" if t.pnl_usd < 0 else "➖"
                
                text += f"#{trade_idx} {pnl_emoji} {t.instrument} {t.side}\n"
                text += f"   📅 Вход: {entry_time_str} → Выход: {exit_time_str}\n"
                text += f"   💰 Вход: {t.entry_price:.2f} руб"
                if t.exit_price:
                    text += f" | Выход: {t.exit_price:.2f} руб\n"
                else:
                    text += f" | Выход: N/A\n"
                text += f"   📊 Лотов: {t.quantity:.0f}\n"
                text += f"   💵 PnL: {pnl_sign}{t.pnl_usd:.2f} руб ({pnl_sign}{t.pnl_pct:.2f}%)\n\n"
        
        keyboard = [
            [InlineKeyboardButton("🔙 Назад", callback_data="history_menu")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        await self.safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def show_models_settings(self, query):
        """Показывает настройки моделей."""
        text = "🤖 УПРАВЛЕНИЕ МОДЕЛЯМИ:\n\n"
        
        if not self.state.active_instruments:
            text += "Нет активных инструментов. Добавьте инструменты в настройках."
        else:
            for ticker in self.state.active_instruments:
                model_path = self.state.instrument_models.get(ticker)
                if model_path and Path(model_path).exists():
                    model_name = Path(model_path).stem
                    text += f"✅ {ticker}: {model_name}\n"
                else:
                    text += f"❌ {ticker}: Авто-поиск\n"
        
        keyboard = []
        for ticker in self.state.active_instruments:
            keyboard.append([InlineKeyboardButton(f"📌 Выбрать модель для {ticker}", callback_data=f"select_model_{ticker}")])
            keyboard.append([InlineKeyboardButton(f"🔄 Выбрать MTF модели для {ticker}", callback_data=f"select_mtf_models_{ticker}")])
        
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="status_info")])
        keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
        
        await self.safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def show_model_selection(self, query, ticker: str):
        """Показывает выбор модели для инструмента с результатами тестов."""
        models = self.model_manager.find_models_for_instrument(ticker)
        
        if not models:
            await self.safe_edit_message(
                query,
                f"❌ Для {ticker} не найдено моделей.\n\n"
                "Используйте кнопку 'Обучить модели' для создания моделей.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎓 Обучить модели", callback_data=f"retrain_{ticker}")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="settings_models")]
                ])
            )
            return
        
        text = f"📌 ВЫБОР МОДЕЛИ ДЛЯ {ticker}:\n\n"
        keyboard = []
        
        # Загружаем результаты тестов
        test_results = self.model_manager.get_model_test_results(ticker)
        
        # Проверяем, есть ли хотя бы одна протестированная модель
        has_tested = any(str(m) in test_results for m in models)
        
        for idx, model_path in enumerate(models):
            model_name = model_path.stem
            is_current = self.state.instrument_models.get(ticker) == str(model_path)
            prefix = "✅ " if is_current else ""
            
            # Получаем результаты теста для этой модели
            model_results = test_results.get(str(model_path), {})
            
            if model_results:
                pnl = model_results.get("total_pnl_pct", 0)
                winrate = model_results.get("win_rate", 0)
                trades = model_results.get("total_trades", 0)
                trades_per_day = model_results.get("trades_per_day", 0)
                profit_factor = model_results.get("profit_factor", 0)
                
                pnl_sign = "+" if pnl >= 0 else ""
                pnl_color = "🟢" if pnl > 0 else "🔴" if pnl < 0 else "⚪"
                text += f"{prefix}{pnl_color} {model_name}\n"
                text += f"   PnL: {pnl_sign}{pnl:.2f}% | WR: {winrate:.1f}% | PF: {profit_factor:.2f}\n"
                text += f"   Сделок: {trades} ({trades_per_day:.1f}/день)\n\n"
            else:
                text += f"{prefix}⚪ {model_name} (не тестирована)\n\n"
            
            keyboard.append([InlineKeyboardButton(
                f"{'✅ ' if is_current else ''}{model_name}",
                callback_data=f"apply_model_{ticker}_{idx}"
            )])
        
        if not has_tested:
            keyboard.append([InlineKeyboardButton("🧪 Тестировать все модели (14 дней)", callback_data=f"test_all_{ticker}")])
        else:
            keyboard.append([InlineKeyboardButton("🔄 Обновить тесты", callback_data=f"test_all_{ticker}")])
        
        keyboard.append([InlineKeyboardButton("🎓 Обучить все модели", callback_data=f"retrain_{ticker}")])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="settings_models")])
        keyboard.append([InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")])
        
        await self.safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def apply_selected_model(self, query, ticker: str, model_index: int):
        """Применяет выбранную модель."""
        models = self.model_manager.find_models_for_instrument(ticker)
        
        if model_index >= len(models):
            await query.answer("Ошибка: модель не найдена", show_alert=True)
            return
        
        model_path = models[model_index]
        self.model_manager.apply_model(ticker, str(model_path))
        
        await query.answer(f"✅ Модель применена для {ticker}!", show_alert=True)
        await self.show_models_settings(query)
    
    def load_mtf_models_for_instrument(self, ticker: str) -> Dict[str, Optional[str]]:
        """Загружает сохраненные MTF модели для инструмента."""
        mtf_models_file = Path("mtf_models.json")
        if not mtf_models_file.exists():
            return {}
        
        try:
            with open(mtf_models_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get(ticker.upper(), {})
        except Exception as e:
            logger.error(f"Error loading MTF models: {e}")
            return {}
    
    def save_mtf_models_for_instrument(self, ticker: str, model_1h: Optional[str], model_15m: Optional[str]):
        """Сохраняет MTF модели для инструмента."""
        mtf_models_file = Path("mtf_models.json")
        data = {}
        if mtf_models_file.exists():
            try:
                with open(mtf_models_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                pass
        
        data[ticker.upper()] = {
            "model_1h": model_1h,
            "model_15m": model_15m
        }
        
        try:
            with open(mtf_models_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(f"✅ MTF models saved to {mtf_models_file} for {ticker.upper()}: 1h={model_1h}, 15m={model_15m}")
        except Exception as e:
            logger.error(f"❌ Error saving MTF models to {mtf_models_file}: {e}")
            raise
    
    async def show_mtf_model_selection(self, query, ticker: str):
        """Показывает меню выбора MTF моделей для инструмента."""
        ticker = ticker.upper()
        
        # Загружаем сохраненные MTF модели
        mtf_models = self.load_mtf_models_for_instrument(ticker)
        
        text = f"🔄 ВЫБОР MTF МОДЕЛЕЙ ДЛЯ {ticker}:\n\n"
        
        if mtf_models:
            model_1h_name = mtf_models.get("model_1h", "Не выбрана")
            model_15m_name = mtf_models.get("model_15m", "Не выбрана")
            text += f"📊 Текущие модели:\n"
            text += f"   1h: {model_1h_name}\n"
            text += f"   15m: {model_15m_name}\n\n"
        else:
            text += "📊 Модели не выбраны\n\n"
        
        text += "Выберите таймфрейм для выбора модели:"
        
        keyboard = [
            [InlineKeyboardButton("⏰ Выбрать 1h модель", callback_data=f"select_mtf_1h_{ticker}")],
            [InlineKeyboardButton("⏱ Выбрать 15m модель", callback_data=f"select_mtf_15m_{ticker}")],
            [InlineKeyboardButton("✅ Применить MTF стратегию", callback_data=f"apply_mtf_strategy_{ticker}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="settings_models")]
        ]
        
        await self.safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def show_mtf_timeframe_selection(self, query, ticker: str, timeframe: str):
        """Показывает список моделей для выбранного таймфрейма."""
        ticker = ticker.upper()
        models_dir = Path("ml_models")
        
        # Ищем модели для таймфрейма
        if timeframe == "1h":
            patterns = [f"*_{ticker}_60_*.pkl", f"*_{ticker}_*1h*.pkl"]
        else:  # 15m
            patterns = [f"*_{ticker}_15_*.pkl", f"*_{ticker}_*15m*.pkl"]
        
        models = []
        for pattern in patterns:
            models.extend(models_dir.glob(pattern))
        
        models = sorted(list(set(models)))  # Убираем дубликаты и сортируем
        
        if not models:
            await self.safe_edit_message(
                query,
                f"❌ Для {ticker} не найдено {timeframe} моделей.\n\n"
                f"Используйте кнопку 'Обучить модели' для создания моделей.",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎓 Обучить модели", callback_data=f"retrain_{ticker}")],
                    [InlineKeyboardButton("🔙 Назад", callback_data=f"select_mtf_models_{ticker}")]
                ])
            )
            return
        
        # Загружаем сохраненные MTF модели
        mtf_models = self.load_mtf_models_for_instrument(ticker)
        current_model = mtf_models.get(f"model_{timeframe}")
        
        text = f"📌 ВЫБОР {timeframe.upper()} МОДЕЛИ ДЛЯ {ticker}:\n\n"
        keyboard = []
        
        for idx, model_path in enumerate(models):
            model_name = model_path.stem
            is_current = current_model == model_name
            prefix = "✅ " if is_current else ""
            
            text += f"{prefix}{model_name}\n"
            
            keyboard.append([InlineKeyboardButton(
                f"{'✅ ' if is_current else ''}{model_name}",
                callback_data=f"apply_mtf_model_{ticker}_{timeframe}_{idx}"
            )])
        
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data=f"select_mtf_models_{ticker}")])
        
        await self.safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard))
    
    async def select_mtf_model(self, query, ticker: str, timeframe: str, model_index: int):
        """Выбирает модель для таймфрейма."""
        ticker = ticker.upper()
        models_dir = Path("ml_models")
        
        # Ищем модели для таймфрейма
        if timeframe == "1h":
            patterns = [f"*_{ticker}_60_*.pkl", f"*_{ticker}_*1h*.pkl"]
        else:  # 15m
            patterns = [f"*_{ticker}_15_*.pkl", f"*_{ticker}_*15m*.pkl"]
        
        models = []
        for pattern in patterns:
            models.extend(models_dir.glob(pattern))
        
        models = sorted(list(set(models)))
        
        if model_index >= len(models):
            await query.answer("Ошибка: модель не найдена", show_alert=True)
            return
        
        model_path = models[model_index]
        model_name = model_path.stem
        
        # Загружаем текущие MTF модели
        mtf_models = self.load_mtf_models_for_instrument(ticker)
        if not mtf_models:
            mtf_models = {}
        
        # Обновляем выбранную модель
        if timeframe == "1h":
            mtf_models["model_1h"] = model_name
        else:
            mtf_models["model_15m"] = model_name
        
        # Сохраняем
        self.save_mtf_models_for_instrument(
            ticker,
            mtf_models.get("model_1h"),
            mtf_models.get("model_15m")
        )
        
        # Проверяем, что сохранение прошло успешно
        saved_models = self.load_mtf_models_for_instrument(ticker)
        if saved_models.get(f"model_{timeframe}") != model_name:
            logger.error(f"Failed to save MTF model for {ticker}: expected {model_name}, got {saved_models.get(f'model_{timeframe}')}")
            await query.answer(f"⚠️ Модель выбрана, но не сохранена. Попробуйте еще раз.", show_alert=True)
        else:
            logger.info(f"✅ MTF model saved for {ticker}: {timeframe}={model_name}")
        
        await query.answer(f"✅ {timeframe.upper()} модель выбрана: {model_name}!", show_alert=True)
        await self.show_mtf_model_selection(query, ticker)
    
    async def apply_mtf_strategy(self, query, ticker: str):
        """Применяет выбранные MTF модели и перезапускает стратегию."""
        ticker = ticker.upper()
        mtf_models = self.load_mtf_models_for_instrument(ticker)
        
        if not mtf_models or not mtf_models.get("model_1h") or not mtf_models.get("model_15m"):
            await query.answer(
                "❌ Необходимо выбрать обе модели (1h и 15m) перед применением MTF стратегии!",
                show_alert=True
            )
            await self.show_mtf_model_selection(query, ticker)
            return
        
        # Проверяем, что модели существуют
        models_dir = Path("ml_models")
        model_1h_path = models_dir / f"{mtf_models['model_1h']}.pkl"
        model_15m_path = models_dir / f"{mtf_models['model_15m']}.pkl"
        
        if not model_1h_path.exists() or not model_15m_path.exists():
            await query.answer(
                "❌ Одна из выбранных моделей не найдена! Проверьте файлы моделей.",
                show_alert=True
            )
            await self.show_mtf_model_selection(query, ticker)
            return
        
        # Убеждаемся, что MTF стратегия включена
        if not self.settings.ml_strategy.use_mtf_strategy:
            await query.answer(
                "⚠️ MTF стратегия не включена в настройках ML. Включите её сначала.",
                show_alert=True
            )
            return
        
        # Перезапускаем стратегию в trading_loop
        if hasattr(self, 'trading_loop') and self.trading_loop:
            try:
                # Очищаем существующую стратегию для инструмента
                if ticker in self.trading_loop.strategies:
                    del self.trading_loop.strategies[ticker]
                    logger.info(f"Cleared existing strategy for {ticker} to apply new MTF models")
                
                # Принудительно перезагружаем стратегию сразу
                # Path уже импортирован в начале функции
                model_1h_path = models_dir / f"{mtf_models['model_1h']}.pkl"
                model_15m_path = models_dir / f"{mtf_models['model_15m']}.pkl"
                
                if model_1h_path.exists() and model_15m_path.exists():
                    try:
                        from bot.ml.mtf_strategy import MultiTimeframeMLStrategy
                        self.trading_loop.strategies[ticker] = MultiTimeframeMLStrategy(
                            model_1h_path=str(model_1h_path),
                            model_15m_path=str(model_15m_path),
                            confidence_threshold_1h=self.settings.ml_strategy.mtf_confidence_threshold_1h,
                            confidence_threshold_15m=self.settings.ml_strategy.mtf_confidence_threshold_15m,
                            alignment_mode=self.settings.ml_strategy.mtf_alignment_mode,
                            require_alignment=self.settings.ml_strategy.mtf_require_alignment,
                        )
                        logger.info(f"✅ MTF strategy reloaded immediately for {ticker}")
                    except Exception as e:
                        logger.error(f"Error reloading MTF strategy for {ticker}: {e}", exc_info=True)
                        await query.answer(
                            f"⚠️ Модели сохранены, но ошибка при перезагрузке стратегии: {str(e)[:100]}",
                            show_alert=True
                        )
                        await self.show_mtf_model_selection(query, ticker)
                        return
                else:
                    logger.warning(f"MTF model files not found for {ticker}")
                    await query.answer(
                        "⚠️ Модели сохранены, но файлы моделей не найдены. Стратегия будет загружена при следующем цикле.",
                        show_alert=True
                    )
                    await self.show_mtf_model_selection(query, ticker)
                    return
                
                # Убеждаемся, что модели сохранены
                self.save_mtf_models_for_instrument(
                    ticker,
                    mtf_models['model_1h'],
                    mtf_models['model_15m']
                )
                logger.info(f"✅ MTF models saved for {ticker}: 1h={mtf_models['model_1h']}, 15m={mtf_models['model_15m']}")
                
                await query.answer(
                    f"✅ MTF стратегия применена для {ticker}!\n"
                    f"1h: {mtf_models['model_1h']}\n"
                    f"15m: {mtf_models['model_15m']}\n\n"
                    "Стратегия перезагружена и готова к использованию.",
                    show_alert=True
                )
                # Обновляем UI - загружаем заново, чтобы показать актуальные модели
                await self.show_mtf_model_selection(query, ticker)
            except Exception as e:
                logger.error(f"Error applying MTF strategy for {ticker}: {e}", exc_info=True)
                await query.answer("❌ Ошибка при применении стратегии. Проверьте логи.", show_alert=True)
        else:
            await query.answer(
                f"✅ MTF модели сохранены для {ticker}!\n"
                f"1h: {mtf_models['model_1h']}\n"
                f"15m: {mtf_models['model_15m']}\n\n"
                "Стратегия будет загружена при следующем запуске бота.",
                show_alert=True
            )
            await self.show_mtf_model_selection(query, ticker)

    async def show_risk_settings(self, query):
        """Показывает настройки риска."""
        risk = self.settings.risk
        
        text = "⚙️ НАСТРОЙКИ РИСКА\n\n"
        text += f"💰 Маржа от баланса: {risk.margin_pct_balance*100:.0f}%\n"
        text += f"💰 Фиксированная сумма: {risk.base_order_usd:.2f} руб\n"
        text += f"ℹ️ Используется меньшее значение\n\n"
        text += f"📉 Stop Loss: {risk.stop_loss_pct*100:.2f}%\n"
        text += f"📈 Take Profit: {risk.take_profit_pct*100:.2f}%\n\n"
        text += f"💸 Комиссия (per side): {risk.fee_rate*100:.4f}%\n\n"
        text += f"🔄 Трейлинг стоп: {'✅ Включен' if risk.enable_trailing_stop else '❌ Выключен'}\n"
        text += f"💎 Частичное закрытие: {'✅ Включено' if risk.enable_partial_close else '❌ Выключено'}\n"
        text += f"🛡️ Безубыток: {'✅ Включен' if risk.enable_breakeven else '❌ Выключен'}\n"
        text += f"❄️ Cooldown после убытков: {'✅ Включен' if risk.enable_loss_cooldown else '❌ Выключен'}\n"
        
        keyboard = [
            [InlineKeyboardButton(f"💰 Маржа: {risk.margin_pct_balance*100:.0f}%", callback_data="edit_risk_margin_pct_balance")],
            [InlineKeyboardButton(f"💰 Сумма: {risk.base_order_usd:.2f} руб", callback_data="edit_risk_base_order_usd")],
            [InlineKeyboardButton(f"📉 SL: {risk.stop_loss_pct*100:.2f}%", callback_data="edit_risk_stop_loss_pct")],
            [InlineKeyboardButton(f"📈 TP: {risk.take_profit_pct*100:.2f}%", callback_data="edit_risk_take_profit_pct")],
            [InlineKeyboardButton(f"💸 Комиссия: {risk.fee_rate*100:.4f}%", callback_data="edit_risk_fee_rate")],
            [InlineKeyboardButton(f"🔄 Трейлинг: {'✅' if risk.enable_trailing_stop else '❌'}", callback_data="toggle_risk_enable_trailing_stop")],
            [InlineKeyboardButton(f"💎 Частичное закрытие: {'✅' if risk.enable_partial_close else '❌'}", callback_data="toggle_risk_enable_partial_close")],
            [InlineKeyboardButton(f"🛡️ Безубыток: {'✅' if risk.enable_breakeven else '❌'}", callback_data="toggle_risk_enable_breakeven")],
            [InlineKeyboardButton(f"❄️ Cooldown: {'✅' if risk.enable_loss_cooldown else '❌'}", callback_data="toggle_risk_enable_loss_cooldown")],
            [InlineKeyboardButton("🔄 Сбросить на стандартные", callback_data="reset_risk_defaults")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        
        await self.safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def start_edit_risk_setting(self, query, setting_name: str):
        """Начинает редактирование настройки риска."""
        user_id = query.from_user.id
        
        descriptions = {
            "margin_pct_balance": ("Маржа от баланса (в %)", "20", "Пример: 20 означает 20% от баланса"),
            "base_order_usd": ("Фиксированная сумма (в руб)", "10000", "Пример: 10000 означает 10000 руб на позицию"),
            "stop_loss_pct": ("Stop Loss (в %)", "1.0", "Пример: 1.0 означает 1%"),
            "take_profit_pct": ("Take Profit (в %)", "2.5", "Пример: 2.5 означает 2.5%"),
            "fee_rate": ("Комиссия биржи (per side, в %)", "0.05", "Пример: 0.05 означает 0.05% за вход/выход"),
        }
        
        if setting_name not in descriptions:
            await query.answer("Неизвестная настройка", show_alert=True)
            return
        
        desc, example, hint = descriptions[setting_name]
        current_value = getattr(self.settings.risk, setting_name, 0)
        
        if setting_name.endswith("_pct"):
            current_display = current_value * 100
        elif setting_name == "base_order_usd":
            current_display = current_value
        else:
            current_display = current_value
        
        self.waiting_for_risk_setting[user_id] = setting_name
        
        await query.edit_message_text(
            f"✏️ РЕДАКТИРОВАНИЕ: {desc}\n\n"
            f"Текущее значение: {current_display:.2f}\n"
            f"{hint}\n\n"
            f"Введите новое значение (только число):",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Отмена", callback_data="settings_risk")]
            ])
        )

    async def process_risk_setting_input(self, update: Update, setting_name: str, text: str):
        """Обрабатывает ввод значения настройки риска."""
        try:
            value = float(text.replace(",", "."))
            risk = self.settings.risk
            
            if setting_name == "margin_pct_balance":
                if 1.0 <= value <= 100.0:
                    risk.margin_pct_balance = value / 100.0
                else:
                    await update.message.reply_text("❌ Значение должно быть от 1 до 100%")
                    return
            elif setting_name == "stop_loss_pct":
                if 0.1 <= value <= 10.0:
                    risk.stop_loss_pct = value / 100.0
                else:
                    await update.message.reply_text("❌ Значение должно быть от 0.1 до 10%")
                    return
            elif setting_name == "take_profit_pct":
                if 0.5 <= value <= 20.0:
                    risk.take_profit_pct = value / 100.0
                else:
                    await update.message.reply_text("❌ Значение должно быть от 0.5 до 20%")
                    return
            elif setting_name == "fee_rate":
                if 0.0 <= value <= 5.0:
                    risk.fee_rate = value / 100.0
                else:
                    await update.message.reply_text("❌ Значение должно быть от 0 до 5%")
                    return
            elif setting_name == "base_order_usd":
                if 1.0 <= value <= 1000000.0:
                    risk.base_order_usd = value
                else:
                    await update.message.reply_text("❌ Значение должно быть от 1 до 1000000 руб")
                    return
            
            self.save_risk_settings()
            await update.message.reply_text(
                f"✅ Настройка обновлена: {setting_name} = {value:.2f}",
                reply_markup=self.get_main_keyboard()
            )
        except ValueError:
            await update.message.reply_text("❌ Неверный формат! Введите число")
        except Exception as e:
            logger.error(f"Error processing risk setting input: {e}")
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")

    async def toggle_risk_setting(self, query, setting_name: str):
        """Переключает булеву настройку риска."""
        risk = self.settings.risk
        
        if setting_name == "enable_trailing_stop":
            risk.enable_trailing_stop = not risk.enable_trailing_stop
        elif setting_name == "enable_partial_close":
            risk.enable_partial_close = not risk.enable_partial_close
        elif setting_name == "enable_breakeven":
            risk.enable_breakeven = not risk.enable_breakeven
        elif setting_name == "enable_loss_cooldown":
            risk.enable_loss_cooldown = not risk.enable_loss_cooldown
        else:
            await query.answer("Неизвестная настройка", show_alert=True)
            return
        
        self.save_risk_settings()
        await query.answer("✅ Настройка обновлена!")
        await self.show_risk_settings(query)

    async def reset_risk_defaults(self, query):
        """Сбрасывает настройки риска на стандартные."""
        self.settings.risk = RiskParams()
        self.save_risk_settings()
        await query.answer("✅ Настройки сброшены на стандартные!", show_alert=True)
        await self.show_risk_settings(query)

    def save_risk_settings(self):
        """Сохраняет настройки риска в файл."""
        try:
            config_file = Path("risk_settings.json")
            risk_dict = {
                "margin_pct_balance": self.settings.risk.margin_pct_balance,
                "base_order_usd": self.settings.risk.base_order_usd,
                "stop_loss_pct": self.settings.risk.stop_loss_pct,
                "take_profit_pct": self.settings.risk.take_profit_pct,
                "enable_trailing_stop": self.settings.risk.enable_trailing_stop,
                "enable_partial_close": self.settings.risk.enable_partial_close,
                "enable_breakeven": self.settings.risk.enable_breakeven,
                "enable_loss_cooldown": self.settings.risk.enable_loss_cooldown,
                "fee_rate": self.settings.risk.fee_rate,
            }
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(risk_dict, f, indent=2, ensure_ascii=False)
            logger.info("Risk settings saved to risk_settings.json")
        except Exception as e:
            logger.error(f"Error saving risk settings: {e}")

    async def show_ml_settings(self, query):
        """Показывает настройки ML стратегии."""
        ml_settings = self.settings.ml_strategy
        
        text = "🧠 НАСТРОЙКИ ML СТРАТЕГИИ\n\n"
        text += f"🔄 MTF стратегия (1h + 15m): {'✅ Включена' if ml_settings.use_mtf_strategy else '❌ Выключена'}\n"
        if ml_settings.use_mtf_strategy:
            text += f"   • Порог 1h: {ml_settings.mtf_confidence_threshold_1h*100:.0f}%\n"
            text += f"   • Порог 15m: {ml_settings.mtf_confidence_threshold_15m*100:.0f}%\n"
            text += f"   • Режим: {ml_settings.mtf_alignment_mode}\n\n"
        text += f"🎯 Минимальная уверенность: {ml_settings.confidence_threshold*100:.0f}%\n"
        text += f"💪 Минимальная сила сигнала: {ml_settings.min_signal_strength}\n"
        text += f"🔄 MTF фичи: {'✅ Включены' if ml_settings.mtf_enabled else '❌ Выключены'}\n\n"
        text += f"ℹ️ Уверенность модели — это вероятность правильного предсказания.\n"
        text += f"Чем выше порог, тем меньше сигналов, но качественнее.\n\n"
        text += f"🔹 Рекомендуемые значения:\n"
        text += f"   • Консервативно: 70-80%\n"
        text += f"   • Сбалансированно: 50-70%\n"
        text += f"   • Агрессивно: 30-50%\n"
        
        keyboard = [
            [InlineKeyboardButton(
                f"🔄 MTF стратегия: {'✅ Вкл' if ml_settings.use_mtf_strategy else '❌ Выкл'}", 
                callback_data="toggle_ml_use_mtf_strategy"
            )],
            [InlineKeyboardButton(f"🎯 Уверенность: {ml_settings.confidence_threshold*100:.0f}%", callback_data="edit_ml_confidence_threshold")],
            [InlineKeyboardButton(f"💪 Сила: {ml_settings.min_signal_strength}", callback_data="edit_ml_min_signal_strength")],
            [InlineKeyboardButton(f"🔄 MTF фичи: {'✅' if ml_settings.mtf_enabled else '❌'}", callback_data="toggle_ml_mtf_enabled")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        
        await self.safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def start_edit_ml_setting(self, query, setting_name: str):
        """Начинает редактирование ML настройки."""
        user_id = query.from_user.id
        
        if setting_name == "confidence_threshold":
            current_value = self.settings.ml_strategy.confidence_threshold * 100
            self.waiting_for_ml_setting[user_id] = setting_name
            await query.edit_message_text(
                f"✏️ РЕДАКТИРОВАНИЕ: Минимальная уверенность модели\n\n"
                f"Текущее значение: {current_value:.0f}%\n\n"
                f"Введите новое значение от 1 до 100 (в процентах):",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Отмена", callback_data="settings_ml")]
                ])
            )
        elif setting_name == "min_signal_strength":
            current_value = self.settings.ml_strategy.min_signal_strength
            self.waiting_for_ml_setting[user_id] = setting_name
            await query.edit_message_text(
                f"✏️ РЕДАКТИРОВАНИЕ: Минимальная сила сигнала\n\n"
                f"Текущее значение: {current_value}\n\n"
                f"Введите новое значение:\n"
                f"слабое, умеренное, среднее, сильное, очень_сильное",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Отмена", callback_data="settings_ml")]
                ])
            )
        else:
            await query.answer("Неизвестная настройка", show_alert=True)

    async def process_ml_setting_input(self, update: Update, setting_name: str, text: str):
        """Обрабатывает ввод ML настройки."""
        try:
            ml_settings = self.settings.ml_strategy
            
            if setting_name == "confidence_threshold":
                value = float(text.replace(",", "."))
                if 1.0 <= value <= 100.0:
                    ml_settings.confidence_threshold = value / 100.0
                else:
                    await update.message.reply_text("❌ Значение должно быть от 1 до 100%")
                    return
            elif setting_name == "min_signal_strength":
                normalized = text.strip().lower().replace(" ", "_")
                valid_strengths = ["слабое", "умеренное", "среднее", "сильное", "очень_сильное"]
                if normalized in valid_strengths:
                    ml_settings.min_signal_strength = normalized
                else:
                    await update.message.reply_text("❌ Неверное значение. Используйте: слабое, умеренное, среднее, сильное, очень_сильное")
                    return
            
            self.save_ml_settings()
            await update.message.reply_text(
                f"✅ Настройка обновлена!",
                reply_markup=self.get_main_keyboard()
            )
        except ValueError:
            await update.message.reply_text("❌ Неверный формат")
        except Exception as e:
            logger.error(f"Error processing ML setting input: {e}")
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")

    async def toggle_ml_setting(self, query, setting_name: str):
        """Переключает булеву ML настройку."""
        if setting_name == "mtf_enabled":
            self.settings.ml_strategy.mtf_enabled = not self.settings.ml_strategy.mtf_enabled
            self.save_ml_settings()
            await query.answer("✅ Настройка обновлена!")
            await self.show_ml_settings(query)
        elif setting_name == "use_mtf_strategy":
            old_value = self.settings.ml_strategy.use_mtf_strategy
            self.settings.ml_strategy.use_mtf_strategy = not self.settings.ml_strategy.use_mtf_strategy
            new_value = self.settings.ml_strategy.use_mtf_strategy
            self.save_ml_settings()
            
            # Очищаем стратегии для перезагрузки с новыми настройками
            if hasattr(self, 'trading_loop') and self.trading_loop:
                self.trading_loop.strategies.clear()
                logger.info("Cleared all strategies to reload with new MTF settings")
            
            status = "включена" if new_value else "выключена"
            await query.answer(f"✅ MTF стратегия {status}!")
            await self.show_ml_settings(query)

    def save_ml_settings(self):
        """Сохраняет ML настройки в файл."""
        try:
            config_file = Path("ml_settings.json")
            ml_dict = {
                "confidence_threshold": self.settings.ml_strategy.confidence_threshold,
                "min_signal_strength": self.settings.ml_strategy.min_signal_strength,
                "mtf_enabled": self.settings.ml_strategy.mtf_enabled,
                "use_mtf_strategy": self.settings.ml_strategy.use_mtf_strategy,
                "mtf_confidence_threshold_1h": self.settings.ml_strategy.mtf_confidence_threshold_1h,
                "mtf_confidence_threshold_15m": self.settings.ml_strategy.mtf_confidence_threshold_15m,
                "mtf_alignment_mode": self.settings.ml_strategy.mtf_alignment_mode,
                "mtf_require_alignment": self.settings.ml_strategy.mtf_require_alignment,
            }
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(ml_dict, f, indent=2, ensure_ascii=False)
            logger.info(f"ML settings saved to ml_settings.json: use_mtf_strategy={ml_dict['use_mtf_strategy']}")
        except Exception as e:
            logger.error(f"Error saving ML settings: {e}")

    async def show_strategy_settings(self, query):
        """Показывает настройки стратегии."""
        strategy = self.settings.ml_strategy
        
        text = "🔧 НАСТРОЙКИ СТРАТЕГИИ\n\n"
        text += f"⏱️ Таймфрейм: {self.settings.timeframe}\n"
        text += f"📊 Лимит свечей: {self.settings.kline_limit}\n"
        text += f"🔄 Интервал опроса: {self.settings.live_poll_seconds} сек\n"
        text += f"🛡️ Фильтр стабильности: {'✅ Включен' if strategy.stability_filter else '❌ Выключен'}\n"
        
        keyboard = [
            [InlineKeyboardButton(f"⏱️ Таймфрейм: {self.settings.timeframe}", callback_data="edit_strategy_timeframe")],
            [InlineKeyboardButton(f"📊 Лимит свечей: {self.settings.kline_limit}", callback_data="edit_strategy_kline_limit")],
            [InlineKeyboardButton(f"🔄 Интервал опроса: {self.settings.live_poll_seconds} сек", callback_data="edit_strategy_live_poll_seconds")],
            [InlineKeyboardButton(f"🛡️ Фильтр стабильности: {'✅' if strategy.stability_filter else '❌'}", callback_data="toggle_strategy_stability_filter")],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        
        await self.safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def start_edit_strategy_setting(self, query, setting_name: str):
        """Начинает редактирование настройки стратегии."""
        user_id = query.from_user.id
        self.waiting_for_strategy_setting[user_id] = setting_name
        
        if setting_name == "timeframe":
            current_value = self.settings.timeframe
            await query.edit_message_text(
                f"✏️ РЕДАКТИРОВАНИЕ: Таймфрейм\n\n"
                f"Текущее значение: {current_value}\n\n"
                f"Введите новый таймфрейм:\n"
                f"15min, 1hour, day",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Отмена", callback_data="settings_strategy")]
                ])
            )
        elif setting_name == "kline_limit":
            current_value = self.settings.kline_limit
            await query.edit_message_text(
                f"✏️ РЕДАКТИРОВАНИЕ: Лимит свечей\n\n"
                f"Текущее значение: {current_value}\n\n"
                f"Введите новое значение (от 100 до 10000):",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Отмена", callback_data="settings_strategy")]
                ])
            )
        elif setting_name == "live_poll_seconds":
            current_value = self.settings.live_poll_seconds
            await query.edit_message_text(
                f"✏️ РЕДАКТИРОВАНИЕ: Интервал опроса\n\n"
                f"Текущее значение: {current_value} сек\n\n"
                f"Введите новое значение (от 10 до 600 секунд):",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("❌ Отмена", callback_data="settings_strategy")]
                ])
            )

    async def process_strategy_setting_input(self, update: Update, setting_name: str, text: str):
        """Обрабатывает ввод настройки стратегии."""
        try:
            if setting_name == "timeframe":
                valid_timeframes = ["15min", "1hour", "day"]
                if text.strip() in valid_timeframes:
                    self.settings.timeframe = text.strip()
                else:
                    await update.message.reply_text("❌ Неверный таймфрейм. Используйте: 15min, 1hour, day")
                    return
            elif setting_name == "kline_limit":
                value = int(text)
                if 100 <= value <= 10000:
                    self.settings.kline_limit = value
                else:
                    await update.message.reply_text("❌ Значение должно быть от 100 до 10000")
                    return
            elif setting_name == "live_poll_seconds":
                value = int(text)
                if 10 <= value <= 600:
                    self.settings.live_poll_seconds = value
                else:
                    await update.message.reply_text("❌ Значение должно быть от 10 до 600 секунд")
                    return
            
            self.save_strategy_settings()
            await update.message.reply_text(
                f"✅ Настройка обновлена!",
                reply_markup=self.get_main_keyboard()
            )
        except ValueError:
            await update.message.reply_text("❌ Неверный формат")
        except Exception as e:
            logger.error(f"Error processing strategy setting input: {e}")
            await update.message.reply_text(f"❌ Ошибка: {str(e)}")

    async def toggle_strategy_setting(self, query, setting_name: str):
        """Переключает булеву настройку стратегии."""
        if setting_name == "stability_filter":
            self.settings.ml_strategy.stability_filter = not self.settings.ml_strategy.stability_filter
            self.save_strategy_settings()
            await query.answer("✅ Настройка обновлена!")
            await self.show_strategy_settings(query)

    def save_strategy_settings(self):
        """Сохраняет настройки стратегии в файл."""
        try:
            config_file = Path("strategy_settings.json")
            strategy_dict = {
                "timeframe": self.settings.timeframe,
                "kline_limit": self.settings.kline_limit,
                "live_poll_seconds": self.settings.live_poll_seconds,
                "stability_filter": self.settings.ml_strategy.stability_filter,
            }
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(strategy_dict, f, indent=2, ensure_ascii=False)
            logger.info("Strategy settings saved to strategy_settings.json")
        except Exception as e:
            logger.error(f"Error saving strategy settings: {e}")

    async def show_api_settings(self, query):
        """Показывает настройки API."""
        api = self.settings.api
        
        text = "🌐 НАСТРОЙКИ API (TINKOFF)\n\n"
        text += f"Режим: {'🧪 ПЕСОЧНИЦА' if api.sandbox else '💰 РЕАЛЬНЫЙ РЕЖИМ'}\n"
        text += f"Токен: {'✅ Установлен' if api.token else '❌ Не установлен'}\n\n"
        text += f"⚠️ ВНИМАНИЕ: Переключение режима требует перезапуска бота!\n"
        text += f"После переключения остановите и запустите бота заново.\n"
        
        keyboard = [
            [InlineKeyboardButton(
                f"🌐 Режим: {'🧪 ПЕСОЧНИЦА' if api.sandbox else '💰 РЕАЛЬНЫЙ'}",
                callback_data="toggle_sandbox"
            )],
            [InlineKeyboardButton("🔙 Назад", callback_data="main_menu")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        
        await self.safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def toggle_sandbox_mode(self, query):
        """Переключает режим песочницы."""
        self.settings.api.sandbox = not self.settings.api.sandbox
        
        # Сохраняем в .env файл
        try:
            from pathlib import Path
            import os
            from dotenv import set_key
            
            env_path = Path(".env")
            if env_path.exists():
                set_key(str(env_path), "TINKOFF_SANDBOX", "true" if self.settings.api.sandbox else "false")
            else:
                # Создаем .env файл
                with open(env_path, 'w') as f:
                    f.write(f"TINKOFF_SANDBOX={'true' if self.settings.api.sandbox else 'false'}\n")
            
            # Обновляем переменную окружения
            os.environ["TINKOFF_SANDBOX"] = "true" if self.settings.api.sandbox else "false"
            
            # Пересоздаем клиент с новым режимом
            if self.tinkoff:
                self.tinkoff.sandbox = self.settings.api.sandbox
            
            await query.answer(
                f"✅ Режим изменен на {'ПЕСОЧНИЦУ' if self.settings.api.sandbox else 'РЕАЛЬНЫЙ'}!\n"
                "⚠️ Перезапустите бота для применения изменений.",
                show_alert=True
            )
            await self.show_api_settings(query)
        except Exception as e:
            logger.error(f"Error toggling sandbox mode: {e}")
            await query.answer("❌ Ошибка при переключении режима", show_alert=True)

    async def show_emergency_menu(self, query):
        """Показывает меню экстренных действий."""
        text = "🚨 ЭКСТРЕННЫЕ ДЕЙСТВИЯ\n\n"
        text += "Внимание! Эти действия необратимы.\n"
        text += "Используйте только в случае необходимости.\n"
        
        keyboard = [
            [InlineKeyboardButton("🔄 СИНХРОНИЗИРОВАТЬ ПОЗИЦИИ", callback_data="sync_positions")],
            [InlineKeyboardButton("🛑 СТОП И ЗАКРЫТЬ ВСЕ ПОЗИЦИИ", callback_data="emergency_stop_all")],
            [InlineKeyboardButton("⏸️ ПАУЗА (остановить торговлю)", callback_data="bot_stop")],
            [InlineKeyboardButton("❌ Отмена", callback_data="main_menu")]
        ]
        
        await self.safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def sync_positions(self, query):
        """Синхронизировать позиции с биржей."""
        await query.answer("🔄 Синхронизирую позиции...")
        
        try:
            if hasattr(self, 'trading_loop') and self.trading_loop:
                await self.trading_loop.sync_positions_with_exchange()
                message = "✅ Синхронизация позиций завершена!\n\n"
                message += "Локальное состояние обновлено в соответствии с биржей."
            else:
                message = "⚠️ Trading loop не доступен для синхронизации."
            
            await self.safe_edit_message(query, message, reply_markup=self.get_main_keyboard())
        except Exception as e:
            logger.error(f"Error syncing positions: {e}")
            await self.safe_edit_message(
                query,
                f"❌ Ошибка при синхронизации позиций:\n{str(e)}",
                reply_markup=self.get_main_keyboard()
            )
    
    async def emergency_stop_all(self, query):
        """Экстренная остановка с закрытием всех позиций."""
        await query.answer("⚠️ Выполняю экстренную остановку...", show_alert=True)
        
        try:
            self.state.set_running(False)
            
            closed_positions = []
            if self.tinkoff:
                for ticker in self.state.active_instruments:
                    try:
                        instrument_info = self.storage.get_instrument_by_ticker(ticker)
                        if not instrument_info:
                            continue
                        figi = instrument_info["figi"]
                        
                        # Получаем позицию (с таймаутом 30 секунд)
                        try:
                            pos_info = await asyncio.wait_for(
                                asyncio.to_thread(self.tinkoff.get_position_info, figi=figi),
                                timeout=30.0
                            )
                        except asyncio.TimeoutError:
                            logger.error(f"Timeout getting position info for {ticker} (30s exceeded)")
                            pos_info = None
                        except Exception as e:
                            logger.error(f"Error getting position info for {ticker}: {e}")
                            pos_info = None
                        
                        if pos_info and pos_info.get("retCode") == 0:
                            list_data = pos_info.get("result", {}).get("list", [])
                            for p in list_data:
                                quantity = safe_float(p.get("quantity"), 0)
                                if quantity > 0:
                                    # Закрываем позицию (продаем все)
                                    resp = await asyncio.to_thread(
                                        self.tinkoff.place_order,
                                        figi=figi,
                                        quantity=int(quantity),
                                        direction="Sell",
                                        order_type="Market"
                                    )
                                    if resp.get("retCode") == 0:
                                        closed_positions.append(ticker)
                    except Exception as e:
                        logger.error(f"Error closing position for {ticker}: {e}")
            
            message = "🚨 ЭКСТРЕННАЯ ОСТАНОВКА ВЫПОЛНЕНА\n\n"
            message += f"Бот остановлен: ✅\n"
            message += f"Закрыто позиций: {len(closed_positions)}\n"
            if closed_positions:
                message += f"Инструменты: {', '.join(closed_positions)}"
            
            await self.safe_edit_message(query, message, reply_markup=self.get_main_keyboard())
        except Exception as e:
            logger.error(f"Error in emergency stop: {e}")
            await self.safe_edit_message(
                query,
                f"❌ Ошибка при экстренной остановке:\n{str(e)}",
                reply_markup=self.get_main_keyboard()
            )

    async def show_dashboard(self, query):
        """Показывает dashboard с ключевыми метриками."""
        text = "📊 DASHBOARD\n\n"
        text += f"🕐 Обновлено: {datetime.now().strftime('%H:%M:%S')}\n\n"
        
        # Баланс
        wallet_balance = 0.0
        available_balance = 0.0  # Initialize - will be set from API
        if self.tinkoff:
            try:
                # Добавляем таймаут для получения баланса (30 секунд)
                balance_info = await asyncio.wait_for(
                    asyncio.to_thread(self.tinkoff.get_wallet_balance),
                    timeout=30.0
                )
                if balance_info.get("retCode") == 0:
                    result = balance_info.get("result", {})
                    list_data = result.get("list", [])
                    if list_data:
                        wallet = list_data[0].get("coin", [])
                        rub_coin = next((c for c in wallet if c.get("coin") == "RUB"), None)
                        if rub_coin:
                            wallet_balance = safe_float(rub_coin.get("walletBalance"), 0)
                            # Use availableBalance from API directly - exchange knows best
                            available_balance = safe_float(rub_coin.get("availableBalance"), wallet_balance)
            except asyncio.TimeoutError:
                logger.error("Timeout getting balance in dashboard (30s exceeded)")
            except Exception as e:
                logger.error(f"Error getting balance: {e}")
        
        # Открытые позиции
        open_count = 0
        total_pnl = 0
        total_margin = 0.0
        if self.tinkoff:
            try:
                # Получаем общую замороженную маржу из API (из валютной позиции)
                try:
                    all_pos_info = await asyncio.wait_for(
                        asyncio.to_thread(self.tinkoff.get_position_info),
                        timeout=30.0
                    )
                    if all_pos_info and all_pos_info.get("retCode") == 0:
                        result = all_pos_info.get("result", {})
                        total_blocked_margin_from_api = result.get("total_blocked_margin", 0.0)
                        if total_blocked_margin_from_api > 0:
                            logger.debug(f"Got total blocked margin from API in dashboard: {total_blocked_margin_from_api:.2f} руб")
                except Exception as e:
                    logger.debug(f"Error getting total blocked margin in dashboard: {e}")
                
                for ticker in self.state.active_instruments:
                    instrument_info = self.storage.get_instrument_by_ticker(ticker)
                    if not instrument_info:
                        continue
                    figi = instrument_info["figi"]
                    
                    # Получаем позицию (с таймаутом 30 секунд)
                    try:
                        pos_info = await asyncio.wait_for(
                            asyncio.to_thread(self.tinkoff.get_position_info, figi=figi),
                            timeout=30.0
                        )
                    except asyncio.TimeoutError:
                        logger.error(f"Timeout getting position info for {ticker} (30s exceeded)")
                        pos_info = None
                    except Exception as e:
                        logger.error(f"Error getting position info for {ticker}: {e}")
                        pos_info = None
                    
                    if pos_info and pos_info.get("retCode") == 0:
                        list_data = pos_info.get("result", {}).get("list", [])
                        for p in list_data:
                            quantity = safe_float(p.get("quantity"), 0)
                            if quantity > 0:
                                open_count += 1
                                entry_price = safe_float(p.get("average_price"), 0)
                                current_price = safe_float(p.get("current_price"), 0)
                                
                                # Get lot size for accurate calculations
                                lot_size = 1.0
                                try:
                                    lot_size = await asyncio.wait_for(
                                        asyncio.to_thread(self.tinkoff.get_qty_step, figi),
                                        timeout=10.0
                                    )
                                    if lot_size <= 0:
                                        lot_size = 1.0
                                except Exception as e:
                                    logger.debug(f"Error getting lot size for {ticker} in dashboard: {e}, using default 1.0")
                                    lot_size = 1.0
                                
                                # PnL с учетом размера лота
                                pnl_rub = (current_price - entry_price) * quantity * lot_size
                                total_pnl += pnl_rub
                                
                                # Маржа: используем реальное гарантийное обеспечение из API, если доступно
                                margin = None
                                if "current_margin" in p:
                                    margin = safe_float(p.get("current_margin"), 0)
                                elif "initial_margin" in p:
                                    margin = safe_float(p.get("initial_margin"), 0)
                                elif "blocked" in p:
                                    margin = safe_float(p.get("blocked"), 0)
                                
                                # Fallback: используем справочник реальных коэффициентов маржи
                                if margin is None or margin == 0:
                                    from bot.margin_rates import get_margin_for_position
                                    margin = get_margin_for_position(
                                        ticker=ticker,
                                        quantity=quantity,
                                        entry_price=entry_price,
                                        lot_size=lot_size
                                    )
                                
                                total_margin += margin
            except Exception as e:
                logger.error(f"Error getting positions: {e}")
        
        # Доступный баланс - используем total_blocked_margin из API (из валютной позиции)
        # Это самый точный способ получить реальную замороженную маржу
        if total_blocked_margin_from_api > 0:
            # Используем замороженную маржу из API
            available_balance = wallet_balance - total_blocked_margin_from_api
            if available_balance < 0:
                available_balance = 0.0
            logger.debug(
                f"[show_dashboard] Using API blocked margin: "
                f"wallet={wallet_balance:.2f}, blocked={total_blocked_margin_from_api:.2f}, "
                f"available={available_balance:.2f}"
            )
        elif open_count > 0 and total_margin > 0:
            # Fallback: используем расчетную маржу из позиций
            calculated_available = wallet_balance - total_margin
            if calculated_available < 0:
                calculated_available = 0.0
            available_balance = calculated_available
            logger.debug(
                f"[show_dashboard] Using calculated margin: "
                f"wallet={wallet_balance:.2f}, margin={total_margin:.2f}, "
                f"available={available_balance:.2f}"
            )
        elif available_balance == 0.0 and wallet_balance > 0:
            # Если нет позиций, используем баланс как доступный
            available_balance = wallet_balance
        
        if wallet_balance > 0:
            stats = self.state.get_stats()
            total_pnl_pct = (stats['total_pnl'] / wallet_balance * 100) if wallet_balance > 0 else 0
            
            # Информация о распределении депозита
            text += f"💰 БАЛАНС:\n"
            text += f"Всего: {wallet_balance:.2f} руб\n"
            text += f"Доступно: {available_balance:.2f} руб\n"
            if total_margin > 0:
                margin_pct = (total_margin / wallet_balance * 100) if wallet_balance > 0 else 0
                text += f"В позициях (маржа): {total_margin:.2f} руб ({margin_pct:.1f}%)\n"
            text += "\n"
            
            text += "💰 БАЛАНС\n"
            text += f"Текущий: {wallet_balance:.2f} руб ({total_pnl_pct:+.2f}%)\n"
            text += f"Доступно: {available_balance:.2f} руб\n"
            text += f"В позициях: {total_margin:.2f} руб\n\n"
        
        text += f"📈 ОТКРЫТЫЕ ПОЗИЦИИ ({open_count})\n"
        if open_count > 0:
            text += f"Текущий PnL: {total_pnl:+.2f} руб\n\n"
        else:
            text += "(нет открытых позиций)\n\n"
        
        # Статистика за сегодня
        today = datetime.now().date()
        all_trades = self.state.trades if hasattr(self.state, 'trades') else []
        today_trades = [t for t in all_trades 
                       if t.status == "closed" and t.exit_time and
                       datetime.fromisoformat(t.exit_time).date() == today]
        
        if today_trades:
            today_pnl = sum(t.pnl_usd for t in today_trades)
            today_wins = len([t for t in today_trades if t.pnl_usd > 0])
            
            text += "📊 СЕГОДНЯ\n"
            text += f"Сделок: {len(today_trades)} ({today_wins} прибыльных)\n"
            text += f"PnL: {today_pnl:+.2f} руб\n"
            
            if today_trades:
                best_trade = max(today_trades, key=lambda t: t.pnl_usd)
                text += f"Лучшая: {best_trade.instrument} {best_trade.pnl_usd:+.2f} руб\n\n"
        else:
            text += "📊 СЕГОДНЯ\n(нет завершенных сделок)\n\n"
        
        # Статус системы
        text += "⚡ СИСТЕМА\n"
        text += f"Статус: {'🟢 Работает' if self.state.is_running else '🔴 Остановлен'}\n"
        text += f"Режим: {'🧪 Песочница' if self.settings.api.sandbox else '💰 Реальный'}\n"
        text += f"Активных инструментов: {len(self.state.active_instruments)}\n"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Обновить", callback_data="dashboard")],
            [InlineKeyboardButton("📊 Подробная статистика", callback_data="stats")],
            [InlineKeyboardButton("🏠 Главное меню", callback_data="main_menu")]
        ]
        
        await self.safe_edit_message(query, text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def send_message(self, text: str):
        """Send message to authorized user."""
        if not self.settings.allowed_user_id:
            return
        
        try:
            if self.app:
                await self.app.bot.send_message(
                    chat_id=self.settings.allowed_user_id,
                    text=text
                )
        except Exception as e:
            logger.error(f"Error sending message: {e}")
    
    async def send_notification(self, text: str, user_id: Optional[int] = None):
        """Send notification to user."""
        target_user_id = user_id or self.settings.allowed_user_id
        if not target_user_id:
            return
        
        try:
            if self.app:
                await self.app.bot.send_message(
                    chat_id=target_user_id,
                    text=text
                )
        except Exception as e:
            logger.error(f"Error sending notification: {e}")
    
    async def test_all_models_async(self, ticker: str, user_id: int):
        """Тестирует все модели для инструмента"""
        try:
            models = self.model_manager.find_models_for_instrument(ticker)
            if not models:
                await self.send_notification(f"❌ Для {ticker} не найдено моделей для тестирования.", user_id)
                return
            
            await self.send_notification(f"🧪 Начато тестирование {len(models)} моделей для {ticker}...", user_id)
            
            tested = 0
            for model_path in models:
                model_name = model_path.stem
                await self.send_notification(f"🧪 Тестирую {model_name}...", user_id)
                
                try:
                    results = self.model_manager.test_model(model_path, ticker, days=14)
                    
                    if results:
                        self.model_manager.save_model_test_result(ticker, str(model_path), results)
                        tested += 1
                        await self.send_notification(
                            f"✅ {model_name}:\n"
                            f"PnL: {results['total_pnl_pct']:+.2f}% | "
                            f"WR: {results['win_rate']:.1f}% | "
                            f"Сделок: {results['total_trades']} ({results['trades_per_day']:.1f}/день)",
                            user_id
                        )
                    else:
                        await self.send_notification(f"❌ Ошибка при тестировании {model_name}\n(проверьте логи для деталей)", user_id)
                except Exception as e:
                    logger.error(f"Error testing {model_name}: {e}", exc_info=True)
                    await self.send_notification(f"❌ Ошибка при тестировании {model_name}:\n{str(e)[:200]}", user_id)
            
            await self.send_notification(
                f"✅ Тестирование завершено!\n"
                f"Протестировано: {tested}/{len(models)} моделей",
                user_id
            )
            
        except Exception as e:
            logger.error(f"Error testing models for {ticker}: {e}")
            await self.send_notification(f"❌ Ошибка при тестировании моделей: {str(e)}", user_id)
    
    async def retrain_models_async(self, ticker: str, user_id: int):
        """Обучает все модели для конкретного инструмента"""
        import subprocess
        from pathlib import Path
        
        logger.info(f"[retrain_models_async] Starting training for {ticker}, user_id={user_id}")
        
        try:
            await self.send_notification(
                f"🎓 Начато обучение всех моделей для {ticker}...\n"
                "Это может занять 10-30 минут.\n"
                "Вы будете получать уведомления о прогрессе.",
                user_id
            )
            
            # Путь к скрипту обучения
            script_path = Path("train_models.py")
            
            if not script_path.exists():
                error_msg = f"❌ Скрипт обучения не найден: {script_path}"
                logger.error(f"[retrain_models_async] {error_msg}")
                await self.send_notification(error_msg, user_id)
                return
            
            # Определяем параметры MTF из настроек
            use_mtf = getattr(self.settings.ml_strategy, 'mtf_enabled', False)
            cmd_args = [sys.executable, str(script_path), "--ticker", ticker]
            
            # Добавляем параметры MTF
            if use_mtf:
                cmd_args.append("--mtf")
            else:
                cmd_args.append("--no-mtf")
            
            logger.info(f"[retrain_models_async] Running command: {' '.join(cmd_args)}")
            
            # Запускаем обучение в отдельном процессе
            process = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(script_path.parent)
            )
            
            logger.info(f"[retrain_models_async] Training process started for {ticker}, PID={process.pid}")
            
            # Отслеживаем вывод
            trained_models = []
            current_model = None
            
            while True:
                line = await process.stdout.readline()
                if not line:
                    break
                
                line_text = line.decode('utf-8', errors='ignore').strip()
                
                # Парсим вывод для уведомлений
                if "Обучение:" in line_text and ticker in line_text:
                    parts = line_text.split("Обучение:")
                    if len(parts) > 1:
                        model_name = parts[1].strip().split()[0] if parts[1].strip() else None
                        if model_name:
                            current_model = model_name
                            await self.send_notification(f"🔄 Обучение модели: {model_name} для {ticker}...", user_id)
                
                if "✅" in line_text and current_model:
                    trained_models.append(current_model)
                    await self.send_notification(f"✅ {current_model} обучена для {ticker}", user_id)
                    current_model = None
                
                if "❌" in line_text and current_model:
                    await self.send_notification(f"❌ Ошибка при обучении {current_model} для {ticker}", user_id)
                    current_model = None
            
            # Ждем завершения процесса
            await process.wait()
            
            if process.returncode == 0:
                await self.send_notification(
                    f"✅ Обучение всех моделей для {ticker} завершено!\n"
                    f"Обучено моделей: {len(trained_models)}\n\n"
                    "Обновите список моделей для просмотра результатов.",
                    user_id
                )
            else:
                # Читаем ошибки
                stderr = await process.stderr.read()
                error_msg = stderr.decode('utf-8', errors='ignore')[:500]
                await self.send_notification(
                    f"❌ Ошибка при обучении моделей для {ticker}:\n{error_msg}",
                    user_id
                )
                
        except Exception as e:
            logger.error(f"[retrain_models_async] Error retraining models for {ticker}: {e}", exc_info=True)
            try:
                await self.send_notification(f"❌ Ошибка при обучении моделей для {ticker}: {str(e)}", user_id)
            except Exception as send_error:
                logger.error(f"[retrain_models_async] Error sending Telegram message: {send_error}")
