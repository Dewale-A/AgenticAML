"""
Agent 3: Sanctions Screener
Screens customers and counterparties against sanctions lists, PEP databases,
and adverse media. Uses fuzzy name matching with configurable thresholds.

Governance: Confirmed matches MUST auto-block (CBN mandate).
All screening results logged regardless of outcome.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

import aiosqlite

from src.database import create_sanctions_match, list_sanctions_matches, now_wat
from src.data.sanctions_lists import SANCTIONS_DB
from src.governance.audit import log_agent_decision, log_sanctions_screening
from src.models import (
    SanctionsMatchResult,
    SanctionsScreenResult,
)

# Match score thresholds
EXACT_THRESHOLD = 1.0
STRONG_THRESHOLD = 0.85
PARTIAL_THRESHOLD = 0.70
WEAK_THRESHOLD = 0.55


class SanctionsScreenerAgent:
    name = "sanctions_screener_agent"

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def screen(
        self,
        name: str,
        aliases: Optional[List[str]] = None,
        date_of_birth: Optional[str] = None,
        nationality: Optional[str] = None,
        address: Optional[str] = None,
        customer_id: Optional[str] = None,
        transaction_id: Optional[str] = None,
    ) -> SanctionsScreenResult:
        """
        Screen a name against all sanctions lists.
        Logs to audit trail before returning (mandatory regardless of outcome).
        """
        all_names = [name] + (aliases or [])
        all_matches: List[SanctionsMatchResult] = []
        lists_checked = list(SANCTIONS_DB.keys())

        for list_name, entries in SANCTIONS_DB.items():
            for entry in entries:
                best_score, best_name = self._best_match_score(all_names, entry)
                if best_score >= WEAK_THRESHOLD:
                    match_type = self._score_to_type(best_score)
                    action = self._determine_action(match_type, entry, date_of_birth)
                    match_result = SanctionsMatchResult(
                        list_name=list_name,
                        matched_entity=entry.get("name", ""),
                        match_type=match_type,
                        match_score=round(best_score, 4),
                        action_taken=action,
                        details={
                            "matched_on_name": best_name,
                            "entry_type": entry.get("type", "individual"),
                            "entry_nationality": entry.get("nationality"),
                            "entry_dob": entry.get("date_of_birth"),
                            "reason": entry.get("reason", ""),
                        },
                    )
                    all_matches.append(match_result)

                    # Persist match to DB
                    entity_id = transaction_id or customer_id or "unknown"
                    await create_sanctions_match(
                        self.db,
                        {
                            "customer_id": customer_id,
                            "transaction_id": transaction_id,
                            "list_name": list_name,
                            "matched_entity": entry.get("name", ""),
                            "match_type": match_type,
                            "match_score": best_score,
                            "action_taken": action,
                        },
                    )

        # Overall recommendation
        overall = self._overall_recommendation(all_matches)

        # MANDATORY: Log screening to audit trail regardless of outcome
        entity_id = transaction_id or customer_id or name
        await log_sanctions_screening(
            db=self.db,
            entity_id=entity_id,
            name_screened=name,
            lists_checked=lists_checked,
            match_count=len(all_matches),
            recommendation=overall,
        )

        await log_agent_decision(
            db=self.db,
            agent_name=self.name,
            entity_type="transaction" if transaction_id else "customer",
            entity_id=entity_id,
            decision=overall,
            confidence=self._compute_confidence(all_matches),
            details={
                "name_screened": name,
                "match_count": len(all_matches),
                "recommendation": overall,
                "lists_checked": lists_checked,
            },
        )

        return SanctionsScreenResult(
            name_screened=name,
            overall_recommendation=overall,
            matches=all_matches,
            screened_at=now_wat(),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _normalize(self, text: str) -> str:
        """Normalize text for comparison: lowercase, strip accents, remove punctuation."""
        text = text.lower().strip()
        text = unicodedata.normalize("NFKD", text)
        text = text.encode("ascii", "ignore").decode("ascii")
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _similarity(self, a: str, b: str) -> float:
        """Compute string similarity using SequenceMatcher."""
        return SequenceMatcher(None, self._normalize(a), self._normalize(b)).ratio()

    def _token_sort_ratio(self, a: str, b: str) -> float:
        """Sort tokens alphabetically before comparing (handles name order variations)."""
        a_sorted = " ".join(sorted(self._normalize(a).split()))
        b_sorted = " ".join(sorted(self._normalize(b).split()))
        return SequenceMatcher(None, a_sorted, b_sorted).ratio()

    def _best_match_score(self, candidate_names: List[str], entry: Dict) -> tuple[float, str]:
        """Return the best match score against all entry names and aliases."""
        entry_names = [entry.get("name", "")] + entry.get("aliases", [])
        best_score = 0.0
        best_name = ""
        for cname in candidate_names:
            for ename in entry_names:
                if not ename:
                    continue
                s1 = self._similarity(cname, ename)
                s2 = self._token_sort_ratio(cname, ename)
                score = max(s1, s2)
                if score > best_score:
                    best_score = score
                    best_name = cname
        return best_score, best_name

    def _score_to_type(self, score: float) -> str:
        if score >= EXACT_THRESHOLD:
            return "exact"
        elif score >= STRONG_THRESHOLD:
            return "strong"
        elif score >= PARTIAL_THRESHOLD:
            return "partial"
        return "weak"

    def _determine_action(self, match_type: str, entry: Dict, dob: Optional[str]) -> str:
        """Determine action based on match type. Exact/strong = block. Partial/weak = review."""
        if match_type == "exact":
            return "block"
        elif match_type == "strong":
            # Additional DOB confirmation for strong matches
            if dob and entry.get("date_of_birth") and dob == entry["date_of_birth"]:
                return "block"
            return "block"  # Strong match defaults to block per CBN mandate
        elif match_type == "partial":
            return "review"
        return "review"

    def _overall_recommendation(self, matches: List[SanctionsMatchResult]) -> str:
        if not matches:
            return "clear"
        actions = [m.action_taken for m in matches]
        if "block" in actions:
            return "block"
        return "review"

    def _compute_confidence(self, matches: List[SanctionsMatchResult]) -> float:
        if not matches:
            return 0.99  # High confidence in clear result
        # Confidence based on best match score
        best = max(m.match_score for m in matches)
        return round(best, 4)
