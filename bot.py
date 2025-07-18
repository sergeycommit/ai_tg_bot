import logging
import os
import traceback
from datetime import datetime, timedelta
import asyncio
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton, LabeledPrice
from aiogram.enums import ChatMemberStatus
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import text, Column, Integer, String, Boolean, DateTime, ForeignKey, Text, select
from openai import AsyncOpenAI
import asyncpg
from config import (
    BOT_TOKEN, OR_API_KEY, CHANNEL, CHANNEL_URL, DATABASE_URL, 
    FREE_REQUESTS_PER_DAY, ADMIN_USER_ID, HF_API_KEY, MODEL, DB_PASSWORD,
    DEFAULT_NOTIFICATION_MESSAGE
)
from typing import Optional
from migrations import migrate_database
from models import *

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Validate required configuration
if not BOT_TOKEN:
    logger.error("BOT_TOKEN is not set in environment variables")
    exit(1)
if not OR_API_KEY:
    logger.error("OR_API_KEY is not set in environment variables")
    exit(1)
if not MODEL:
    logger.error("MODEL is not set in environment variables")
    exit(1)
if not DATABASE_URL:
    logger.error("DATABASE_URL could not be constructed - check database settings")
    exit(1)

# Initialize bot and dispatcher
bot = Bot(token=BOT_TOKEN)
router = Dispatcher()

# Initialize OpenAI client
openai_client = AsyncOpenAI(api_key=OR_API_KEY, base_url="https://openrouter.ai/api/v1")

# Premium subscription settings
PREMIUM_PLANS = {
    "month": {
        "title": "Premium for 1 Month",
        "price": 100,  # Stars
        "duration_days": 30,
        "description": "✨ Premium subscription for 1 month\n"
                      "✅ Unlimited requests\n"
                      "✅ Priority support\n"
                      "✅ Early access to new features"
    },
    "quarter": {
        "title": "Premium for 3 Months",
        "price": 250,  # Stars
        "duration_days": 90,
        "description": "✨ Premium subscription for 3 months\n"
                      "✅ Unlimited requests\n"
                      "✅ Priority support\n"
                      "✅ Early access to new features\n"
                      "🎁 17% discount from monthly plan"
    },
    "year": {
        "title": "Premium for 1 Year",
        "price": 800,  # Stars
        "duration_days": 365,
        "description": "✨ Premium subscription for 12 months\n"
                      "✅ Unlimited requests\n"
                      "✅ Priority support\n"
                      "✅ Early access to new features\n"
                      "🎁 33% discount from monthly plan"
    }
}

