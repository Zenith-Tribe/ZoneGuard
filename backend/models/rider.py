from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, ForeignKey
from sqlalchemy.sql import func
from db.database import Base


class Rider(Base):
    __tablename__ = "riders"

    id = Column(String, primary_key=True)  # e.g. "AMZFLEX-BLR-04821"
    name = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    zone_id = Column(String, ForeignKey("zones.id"), nullable=False)
    weekly_earnings_baseline = Column(Float, default=0)
    tenure_weeks = Column(Integer, default=0)
    kyc_verified = Column(Boolean, default=False)
    upi_id = Column(String, nullable=True)
    eshram_id = Column(String, nullable=True)
    eshram_verified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
