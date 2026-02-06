"""SQLAlchemy database models for trade logging."""

from datetime import datetime

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, JSON
from sqlalchemy.orm import declarative_base, sessionmaker

from trading_bot.config import settings

Base = declarative_base()


class TradeLog(Base):
    __tablename__ = "trade_logs"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(String(10), nullable=False, index=True)
    action = Column(String(20), nullable=False)
    price = Column(Float, nullable=False)
    stop_loss = Column(Float)
    take_profit = Column(Float)
    risk_reward_ratio = Column(Float)
    weighted_score = Column(Float)
    consensus_strength = Column(Float)
    position_size = Column(Integer)
    dollar_risk = Column(Float)
    regime = Column(String(30))
    contributing_strategies = Column(JSON)
    metadata_json = Column(JSON)


class ScanLog(Base):
    __tablename__ = "scan_logs"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    symbols_scanned = Column(Integer)
    signals_generated = Column(Integer)
    alerts_sent = Column(Integer)
    duration_seconds = Column(Float)


def get_engine():
    return create_engine(settings.database_url)


def get_session():
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()


def init_db():
    engine = get_engine()
    Base.metadata.create_all(engine)


def log_trade(signal):
    """Log an aggregated signal to the database."""
    try:
        session = get_session()
        trade = TradeLog(
            symbol=signal.symbol,
            action=signal.action,
            price=signal.price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            risk_reward_ratio=signal.risk_reward_ratio,
            weighted_score=signal.weighted_score,
            consensus_strength=signal.consensus_strength,
            position_size=signal.position_size,
            dollar_risk=signal.dollar_risk,
            regime=signal.regime,
            contributing_strategies=signal.contributing_strategies,
        )
        session.add(trade)
        session.commit()
        session.close()
    except Exception as e:
        import logging
        logging.getLogger("trading_bot").error(f"DB logging error: {e}")
