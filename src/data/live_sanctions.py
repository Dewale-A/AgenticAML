"""
Live sanctions list downloader and parser for AgenticAML.

Downloads and parses real sanctions data from official sources:
- OFAC SDN List (US Treasury): sdn.csv, alt.csv, add.csv
- UN Consolidated Sanctions List: consolidated.xml

These lists are legally required for CBN AML/CFT compliance:
- OFAC SDN: mandatory for Nigerian banks with USD correspondent banking
  relationships under US OFAC regulations and CBN BSD/DIR/PUB/LAB/019/002.
- UN Consolidated: mandatory for all UN member states under Chapter VII
  of the UN Charter. CBN requires screening against all UN SC resolutions.

Caching strategy:
- In-memory cache avoids repeated parsing within a single server session.
- Disk cache (src/data/cache/) persists across server restarts so a brief
  outage in OFAC/UN servers does not disable screening at startup.
- TTL is controlled by SANCTIONS_CACHE_TTL_HOURS env var (default: 6 hours).
  OFAC updates the SDN list roughly daily; 6 hours is a balanced default.

Fallback: if any download fails, the caller falls back to SANCTIONS_DB
(simulated data) so the server continues operating. A warning is logged.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Resolve cache directory relative to this file so it works from any working dir.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(_THIS_DIR, "cache")

# Cache TTL: how long downloaded data is considered fresh before re-downloading.
# OFAC publishes SDN updates on business days; 6 hours is a safe default that
# balances regulatory freshness requirements against network load.
CACHE_TTL_SECONDS = int(os.getenv("SANCTIONS_CACHE_TTL_HOURS", "6")) * 3600

# OFAC source URLs. All three files are required for a complete SDN dataset:
# - sdn.csv: primary list of sanctioned names, types, and programs
# - alt.csv: alternative names (aliases) linked to each SDN entity
# - add.csv: address data including country/nationality per entity
OFAC_SDN_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"
OFAC_ALT_URL = "https://www.treasury.gov/ofac/downloads/alt.csv"
OFAC_ADD_URL = "https://www.treasury.gov/ofac/downloads/add.csv"

# UN Consolidated Sanctions XML. Single file containing all individuals and entities.
UN_CONSOLIDATED_URL = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"

# HTTP timeout tuned for large file downloads.
# OFAC SDN CSV is approx 1.5 MB; UN XML is approx 5 MB.
# connect=15s handles slow DNS/TCP. read=120s handles large file transfers.
HTTP_TIMEOUT = httpx.Timeout(connect=15.0, read=120.0, write=30.0, pool=15.0)

# In-memory cache structure: { cache_key: {"data": [...], "fetched_at": float} }
# Cleared on process restart; disk cache provides persistence across restarts.
_MEMORY_CACHE: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_path(cache_key: str) -> str:
    """Return the disk cache file path for a named list.

    Files are stored as JSON in src/data/cache/ so they survive server restarts
    and are human-inspectable for debugging. The directory is created on demand.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{cache_key}.json")


def _load_disk_cache(cache_key: str) -> list[dict] | None:
    """Load cached entries from disk if the file exists and is within TTL.

    Returns None if the cache file is missing, unreadable, or has expired.
    The caller should then trigger a fresh download.
    """
    path = _cache_path(cache_key)
    if not os.path.exists(path):
        return None

    # Check file age against TTL before loading to avoid stale data.
    age = time.time() - os.path.getmtime(path)
    if age >= CACHE_TTL_SECONDS:
        logger.debug(f"Disk cache expired for {cache_key} (age={age:.0f}s)")
        return None

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        logger.debug(f"Loaded {len(data)} entries from disk cache: {path}")
        return data
    except Exception as e:
        logger.warning(f"Failed to load disk cache for {cache_key}: {e}")
        return None


def _save_disk_cache(cache_key: str, entries: list[dict]) -> None:
    """Persist parsed entries to disk for use after server restart.

    Failures are non-fatal: the server continues running without disk cache.
    The in-memory cache will still serve requests within the current session.
    """
    path = _cache_path(cache_key)
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entries, f)
        logger.info(f"Disk cache saved: {path} ({len(entries)} entries)")
    except Exception as e:
        logger.warning(f"Failed to save disk cache for {cache_key}: {e}")


