"""
Agent 3: Sanctions Screener (Watchlist Screener)

Screens customers and counterparties against multiple sanctions lists and
PEP databases using fuzzy name matching.

CBN AML/CFT guidelines mandate that financial institutions screen ALL
customers and counterparties against the OFAC SDN list, UN Consolidated
Sanctions list, and the NFIU domestic watchlist before processing transactions.
Screening results MUST be logged regardless of outcome.

Fuzzy matching is used instead of exact matching because:
1. Names may be transliterated differently from Arabic/Russian/Chinese.
2. Sanctioned individuals use aliases and name variations to evade detection.
3. Data entry errors in customer records must still match against known names.

Match type thresholds:
- exact (1.0): perfect string match after normalisation
- strong (>=0.85): near-certain match — default to block per CBN mandate
- partial (>=0.70): probable match — requires human review
- weak (>=0.55): possible match — flagged for review, low block probability

match_category field (ROADMAP Phase 1, Section 2):
- 'sanctions': match on OFAC SDN, UN Consolidated, or Nigerian domestic list
- 'pep': match on PEP database (Politically Exposed Person)
- 'adverse_media': match on internal adverse media indicators list
This categorisation supports the "Watchlist Screening" tab sub-category UI
(replacing the simpler "Sanctions" tab) per CBN terminology alignment.

Governance: Confirmed 'block' matches trigger an immediate auto-block and
require senior compliance officer confirmation before any reversal.
All screening results — including clean results — are logged to the audit trail.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

import aiosqlite

from src.data.sanctions_lists import SANCTIONS_DB
from src.database import create_sanctions_match, now_wat
from src.governance.audit import log_agent_decision, log_sanctions_screening
from src.models import (
    SanctionsMatchResult,
    SanctionsScreenResult,
)

# Match score thresholds — tuned to balance false positive rate against
# detection sensitivity for Nigerian banking name patterns.
EXACT_THRESHOLD = 1.0   # Perfect normalised match
STRONG_THRESHOLD = 0.85 # High-confidence match (default: block)
PARTIAL_THRESHOLD = 0.70 # Probable match (human review required)
WEAK_THRESHOLD = 0.55   # Possible match (review flag, low block probability)


class SanctionsScreenerAgent:
    name = "sanctions_screener_agent"

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def screen(
        self,
        name: str,
        aliases: list[str] | None = None,
        date_of_birth: str | None = None,
        nationality: str | None = None,
        address: str | None = None,
        customer_id: str | None = None,
        transaction_id: str | None = None,
    ) -> SanctionsScreenResult:
        """Screen a name against all configured sanctions lists.

        Screening logic:
        1. Build a list of all name variants to check (name + aliases).
        2. For each list entry, compute the best match score across all
           name variants using both string similarity and token-sort ratio.
        3. Any match above the weak threshold (0.55) is recorded.
        4. Determine action based on match type (block/review/clear).
        5. Log all matches to the sanctions_matches table.
        6. Log the screening activity to the audit trail (mandatory even if
           no matches found — CBN requires evidence of screening activity).

        CBN and FATF require screening of BOTH the customer name AND the
        counterparty name. The main.py pipeline calls this method twice.
        """
        # Include aliases in screening to catch known name variants
        all_names = [name] + (aliases or [])
        all_matches: list[SanctionsMatchResult] = []
        lists_checked = list(SANCTIONS_DB.keys())

        for list_name, entries in SANCTIONS_DB.items():
            # Derive the match category from the list name.
            # This mapping drives the Watchlist Screening UI sub-category badges:
            # - sanctions (red): OFAC, UN, domestic sanctions lists
            # - pep (orange): Politically Exposed Person databases
            # - adverse_media (yellow): internal adverse media indicators
            match_category = self._list_to_category(list_name)

            for entry in entries:
                # Find the best match score against this entry's names and aliases
                best_score, best_name = self._best_match_score(all_names, entry)

                # Only process matches above the weak threshold to reduce noise
                if best_score >= WEAK_THRESHOLD:
                    match_type = self._score_to_type(best_score)
                    action = self._determine_action(match_type, entry, date_of_birth)
                    match_result = SanctionsMatchResult(
                        list_name=list_name,
                        matched_entity=entry.get("name", ""),
                        match_type=match_type,
                        match_score=round(best_score, 4),
                        action_taken=action,
                        match_category=match_category,
                        details={
                            "matched_on_name": best_name,
                            "entry_type": entry.get("type", "individual"),
                            "entry_nationality": entry.get("nationality"),
                            "entry_dob": entry.get("date_of_birth"),
                            "reason": entry.get("reason", ""),
                            "match_category": match_category,
                        },
                    )
                    all_matches.append(match_result)

                    # Persist every match (above weak threshold) to the DB.
                    # This includes partial/weak matches that result in 'review'
                    # rather than 'block' — the full match history must be
                    # available for compliance investigations.
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
                            "match_category": match_category,
                        },
                    )

        # Overall recommendation: 'block' if any match recommends block,
        # 'review' if any match requires review, 'clear' if no matches above weak threshold.
        overall = self._overall_recommendation(all_matches)

        # MANDATORY: Log all screening activity to the audit trail.
        # CBN requires evidence that screening was performed, even for clean results.
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
        """Normalise text for comparison: lowercase, strip accents, remove punctuation.

        Normalisation is critical for cross-language matching:
        - NFKD Unicode normalisation splits combined characters (e.g., é → e + ́)
        - ASCII encoding drops the accent marks
        - Punctuation removal handles variations like "Al-Rashidi" vs "Al Rashidi"

        This allows the same underlying name to match regardless of how it
        was romanised or punctuated in different systems.
        """
        text = text.lower().strip()
        text = unicodedata.normalize("NFKD", text)
        text = text.encode("ascii", "ignore").decode("ascii")
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _similarity(self, a: str, b: str) -> float:
        """Compute string similarity using Python's SequenceMatcher.

        SequenceMatcher uses the Ratcliff/Obershelp algorithm, which is
        well-suited for name comparison because it handles common substring
        matches and is length-normalised. This is faster than edit-distance
        and produces more intuitive scores for name variations.
        """
        return SequenceMatcher(None, self._normalize(a), self._normalize(b)).ratio()

    def _token_sort_ratio(self, a: str, b: str) -> float:
        """Compare names after sorting tokens alphabetically.

        This handles name component reordering — 'John Smith' vs 'Smith John',
        or Arabic names where given/family name order varies. Sorting tokens
        before comparison makes the match order-invariant.
        """
        a_sorted = " ".join(sorted(self._normalize(a).split()))
        b_sorted = " ".join(sorted(self._normalize(b).split()))
        return SequenceMatcher(None, a_sorted, b_sorted).ratio()

    def _best_match_score(self, candidate_names: list[str], entry: dict) -> tuple[float, str]:
        """Return the best match score and matched name variant.

        Checks all combinations of:
        - Candidate names (customer name + aliases)
        - Entry names (sanctions list name + aliases)

        For each pair, takes the maximum of string similarity and token-sort
        ratio — using both measures handles cases where one approach
        outperforms the other for a particular name pattern.
        """
        entry_names = [entry.get("name", "")] + entry.get("aliases", [])
        best_score = 0.0
        best_name = ""
        for cname in candidate_names:
            for ename in entry_names:
                if not ename:
                    continue
                s1 = self._similarity(cname, ename)
                s2 = self._token_sort_ratio(cname, ename)
                # Take the maximum of both measures — either approach can
                # produce a better score depending on name structure
                score = max(s1, s2)
                if score > best_score:
                    best_score = score
                    best_name = cname
        return best_score, best_name

    def _score_to_type(self, score: float) -> str:
        """Map a similarity score to a categorical match type.

        The thresholds were calibrated against a test set of Nigerian name
        variations and known sanctions list entries to minimise false positives
        while maintaining high detection rates for genuine matches.
        """
        if score >= EXACT_THRESHOLD:
            return "exact"
        elif score >= STRONG_THRESHOLD:
            return "strong"
        elif score >= PARTIAL_THRESHOLD:
            return "partial"
        return "weak"

    def _determine_action(self, match_type: str, entry: dict, dob: str | None) -> str:
        """Determine the recommended action for a given match.

        CBN mandates that exact and strong matches MUST be blocked.
        Partial and weak matches require human review before any action.

        For strong matches, DOB confirmation is attempted as a secondary
        check. Even without DOB confirmation, strong matches default to
        block because the name similarity is sufficient to warrant it under
        CBN AML guidelines. DOB confirmation is additional evidence, not
        a requirement for blocking.
        """
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

    def _overall_recommendation(self, matches: list[SanctionsMatchResult]) -> str:
        """Determine the overall screening recommendation across all matches.

        'block' takes absolute precedence — a single confirmed match on any
        list is sufficient to block the transaction. 'review' applies if any
        match is partial/weak. 'clear' only if no matches above the weak threshold.
        """
        if not matches:
            return "clear"
        actions = [m.action_taken for m in matches]
        if "block" in actions:
            return "block"
        return "review"

    def _compute_confidence(self, matches: list[SanctionsMatchResult]) -> float:
        """Compute screening confidence based on match quality.

        No matches → 0.99 confidence (very high confidence in a clean result).
        Any matches → confidence equals the best match score, reflecting
        that the higher the similarity, the more certain the hit.
        """
        if not matches:
            return 0.99  # High confidence in clear result
        # Confidence based on best match score
        best = max(m.match_score for m in matches)
        return round(best, 4)

    def _list_to_category(self, list_name: str) -> str:
        """Map a sanctions list name to its watchlist category.

        This categorisation is used by the Watchlist Screening UI tab to filter
        matches into three sub-categories with distinct badge colours (ROADMAP Section 2):
        - sanctions (red): OFAC SDN, UN Consolidated, Nigerian domestic sanctions
        - pep (orange): Politically Exposed Person databases
        - adverse_media (yellow): adverse media and legal proceedings indicators

        The mapping is based on the list_name keys defined in SANCTIONS_DB.
        Any unrecognised list defaults to 'sanctions' (most restrictive category).
        """
        name_upper = list_name.upper()
        if "PEP" in name_upper:
            return "pep"
        if "ADVERSE" in name_upper or "MEDIA" in name_upper:
            return "adverse_media"
        # OFAC, UN, NIGERIAN_DOMESTIC, and internal watchlists default to 'sanctions'
        return "sanctions"
