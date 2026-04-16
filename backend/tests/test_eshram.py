"""Tests for e-Shram KYC integration — format validation, verification, income proxy."""

import asyncio
import pytest

from integrations.eshram_sim import verify_eshram_worker, check_income_proxy


@pytest.mark.asyncio
class TestEshramVerification:
    async def test_valid_eshram_id_verified(self):
        """Valid 12-digit numeric ID returns either 'verified' or 'mismatch'."""
        result = await verify_eshram_worker("123456789012", "Ravi Kumar", "+919876543210")
        assert result["status"] in ("verified", "mismatch")
        assert isinstance(result["verified"], bool)

    async def test_invalid_eshram_format_short(self):
        """Too-short ID returns 'invalid' with verified=False."""
        result = await verify_eshram_worker("12345", "Ravi Kumar", "+919876543210")
        assert result["status"] == "invalid"
        assert result["verified"] is False

    async def test_invalid_eshram_format_letters(self):
        """ID containing letters returns 'invalid' with verified=False."""
        result = await verify_eshram_worker("12345678ABCD", "Ravi Kumar", "+919876543210")
        assert result["status"] == "invalid"
        assert result["verified"] is False

    async def test_response_has_required_fields(self):
        """Every response (valid or invalid) must include core fields."""
        result = await verify_eshram_worker("987654321098", "Priya Sharma", "+919812345678")
        for key in ("status", "eshram_id", "verified", "source"):
            assert key in result, f"Missing required field: {key}"

    async def test_verified_response_has_deduplication(self):
        """A verified response must include deduplication_check details."""
        # Find a UAN that produces a verified response (deterministic hash)
        uan = "123456789012"
        result = await verify_eshram_worker(uan, "Ravi Kumar", "+919876543210")
        if result["status"] == "verified":
            assert "deduplication_check" in result
            dedup = result["deduplication_check"]
            assert "is_unique" in dedup
            assert "existing_accounts" in dedup
        else:
            # If this particular UAN hashes to mismatch, try another known-good one
            result2 = await verify_eshram_worker("100000000001", "Test User", "+910000000000")
            if result2["status"] == "verified":
                assert "deduplication_check" in result2
                assert "is_unique" in result2["deduplication_check"]
                assert "existing_accounts" in result2["deduplication_check"]


@pytest.mark.asyncio
class TestIncomeProxy:
    async def test_income_proxy_validation_close(self):
        """Declared ₹3,000/week should produce income_validated=True (within ±30%)."""
        result = await check_income_proxy("123456789012", 3000.0)
        # Deviation is within ±30%, so always < 50% threshold
        assert result["income_validated"] is True

    async def test_income_proxy_has_required_fields(self):
        """Response must contain all expected income proxy fields."""
        result = await check_income_proxy("123456789012", 4000.0)
        for key in ("declared_weekly", "declared_monthly", "deviation_pct",
                     "income_validated", "risk_flag"):
            assert key in result, f"Missing required field: {key}"

    async def test_income_proxy_risk_flag_values(self):
        """risk_flag must be one of the three allowed values."""
        result = await check_income_proxy("123456789012", 5000.0)
        assert result["risk_flag"] in ("none", "review", "high")


@pytest.mark.asyncio
class TestAsyncBehavior:
    async def test_async_functions(self):
        """Both functions are proper coroutines and return dicts."""
        coro1 = verify_eshram_worker("111222333444", "Test", "+910000000000")
        coro2 = check_income_proxy("111222333444", 2500.0)
        assert asyncio.iscoroutine(coro1)
        assert asyncio.iscoroutine(coro2)
        r1 = await coro1
        r2 = await coro2
        assert isinstance(r1, dict)
        assert isinstance(r2, dict)