def _update_memory_cache(cache_key: str, entries: list[dict]) -> None:
    """Store parsed entries in the in-memory cache with the current timestamp."""
    _MEMORY_CACHE[cache_key] = {
        "data": entries,
        "fetched_at": time.time(),
    }


def _get_memory_cache(cache_key: str) -> list[dict] | None:
    """Return in-memory cached entries if they are still within TTL.

    In-memory lookup is checked before disk to minimise I/O on frequent calls.
    """
    entry = _MEMORY_CACHE.get(cache_key)
    if entry is None:
        return None
    age = time.time() - entry["fetched_at"]
    if age >= CACHE_TTL_SECONDS:
        return None
    return entry["data"]


# ---------------------------------------------------------------------------
# OFAC SDN downloader
# ---------------------------------------------------------------------------

async def download_ofac_sdn() -> list[dict]:
    """Download and parse the OFAC SDN list with aliases and nationality data.

    Downloads three files in parallel for efficiency:
    1. sdn.csv  - primary list (name, type, sanctions program)
    2. alt.csv  - alias names keyed by entity number
    3. add.csv  - address/country data keyed by entity number

    Returns a list of dicts in SANCTIONS_DB format:
    {name, aliases, type, nationality, date_of_birth, reason, program, match_category}

    OFAC sdn.csv field order (0-indexed):
    0: ent_num, 1: SDN_Name, 2: SDN_Type, 3: Program, 4: Title, 5: Call_Sign,
    6: Vess_type, 7: Tonnage, 8: GRT, 9: Vess_flag, 10: Vess_owner, 11: Remarks

    OFAC alt.csv field order:
    0: ent_num, 1: alt_num, 2: alt_type, 3: alt_name, 4: alt_remarks

    OFAC add.csv field order:
    0: ent_num, 1: add_num, 2: add_type, 3: add_country, 4: add_city,
    5: add_state, 6: add_postal_code, 7: add_remarks
    """
    cache_key = "ofac_sdn_live"

    # Check in-memory cache (fastest path, no I/O)
    cached = _get_memory_cache(cache_key)
    if cached is not None:
        logger.debug(f"OFAC SDN: in-memory cache hit ({len(cached)} entries)")
        return cached

    # Check disk cache (persists across restarts, avoids redundant downloads)
    disk_cached = _load_disk_cache(cache_key)
    if disk_cached is not None:
        logger.info(f"OFAC SDN: disk cache hit ({len(disk_cached)} entries)")
        _update_memory_cache(cache_key, disk_cached)
        return disk_cached

    # No fresh cache available: download from US Treasury.
    start = time.time()
    logger.info("OFAC SDN: downloading from US Treasury (sdn.csv + alt.csv + add.csv)...")

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        # Fetch all three files concurrently to minimise total download time.
        results = await asyncio.gather(
            client.get(OFAC_SDN_URL),
            client.get(OFAC_ALT_URL),
            client.get(OFAC_ADD_URL),
            return_exceptions=True,
        )

    sdn_resp, alt_resp, add_resp = results

    # SDN file is mandatory: raise if it failed.
    if isinstance(sdn_resp, Exception):
        raise sdn_resp
    sdn_resp.raise_for_status()
    sdn_size = len(sdn_resp.content)
    logger.info(f"OFAC SDN: sdn.csv downloaded ({sdn_size:,} bytes)")

    # Build alias lookup: ent_num -> [alias_name, ...]
    # OFAC encodes aliases as separate rows in alt.csv linked by entity number.
    alt_map: dict[str, list[str]] = {}
    if not isinstance(alt_resp, Exception) and alt_resp.status_code == 200:
        # OFAC files use latin-1 encoding (not UTF-8).
        alt_text = alt_resp.content.decode("latin-1", errors="replace")
        for row in csv.reader(io.StringIO(alt_text)):
            if len(row) >= 4:
                ent_num = row[0].strip().strip('"')
                alt_name = row[3].strip().strip('"')
                # OFAC uses " -0- " as a null/empty placeholder value.
                if alt_name and alt_name != "-0-" and ent_num:
                    alt_map.setdefault(ent_num, []).append(alt_name)
        logger.info(f"OFAC SDN: alt.csv parsed ({len(alt_map)} entities with aliases)")
    else:
        logger.warning("OFAC SDN: alt.csv unavailable, aliases will be empty")

    # Build nationality/country lookup: ent_num -> country_code.
    # The add.csv country column contains the full country name (not ISO code).
    # We store the first address country found per entity as a best-effort nationality.
    add_map: dict[str, str] = {}
    if not isinstance(add_resp, Exception) and add_resp.status_code == 200:
        add_text = add_resp.content.decode("latin-1", errors="replace")
        for row in csv.reader(io.StringIO(add_text)):
            if len(row) >= 4:
                ent_num = row[0].strip().strip('"')
                country = row[3].strip().strip('"')
                if country and country != "-0-" and ent_num and ent_num not in add_map:
                    add_map[ent_num] = country
        logger.info(f"OFAC SDN: add.csv parsed ({len(add_map)} address entries)")
    else:
        logger.warning("OFAC SDN: add.csv unavailable, nationality data will be empty")

    # Parse the primary SDN file into SANCTIONS_DB-compatible entries.
    entries: list[dict] = []
    sdn_text = sdn_resp.content.decode("latin-1", errors="replace")
    for row in csv.reader(io.StringIO(sdn_text)):
        if len(row) < 4:
            continue  # Skip malformed/header rows

        ent_num = row[0].strip().strip('"')
        sdn_name = row[1].strip().strip('"')
        sdn_type = row[2].strip().strip('"').lower()
        program = row[3].strip().strip('"')

        # Skip placeholder/empty rows that OFAC uses as structural delimiters.
        if not sdn_name or sdn_name == "-0-":
            continue

        # Map OFAC SDN_Type values to our internal "individual" / "entity" distinction.
        # OFAC types: "Individual", "Entity", "Vessel", "Aircraft"
        # Vessels and aircraft are classified as "entity" for screening purposes.
        entry_type = "individual" if "individual" in sdn_type else "entity"

        entry: dict[str, Any] = {
            "name": sdn_name,
            "aliases": alt_map.get(ent_num, []),
            "type": entry_type,
            # OFAC add.csv stores country names, not ISO codes. Store as-is.
            # The fuzzy matcher handles long country names in nationality fields.
            "nationality": add_map.get(ent_num),
            # SDN CSV does not include date of birth in the main file.
            # DOB appears in the Remarks column for some entries but requires
            # additional parsing that is deferred to a future enhancement.
            "date_of_birth": None,
            "reason": f"OFAC SDN: {program}",
            "program": program,
            # All OFAC entries are hard sanctions (not PEP or adverse media).
            "match_category": "sanctions",
        }
        entries.append(entry)

    elapsed = time.time() - start
    logger.info(
        f"OFAC SDN: complete. {len(entries)} entries parsed in {elapsed:.1f}s "
        f"(sdn.csv: {sdn_size:,} bytes)"
    )

    _update_memory_cache(cache_key, entries)
    _save_disk_cache(cache_key, entries)
    return entries