# Database setup
engine = create_async_engine(DATABASE_URL)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def create_database_if_not_exists():
    """Initialize database with migrations"""
    max_retries = 5
    retry_delay = 5  # seconds
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Attempting to connect to database (attempt {attempt + 1}/{max_retries})")
            # Mask password in logs
            safe_url = DATABASE_URL
            if DB_PASSWORD and DB_PASSWORD.strip():
                safe_url = DATABASE_URL.replace(DB_PASSWORD, '***')
            logger.info(f"Database URL: {safe_url}")
            
            async with async_session() as session:
                # Test connection
                await session.execute(text("SELECT 1"))
                logger.info("Database connection successful")
                
                # Create tables
                await session.execute(text("""
                    CREATE TABLE IF NOT EXISTS users (
                        id SERIAL PRIMARY KEY,
                        user_id BIGINT UNIQUE NOT NULL,
                        username VARCHAR,
                        first_name VARCHAR,
                        last_name VARCHAR,
                        is_premium BOOLEAN DEFAULT FALSE,
                        premium_until TIMESTAMP,
                        requests_today INTEGER DEFAULT 0,
                        last_request_date DATE
                    )
                """))
                
                await session.execute(text("""
                    CREATE TABLE IF NOT EXISTS chat_messages (
                        id SERIAL PRIMARY KEY,
                        user_id INTEGER REFERENCES users(id),
                        role VARCHAR,
                        content TEXT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                
                await session.commit()
                logger.info("Database tables created successfully")
                
                # Apply migrations
                success = await migrate_database(session)
                if success:
                    logger.info("Database migrations applied successfully")
                else:
                    logger.error("Failed to apply database migrations")
                    return False
                    
                return True
                
        except Exception as e:
            logger.error(f"Database connection attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                logger.error("All database connection attempts failed")
                return False
    
    return False

async def get_chat_history(user_id: int, limit: int = 5) -> list:
    """
    Get recent chat history for a user (last 5 messages)
    """
    try:
        async with async_session() as session:
            # Get user
            stmt = select(User).where(User.user_id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            
            if not user:
                return []
            
            # Get recent messages ordered by timestamp
            stmt = select(ChatMessage)\
                .where(ChatMessage.user_id == user.id)\
                .order_by(ChatMessage.timestamp.desc())\
                .limit(limit)
            result = await session.execute(stmt)
            messages = result.scalars().all()
            
            # Convert to OpenAI message format and reverse order
            return [
                {"role": msg.role, "content": msg.content}
                for msg in reversed(messages)
            ]
    except Exception as e:
        logger.error(f"Error getting chat history for user {user_id}: {e}")
        return []

async def save_message(user_id: int, role: str, content: str):
    """
    Save a message to chat history
    """
    try:
        async with async_session() as session:
            # Get user by telegram user_id, not database id
            stmt = select(User).where(User.user_id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            
            if not user:
                logger.warning(f"User {user_id} not found when trying to save message")
                return
            
            message = ChatMessage(
                user_id=user.id,
                role=role,
                content=content
            )
            session.add(message)
            await session.commit()
    except Exception as e:
        logger.error(f"Error saving message for user {user_id}: {e}")

async def get_chatgpt_response(message: str, chat_history: list) -> str:
    """
    Get response from ChatGPT API with chat history
    """
    try:
        if not MODEL:
            logger.error("MODEL is not defined in environment variables")
            return "Sorry, the AI model is not configured. Please contact the administrator."

        # Prepare messages with history
        messages = [
            {"role": "system", "content": "You are a helpful AI assistant."},
            *chat_history,
            {"role": "user", "content": message}
        ]
        
        response = await openai_client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.7,
            max_tokens=1000
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"Error getting ChatGPT response: {str(e)}")
        return "Sorry, I'm having trouble connecting to ChatGPT right now. Please try again later."

async def check_subscription(user_id: int) -> bool:
    """
    Check if user is subscribed to the channel
    """
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL, user_id=user_id)
        return member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
    except Exception as e:
        logger.error(f"Error checking subscription: {str(e)}")
        return False

async def send_subscription_message(message: Message):
    """
    Send subscription request message
    """
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(
        text="📢 Subscribe to Channel",
        url=CHANNEL_URL
    ))
    builder.add(InlineKeyboardButton(
        text="🔄 Check Subscription",
        callback_data="check_subscription"
    ))
    
    await message.answer(
        "⚠️ To use the bot, you need to subscribe to our channel first!\n"
        "After subscribing, click the 'Check Subscription' button.",
        reply_markup=builder.as_markup()
    )

@router.callback_query(lambda c: c.data == "check_subscription")
async def process_subscription_check(callback_query: types.CallbackQuery):
    """
    Handle subscription check button click
    """
    if await check_subscription(callback_query.from_user.id):
        await callback_query.message.delete()
        await callback_query.answer("Thank you for subscribing! You can now use the bot.", show_alert=True)
    else:
        await callback_query.answer("You are not subscribed to the channel yet!", show_alert=True)

async def get_user(session: AsyncSession, user_id: int) -> Optional[User]:
    """Get user from database"""
    result = await session.execute(select(User).where(User.user_id == user_id))
    return result.scalar_one_or_none()

@router.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command"""
    try:
        if not message.from_user:
            logger.error("Received /start command with no user information")
            await message.answer("An error occurred. Please try again later.")
            return
            
        logger.info(f"Start command received from user {message.from_user.id}")
        
        # Get or create user
        async with async_session() as session:
            logger.info(f"Checking if user {message.from_user.id} exists in database")
            user = await get_user(session, message.from_user.id)
            
            if not user:
                logger.info(f"Creating new user {message.from_user.id}")
                new_user = User(
                    user_id=message.from_user.id,
                    username=message.from_user.username or None,
                    first_name=message.from_user.first_name or None,
                    last_name=message.from_user.last_name or None,
                    is_premium=False,
                    requests_today=0,
                    last_request_date=datetime.utcnow().date()
                )
                session.add(new_user)
                await session.commit()
                logger.info(f"Created new user: {new_user.user_id}")
            else:
                logger.info(f"User {message.from_user.id} already exists in database")

        # Send welcome message
        logger.info(f"Sending welcome message to user {message.from_user.id}")
        user_name = message.from_user.first_name or message.from_user.username or "User"
        await message.answer(
            f"👋 Hello, {user_name}!\n\n"
            "I'm an AI bot that can:\n"
            "• Answer your questions\n"
            "• Process voice messages\n"
            "• Help with various tasks\n\n"
            "Just send me message!\n"
            "Use /premium to get unlimited access!"
        )
        logger.info(f"Welcome message sent successfully to user {message.from_user.id}")
        
    except Exception as e:
        logger.error(f"Error in start command for user {message.from_user.id}: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        await message.answer("An error occurred. Please try again later.")

@router.callback_query(lambda c: c.data == "show_premium_plans")
async def show_premium_plans(callback: types.CallbackQuery):
    """Show premium plans when Get Premium button is clicked"""
    try:
        text = "🌟 <b>Premium Subscription</b>\n\n"
        text += "Choose the plan that suits you best:\n\n"
        
        for plan_id, plan in PREMIUM_PLANS.items():
            text += f"<b>{plan['title']}</b>\n"
            text += f"💰 Price: {plan['price']} Stars\n"
            text += f"{plan['description']}\n\n"
        
        text += "Click the button below to select a plan and proceed with payment."
        
        builder = InlineKeyboardBuilder()
        for plan_id, plan in PREMIUM_PLANS.items():
            builder.button(text=f"Buy {plan['title']}", callback_data=f"buy_premium:{plan_id}")
        builder.adjust(1)
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in show_premium_plans: {e}")
        await callback.message.answer("An error occurred. Please try again later.")
        await callback.answer()

@router.message(Command("clear"))
async def cmd_clear(message: Message):
    """
    Clear chat history for the user
    """
    try:
        user_id = message.from_user.id
        async with async_session() as session:
            stmt = select(User).where(User.user_id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            
            if user:
                # Delete all messages for the user using SQL
                await session.execute(text("DELETE FROM chat_messages WHERE user_id = :user_id"), {"user_id": user.id})
                await session.commit()
        
        await message.answer("Chat history has been cleared!")
    except Exception as e:
        logger.error(f"Error clearing chat history: {e}")
        await message.answer("An error occurred while clearing chat history. Please try again later.")

@router.message(Command("premium"))
async def cmd_premium(message: Message):
    """Handle premium subscription command"""
    try:
        text = "🌟 <b>Premium Subscription</b>\n\n"
        text += "Choose the plan that suits you best:\n\n"
        
        for plan_id, plan in PREMIUM_PLANS.items():
            text += f"<b>{plan['title']}</b>\n"
            text += f"💰 Price: {plan['price']} Stars\n"
            text += f"{plan['description']}\n\n"
        
        text += "Click the button below to select a plan and proceed with payment."
        
        builder = InlineKeyboardBuilder()
        for plan_id, plan in PREMIUM_PLANS.items():
            builder.button(text=f"Buy {plan['title']}", callback_data=f"buy_premium:{plan_id}")
        builder.adjust(1)
        
        await message.answer(text, reply_markup=builder.as_markup())
    except Exception as e:
        logger.error(f"Error in cmd_premium: {e}")
        await message.answer("An error occurred. Please try again later.")

@router.callback_query(lambda c: c.data.startswith("buy_premium:"))
async def process_buy_premium(callback: types.CallbackQuery):
    """Handle premium subscription purchase"""
    try:
        plan_id = callback.data.split(":")[1]
        plan = PREMIUM_PLANS[plan_id]
        
        await bot.send_invoice(
            chat_id=callback.message.chat.id,
            title=plan["title"],
            description=plan["description"],
            payload=f"premium_subscription:{plan_id}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=plan["title"], amount=plan["price"])],
            start_parameter="premium_subscription",
            need_name=False,
            need_phone_number=False,
            need_email=False,
            need_shipping_address=False,
            is_flexible=False
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"Error in process_buy_premium: {e}")
        await callback.message.answer("❌ An error occurred while creating the invoice. Please try again later.")
        await callback.answer()

@router.pre_checkout_query()
async def process_pre_checkout_query(pre_checkout_query: types.PreCheckoutQuery):
    """Handle pre-checkout query"""
    try:
        await pre_checkout_query.answer(ok=True)
    except Exception as e:
        logger.error(f"Error in process_pre_checkout_query: {e}")
        await pre_checkout_query.answer(ok=False, error_message="An error occurred. Please try again later.")

@router.message(lambda message: message.successful_payment)
async def process_successful_payment(message: Message):
    """Handle successful payment"""
    try:
        plan_id = message.successful_payment.invoice_payload.split(":")[1]
        plan = PREMIUM_PLANS[plan_id]
        
        # Update user's premium status
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if user:
                user.is_premium = True
                user.premium_until = datetime.utcnow() + timedelta(days=plan["duration_days"])
                await session.commit()
                
                await message.answer(
                    f"✅ Thank you for purchasing Premium!\n\n"
                    f"Your premium subscription is active until: {user.premium_until.strftime('%d.%m.%Y')}\n\n"
                    f"You now have access to:\n"
                    f"• Unlimited requests\n"
                    f"• Priority support\n"
                    f"• Early access to new features"
                )
            else:
                await message.answer("❌ An error occurred while activating your premium subscription. Please contact support.")
    except Exception as e:
        logger.error(f"Error in process_successful_payment: {e}")
        await message.answer("❌ An error occurred while activating your premium subscription. Please contact support.")

async def check_user_limits(user_id: int) -> bool:
    try:
        # Check if user is admin
        if user_id == ADMIN_USER_ID:
            return True
            
        async with async_session() as session:
            stmt = select(User).where(User.user_id == user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            
            if not user:
                logger.warning(f"User {user_id} not found when checking limits")
                return False
            
            # Reset daily counter if it's a new day
            current_date = datetime.utcnow().date()
            
            # Handle both datetime and date types for last_request_date
            last_date = user.last_request_date
            if isinstance(last_date, datetime):
                last_date = last_date.date()
            
            if last_date is None or last_date < current_date:
                user.requests_today = 0
                user.last_request_date = current_date
                await session.commit()
            
            # Check if user has premium and it's still valid
            if user.is_premium and user.premium_until and user.premium_until > datetime.utcnow():
                return True
            elif user.is_premium and (not user.premium_until or user.premium_until <= datetime.utcnow()):
                # Premium expired, reset status
                user.is_premium = False
                user.premium_until = None
                await session.commit()
            
            if user.requests_today >= FREE_REQUESTS_PER_DAY:
                logger.info(f"User {user_id} reached daily limit: {user.requests_today}/{FREE_REQUESTS_PER_DAY}")
                return False
            
            user.requests_today += 1
            user.last_request_date = current_date
            await session.commit()
            logger.info(f"User {user_id} request count updated: {user.requests_today}/{FREE_REQUESTS_PER_DAY}")
            return True
    except Exception as e:
        logger.error(f"Error checking user limits for user {user_id}: {e}")
        return False

async def whisper_stt(audio_file_path: str) -> str:
    logger.info("Request to whisper_stt")
    try:
        API_URL = "https://api-inference.huggingface.co/models/openai/whisper-large-v3-turbo"
        headers = {"Authorization": f"Bearer {HF_API_KEY}"}
        
        # Read the audio file in binary mode
        with open(audio_file_path, 'rb') as f:
            audio_data = f.read()
            
        response = requests.post(API_URL, headers=headers, data=audio_data)
        
        # Log the response status and content for debugging
        logger.info(f"Whisper API Response Status: {response.status_code}")
        logger.info(f"Whisper API Response Content: {response.text[:200]}...")  # Log first 200 chars
        
        if response.status_code != 200:
            logger.error(f"Whisper API Error: {response.text}")
            return ""
            
        try:
            result = response.json()
            if "text" in result:
                return result["text"]
            else:
                logger.error(f"Unexpected API response format: {result}")
                return ""
        except ValueError as e:
            logger.error(f"Failed to parse API response as JSON: {e}")
            logger.error(f"Raw response: {response.text}")
            return ""
            
    except Exception as e:
        logger.error(f"Error querying whisper_stt: {str(e)}")
        return ""

@router.message(Command("help"))
async def cmd_help(message: Message):
    """Handle /help command"""
    help_text = (
        "🤖 <b>AI Assistant Bot</b>\n\n"
        "I'm an AI-powered bot that can help you with various tasks:\n"
        "• Answer your questions\n"
        "• Process voice messages\n"
        "• Help with text analysis\n"
        "• And much more!\n\n"
        "<b>Available Commands:</b>\n"
        "• /start - Start the bot\n"
        "• /help - Show this help message\n"
        "• /status - Show your current status and limits\n"
        "• /reset_my_limit - Reset your daily limit\n"
        "• /premium - Get premium subscription\n"
        "• /clear - Clear chat history\n"
        "• /migrate - Apply database migrations (admin only)\n"
        "• /reset_limits - Reset daily limits for all users (admin only)\n\n"
        "<b>Free Usage:</b>\n"
        "• 300 free requests per day\n"
        "• Basic AI features\n\n"
        "<b>Premium Features:</b>\n"
        "• Unlimited requests\n"
        "• Priority support\n"
        "• Early access to new features\n\n"
        "📧 <b>Support:</b>\n"
        "If you have any questions or need help, contact us at:\n"
        "tdallstr@gmail.com"
    )
    
    await message.answer(help_text, parse_mode="HTML")

@router.message(Command("status"))
async def cmd_status(message: Message):
    """Show user status and limits"""
    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                await message.answer("❌ User not found in database.")
                return
            
            status_text = f"📊 <b>Your Status</b>\n\n"
            status_text += f"👤 User ID: {user.user_id}\n"
            status_text += f"📅 Last request date: {user.last_request_date}\n"
            status_text += f"📝 Requests today: {user.requests_today}\n"
            status_text += f"🎯 Daily limit: {FREE_REQUESTS_PER_DAY}\n"
            status_text += f"💎 Premium: {'Yes' if user.is_premium else 'No'}\n"
            
            if user.is_premium and user.premium_until:
                status_text += f"⏰ Premium until: {user.premium_until.strftime('%d.%m.%Y %H:%M')}\n"
            
            current_date = datetime.utcnow().date()
            status_text += f"🗓️ Current date: {current_date}\n"
            
            await message.answer(status_text, parse_mode="HTML")
            
    except Exception as e:
        logger.error(f"Error in status command: {e}")
        await message.answer("❌ An error occurred while getting status.")

@router.message(Command("reset_my_limit"))
async def cmd_reset_my_limit(message: Message):
    """Reset daily limit for current user"""
    try:
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                await message.answer("❌ User not found in database.")
                return
            
            user.requests_today = 0
            user.last_request_date = datetime.utcnow().date()
            await session.commit()
            
            await message.answer("✅ Your daily limit has been reset!")
            logger.info(f"Daily limit reset for user {message.from_user.id}")
            
    except Exception as e:
        logger.error(f"Error in reset_my_limit command: {e}")
        await message.answer("❌ An error occurred while resetting your limit.")

@router.message(Command("reset_limits"))
async def cmd_reset_limits(message: Message):
    """Reset daily limits for all users (admin only)"""
    # Check if user is admin
    if message.from_user.id != ADMIN_USER_ID:
        await message.answer("❌ This command is only available for administrators.")
        return
        
    try:
        # Send initial message
        status_message = await message.answer("🔄 Resetting daily limits for all users...")
        
        async with async_session() as session:
            # Reset requests_today for all users
            await session.execute(text("UPDATE users SET requests_today = 0, last_request_date = CURRENT_DATE"))
            await session.commit()
            
            await status_message.edit_text("✅ Daily limits have been reset for all users!")
            logger.info("Daily limits reset by admin")
            
    except Exception as e:
        logger.error(f"Error in reset_limits command: {e}")
        await message.answer("❌ An error occurred while resetting limits.")

@router.message(Command("migrate"))
async def cmd_migrate(message: Message):
    """Handle /migrate command"""
    # Check if user is admin
    if message.from_user.id != ADMIN_USER_ID:
        await message.answer("❌ This command is only available for administrators.")
        return
        
    try:
        # Send initial message
        status_message = await message.answer("🔄 Applying database migrations...")
        
        async with async_session() as session:
            success = await migrate_database(session)
            if success:
                await status_message.edit_text("✅ Database migrations applied successfully!")
                # Send additional notification to admin
                await bot.send_message(
                    ADMIN_USER_ID,
                    "✅ Database migrations completed successfully!\n"
                    "All tables and columns are up to date."
                )
            else:
                await status_message.edit_text("❌ Error applying database migrations. Check logs for details.")
                # Send error notification to admin
                await bot.send_message(
                    ADMIN_USER_ID,
                    "❌ Database migration failed!\nCheck logs for details."
                )
    except Exception as e:
        logger.error(f"Error in migrate command: {e}")
        await message.answer("❌ An error occurred while applying migrations.")
        # Send error notification to admin
        try:
            await bot.send_message(
                ADMIN_USER_ID,
                f"❌ Database migration failed!\nError: {str(e)}"
            )
        except Exception as notify_error:
            logger.error(f"Failed to send admin notification: {notify_error}")

@router.message(Command("notificate"))
async def cmd_notificate(message: Message):
    """Send notification to all users (admin only)"""
    # Check if user is admin
    if message.from_user.id != ADMIN_USER_ID:
        await message.answer("❌ This command is only available for administrators.")
        return
        
    try:
        # Send initial message
        status_message = await message.answer("🔄 Sending notifications to all users...")
        
        # Use notification text from config
        text = DEFAULT_NOTIFICATION_MESSAGE
        
        # Get all users from database
        async with async_session() as session:
            stmt = select(User)
            result = await session.execute(stmt)
            users = result.scalars().all()
            
            success_count = 0
            error_count = 0
            
            for user in users:
                try:
                    await bot.send_message(user.user_id, text)
                    success_count += 1
                    # Small delay to avoid rate limiting
                    await asyncio.sleep(0.1)
                except Exception as e:
                    error_count += 1
                    logger.error(f"Failed to send notification to user {user.user_id}: {e}")
                    continue
            
            # Update status message
            await status_message.edit_text(
                f"✅ Notifications sent successfully!\n"
                f"📊 Statistics:\n"
                f"✅ Successfully sent: {success_count}\n"
                f"❌ Failed: {error_count}\n"
                f"📝 Total users: {len(users)}"
            )
            
            logger.info(f"Notification broadcast completed. Success: {success_count}, Errors: {error_count}")
            
    except Exception as e:
        logger.error(f"Error in notificate command: {e}")
        await message.answer("❌ An error occurred while sending notifications.")
        # Send error notification to admin
        try:
            await bot.send_message(
                ADMIN_USER_ID,
                f"❌ Notification broadcast failed!\nError: {str(e)}"
            )
        except Exception as notify_error:
            logger.error(f"Failed to send admin notification: {notify_error}")

@router.message(Command("notificate_custom"))
async def cmd_notificate_custom(message: Message):
    """Send custom notification to all users (admin only)"""
    # Check if user is admin
    if message.from_user.id != ADMIN_USER_ID:
        await message.answer("❌ This command is only available for administrators.")
        return
    
    # Check if message has text after command
    command_text = message.text.strip()
    if command_text == "/notificate_custom":
        await message.answer(
            "📝 Usage: /notificate_custom <your message>\n\n"
            "Example:\n"
            "/notificate_custom Привет всем! У нас обновление! 🎉"
        )
        return
        
    try:
        # Extract custom text (remove command)
        custom_text = command_text.replace("/notificate_custom", "").strip()
        
        if not custom_text:
            await message.answer("❌ Please provide a message to send.")
            return
        
        # Send initial message
        status_message = await message.answer("🔄 Sending custom notifications to all users...")
        
        # Get all users from database
        async with async_session() as session:
            stmt = select(User)
            result = await session.execute(stmt)
            users = result.scalars().all()
            
            success_count = 0
            error_count = 0
            
            for user in users:
                try:
                    await bot.send_message(user.user_id, custom_text)
                    success_count += 1
                    # Small delay to avoid rate limiting
                    await asyncio.sleep(0.1)
                except Exception as e:
                    error_count += 1
                    logger.error(f"Failed to send custom notification to user {user.user_id}: {e}")
                    continue
            
            # Update status message
            await status_message.edit_text(
                f"✅ Custom notifications sent successfully!\n"
                f"📊 Statistics:\n"
                f"✅ Successfully sent: {success_count}\n"
                f"❌ Failed: {error_count}\n"
                f"📝 Total users: {len(users)}\n\n"
                f"📤 Message sent:\n{custom_text[:100]}{'...' if len(custom_text) > 100 else ''}"
            )
            
            logger.info(f"Custom notification broadcast completed. Success: {success_count}, Errors: {error_count}")
            
    except Exception as e:
        logger.error(f"Error in notificate_custom command: {e}")
        await message.answer("❌ An error occurred while sending custom notifications.")
        # Send error notification to admin
        try:
            await bot.send_message(
                ADMIN_USER_ID,
                f"❌ Custom notification broadcast failed!\nError: {str(e)}"
            )
        except Exception as notify_error:
            logger.error(f"Failed to send admin notification: {notify_error}")

@router.message()
async def handle_message(message: Message):
    """Handle incoming messages"""
    try:
        # Ensure user exists in database
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                # Create user if doesn't exist
                new_user = User(
                    user_id=message.from_user.id,
                    username=message.from_user.username or None,
                    first_name=message.from_user.first_name or None,
                    last_name=message.from_user.last_name or None,
                    is_premium=False,
                    requests_today=0,
                    last_request_date=datetime.utcnow().date()
                )
                session.add(new_user)
                await session.commit()
                logger.info(f"Created new user: {new_user.user_id}")

        # Check subscription
        if not await check_subscription(message.from_user.id):
            await send_subscription_message(message)
            return

        # Check user limits
        if not await check_user_limits(message.from_user.id):
            await message.answer(
                "⚠️ You've reached your daily message limit.\n"
                "Upgrade to Premium for unlimited access!\n"
                "Use /premium to see available plans."
            )
            return

        # Handle voice messages
        if message.voice:
            try:
                # Create voice directory if it doesn't exist
                os.makedirs('voice', exist_ok=True)
                
                # Get voice file info
                voice = message.voice
                file_id = voice.file_id
                file = await bot.get_file(file_id)
                
                # Download voice file
                voice_path = f"voice/{message.from_user.id}.ogg"
                await bot.download_file(file.file_path, voice_path)
                
                # Convert voice to text using Whisper
                text = await whisper_stt(voice_path)
                
                # Delete the voice file after processing
                os.remove(voice_path)
                
                if not text:
                    await message.answer("Sorry, I couldn't understand the voice message. Please try again.")
                    return
                
                # Get chat history
                chat_history = await get_chat_history(message.from_user.id)
                
                # Get response from ChatGPT
                response = await get_chatgpt_response(text, chat_history)
                
                # Save messages to history
                await save_message(message.from_user.id, "user", text)
                await save_message(message.from_user.id, "assistant", response)
                
                # Send response
                await message.answer(response)
                
            except Exception as e:
                logger.error(f"Error processing voice message: {e}")
                await message.answer("Sorry, there was an error processing your voice message. Please try again.")
                return

        # Process text messages
        if message.text:
            # Get chat history
            chat_history = await get_chat_history(message.from_user.id)
            
            # Get response from ChatGPT
            response = await get_chatgpt_response(message.text, chat_history)
            
            # Save messages to history
            await save_message(message.from_user.id, "user", message.text)
            await save_message(message.from_user.id, "assistant", response)
            
            # Send response
            await message.answer(response)
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        await message.answer("Sorry, an error occurred while processing your message.")

async def main():
    """Main function"""
    try:
        logger.info("Starting AI Telegram Bot...")
        
        # Create database tables
        db_initialized = await create_database_if_not_exists()
        if not db_initialized:
            logger.error("Failed to initialize database. Exiting.")
            return
        
        logger.info("Database initialized successfully")
        logger.info("Bot is starting...")
        
        # Start polling with retry on network errors
        while True:
            try:
                await router.start_polling(bot)
            except Exception as e:
                logger.error(f"Error in polling: {e}")
                await asyncio.sleep(5)  # Wait 5 seconds before retrying
                continue
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"Critical error in main: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main()) 