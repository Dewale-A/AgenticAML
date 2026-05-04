"""
Sample transaction generator for AgenticAML demo data.
Generates realistic Nigerian banking transactions with suspicious patterns.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

# West Africa Time (UTC+1) — all timestamps anchored to WAT for CBN reporting compliance
WAT = timezone(timedelta(hours=1))

# Subset of transaction types supported by the Nigerian payments ecosystem.
# mobile_money covers NIP/NIBSS transfers; pos_payment covers PoS terminal transactions.
TRANSACTION_TYPES = [
    "transfer", "cash_deposit", "cash_withdrawal",
    "international_wire", "mobile_money", "pos_payment",
]

# Channels mirror the CBN-recognised channels in the Nigeria Payments System.
# USSD is critical in Nigeria — accounts for a large share of rural financial inclusion transactions.
CHANNELS = ["branch", "mobile_app", "internet_banking", "atm", "pos", "ussd"]

# Major Nigerian commercial banks licensed by CBN.
# Used to generate realistic counterparty bank names in sample transactions.
NIGERIAN_BANKS = [
    "GTBank", "Access Bank", "Zenith Bank", "First Bank", "UBA",
    "FCMB", "Stanbic IBTC", "Sterling Bank", "Union Bank", "Fidelity Bank",
    "Ecobank", "Polaris Bank", "Wema Bank", "Heritage Bank", "SunTrust Bank",
]

# Nigerian states used as domestic geolocation labels.
# Transactions staying within Nigeria are lower risk than cross-border wires.
NIGERIAN_STATES = [
    "Lagos", "Abuja", "Kano", "Port Harcourt", "Ibadan",
    "Kaduna", "Enugu", "Onitsha", "Aba", "Warri",
]

# International destinations for wire transactions.
# Tehran (IR), Pyongyang (KP), and Khartoum (SD) are OFAC/UN sanctioned jurisdictions —
# transactions to these destinations automatically trigger HIGH_RISK_GEOGRAPHY alerts.
INTERNATIONAL_LOCATIONS = [
    "London, UK", "Dubai, UAE", "New York, USA", "Guangzhou, CN",
    "Johannesburg, ZA", "Accra, GH", "Nairobi, KE", "Tehran, IR",
    "Pyongyang, KP", "Khartoum, SD",
]


def random_account() -> str:
    """Generate a realistic 10-digit Nigerian account number."""
    # Nigerian NUBAN account numbers are exactly 10 digits (CBN NUBAN standard)
    return "".join([str(random.randint(0, 9)) for _ in range(10)])


def random_amount(min_amt: float, max_amt: float, round_to: int = 100) -> float:
    """Generate a random amount rounded to nearest NGN round_to."""
    amt = random.uniform(min_amt, max_amt)
    # Round to the nearest unit (default NGN 100) to produce realistic-looking amounts
    return round(amt / round_to) * round_to


def random_timestamp(days_back_max: int = 90, days_back_min: int = 0) -> str:
    """Generate a random WAT timestamp within a date range."""
    days = random.uniform(days_back_min, days_back_max)
    ts = datetime.now(WAT) - timedelta(days=days)
    return ts.isoformat()


def generate_normal_transaction(customer_id: str, customer_name: str) -> dict:
    """Generate a normal, non-suspicious transaction."""
    direction = random.choice(["inbound", "outbound"])
    # Limit normal transactions to everyday retail types — avoids accidental pattern triggers
    txn_type = random.choice(["transfer", "mobile_money", "pos_payment"])
    return {
        "customer_id": customer_id,
        "counterparty_name": f"Customer {random.randint(1000, 9999)}",
        "counterparty_account": random_account(),
        # NGN 5,000 - 500,000 range represents typical retail/SME activity
        "amount": random_amount(5_000, 500_000),
        "currency": "NGN",
        "transaction_type": txn_type,
        "channel": random.choice(CHANNELS),
        "direction": direction,
        "geo_location": random.choice(NIGERIAN_STATES) + ", NG",
        # At least 1 day old so it doesn't overlap with "today's" suspicious activity
        "timestamp": random_timestamp(90, 1),
        "status": "cleared",
        "risk_score": round(random.uniform(0.03, 0.18), 3),
    }


def generate_structuring_transactions(customer_id: str, count: int = 5) -> list[dict]:
    """Generate structuring pattern: multiple cash txns just below NGN 5M."""
    # Structuring (smurfing): deliberately breaking a large amount into multiple deposits
    # just below the NGN 5,000,000 Currency Transaction Report (CTR) threshold to evade
    # mandatory reporting. This is a criminal offence under MLPPA 2022, Section 15.
    txns = []
    base_time = datetime.now(WAT) - timedelta(days=random.randint(1, 30))
    for i in range(count):
        # All amounts in the NGN 4.4M - 4.95M band — clearly sub-threshold but large
        amount = random_amount(4_400_000, 4_950_000, round_to=50_000)
        # Space deposits ~4 hours apart to simulate visits to different branches
        ts = base_time - timedelta(hours=i * 4 + random.uniform(0, 3))
        txns.append({
            "customer_id": customer_id,
            "counterparty_name": f"Cash Depositor {i+1}",  # Different depositor names (smurfing)
            "counterparty_account": random_account(),
            "amount": amount,
            "currency": "NGN",
            "transaction_type": "cash_deposit",
            "channel": random.choice(["branch", "atm"]),  # Physical channels for cash
            "direction": "inbound",
            "geo_location": random.choice(NIGERIAN_STATES) + ", NG",
            "timestamp": ts.isoformat(),
            "status": "flagged",  # Pre-flagged to show alert state in demo
            "risk_score": round(random.uniform(0.65, 0.88), 3),
        })
    return txns


def generate_rapid_movement_transactions(customer_id: str) -> list[dict]:
    """Generate rapid fund movement: large inflows followed quickly by outflows."""
    # Classic ML layering typology: funds arrive from an offshore source then are
    # immediately dispersed across multiple domestic accounts to break the audit trail.
    # FATF Typology: "Pass-through" or "funnel account" pattern.
    txns = []
    base_time = datetime.now(WAT) - timedelta(days=random.randint(2, 15))
    # Large inflow amount — NGN 8M-25M is significant enough to trigger materiality gate
    amount = random_amount(8_000_000, 25_000_000, round_to=1_000_000)

    # Large inflow — single international wire from a high-risk origin
    txns.append({
        "customer_id": customer_id,
        "counterparty_name": "Offshore Sender Ltd",
        "counterparty_account": random_account(),
        "amount": amount,
        "currency": "NGN",
        "transaction_type": "international_wire",
        "channel": "internet_banking",
        "direction": "inbound",
        # Origin restricted to high-risk but non-sanctioned locations for this pattern
        "geo_location": random.choice(["Dubai, UAE", "London, UK", "Guangzhou, CN"]),
        "timestamp": base_time.isoformat(),
        "status": "flagged",
        "risk_score": round(random.uniform(0.62, 0.82), 3),
    })

    # Quick outflows within 24-48 hours — dispersal to multiple beneficiaries
    remaining = amount
    for i in range(random.randint(3, 6)):
        if remaining <= 100_000:
            break
        # Each outflow is 30-70% of remaining balance, ensuring rapid depletion
        out_amt = random_amount(min(remaining * 0.3, 5_000_000), min(remaining * 0.7, 10_000_000), 500_000)
        remaining -= out_amt
        # 6-36 hour window demonstrates the "rapid" nature of the movement
        ts = base_time + timedelta(hours=random.uniform(6, 36))
        txns.append({
            "customer_id": customer_id,
            "counterparty_name": f"Recipient Account {i+1}",
            "counterparty_account": random_account(),
            "amount": out_amt,
            "currency": "NGN",
            "transaction_type": "transfer",
            "channel": "internet_banking",
            "direction": "outbound",
            "geo_location": random.choice(NIGERIAN_STATES) + ", NG",
            "timestamp": ts.isoformat(),
            "status": "flagged",
            "risk_score": round(random.uniform(0.55, 0.78), 3),
        })

    return txns


def generate_dormant_account_transaction(customer_id: str) -> dict:
    """Generate a large transaction on a previously dormant account."""
    # CBN guidelines define a dormant account as one with no customer-initiated transactions
    # for 12 months (banks) or 6 months (MFBs). A sudden large transaction on a dormant
    # account is a CBN red flag that mandates enhanced monitoring and possible STR filing.
    return {
        "customer_id": customer_id,
        "counterparty_name": "Unknown Counterparty",  # Unknown origin adds to suspicion
        "counterparty_account": random_account(),
        # NGN 5M-20M is a material amount that would require CTR even on an active account
        "amount": random_amount(5_000_000, 20_000_000, 1_000_000),
        "currency": "NGN",
        "transaction_type": "cash_deposit",
        "channel": "branch",    # Branch cash deposit — no digital trail for source of funds
        "direction": "inbound",
        "geo_location": random.choice(NIGERIAN_STATES) + ", NG",
        "timestamp": (datetime.now(WAT) - timedelta(days=1)).isoformat(),
        "status": "flagged",
        "risk_score": round(random.uniform(0.62, 0.78), 3),
    }


def generate_round_amount_transactions(customer_id: str, count: int = 6) -> list[dict]:
    """Generate pattern of round-number transfers (classic ML indicator)."""
    # Exact round-figure amounts (5M, 10M, 15M, 20M) are a well-documented FATF typology.
    # Unlike structuring (amounts just below a threshold), this pattern reflects
    # deliberate use of convenient round numbers to conceal the true economic purpose.
    txns = []
    # Escalating sequence makes the pattern obvious — 5M → 10M → 15M → 20M
    round_amounts = [5_000_000, 10_000_000, 15_000_000, 20_000_000, 5_000_000, 10_000_000]
    for i in range(min(count, len(round_amounts))):
        days_ago = random.randint(1, 60)  # Spread across 60-day lookback window
        txns.append({
            "customer_id": customer_id,
            "counterparty_name": f"Recipient {chr(65+i)}",  # A, B, C, D, E, F — different recipients
            "counterparty_account": random_account(),
            "amount": float(round_amounts[i]),
            "currency": "NGN",
            "transaction_type": "transfer",
            "channel": random.choice(["internet_banking", "mobile_app"]),
            "direction": "outbound",
            "geo_location": random.choice(NIGERIAN_STATES) + ", NG",
            "timestamp": (datetime.now(WAT) - timedelta(days=days_ago)).isoformat(),
            "status": "flagged",
            "risk_score": round(random.uniform(0.38, 0.58), 3),
        })
    return txns


def generate_high_risk_geo_transaction(customer_id: str) -> dict:
    """Generate a transaction involving a high-risk jurisdiction."""
    # Transactions to OFAC/UN sanctioned countries (Iran, DPRK, Sudan) are prohibited
    # under US secondary sanctions and CBN's Anti-Money Laundering/CFT frameworks.
    # CBN requires mandatory EDD and STR consideration for any such transaction.
    return {
        "customer_id": customer_id,
        "counterparty_name": "International Trading Corp",
        "counterparty_account": random_account(),
        "amount": random_amount(2_000_000, 15_000_000, 500_000),
        "currency": "NGN",
        "transaction_type": "international_wire",
        "channel": "internet_banking",
        "direction": "outbound",
        # Restricted to the three most high-risk OFAC/UN-designated jurisdictions in demo
        "geo_location": random.choice(["Tehran, IR", "Pyongyang, KP", "Khartoum, SD"]),
        "timestamp": (datetime.now(WAT) - timedelta(days=random.randint(1, 30))).isoformat(),
        "status": "flagged",
        "risk_score": round(random.uniform(0.75, 0.95), 3),
    }


def generate_pep_transactions(customer_id: str, count: int = 4) -> list[dict]:
    """Generate PEP-related large round-figure transactions."""
    # PEP typology: elected official receives large round amounts from government contractors.
    # FATF Recommendation 12 requires financial institutions to identify the source of funds
    # for PEPs and to apply enhanced scrutiny to politically sensitive transactions.
    txns = []
    # Amounts are suspiciously large and round — NGN 25M, 50M, 75M, 100M
    amounts = [50_000_000, 25_000_000, 100_000_000, 75_000_000]
    for i in range(min(count, len(amounts))):
        txns.append({
            "customer_id": customer_id,
            "counterparty_name": f"Government Contractor {i+1} Ltd",  # Politically connected counterparties
            "counterparty_account": random_account(),
            "amount": float(amounts[i]),
            "currency": "NGN",
            "transaction_type": "transfer",
            "channel": "internet_banking",
            "direction": "inbound",  # Funds flowing INTO the PEP's account
            "geo_location": "Abuja, NG",  # Abuja — seat of government, consistent with PEP profile
            "timestamp": (datetime.now(WAT) - timedelta(days=random.randint(5, 60))).isoformat(),
            "status": "flagged",
            "risk_score": round(random.uniform(0.65, 0.85), 3),
        })
    return txns


def generate_transactions_for_customer(
    customer: dict,
    total_count: int = 10,
    suspicious_type: str | None = None,
) -> list[dict]:
    """
    Generate a mix of transactions for a customer.
    suspicious_type: structuring | rapid_movement | dormant | round_amounts |
                     high_risk_geo | pep | None (normal)
    """
    txns: list[dict] = []
    customer_id = customer["id"]
    customer_name = customer["name"]

    # Always prepend normal transactions to provide a realistic baseline
    # before injecting the suspicious pattern — mirrors real-world account activity
    normal_count = max(2, total_count // 3)
    for _ in range(normal_count):
        txns.append(generate_normal_transaction(customer_id, customer_name))

    # Calculate how many slots remain for the suspicious pattern
    remaining = total_count - normal_count

    # Dispatch to the appropriate pattern generator based on the customer's risk scenario.
    # Each branch produces transactions pre-marked as "flagged" so they will trigger
    # the corresponding detection rules in the transaction_monitor and pattern_analyzer agents.
    if suspicious_type == "structuring":
        # Cap at 7 sub-threshold deposits — enough to clearly demonstrate the pattern
        txns += generate_structuring_transactions(customer_id, count=min(remaining, 7))
    elif suspicious_type == "rapid_movement":
        # Generates a variable number of outflows based on the inflow amount
        txns += generate_rapid_movement_transactions(customer_id)
    elif suspicious_type == "dormant":
        # Single large reactivation transaction is sufficient to trigger the rule
        txns.append(generate_dormant_account_transaction(customer_id))
    elif suspicious_type == "round_amounts":
        txns += generate_round_amount_transactions(customer_id, count=min(remaining, 6))
    elif suspicious_type == "high_risk_geo":
        # One sanctioned-jurisdiction wire + two round-amount transfers compound the risk score
        txns.append(generate_high_risk_geo_transaction(customer_id))
        txns += generate_round_amount_transactions(customer_id, count=2)
    elif suspicious_type == "pep":
        txns += generate_pep_transactions(customer_id, count=min(remaining, 4))
    else:
        # Normal customer: fill remaining slots with everyday transactions
        for _ in range(remaining):
            txns.append(generate_normal_transaction(customer_id, customer_name))

    return txns