# ---------------------------------------------------------------------------
# UN Consolidated Sanctions List downloader
# ---------------------------------------------------------------------------

async def download_un_consolidated() -> list[dict]:
    """Download and parse the UN Security Council Consolidated Sanctions List.

    The XML format contains both INDIVIDUAL and ENTITY sections. Name components,
    aliases, nationalities, dates of birth, committee reference numbers, and
    applicable sanctions resolutions are all parsed.

    All UN member states are legally required to enforce these designations
    under Chapter VII of the UN Charter. Nigerian banks must screen against
    this list per CBN AML/CFT guidelines.
    """
    cache_key = "un_consolidated_live"

    # Check in-memory cache first (no I/O)
    cached = _get_memory_cache(cache_key)
    if cached is not None:
        logger.debug(f"UN Consolidated: in-memory cache hit ({len(cached)} entries)")
        return cached

    # Check disk cache (avoids re-downloading after restart)
    disk_cached = _load_disk_cache(cache_key)
    if disk_cached is not None:
        logger.info(f"UN Consolidated: disk cache hit ({len(disk_cached)} entries)")
        _update_memory_cache(cache_key, disk_cached)
        return disk_cached

    start = time.time()
    logger.info("UN Consolidated: downloading from UN Security Council...")

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(UN_CONSOLIDATED_URL)

    response.raise_for_status()
    file_size = len(response.content)
    logger.info(f"UN Consolidated: XML downloaded ({file_size:,} bytes)")

    entries = _parse_un_xml(response.content)

    elapsed = time.time() - start
    logger.info(
        f"UN Consolidated: complete. {len(entries)} entries parsed in {elapsed:.1f}s "
        f"(file size: {file_size:,} bytes)"
    )

    _update_memory_cache(cache_key, entries)
    _save_disk_cache(cache_key, entries)
    return entries


