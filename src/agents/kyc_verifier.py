"""
Agent 2: KYC Verifier

Verifies customer identity documents and assesses KYC compliance status.
In production this agent would call NIBSS (for BVN verification) and
NIMC (for NIN verification) APIs. In this demo, format-based validation
is used as a proxy.

CBN's tiered KYC framework (Tiers 1-3) specifies which identity documents
are required at each account tier. This agent enforces Tier-3 requirements
(the strictest tier): BVN + NIN + proof of address are all mandatory for
individual accounts above the basic transaction limit.

PEP detection uses keyword matching on customer names as a first-pass
heuristic. In production this would be supplemented by screening against
commercial PEP databases (e.g., Refinitiv, Dow Jones Risk & Compliance).

Risk tier assignment is cumulative and never auto-downgrades — a human
approval is required to reduce a customer's risk classification, which
prevents accidental or fraudulent risk understatement.
"""

from __future__ import annotations

import re
from typing import Any

import aiosqlite

from src.database import get_customer, update_customer
from src.governance.audit import log_agent_decision
from src.models import KycVerifierResult

# PEP indicator keywords in customer names and titles.
# This is a simplified heuristic — it catches common Nigerian PEP title
# patterns and words associated with politically exposed persons. In
# production, this would be supplemented by a commercial PEP database.
PEP_KEYWORDS = [
    "senator", "honourable", "governor", "minister", "commissioner",
    "ambassador", "general", "admiral", "president", "alhaji", "chief",
    "rtd", "rtd.", "retired", "former",
]

# Fields required for individual accounts (CBN Tier-3 KYC requirements).
# All six are mandatory; missing any three triggers a KYC 'failed' status.
REQUIRED_INDIVIDUAL = ["name", "bvn", "nin", "date_of_birth", "phone", "address"]

# Fields required for corporate accounts. NIN and date_of_birth do not
# apply to legal entities, so only company-level identifiers are required.
REQUIRED_CORPORATE = ["name", "bvn", "phone", "address"]


