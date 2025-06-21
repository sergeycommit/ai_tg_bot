from sqlalchemy import text, inspect, MetaData, Table, Column
from sqlalchemy.ext.asyncio import AsyncSession
import logging
from models import Base, User, ChatMessage
from config import ADMIN_USER_ID
import asyncio

logger = logging.getLogger(__name__)

async def get_table_columns(session: AsyncSession, table_name: str) -> list:
    """Get list of existing columns in the database table"""
    try:
        result = await session.execute(text(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table_name}'
        """))
        return [row[0] for row in result]
    except Exception as e:
        logger.error(f"Error getting columns for table {table_name}: {e}")
        return []

def get_model_columns(table_name: str) -> list:
    """Get list of columns from the model"""
    if table_name == 'users':
        return [c.name for c in User.__table__.columns]
    elif table_name == 'chat_messages':
        return [c.name for c in ChatMessage.__table__.columns]
    return []

async def notify_admin(message: str):
    """Send notification to admin"""
    try:
        # Import bot locally to avoid circular import
        import importlib
        bot_module = importlib.import_module('bot')
        bot = bot_module.bot
        
        # Ensure we're in an async context
        if asyncio.get_event_loop().is_running():
            await bot.send_message(ADMIN_USER_ID, message)
        else:
            logger.warning("Cannot send admin notification: not in async context")
    except Exception as e:
        logger.error(f"Failed to send admin notification: {e}")

async def migrate_database(session: AsyncSession):
    """Apply database migrations"""
    try:
        # Create tables if they don't exist
        await session.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                user_id INTEGER UNIQUE NOT NULL,
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
        
        # Process users table
        db_columns = await get_table_columns(session, 'users')
        model_columns = get_model_columns('users')
        missing_columns = [col for col in model_columns if col not in db_columns]
        
        for column in missing_columns:
            column_type = next(c.type for c in User.__table__.columns if c.name == column)
            await session.execute(text(f"""
                ALTER TABLE users ADD COLUMN IF NOT EXISTS {column} {column_type}
            """))
        
        # Process chat_messages table
        db_columns = await get_table_columns(session, 'chat_messages')
        model_columns = get_model_columns('chat_messages')
        missing_columns = [col for col in model_columns if col not in db_columns]
        
        for column in missing_columns:
            column_type = next(c.type for c in ChatMessage.__table__.columns if c.name == column)
            await session.execute(text(f"""
                ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS {column} {column_type}
            """))
        
        await session.commit()
        logger.info("Database migrations applied successfully")
        
        # Notify admin about successful migration
        await notify_admin(
            "✅ Database migrations completed successfully!\n"
            "All tables and columns are up to date."
        )
        
        return True
    except Exception as e:
        await session.rollback()
        logger.error(f"Error applying migrations: {e}")
        
        # Notify admin about migration failure
        await notify_admin(f"❌ Database migration failed!\nError: {str(e)}")
        
        return False 