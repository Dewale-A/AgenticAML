"""
Screening List Manager for AgenticAML Continuous Monitoring.

Manages the download, versioning, and change detection for the screening lists
used by the SanctionsScreenerAgent and OnboardingScreenerAgent.

All lists tracked here are free and publicly available:
- OFAC SDN: US Treasury Office of Foreign Assets Control Specially Designated Nationals
- UN Consolidated: United Nations Security Council Consolidated Sanctions List
- Nigerian Domestic: CBN/NFIU domestic watchlist (manually curated)
- Internal PEP: Locally maintained Politically Exposed Persons database

In the demo/development environment, lists are simulated from SANCTIONS_DB in
src/data/sanctions_lists.py. In production, the download methods would fetch
real list files from the source URLs and parse them into the SANCTIONS_DB format.

List versioning:
- Each list is tracked by its checksum (SHA-256) so re-downloads are skipped
  when the list file has not changed.
- The screening_lists table stores the current version, entry count, and
  last update timestamp for dashboard display and audit trail evidence.
"""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta, timezone
from typing import Any

import aiosqlite

from src.data.sanctions_lists import SANCTIONS_DB
from src.database import list_screening_lists, now_wat, upsert_screening_list

# WAT timezone — all timestamps in Nigerian local time per CBN requirements
WAT = timezone(timedelta(hours=1))

# Source metadata for each list. In production, source_url would be used to
# download the actual list file. In demo mode, we use SANCTIONS_DB as the data source.
LIST_METADATA = {
    "ofac_sdn": {
        "source_url": "https://www.treasury.gov/ofac/downloads/sdn.csv",
        "description": "OFAC Specially Designated Nationals and Blocked Persons List",
    },
    "un_consolidated": {
        "source_url": "https://scsanctions.un.org/resources/xml/en/consolidated.xml",
        "description": "UN Security Council Consolidated Sanctions List",
    },
    "nigerian_domestic": {
        "source_url": "internal://cbn-nfiu-watchlist",
        "description": "CBN/NFIU Nigerian domestic AML watchlist",
    },
    "internal_pep": {
        "source_url": "internal://pep-database",
        "description": "Internal PEP database (Nigerian and international PEPs)",
    },
}


class ListManager:
    """Manages screening list versions and updates for continuous monitoring.

    In demo mode, all lists are derived from SANCTIONS_DB. The checksum is
    computed from the JSON serialisation of the list data so that when test
    data changes, the checksum changes and the list record is updated.

    In production, this class would be extended to:
    1. Download list files from source_url.
    2. Parse them into the SANCTIONS_DB format (provider-specific parsers).
    3. Compute SHA-256 of the raw file for authentic change detection.
    4. Store the parsed entries in a local database table for fast queries.
    """

    def __init__(self, db: aiosqlite.Connection):
        self.db = db

    async def refresh_all_lists(self) -> list[dict[str, Any]]:
        """Refresh all configured screening lists and return update summaries.

        Called at startup and by the POST /screening-lists/update endpoint.
        For each list, computes the current checksum from SANCTIONS_DB and
        updates the screening_lists table if the data has changed.

        Returns a list of update result dicts, one per list.
        """
        results = []
        for list_name, entries in SANCTIONS_DB.items():
            result = await self._refresh_list(list_name, entries)
            results.append(result)
        return results

    async def get_list_status(self) -> list[dict]:
        """Return current status of all tracked screening lists.

        Used by GET /screening-lists to show list versions and freshness
        on the monitoring dashboard.
        """
        return await list_screening_lists(self.db)

    async def _refresh_list(self, list_name: str, entries: list[dict]) -> dict[str, Any]:
        """Refresh a single list and return the update result.

        Computes the SHA-256 checksum of the current entry data. If the checksum
        matches the stored value, the list has not changed and no update is needed.
        This avoids unnecessary DB writes and re-processing on every startup.
        """
        # Compute checksum of current list data for change detection
        data_str = json.dumps(entries, sort_keys=True, default=str)
        checksum = hashlib.sha256(data_str.encode()).hexdigest()
        entry_count = len(entries)
        ts = now_wat()

        # Get existing record to check if list has changed
        existing_lists = await list_screening_lists(self.db)
        existing = next((sl for sl in existing_lists if sl["list_name"] == list_name), None)

        if existing and existing.get("checksum") == checksum:
            # List data unchanged — no update needed
            return {
                "list_name": list_name,
                "status": "unchanged",
                "entry_count": entry_count,
                "checksum": checksum,
            }

        # List is new or changed — update the record
        meta = LIST_METADATA.get(list_name, {})
        await upsert_screening_list(self.db, {
            "list_name": list_name,
            "version": ts[:10],  # Use date as version string (YYYY-MM-DD)
            "last_updated": ts,
            "entry_count": entry_count,
            "source_url": meta.get("source_url"),
            "checksum": checksum,
        })

        return {
            "list_name": list_name,
            "status": "updated",
            "entry_count": entry_count,
            "checksum": checksum,
            "previous_checksum": existing.get("checksum") if existing else None,
        }
