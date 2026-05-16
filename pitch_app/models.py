from sqlalchemy import Column, Integer, String, Text, DateTime, Float, func
from pitch_app.db import Base


class Material(Base):
    __tablename__ = "materials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    title = Column(String(255), nullable=False)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(20), nullable=False)
    industry = Column(String(100), nullable=False)
    solution = Column(String(100), nullable=False)
    description = Column(Text, nullable=False, default="")
    sort_order = Column(Integer, nullable=False, default=0)
    active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, server_default=func.current_timestamp(), nullable=False)
    updated_at = Column(DateTime, server_default=func.current_timestamp(), nullable=False)

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    username = Column(String(100), unique=True, nullable=False)
    password = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="seller")  # seller | admin
    active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, server_default=func.current_timestamp(), nullable=False)

class UsageLog(Base):
    __tablename__ = "usage_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    service = Column(String(50), nullable=False)  # openai, sendgrid, railway
    operation = Column(String(100), nullable=False)  # transcription, evaluation, email_sent, etc
    user_id = Column(Integer, nullable=True)
    tokens_used = Column(Integer, nullable=True)  # For OpenAI
    cost_usd = Column(Float, nullable=True)  # Estimated cost
    metadata_ = Column("metadata", Text, nullable=True)  # JSON with additional info
    created_at = Column(DateTime, server_default=func.current_timestamp(), nullable=False)