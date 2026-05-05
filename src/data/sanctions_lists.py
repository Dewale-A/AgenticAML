"""
Sanctions and PEP lists for AgenticAML.

In simulated mode (default, LIVE_SANCTIONS=false): serves the hardcoded
SANCTIONS_DB entries designed to match seed customers for demo and testing.

In live mode (LIVE_SANCTIONS=true): merges real OFAC SDN and UN Consolidated
data from official sources with the simulated domestic/PEP/internal lists.
Falls back to the full simulated SANCTIONS_DB if live downloads fail.

Covers: OFAC SDN, UN Consolidated, Nigerian domestic watchlist, PEP database.
Includes near-matches to demo customer names for fuzzy matching demonstration.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Live data flag
# ---------------------------------------------------------------------------
# Controls whether get_sanctions_db() attempts real downloads.
# Default is False so existing tests pass without network access.
# Set LIVE_SANCTIONS=true in production or when testing live integration.
LIVE_DATA_ENABLED: bool = os.getenv("LIVE_SANCTIONS", "false").lower() == "true"


# ---------------------------------------------------------------------------
# OFAC SDN List (simulated entries)
# ---------------------------------------------------------------------------
# The US Treasury Office of Foreign Assets Control (OFAC) Specially Designated
# Nationals (SDN) list is the primary international sanctions reference.
# Nigerian banks with US dollar correspondent banking relationships are required
# by US law to screen against this list. CBN also mandates its use directly
# under BSD/DIR/PUB/LAB/019/002.
# ---------------------------------------------------------------------------

OFAC_SDN = [
    {
        "name": "Ahmed Al-Rashidi",
        "aliases": ["A. Al-Rashidi", "Ahmed Rashidi", "Ahmad Al-Rashidi"],  # Common name variants for fuzzy matching
        "type": "individual",
        "nationality": "YE",
        "date_of_birth": "1971-03-15",
        "reason": "Terrorism financing, SDGT",
        "program": "SDGT",  # Specially Designated Global Terrorist designation
    },
    {
        "name": "Mahmoud Karimi Trading Co",
        "aliases": ["MK Trading", "Karimi Exports"],
        "type": "entity",
        "nationality": "IR",  # Iran — OFAC IRAN sanctions program; all transactions blocked
        "reason": "Sanctions evasion, IRAN program",
        "program": "IRAN",
    },
    {
        "name": "Viktor Petrov",
        "aliases": ["V. Petrov", "Victor Petrov", "Viktor P."],
        "type": "individual",
        "nationality": "RU",  # Russia — OFAC RUSSIA program post-2022 designations
        "date_of_birth": "1965-11-22",
        "reason": "Russian sanctions, designated oligarch",
        "program": "RUSSIA",
    },
    {
        "name": "Kim Chol",
        "aliases": ["Kim Chol-su", "Chol Kim"],
        "type": "individual",
        "nationality": "KP",  # North Korea — DPRK WMD proliferation; highest-risk jurisdiction
        "date_of_birth": "1978-06-01",
        "reason": "DPRK WMD proliferation",
        "program": "DPRK",
    },
    {
        "name": "Pyongyang Tech Industries",
        "aliases": ["PTI", "PY Tech"],
        "type": "entity",
        "nationality": "KP",
        "reason": "DPRK front company, sanctions evasion",
        "program": "DPRK",
    },
    {
        "name": "Hassan Ibrahim Musa",
        # Note: this name is a near-match to seed customer cust_002 "Emeka Nwosu" — it is
        # intentionally designed to produce a weak (false positive) match for demo purposes,
        # illustrating why human review is required before blocking on low-confidence matches
        "aliases": ["H.I. Musa", "Hassan Musa Ibrahim"],
        "type": "individual",
        "nationality": "SD",  # Sudan — OFAC SUDAN program (militia financing)
        "date_of_birth": "1969-08-14",
        "reason": "Sudan sanctions, militia financing",
        "program": "SUDAN",
    },
    {
        "name": "Alejandro Rodriguez Cartel",
        "aliases": ["ARC", "Rodriguez Organization"],
        "type": "entity",
        "nationality": "MX",
        "reason": "Narco trafficking, drug money laundering",
        "program": "SDNTK",  # Specially Designated Narcotics Trafficking Kingpin
    },
    {
        "name": "Tariq Al-Zawahiri",
        "aliases": ["T. Zawahiri", "Tariq Zawahiri"],
        "type": "individual",
        "nationality": "EG",
        "date_of_birth": "1972-04-30",
        "reason": "Al-Qaeda affiliate, terrorism financing",
        "program": "SDGT",
    },
    {
        "name": "Golden Star Resources LLC",
        "aliases": ["GSR LLC", "Golden Star Resources"],
        "type": "entity",
        "nationality": "CY",  # Cyprus — common shell company jurisdiction for Russia sanctions evasion
        "reason": "Shell company, Russian sanctions evasion",
        "program": "RUSSIA",
    },
    {
        "name": "Abdul Rahman Al-Fadhli",
        "aliases": ["A.R. Al-Fadhli", "Rahman Fadhli"],
        "type": "individual",
        "nationality": "KW",
        "date_of_birth": "1980-02-11",
        "reason": "ISIS financing",
        "program": "SDGT",
    },
]


# ---------------------------------------------------------------------------
# UN Consolidated Sanctions List (simulated entries)
# ---------------------------------------------------------------------------
# The UN Security Council Consolidated List contains individuals and entities
# subject to measures imposed by UN Security Council Resolutions.
# All UN member states (including Nigeria) are legally obligated to enforce
# these designations under Chapter VII of the UN Charter.
# CBN requires Nigerian banks to screen all transactions against this list.
# ---------------------------------------------------------------------------

UN_CONSOLIDATED = [
    {
        "name": "Mohammed Al-Qaeda Affiliate",
        "aliases": ["M. Al-Qaeda", "Mohammed AQ"],
        "type": "individual",
        "nationality": "AF",
        "date_of_birth": "1975-01-01",
        "reason": "UN 1267 - Al-Qaeda affiliated",
        "program": "UN_1267",  # Al-Qaeda/ISIS sanctions regime
    },
    {
        "name": "Libyan Shield Force",
        "aliases": ["LSF", "Shield Force Libya"],
        "type": "entity",
        "nationality": "LY",
        "reason": "UN 1970 - Libya arms embargo",
        "program": "UN_1970",
    },
    {
        "name": "Yemen Arms Trading Network",
        "aliases": ["YATN", "Yemen Trading Network"],
        "type": "entity",
        "nationality": "YE",
        "reason": "UN 2140 - Yemen arms embargo",
        "program": "UN_2140",
    },
    {
        "name": "Jong-un Kim Supply Chain",
        "aliases": ["Kim Supply Chain", "JKSC"],
        "type": "entity",
        "nationality": "KP",
        "reason": "UN 1718 - DPRK proliferation",
        "program": "UN_1718",  # Addresses DPRK's nuclear/WMD programme
    },
    {
        "name": "Ibrahim Al-Hassan",
        "aliases": ["I. Al-Hassan", "Ibrahim Hassan"],
        "type": "individual",
        "nationality": "ML",  # Mali — UN 2374 targets destabilising actors in the Sahel
        "date_of_birth": "1982-09-25",
        "reason": "UN 2374 - Mali stabilization",
        "program": "UN_2374",
    },
    {
        "name": "Kabila Mining Enterprises",
        "aliases": ["KME", "Kabila Mines"],
        "type": "entity",
        "nationality": "CD",  # DRC — UN 1533 targets conflict minerals financing
        "reason": "UN 1533 - DRC conflict minerals",
        "program": "UN_1533",
    },
    {
        "name": "Ahmad Shah Massoud Finance",
        "aliases": ["ASMF", "Massoud Finance"],
        "type": "entity",
        "nationality": "AF",
        "reason": "UN 1988 - Taliban financing",
        "program": "UN_1988",  # Taliban-specific sanctions regime
    },
    {
        "name": "Central African Republic Arms",
        "aliases": ["CAR Arms", "CARA"],
        "type": "entity",
        "nationality": "CF",
        "reason": "UN 2127 - CAR arms embargo",
        "program": "UN_2127",
    },
]


# ---------------------------------------------------------------------------
# Nigerian Domestic Watchlist / NFIU Watchlist (simulated)
# ---------------------------------------------------------------------------
# The NFIU (Nigerian Financial Intelligence Unit) maintains a domestic watchlist
# that consolidates designations from:
#   - EFCC (Economic and Financial Crimes Commission)
#   - NDLEA (National Drug Law Enforcement Agency)
#   - DSS (Department of State Services)
#   - CBN enforcement actions
# Nigerian banks are required to screen against this list in addition to
# international lists. Matches must be reported to NFIU within 24 hours.
# ---------------------------------------------------------------------------

NIGERIAN_DOMESTIC = [
    {
        "name": "Emeka Okonkwo Fraudster",
        "aliases": ["E. Okonkwo", "Emeka O."],
        "type": "individual",
        "nationality": "NG",
        "date_of_birth": "1985-07-20",
        "reason": "EFCC conviction - advance fee fraud (419)",
        "program": "EFCC_WATCHLIST",  # 419 fraud — a prominent Nigeria-specific financial crime
    },
    {
        "name": "Lagos Ponzi Scheme Ltd",
        "aliases": ["LPS Ltd", "Lagos Ponzi"],
        "type": "entity",
        "nationality": "NG",
        "reason": "SEC Nigeria enforcement - Ponzi scheme",
        "program": "SEC_NG",  # SEC Nigeria — securities and investment fraud
    },
    {
        # Exact name match to seed customer cust_015 "Chukwuemeka Eze"
        # This entry deliberately mirrors the seed customer to trigger a high-confidence
        # (0.97) match and demonstrate the auto-block flow in sanctions_screener_agent
        "name": "Chukwuemeka Eze",
        "aliases": ["C. Eze", "Chukwu Eze", "Emeka Eze"],
        "type": "individual",
        "nationality": "NG",
        "date_of_birth": "1979-11-03",
        "reason": "NDLEA - drug trafficking, money laundering",
        "program": "NDLEA",  # NDLEA = National Drug Law Enforcement Agency
    },
    {
        "name": "Yusuf Musa Bello",
        "aliases": ["Y.M. Bello", "Yusuf Bello", "Musa Bello"],
        "type": "individual",
        "nationality": "NG",
        "date_of_birth": "1988-04-18",
        "reason": "EFCC investigation - oil bunkering fraud",
        "program": "EFCC_WATCHLIST",
    },
    {
        "name": "Port Harcourt Oil Trade Network",
        "aliases": ["PHOTN", "PH Oil Trade"],
        "type": "entity",
        "nationality": "NG",
        "reason": "NNPC investigation - crude oil theft proceeds",
        "program": "NNPC_INVESTIGATION",  # NNPC = Nigerian National Petroleum Corporation
    },
    {
        "name": "Abdullahi Ibrahim Tanko",
        # Near-match to seed customer cust_013 "Musa Ibrahim Tanko" — shared surname "Ibrahim Tanko"
        # produces a moderate fuzzy score, demonstrating the review (not auto-block) path
        "aliases": ["A.I. Tanko", "Abdullahi Tanko", "Ibrahim Tanko"],
        "type": "individual",
        "nationality": "NG",
        "date_of_birth": "1975-12-30",
        "reason": "EFCC - terrorism financing (Boko Haram links)",
        "program": "TERRORISM_FINANCING",
    },
    {
        "name": "Seun Adebayo Tech Solutions",
        # Entity name containing "Adebayo" — near-match to seed customer cust_007
        # "Oluwaseun Adebayo". Tests whether the screener correctly avoids false positives
        # on partial surname matches when the entity type differs.
        "aliases": ["SATS", "Adebayo Tech"],
        "type": "entity",
        "nationality": "NG",
        "reason": "CBN enforcement - unlicensed forex trading, layering",
        "program": "CBN_ENFORCEMENT",  # CBN enforcement actions for unlicensed FX dealing
    },
    {
        "name": "Blessing Okafor Eze",
        "aliases": ["Blessing Okafor", "B. Okafor", "Blessing Eze"],
        "type": "individual",
        "nationality": "NG",
        "date_of_birth": "1992-05-14",
        "reason": "EFCC - BEC fraud proceeds laundering",
        "program": "EFCC_WATCHLIST",  # BEC = Business Email Compromise — major vector for ML proceeds
    },
    {
        "name": "Kano Textile Money Exchange",
        "aliases": ["KTME", "Kano Money Exchange"],
        "type": "entity",
        "nationality": "NG",
        "reason": "CBN - unlicensed BDC, TBML indicators",
        "program": "CBN_ENFORCEMENT",  # TBML = Trade-Based Money Laundering; BDC = Bureau de Change
    },
    {
        "name": "Alhaji Usman Garba Musa",
        # Near-match to seed customer cust_014 "Usman Garba Musa" — title "Alhaji" is the only
        # difference. Produces a strong fuzzy score (~0.92) to test the review-path threshold.
        "aliases": ["Usman Garba", "U.G. Musa", "Alhaji Usman"],
        "type": "individual",
        "nationality": "NG",
        "date_of_birth": "1968-03-08",
        "reason": "EFCC - public fund diversion, corruption",
        "program": "CORRUPTION",
    },
]


# ---------------------------------------------------------------------------
# PEP Database (simulated Nigerian PEPs with near-matches to seed customers)
# ---------------------------------------------------------------------------
# Politically Exposed Persons (PEPs) are individuals who hold or have held
# prominent public positions. Under FATF Recommendation 12 and CBN KYC Regulations,
# all PEPs must be identified and subjected to Enhanced Due Diligence (EDD).
# This is NOT a sanctions list — PEP status alone does not prohibit banking;
# it mandates heightened monitoring and source-of-funds verification.
# ---------------------------------------------------------------------------

PEP_DATABASE = [
    {
        # Exact match to seed customer cust_008 "Senator Adewale Ogundimu"
        # Produces a 1.0 match score and triggers the PEP EDD workflow
        "name": "Senator Adewale Ogundimu",
        "aliases": ["Sen. Adewale Ogundimu", "Adewale Ogundimu"],
        "type": "individual",
        "nationality": "NG",
        "date_of_birth": "1962-08-20",
        "position": "Senator, Lagos State",  # Active legislator with budget oversight powers
        "reason": "Current PEP - Senate Finance Committee",
        "program": "PEP",
    },
    {
        "name": "Honourable Kemi Adeleke",
        "aliases": ["Hon. Kemi Adeleke", "Kemi Adeleke"],
        "type": "individual",
        "nationality": "NG",
        "date_of_birth": "1975-02-14",
        "position": "House of Representatives Member",
        "reason": "Current PEP - House Appropriations Committee",
        "program": "PEP",
    },
    {
        "name": "Engr. Ibrahim Mohammed",
        "aliases": ["Ibrahim Mohammed", "I. Mohammed"],
        "type": "individual",
        "nationality": "NG",
        "date_of_birth": "1970-11-05",
        "position": "Former Minister of Works",
        "reason": "Former PEP - government contractor relationships",
        "program": "PEP",  # Former PEPs remain in DB — CBN requires monitoring for 5 years post-tenure
    },
    {
        "name": "Chief Nnamdi Okoye",
        "aliases": ["Nnamdi Okoye", "Chief N. Okoye"],
        "type": "individual",
        "nationality": "NG",
        "date_of_birth": "1958-06-30",
        "position": "State Government Commissioner (Retired)",
        "reason": "Former PEP - state budget oversight",
        "program": "PEP",
    },
    {
        "name": "Ambassador Fatima Al-Hassan",
        "aliases": ["Fatima Al-Hassan", "Amb. Fatima Al-Hassan"],
        "type": "individual",
        "nationality": "NG",
        "date_of_birth": "1967-09-12",
        "position": "Nigerian Ambassador (Retired)",
        "reason": "Former PEP - diplomatic",
        "program": "PEP",
    },
    {
        "name": "General Emeka Chukwudifu (Rtd)",
        "aliases": ["Emeka Chukwudifu", "Gen. Emeka Chukwudifu"],
        "type": "individual",
        "nationality": "NG",
        "date_of_birth": "1955-04-01",
        "position": "Retired Military General",
        "reason": "Former PEP - military high command",
        "program": "PEP",
    },
    {
        "name": "Dr. Amina Suleiman",
        # This entry also appears as the model validator in seed data — demonstrates that
        # the same individual can be both a PEP and a legitimate professional. The screener
        # must distinguish context; her appearance as a compliance professional (not a customer)
        # would not trigger a PEP alert in a real deployment.
        "aliases": ["Amina Suleiman", "Dr. A. Suleiman"],
        "type": "individual",
        "nationality": "NG",
        "date_of_birth": "1978-01-22",
        "position": "NNPC Board Director",
        "reason": "Current PEP - state enterprise board",
        "program": "PEP",
    },
    {
        "name": "Alhaji Bello Rabiu Kano",
        # Full formal name of the traditional ruler — produces a partial match against
        # seed customer cust_020 "Bello Rabiu" and will score high in fuzzy matching
        "aliases": ["Bello Rabiu", "A. Bello Rabiu Kano"],
        "type": "individual",
        "nationality": "NG",
        "date_of_birth": "1960-07-17",
        "position": "Kano State Emirate Council Member",
        "reason": "PEP - traditional ruler with political influence",
        "program": "PEP",
    },
    # Near-match to seed customer "Bello Rabiu" (cust_020)
    # A second, shorter PEP entry with same name and close DOB forces the screener
    # to return multiple potential matches — demonstrates how the best-score
    # selection logic works when a name appears more than once in the database
    {
        "name": "Bello Rabiu",
        "aliases": ["B. Rabiu", "Bellor Rabiu"],
        "type": "individual",
        "nationality": "NG",
        "date_of_birth": "1982-03-10",  # Same DOB as cust_020 — strengthens match confidence
        "position": "Local Government Councilor",
        "reason": "PEP - local government",
        "program": "PEP",
    },
]


# ---------------------------------------------------------------------------
# Internal watchlist (added by compliance team)
# ---------------------------------------------------------------------------
# Banks maintain their own internal watchlists that supplement external lists.
# These capture individuals who have not been formally sanctioned but have
# previously triggered SARs, failed KYC, or been linked to suspicious networks.
# CBN encourages maintaining such lists as part of a risk-based AML programme.
# ---------------------------------------------------------------------------

INTERNAL_WATCHLIST = [
    {
        # Near-match to seed customer cust_006 "Tunde Bakare" — an existing SAR
        # was previously filed against this name. The "Tunde Bakare Suspicious" variant
        # avoids an exact hit but will score ~0.85 in fuzzy matching, triggering review.
        "name": "Tunde Bakare Suspicious",
        "aliases": ["Tunde Bakare", "T. Bakare"],  # Exact alias match ensures the customer is caught
        "type": "individual",
        "nationality": "NG",
        "date_of_birth": "1990-08-15",
        "reason": "Internal watchlist - previous SAR filed, pattern of structuring",
        "program": "INTERNAL",
    },
    {
        "name": "Taiwo Adelabu",
        "aliases": ["T. Adelabu", "Taiwo A."],
        "type": "individual",
        "nationality": "NG",
        "date_of_birth": "1987-12-05",
        "reason": "Internal watchlist - failed KYC, multiple accounts",
        "program": "INTERNAL",
    },
    {
        "name": "Rapid Cash Express NG",
        "aliases": ["RCE NG", "Rapid Cash Express"],
        "type": "entity",
        "nationality": "NG",
        "reason": "Internal watchlist - linked to layering scheme",
        "program": "INTERNAL",
    },
]


# ---------------------------------------------------------------------------
# Consolidated sanctions DB
# ---------------------------------------------------------------------------
# Single dictionary mapping list names to their entries.
# The sanctions_screener_agent iterates over all lists in this dict so that
# adding a new list only requires inserting it here — no agent code changes needed.
# ---------------------------------------------------------------------------

SANCTIONS_DB: dict[str, list[dict]] = {
    "OFAC_SDN": OFAC_SDN,
    "UN_CONSOLIDATED": UN_CONSOLIDATED,
    "NIGERIAN_DOMESTIC": NIGERIAN_DOMESTIC,
    "PEP_DATABASE": PEP_DATABASE,
    "INTERNAL_WATCHLIST": INTERNAL_WATCHLIST,
}


def get_all_entries() -> list[dict]:
    """Return all entries across all lists."""
    entries = []
    for list_name, entries_list in SANCTIONS_DB.items():
        # Inject the source list name into each entry so the screener can report
        # which list produced a match without having to maintain separate lookup tables
        for entry in entries_list:
            entries.append({**entry, "list_name": list_name})
    return entries


def count_by_list() -> dict[str, int]:
    """Return count of entries per list."""
    # Useful for dashboard stats and validating list coverage (CBN audit requirement)
    return {name: len(entries) for name, entries in SANCTIONS_DB.items()}


# ---------------------------------------------------------------------------
# Live-data accessor
# ---------------------------------------------------------------------------

async def get_sanctions_db() -> dict[str, list[dict]]:
    """Return the active sanctions database, using live data when enabled.

    When LIVE_DATA_ENABLED is False (the default): returns SANCTIONS_DB
    directly without any network calls. This preserves existing test behaviour
    and is the safe default for development and CI environments.

    When LIVE_DATA_ENABLED is True: merges real OFAC SDN and UN Consolidated
    entries (downloaded from official sources) with the locally maintained
    simulated NIGERIAN_DOMESTIC, PEP_DATABASE, and INTERNAL_WATCHLIST entries.
    If any live download fails, logs a warning and falls back to the full
    simulated SANCTIONS_DB so screening continues uninterrupted.

    The merged structure keeps the same dict[str, list[dict]] shape as
    SANCTIONS_DB so all callers (agents, list manager) need no structural changes.
    """
    if not LIVE_DATA_ENABLED:
        # Fast path: no network, no I/O. Return simulated data as-is.
        # This is the path taken in all tests and local development.
        return SANCTIONS_DB

    # Live mode: attempt to serve real OFAC + UN data merged with local lists.
    # Import deferred to this function so the module does not import httpx or
    # trigger any network activity at module load time when LIVE_SANCTIONS=false.
    try:
        from src.data.live_sanctions import get_cached_entries

        merged: dict[str, list[dict]] = {}

        # OFAC SDN: try live cache first, fall back to simulated entries.
        ofac_live = get_cached_entries("ofac_sdn_live")
        if ofac_live is not None:
            merged["OFAC_SDN"] = ofac_live
            logger.debug(f"get_sanctions_db: OFAC SDN live ({len(ofac_live)} entries)")
        else:
            # Live data not yet downloaded (server just started, or download failed).
            # Use simulated entries so screening is never disabled.
            merged["OFAC_SDN"] = OFAC_SDN
            logger.warning(
                "get_sanctions_db: OFAC SDN live cache empty, using simulated fallback "
                "(run POST /screening-lists/update to download real data)"
            )

        # UN Consolidated: same pattern as OFAC.
        un_live = get_cached_entries("un_consolidated_live")
        if un_live is not None:
            merged["UN_CONSOLIDATED"] = un_live
            logger.debug(f"get_sanctions_db: UN Consolidated live ({len(un_live)} entries)")
        else:
            merged["UN_CONSOLIDATED"] = UN_CONSOLIDATED
            logger.warning(
                "get_sanctions_db: UN Consolidated live cache empty, using simulated fallback"
            )

        # Domestic, PEP, and internal lists remain simulated.
        # These are locally maintained and do not have public download sources.
        merged["NIGERIAN_DOMESTIC"] = NIGERIAN_DOMESTIC
        merged["PEP_DATABASE"] = PEP_DATABASE
        merged["INTERNAL_WATCHLIST"] = INTERNAL_WATCHLIST

        return merged

    except Exception as e:
        # Any unexpected error in the live data path must not break screening.
        # Log the error and return the full simulated database as a safe fallback.
        logger.error(
            f"get_sanctions_db: live data error ({e}), falling back to simulated SANCTIONS_DB"
        )
        return SANCTIONS_DB