def _parse_un_xml(xml_bytes: bytes) -> list[dict]:
    """Parse the UN Consolidated Sanctions XML into SANCTIONS_DB-compatible entries.

    XML structure (abbreviated):
    <CONSOLIDATED_LIST>
      <INDIVIDUALS>
        <INDIVIDUAL>
          <DATAID>, <FIRST_NAME>, <SECOND_NAME>, <THIRD_NAME>, <FOURTH_NAME>
          <INDIVIDUAL_ALIAS><ALIAS_NAME>...<QUALITY>Good quality|Low quality
          <NATIONALITY><VALUE>country name
          <INDIVIDUAL_DATE_OF_BIRTH><DATE>YYYY-MM-DD or <YEAR>YYYY
          <UN_LIST_TYPE>, <REFERENCE_NUMBER>
        </INDIVIDUAL>
      </INDIVIDUALS>
      <ENTITIES>
        <ENTITY>
          <DATAID>, <FIRST_NAME> (entity name)
          <ENTITY_ALIAS><ALIAS_NAME>...<QUALITY>
          <ENTITY_ADDRESS><COUNTRY>
          <UN_LIST_TYPE>, <REFERENCE_NUMBER>
        </ENTITY>
      </ENTITIES>
    </CONSOLIDATED_LIST>

    Note: the UN XML uses "Low quality" aliases to denote uncertain or historical
    name variants. These are excluded to reduce false positives in screening.
    """
    entries: list[dict] = []

    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        logger.error(f"UN Consolidated XML parse error: {e}")
        return entries

    def _txt(parent: ET.Element | None, tag: str) -> str:
        """Safely extract trimmed text from a child element. Returns empty string if absent."""
        if parent is None:
            return ""
        child = parent.find(tag)
        return (child.text or "").strip() if child is not None else ""

    # Parse INDIVIDUAL entries.
    # Individual names are split across up to four name component fields.
    # All non-empty components are joined with a space to form the canonical name.
    for ind in root.findall(".//INDIVIDUAL"):
        name_parts = [
            _txt(ind, "FIRST_NAME"),
            _txt(ind, "SECOND_NAME"),
            _txt(ind, "THIRD_NAME"),
            _txt(ind, "FOURTH_NAME"),
        ]
        full_name = " ".join(p for p in name_parts if p).strip()
        if not full_name:
            continue  # No parseable name; skip entry to avoid null matches

        # Collect aliases, excluding low-quality ones.
        # "Low quality" aliases (UN's designation) are unverified name variants
        # that have a higher false positive risk and are excluded per best practice.
        aliases: list[str] = []
        for alias_elem in ind.findall("INDIVIDUAL_ALIAS"):
            alias_name = _txt(alias_elem, "ALIAS_NAME")
            quality = _txt(alias_elem, "QUALITY")
            if alias_name and quality != "Low quality":
                aliases.append(alias_name)

        # Nationality: take the first nationality element value.
        # The UN XML stores the full country name, not an ISO code.
        nationality = None
        for nat_elem in ind.findall("NATIONALITY"):
            val = _txt(nat_elem, "VALUE")
            if val:
                nationality = val
                break

        # Date of birth: prefer exact DATE, fall back to YEAR if only year is known.
        # Many UN-listed individuals have only a birth year recorded.
        dob = None
        for dob_elem in ind.findall("INDIVIDUAL_DATE_OF_BIRTH"):
            exact = _txt(dob_elem, "DATE")
            if exact:
                dob = exact
                break
            year = _txt(dob_elem, "YEAR")
            if year:
                dob = year
                break

        list_type = _txt(ind, "UN_LIST_TYPE")
        ref_num = _txt(ind, "REFERENCE_NUMBER")

        entries.append({
            "name": full_name,
            "aliases": aliases,
            "type": "individual",
            "nationality": nationality,
            "date_of_birth": dob,
            "reason": f"UN Consolidated: {list_type} (ref: {ref_num})",
            # Program name normalised to uppercase with spaces replaced by underscores
            # to match the convention used in the simulated UN_CONSOLIDATED entries.
            "program": (
                f"UN_{list_type.replace(' ', '_').upper()}" if list_type else "UN_CONSOLIDATED"
            ),
            "match_category": "sanctions",
        })

    # Parse ENTITY entries.
    # Entity names are stored in a single FIRST_NAME element (UN XML convention).
    for ent in root.findall(".//ENTITY"):
        entity_name = _txt(ent, "FIRST_NAME")
        if not entity_name:
            continue

        aliases = []
        for alias_elem in ent.findall("ENTITY_ALIAS"):
            alias_name = _txt(alias_elem, "ALIAS_NAME")
            quality = _txt(alias_elem, "QUALITY")
            if alias_name and quality != "Low quality":
                aliases.append(alias_name)

        # Country extracted from the first entity address record.
        nationality = None
        for addr_elem in ent.findall("ENTITY_ADDRESS"):
            country = _txt(addr_elem, "COUNTRY")
            if country:
                nationality = country
                break

        list_type = _txt(ent, "UN_LIST_TYPE")
        ref_num = _txt(ent, "REFERENCE_NUMBER")

        entries.append({
            "name": entity_name,
            "aliases": aliases,
            "type": "entity",
            "nationality": nationality,
            "date_of_birth": None,  # Entities do not have dates of birth
            "reason": f"UN Consolidated: {list_type} (ref: {ref_num})",
            "program": (
                f"UN_{list_type.replace(' ', '_').upper()}" if list_type else "UN_CONSOLIDATED"
            ),
            "match_category": "sanctions",
        })

    return entries