class KycVerifierAgent:
    name = "kyc_verifier_agent"

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def verify(
        self,
        customer_id: str,
        monitor_context: dict[str, Any] | None = None,
    ) -> KycVerifierResult:
        """Verify KYC completeness and assign risk tier for a customer.

        Verification steps:
        1. Check field completeness against required field list for account type.
        2. Validate BVN and NIN format (11 digits per CBN/NIMC standards).
        3. Check for PEP indicators in customer name or existing PEP flag.
        4. Assign risk tier using a weighted scoring model.
        5. Determine KYC status based on completeness and validation results.
        6. Update the customer record in the database.
        7. Log the decision to the immutable audit trail.

        The monitor_context parameter allows the KYC assessment to be
        informed by the transaction monitor's risk score — a high-risk
        transaction should elevate the customer's risk tier even if their
        documents appear complete.
        """
        customer = await get_customer(self.db, customer_id)
        if not customer:
            # Unknown customer: maximum risk by default. A customer who
            # cannot be found in the system should never pass KYC.
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

        # Step 1: Completeness check
        # missing_fields is a list of field names — passed to the result so
        # the customer service team knows exactly which documents to request.
        missing_fields = [f for f in required if not customer.get(f)]
        completeness_score = 1.0 - (len(missing_fields) / len(required))

        # Step 2: BVN/NIN format validation (simulated in demo)
        # In production: call NIBSS API for BVN biometric verification
        # and NIMC API for NIN biometric verification.
        bvn_valid = self._validate_bvn(customer.get("bvn"))
        nin_valid = self._validate_nin(customer.get("nin"))

        # Step 3: PEP detection
        # PEPs receive enhanced due diligence (EDD) per FATF Recommendation 12.
        # Once PEP status is set, it persists — PEP status is never cleared
        # automatically because former PEPs remain higher risk for years.
        pep_detected = self._check_pep(customer.get("name", ""), customer.get("pep_status", 0))

        # Step 4: Risk tier assignment using weighted scoring
        risk_tier = self._assign_risk_tier(
            customer=customer,
            pep_detected=pep_detected,
            missing_fields=missing_fields,
            bvn_valid=bvn_valid,
            nin_valid=nin_valid,
            monitor_context=monitor_context,
        )

        # Step 5: KYC status determination
        # Three or more missing required fields → 'failed' (too incomplete to proceed).
        # Any missing fields → 'incomplete' (account restricted pending documentation).
        # Invalid BVN → 'requires_update' (document exists but fails validation).
        # All present and valid → 'verified'.
        if missing_fields and account_type == "individual" and len(missing_fields) >= 3:
            kyc_status = "failed"
        elif missing_fields:
            kyc_status = "incomplete"
        elif not bvn_valid and account_type == "individual":
            kyc_status = "requires_update"
        else:
            kyc_status = "verified"

        # Confidence is based on data completeness and document validity.
        # PEP detection slightly reduces confidence (we are uncertain whether
        # all PEP-related risks have been fully assessed).
        confidence = self._compute_confidence(
            completeness_score, bvn_valid, nin_valid, pep_detected
        )

        # Step 6: Update customer record with latest KYC assessment.
        # pep_status is only updated upward — once flagged as PEP, it stays PEP.
        updates: dict[str, Any] = {
            "kyc_status": kyc_status,
            "risk_tier": risk_tier,
            "pep_status": 1 if pep_detected else customer.get("pep_status", 0),
        }
        await update_customer(self.db, customer_id, updates)

        # Step 7: MANDATORY audit trail log before returning.
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

    def _validate_bvn(self, bvn: str | None) -> bool:
        """Validate BVN format: exactly 11 digits per CBN standard.

        The BVN (Bank Verification Number) is a 11-digit biometric identifier
        issued by NIBSS. All Nigerian bank accounts are required to have a
        BVN linked to the customer's biometric data.
        """
        if not bvn:
            return False
        return bool(re.match(r"^\d{11}$", bvn.strip()))

    def _validate_nin(self, nin: str | None) -> bool:
        """Validate NIN format: exactly 11 digits per NIMC standard.

        The NIN (National Identification Number) is an 11-digit national
        identity number issued by NIMC. Required for individual Tier-3 accounts.
        """
        if not nin:
            return False
        return bool(re.match(r"^\d{11}$", nin.strip()))

    def _check_pep(self, name: str, existing_pep_status: int) -> bool:
        """Check for PEP indicators in customer name or use existing PEP flag.

        Two-step check:
        1. If the customer is already flagged as PEP in the database, return True.
        2. Otherwise, scan the name for PEP title keywords.

        This heuristic catches newly onboarded customers whose PEP status
        was not recorded at account opening. Step 1 prevents the costly
        string scan for customers who are already confirmed PEPs.
        """
        if existing_pep_status:
            return True
        name_lower = name.lower()
        return any(kw in name_lower for kw in PEP_KEYWORDS)

    def _assign_risk_tier(
        self,
        customer: dict,
        pep_detected: bool,
        missing_fields: list[str],
        bvn_valid: bool,
        nin_valid: bool,
        monitor_context: dict | None,
    ) -> str:
        """Assign a risk tier using a weighted point scoring model.

        Scoring logic (higher score = higher risk):
        - PEP detected: +40 (highest weight — FATF R.12 mandates EDD for all PEPs)
        - Corporate account: +15 (legal entities have more complex beneficial
          ownership structures, increasing layering risk)
        - Missing BVN: +20 (most critical identity document for Nigerian accounts)
        - Missing NIN: +15 (secondary identity document)
        - Missing address: +10 (address is needed for source-of-funds assessment)
        - Invalid BVN: +15 (document exists but cannot be verified)
        - Invalid NIN: +10 (for individual accounts only)
        - High transaction risk score (≥0.7): +25 (context from monitor agent)
        - Moderate transaction risk (0.4-0.7): +10

        The 'never auto-downgrade' rule (score = max(score, existing_score))
        reflects CBN guidance that risk tier reductions require explicit human
        approval to prevent manipulation of risk classifications. An agent
        cannot lower a customer's risk tier, only maintain or raise it.
        """
        score = 0

        # PEP status is the highest single risk factor
        if pep_detected:
            score += 40

        # Corporate accounts have more opacity (beneficial ownership risk)
        if customer.get("account_type") == "corporate":
            score += 15

        # Missing identity documents
        if "bvn" in missing_fields:
            score += 20
        if "nin" in missing_fields:
            score += 15
        if "address" in missing_fields:
            score += 10

        # Invalid documents (present but format-check fails)
        if not bvn_valid:
            score += 15
        if not nin_valid and customer.get("account_type") == "individual":
            score += 10

        # Transaction context: incorporate risk from the monitor agent
        if monitor_context:
            txn_risk_score = monitor_context.get("risk_score", 0)
            if txn_risk_score >= 0.7:
                score += 25
            elif txn_risk_score >= 0.4:
                score += 10

        # Never auto-downgrade: take the higher of the computed score and
        # the score implied by the customer's existing risk tier.
        current_tier = customer.get("risk_tier", "low")
        tier_scores = {"low": 0, "medium": 20, "high": 40, "very_high": 60}
        existing_score = tier_scores.get(current_tier, 0)
        score = max(score, existing_score)  # Never auto-downgrade

        # Map score to risk tier
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
        """Compute verification confidence from data quality signals.

        Confidence components:
        - completeness_score × 0.5: completeness is the primary signal (max 0.5)
        - bvn_valid: adds 0.25 (BVN is the most authoritative ID for Nigerian banks)
        - nin_valid: adds 0.2 (NIN provides secondary biometric confirmation)
        - pep_detected: multiplies by 0.85 (PEP uncertainty — name match is
          heuristic; the actual PEP risk requires deeper investigation)

        Bounded to [0.1, 0.99] — never 0 (even incomplete data has some
        signal) and never 1.0 (no automated system has perfect certainty).
        """
        confidence = completeness_score * 0.5
        if bvn_valid:
            confidence += 0.25
        if nin_valid:
            confidence += 0.2
        # PEP detection via keyword match is uncertain — reduce confidence
        # to flag that additional human review may be needed
        if pep_detected:
            confidence *= 0.85
        return max(0.1, min(0.99, confidence))
