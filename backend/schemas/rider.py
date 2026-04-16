from pydantic import BaseModel
from datetime import datetime
from typing import Optional


class RiderRegister(BaseModel):
    rider_id: str
    name: str
    phone: Optional[str] = None
    zone_id: str
    weekly_earnings: float
    upi_id: Optional[str] = None
    eshram_id: Optional[str] = None


class RiderResponse(BaseModel):
    id: str
    name: str
    phone: Optional[str]
    zone_id: str
    weekly_earnings_baseline: float
    tenure_weeks: int
    kyc_verified: bool
    upi_id: Optional[str]
    eshram_id: Optional[str] = None
    eshram_verified: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


class RiderKYC(BaseModel):
    upi_id: str
    phone: str


class EShramVerifyRequest(BaseModel):
    eshram_id: str


class EShramVerifyResponse(BaseModel):
    status: str
    eshram_id: str
    verified: bool
    worker_name: Optional[str] = None
    worker_category: Optional[str] = None
    income_band: Optional[str] = None
    deduplication_check: Optional[dict] = None
    message: Optional[str] = None
    source: str = "simulated_eshram_portal"