# ---------------------------------------------------------------------------
# Refresh coordinator
# ---------------------------------------------------------------------------

async def refresh_all_lists() -> dict[str, Any]:
    """Download and refresh all live sanctions lists. Returns per-list stats.

    Called by ListManager when LIVE_SANCTIONS=true. On partial failure,
    the successfully downloaded lists are still returned; the failed ones
    are reported with status='failed' and an error message.

    Return structure:
    {
        "ofac_sdn": {"status": "success", "entry_count": N, "elapsed_seconds": X},
        "un_consolidated": {"status": "failed", "error": "...", "elapsed_seconds": X},
    }
    """
    stats: dict[str, Any] = {}

    # OFAC SDN download and parse
    ofac_start = time.time()
    try:
        ofac_entries = await download_ofac_sdn()
        stats["ofac_sdn"] = {
            "status": "success",
            "entry_count": len(ofac_entries),
            "elapsed_seconds": round(time.time() - ofac_start, 2),
        }
        logger.info(f"OFAC SDN refresh: {len(ofac_entries)} entries in {stats['ofac_sdn']['elapsed_seconds']}s")
    except Exception as e:
        stats["ofac_sdn"] = {
            "status": "failed",
            "error": str(e),
            "elapsed_seconds": round(time.time() - ofac_start, 2),
        }
        logger.error(f"OFAC SDN refresh failed: {e}")

    # UN Consolidated download and parse
    un_start = time.time()
    try:
        un_entries = await download_un_consolidated()
        stats["un_consolidated"] = {
            "status": "success",
            "entry_count": len(un_entries),
            "elapsed_seconds": round(time.time() - un_start, 2),
        }
        logger.info(f"UN Consolidated refresh: {len(un_entries)} entries in {stats['un_consolidated']['elapsed_seconds']}s")
    except Exception as e:
        stats["un_consolidated"] = {
            "status": "failed",
            "error": str(e),
            "elapsed_seconds": round(time.time() - un_start, 2),
        }
        logger.error(f"UN Consolidated refresh failed: {e}")

    return stats


def get_cached_entries(cache_key: str) -> list[dict] | None:
    """Return cached live entries if available, without triggering a download.

    Used by get_sanctions_db() to serve live data without blocking on downloads.
    Returns None if no valid cache exists (download has not succeeded yet).
    """
    # In-memory cache first: fastest path, no disk I/O required.
    cached = _get_memory_cache(cache_key)
    if cached is not None:
        return cached

    # Fall back to disk cache: works after server restart if prior download succeeded.
    return _load_disk_cache(cache_key)
