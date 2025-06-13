import logging
import os
from datetime import datetime, timedelta
import asyncio
import requests
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardButton, LabeledPrice
from aiogram.enums import ChatMemberStatus
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, select
from openai import AsyncOpenAI
import asyncpg
from config import *
from typing import Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

async def create_database_if_not_exists():
    """Create database if it doesn't exist"""
    try:
        # Connect to default postgres database
        sys_conn = await asyncpg.connect(
            user=DB_USER,
            password=DB_PASSWORD,
            host=DB_HOST,
            port=DB_PORT,
            database='postgres'
        )
        
        # Check if database exists
        exists = await sys_conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1",
            DB_NAME
        )
        
        if not exists:
            # Create new database
            await sys_conn.execute(f'CREATE DATABASE "{DB_NAME}"')
            logger.info(f"Database '{DB_NAME}' created successfully!")
        else:
            logger.info(f"Database '{DB_NAME}' already exists.")
        
        await sys_conn.close()
    except Exception as e:
        logger.error(f"Error creating database: {str(e)}")
        raise

# Database setup
Base = declarative_base()
engine = create_async_engine(DATABASE_URL)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True)
    username = Column(String)
    is_premium = Column(Boolean, default=False)
    requests_today = Column(Integer, default=0)
    last_request_date = Column(DateTime, default=datetime.utcnow)
    
    # Relationship with messages
    messages = relationship("ChatMessage", back_populates="user", cascade="all, delete-orphan")

class ChatMessage(Base):
    __tablename__ = "chat_messages"
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    role = Column(String)  # 'user' or 'assistant'
    content = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # Relationship with user
    user = relationship("User", back_populates="messages")

async def get_chat_history(user_id: int, limit: int = 5) -> list:
    """
    Get recent chat history for a user (last 5 messages)
    """
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

async def save_message(user_id: int, role: str, content: str):
    """
    Save a message to chat history
    """
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return
        
        message = ChatMessage(
            user_id=user.id,
            role=role,
            content=content
        )
        session.add(message)
        await session.commit()

async def get_chatgpt_response(message: str, chat_history: list) -> str:
    """
    Get response from ChatGPT API with chat history
    """
    try:
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
    try:
        stmt = select(User).where(User.user_id == user_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Error getting user: {e}")
        return None

@router.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command"""
    try:
        # Check if user is a member of the channel
        if not await check_subscription(message.from_user.id):
            await message.answer(
                "⚠️ To use the bot, you need to subscribe to our channel.",
                reply_markup=InlineKeyboardBuilder()
                .button(text="📢 Subscribe to channel", url=CHANNEL_URL)
                .as_markup()
            )
            return

        # Get or create user
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            if not user:
                user = User(
                    user_id=message.from_user.id,
                    username=message.from_user.username,
                    first_name=message.from_user.first_name,
                    last_name=message.from_user.last_name,
                    is_premium=False,
                    requests_today=0,
                    last_request_date=datetime.now().date()
                )
                session.add(user)
                await session.commit()

        # Send welcome message
        await message.answer(
            f"👋 Hello, {message.from_user.first_name}!\n\n"
            "I'm an AI bot that can:\n"
            "• Answer your questions\n"
            "• Process voice messages\n"
            "• Help with various tasks\n\n"
            "Just send me message!\n"
            "Use /premium to get unlimited access!"
        )
    except Exception as e:
        logger.error(f"Error in start command: {e}")
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
    user_id = message.from_user.id
    async with async_session() as session:
        stmt = select(User).where(User.user_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if user:
            # Delete all messages for the user
            stmt = select(ChatMessage).where(ChatMessage.user_id == user.id)
            result = await session.execute(stmt)
            messages = result.scalars().all()
            
            for message in messages:
                await session.delete(message)
            await session.commit()
    
    await message.answer("Chat history has been cleared!")

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
                user.premium_until = datetime.now() + timedelta(days=plan["duration_days"])
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
    async with async_session() as session:
        stmt = select(User).where(User.user_id == user_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            return False
        
        # Reset daily counter if it's a new day
        if user.last_request_date.date() < datetime.utcnow().date():
            user.requests_today = 0
            user.last_request_date = datetime.utcnow()
            await session.commit()
        
        if user.is_premium:
            return True
        
        if user.requests_today >= FREE_REQUESTS_PER_DAY:
            return False
        
        user.requests_today += 1
        user.last_request_date = datetime.utcnow()
        await session.commit()
        return True

async def whisper_stt(audio_file) -> str:
    logger.info("Request to whisper_stt")
    try:
        API_URL = "https://api-inference.huggingface.co/models/openai/whisper-large-v3-turbo"
        headers = {"Authorization": f"Bearer {HF_API_KEY}"}
        response = requests.post(API_URL, headers=headers, data=audio_file)
        return response.json()["text"]
    except Exception as e:
        logger.error(f"Error querying whisper_stt: {str(e)}")
        return ""

@router.message()
async def handle_message(message: Message):
    user_id = message.from_user.id
    
    # Check subscription first
    if not await check_subscription(user_id):
        await message.answer(
            "⚠️ To use the bot, you need to subscribe to our channel.",
            reply_markup=InlineKeyboardBuilder()
            .button(text="📢 Subscribe to channel", url=CHANNEL_URL)
            .as_markup()
        )
        return

    # Check user limits
    if not await check_user_limits(user_id):
        # Create keyboard with Get Premium button
        builder = InlineKeyboardBuilder()
        builder.button(text="💎 Get Premium", callback_data="show_premium_plans")
        builder.adjust(1)
        
        await message.answer(
            "⚠️ You've reached your daily limit of free requests.\n\n"
            "Get Premium to enjoy unlimited access!",
            reply_markup=builder.as_markup()
        )
        return

    if message.voice:
        # Handle voice message
        voice = await message.voice.get_file()
        audio_file = await bot.download_file(voice.file_path)
        text = await whisper_stt(audio_file)
        if not text:
            await message.answer("Sorry, I couldn't recognize the voice message.")
            return
        message.text = text
    
    # Process text with ChatGPT
    try:
        # Show typing indicator
        await bot.send_chat_action(chat_id=message.chat.id, action="typing")
        
        # Get chat history
        chat_history = await get_chat_history(user_id)
        
        # Get response from ChatGPT
        response = await get_chatgpt_response(message.text, chat_history)
        
        # Save both user message and assistant response
        await save_message(user_id, "user", message.text)
        await save_message(user_id, "assistant", response)
        
        # Send response
        await message.answer(response)
    except Exception as e:
        logger.error(f"Error processing message: {str(e)}")
        await message.answer("Sorry, an error occurred while processing your message.")

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
        "• /premium - Get premium subscription\n"
        "• /clear - Clear chat history\n\n"
        "<b>Free Usage:</b>\n"
        "• 5 free requests per day\n"
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

async def main():
    """Main function"""
    try:
        # Create database tables
        await create_database_if_not_exists()
        
        # Start polling
        await router.start_polling(bot)
    except Exception as e:
        logger.error(f"Error in main: {e}")

if __name__ == "__main__":
    asyncio.run(main()) 