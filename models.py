from datetime import datetime
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Date

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, unique=True, nullable=False)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    last_name = Column(String, nullable=True)
    is_premium = Column(Boolean, default=False)
    premium_until = Column(DateTime, nullable=True)
    requests_today = Column(Integer, default=0)
    last_request_date = Column(Date, nullable=True)

    # Relationship with chat messages
    messages = relationship("ChatMessage", back_populates="user")

    def __init__(self, user_id, username=None, first_name=None, last_name=None, 
                 is_premium=False, premium_until=None, requests_today=0, last_request_date=None):
        self.user_id = user_id
        self.username = username
        self.first_name = first_name
        self.last_name = last_name
        self.is_premium = is_premium
        self.premium_until = premium_until
        self.requests_today = requests_today
        self.last_request_date = last_request_date


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    role = Column(String)  # 'user' or 'assistant'
    content = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

    # Relationship with user
    user = relationship("User", back_populates="messages")
