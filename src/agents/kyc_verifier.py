"""
Agent 2: KYC Verifier
Verifies customer identity against national databases (simulated for demo).
Assesses KYC completeness, PEP status, and assigns risk tier.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import aiosqlite

from src.database import get_customer, update_customer, now_wat
from src.governance.audit import log_agent_decision
from src.models import KycVerifierResult

# PEP indicator keywords in name/title (simplified for demo)
PEP_KEYWORDS = [
    "senator", "honourable", "governor", "minister", "commissioner",
    "ambassador", "general", "admiral", "president", "alhaji", "chief",
    "rtd", "rtd.", "retired", "former",
]

# Required KYC fields for individual accounts
REQUIRED_INDIVIDUAL = ["name", "bvn", "nin", "date_of_birth", "phone", "address"]

# Required KYC fields for corporate accounts
REQUIRED_CORPORATE = ["name", "bvn", "phone", "address"]


class KycVerifierAgent:
    name = "kyc_verifier_agent"

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def verify(
        self,
        customer_id: str,
        monitor_context: Optional[Dict[str, Any]] = None,
    ) -> KycVerifierResult:
        """
        Verify KYC for a customer. Logs to audit trail before returning.
        """
        customer = await get_customer(self.db, customer_id)
        if not customer:
            # Return minimal result for unknown customer
            result = KycVerifierResult(
                customer_id=customer_id,
                kyc_status="failed",
                risk_tier="high",
                missing_fields=["customer_not_found"],
                verification_confidence=0.0,
                pep_detected=False,
                audit_logged=True,
            )
            await log_agent_decision(
                db=self.db,
                agent_name=self.name,
                entity_type="customer",
                entity_id=customer_id,
                decision="failed",
                confidence=0.0,
                details={"reason": "Customer not found in database"},
            )
            return result

        account_type = customer.get("account_type", "individual")
        required = REQUIRED_INDIVIDUAL if account_type == "individual" else REQUIRED_CORPORATE

        # 1. Check completeness
        missing_fields = [f for f in required if not customer.get(f)]
        completeness_score = 1.0 - (len(missing_fields) / len(required))

        # 2. BVN/NIN validation (simulated)
        bvn_valid = self._validate_bvn(customer.get("bvn"))
        nin_valid = self._validate_nin(customer.get("nin"))

        # 3. PEP check
        pep_detected = self._check_pep(customer.get("name", ""), customer.get("pep_status", 0))

        # 4. Risk tier assignment
        risk_tier = self._assign_risk_tier(
            customer=customer,
            pep_detected=pep_detected,
            missing_fields=missing_fields,
            bvn_valid=bvn_valid,
            nin_valid=nin_valid,
            monitor_context=monitor_context,
        )

        # 5. KYC status determination
        if missing_fields and account_type == "individual" and len(missing_fields) >= 3:
            kyc_status = "failed"
        elif missing_fields:
            kyc_status = "incomplete"
        elif not bvn_valid and account_type == "individual":
            kyc_status = "requires_update"
        else:
            kyc_status = "verified"

        # Confidence score based on data completeness and validation results
        confidence = self._compute_confidence(
            completeness_score, bvn_valid, nin_valid, pep_detected
        )

        # Update customer record in DB
        updates: Dict[str, Any] = {
            "kyc_status": kyc_status,
            "risk_tier": risk_tier,
            "pep_status": 1 if pep_detected else customer.get("pep_status", 0),
        }
        await update_customer(self.db, customer_id, updates)

        # MANDATORY: Log to audit trail before returning
        await log_agent_decision(
            db=self.db,
            agent_name=self.name,
            entity_type="customer",
            entity_id=customer_id,
            decision=kyc_status,
            confidence=confidence,
            details={
                "kyc_status": kyc_status,
                "risk_tier": risk_tier,
                "missing_fields": missing_fields,
                "bvn_valid": bvn_valid,
                "nin_valid": nin_valid,
                "pep_detected": pep_detected,
                "completeness_score": completeness_score,
            },
        )

        return KycVerifierResult(
            customer_id=customer_id,
            kyc_status=kyc_status,
            risk_tier=risk_tier,
            missing_fields=missing_fields,
            verification_confidence=round(confidence, 4),
            pep_detected=pep_detected,
            audit_logged=True,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_bvn(self, bvn: Optional[str]) -> bool:
        """BVN is 11 digits per CBN standard."""
        if not bvn:
            return False
        return bool(re.match(r"^\d{11}$", bvn.strip()))

    def _validate_nin(self, nin: Optional[str]) -> bool:
        """NIN is 11 digits per NIMC standard."""
        if not nin:
            return False
        return bool(re.match(r"^\d{11}$", nin.strip()))

    def _check_pep(self, name: str, existing_pep_status: int) -> bool:
        """Check for PEP indicators in name or use existing PEP flag."""
        if existing_pep_status:
            return True
        name_lower = name.lower()
        return any(kw in name_lower for kw in PEP_KEYWORDS)

    def _assign_risk_tier(
        self,
        customer: Dict,
        pep_detected: bool,
        missing_fields: List[str],
        bvn_valid: bool,
        nin_valid: bool,
        monitor_context: Optional[Dict],
    ) -> str:
        score = 0

        # PEP status is highest risk factor
        if pep_detected:
            score += 40

        # Corporate account gets medium base risk
        if customer.get("account_type") == "corporate":
            score += 15

        # Missing critical fields
        if "bvn" in missing_fields:
            score += 20
        if "nin" in missing_fields:
            score += 15
        if "address" in missing_fields:
            score += 10

        # Invalid documents
        if not bvn_valid:
            score += 15
        if not nin_valid and customer.get("account_type") == "individual":
            score += 10

        # Transaction context risk
        if monitor_context:
            txn_risk_score = monitor_context.get("risk_score", 0)
            if txn_risk_score >= 0.7:
                score += 25
            elif txn_risk_score >= 0.4:
                score += 10

        # Existing risk tier (don't downgrade without human approval)
        current_tier = customer.get("risk_tier", "low")
        tier_scores = {"low": 0, "medium": 20, "high": 40, "very_high": 60}
        existing_score = tier_scores.get(current_tier, 0)
        score = max(score, existing_score)  # Never auto-downgrade

        if score >= 60:
            return "very_high"
        elif score >= 40:
            return "high"
        elif score >= 20:
            return "medium"
        return "low"

    def _compute_confidence(
        self,
        completeness_score: float,
        bvn_valid: bool,
        nin_valid: bool,
        pep_detected: bool,
    ) -> float:
        confidence = completeness_score * 0.5
        if bvn_valid:
            confidence += 0.25
        if nin_valid:
            confidence += 0.2
        # PEP detection reduces confidence (we are uncertain)
        if pep_detected:
            confidence *= 0.85
        return max(0.1, min(0.99, confidence))
