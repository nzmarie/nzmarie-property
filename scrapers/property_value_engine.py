import os
import asyncio
import random
import logging
import sys
import json
import time
import re

sys.path.append(os.getcwd())

from bs4 import BeautifulSoup
from scrapers.base_scraper import BaseScraper
from scrapers.property_value_parser import PropertyValueParser
from utils.database import db
from utils.address_helper import generate_address_fingerprint

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

REGION_BASE_PATHS = {
    "auckland": "/auckland",
    "wellington": "/wellington",
}

# Partial-match predicate mirroring the discovery-side suburb filter:
# sub in extracted OR extracted in sub (case-insensitive), over the suburb list.
# NOTE: bare % must be doubled (%% ) because psycopg2 treats % as a format marker.
SUBURB_PARTIAL_MATCH_SQL = (
    "EXISTS (SELECT 1 FROM unnest(%s) AS f(s) "
    "WHERE LOWER(suburb) LIKE '%%' || s || '%%' OR s LIKE '%%' || LOWER(suburb) || '%%')"
)

class PropertyValueEngine(BaseScraper):
    def __init__(self, mode="discovery", force_run=False, simulate=False, region="auckland", task_id=None, suburbs_filter=None, max_runtime=5.5, ta_slug=None, address_filter=None):
        super().__init__(mode, force_run, simulate, region)
        self.base_url = "https://www.propertyvalue.co.nz"
        self.region_path = REGION_BASE_PATHS.get(region, f"/{region}")
        self.task_id = task_id
        self.task_key = f"propertyvalue_{self.mode}_{self.region}"
        self.start_time = time.monotonic()
        self.max_runtime = max_runtime * 3600
        self.suburbs_filter = [
            s.strip().lower() for s in suburbs_filter.split(',') if s.strip()
        ] if suburbs_filter else None
        if self.suburbs_filter:
            logger.info(f"Suburb filter active: {self.suburbs_filter}")
        # Territorial Authority slug filter, e.g. "north-shore-city" -> /auckland/north-shore-city/{id}
        self.ta_slug = ta_slug.strip().lower() if ta_slug else None
        if self.ta_slug:
            logger.info(f"TA filter active: {self.ta_slug}")
        # Single-address targeted refresh, e.g. "850A Beach Road, Waiake". Address part
        # (before the first comma) is used for a partial match against properties.address.
        self.address_filter = address_filter.strip() if address_filter else None
        if self.address_filter:
            logger.info(f"Address filter active: {self.address_filter}")

    async def run(self):
        if self.task_id:
            # If task_id is provided, we assume gh_lock_manager has already checked it
            # but we still want to use it for status updates
            pass
        elif not await self.check_lock(self.task_key):
            return

        await self.init_browser()
        if self.task_id:
            await self.set_status_by_id(self.task_id, "running")
        else:
            await self.set_status(self.task_key, "running")

        try:
            if self.mode == "backfill":
                await self.run_backfill()
            elif self.mode == "discovery":
                await self.run_discovery()
            elif self.mode == "refresh":
                await self.run_refresh()
            
            logger.info(f"✅ {self.mode.title()} mode completed successfully")
        except Exception as e:
            logger.error(f"❌ Fatal error in {self.mode} mode: {e}", exc_info=True)
            raise
        finally:
            if self.task_id:
                # We don't set to idle here if it's managed by the YAML always() block
                # but it's safer to have it here too.
                pass
            else:
                await self.set_status(self.task_key, "idle")
            await self.close_browser()

    async def set_status_by_id(self, task_id, status, last_id=None):
        if self.simulate: return
        # Using UPSERT for robustness
        sql = """
            UPSERT INTO scraping_progress (id, status, updated_at, last_processed_id)
            VALUES (%s, %s, CURRENT_TIMESTAMP, %s)
        """
        # If last_id is not provided, we want to keep the existing one if possible
        # but UPSERT will overwrite. So we might need a more complex query or just handle it.
        # Actually, if we are setting 'ongoing' without a new state, we should fetch old state.
        
        if last_id is None:
            res = db.query("SELECT last_processed_id FROM scraping_progress WHERE id = %s", (task_id,))
            last_id = res[0]['last_processed_id'] if res else None

        db.execute(sql, (task_id, status, last_id))

    async def get_state(self):
        if not self.task_id: return None
        res = db.query("SELECT last_processed_id FROM scraping_progress WHERE id = %s", (self.task_id,))
        if res and res[0]['last_processed_id']:
            try:
                return json.loads(res[0]['last_processed_id'])
            except:
                return None
        return None

    async def _load_suburb_progress(self):
        """Load suburb-level progress from scraping_progress columns."""
        if not self.task_id:
            return None, [], 0, 0, -1
        rows = db.query(
            "SELECT suburbs_target, suburbs_completed, total_suburbs, completed_suburbs, remaining_count "
            "FROM scraping_progress WHERE id = %s",
            (self.task_id,)
        )
        if not rows:
            return None, [], 0, 0, -1
        r = rows[0]
        target = None
        if r.get('suburbs_target'):
            try:
                target = json.loads(r['suburbs_target'])
            except Exception:
                target = None
        done = []
        if r.get('suburbs_completed'):
            try:
                done = json.loads(r['suburbs_completed'])
            except Exception:
                done = []
        total = int(r.get('total_suburbs') or 0)
        completed = int(r.get('completed_suburbs') or 0)
        remaining = r.get('remaining_count')
        return target, done, total, completed, remaining

    async def _init_suburb_progress(self, target_list):
        """Persist the target suburb list; reset completed list if the target changed or forcing a fresh run."""
        target = [s.strip().lower() for s in target_list if s.strip()]
        if not target:
            return
        stored_target, done, _, _, _ = await self._load_suburb_progress()
        if done is None:
            done = []
        if self.force_run or stored_target != target:
            done = []
        db.execute(
            "UPDATE scraping_progress SET suburbs_target = %s, suburbs_completed = %s, "
            "total_suburbs = %s, completed_suburbs = %s, updated_at = NOW() WHERE id = %s",
            (json.dumps(target), json.dumps(done), len(target), len(done), self.task_id)
        )

    async def _mark_suburb_done(self, suburb_name):
        """Append a completed suburb to the persistent progress record."""
        _, done, _, _, _ = await self._load_suburb_progress()
        if done is None:
            done = []
        norm = suburb_name.strip().lower()
        if norm not in done:
            done.append(norm)
        db.execute(
            "UPDATE scraping_progress SET suburbs_completed = %s, completed_suburbs = %s, "
            "updated_at = NOW() WHERE id = %s",
            (json.dumps(done), len(done), self.task_id)
        )

    @staticmethod
    def _all_targets_done(target_list, done):
        """True when every target suburb has at least one completed (partially-matched) suburb."""
        if not target_list:
            return False
        for t in target_list:
            if not any(t in d or d in t for d in done):
                return False
        return True

    async def _discovery_complete(self):
        """Whether discovery has finished all target suburbs (so backfill may mark the task complete)."""
        if self.address_filter:
            # A targeted single-address backfill has no suburb-gating; it's done when the address is processed.
            return True
        if self.suburbs_filter:
            _, done, _, _, _ = await self._load_suburb_progress()
            return self._all_targets_done(self.suburbs_filter, done)
        if not self.task_id:
            return True
        # No suburb filter: discovery marks the task complete only after sweeping the whole region.
        rows = db.query("SELECT status FROM scraping_progress WHERE id = %s", (self.task_id,))
        return bool(rows and rows[0].get('status') == 'complete')

    def _save_remaining(self, remaining):
        """Persist the number of properties still needing backfill."""
        if not self.task_id:
            return
        db.execute(
            "UPDATE scraping_progress SET remaining_count = %s, updated_at = NOW() WHERE id = %s",
            (remaining, self.task_id)
        )

    def _address_match_clause(self):
        """SQL predicate + params to locate a single targeted address (address part before first comma)."""
        addr = self.address_filter.split(',')[0].strip().lower()
        return "LOWER(address) LIKE '%%' || %s || '%%'", (addr,)

    def _count_unbackfilled(self):
        """Count properties in scope (region/suburb filter) that still need details."""
        try:
            if self.address_filter:
                clause, params = self._address_match_clause()
                rows = db.query(
                    "SELECT COUNT(*) AS cnt FROM properties WHERE region = %s AND " + clause,
                    (self.region,) + params
                )
            elif self.suburbs_filter:
                rows = db.query(
                    "SELECT COUNT(*) AS cnt FROM properties "
                    "WHERE (backfilled_at IS NULL OR property_history IS NULL OR has_rental_history IS NULL) "
                    f"AND region = %s AND {SUBURB_PARTIAL_MATCH_SQL}",
                    (self.region, self.suburbs_filter)
                )
            else:
                rows = db.query(
                    "SELECT COUNT(*) AS cnt FROM properties "
                    "WHERE (backfilled_at IS NULL OR property_history IS NULL OR has_rental_history IS NULL) "
                    "AND region = %s",
                    (self.region,)
                )
            return rows[0]['cnt'] if rows else 0
        except Exception as e:
            logger.warning(f"Failed to count unbackfilled properties: {e}")
            return -1

    @staticmethod
    def _ta_slug(ta_link):
        parts = ta_link.strip('/').split('/')
        return parts[-2].lower() if len(parts) >= 2 else ""

    def should_stop(self):
        elapsed = time.monotonic() - self.start_time
        return elapsed > self.max_runtime

    async def _save_properties_batch(self, properties_data):
        """Batch upsert properties from discovery mode."""
        if not properties_data: return
        if self.simulate:
            logger.info(f"[SIMULATION] Would process {len(properties_data)} properties.")
            return

        batch_params = []
        for p in properties_data:
            # Mandatory fingerprint per spec: address|suburb -> lowercase -> [a-z0-9|] only
            fingerprint = generate_address_fingerprint(p['address'], p.get('suburb'))
            if not fingerprint:
                logger.error(f"Refusing to insert property with NULL fingerprint (address={p.get('address')}). Skipping.")
                continue
            batch_params.append((
                p['address'], p['suburb'], p['city'], self.region,
                p['property_url'], fingerprint
            ))

        if not batch_params:
            return

        # Deduplicate by fingerprint WITHIN the batch. CockroachDB rejects a single
        # multi-row INSERT...ON CONFLICT that touches the same row twice ("cannot
        # affect row a second time"), so two colliding fingerprints on one page must
        # be collapsed into a single row (last write wins, same as per-row upserts).
        seen_fp = set()
        deduped = []
        for row in batch_params:
            fp = row[5]
            if fp in seen_fp:
                continue
            seen_fp.add(fp)
            deduped.append(row)
        batch_params = deduped

        sql_template = """
            INSERT INTO properties (id, address, suburb, city, region, property_url, address_fingerprint, created_at)
            VALUES {placeholders}
            ON CONFLICT (address_fingerprint) DO UPDATE
            SET address = EXCLUDED.address, suburb = EXCLUDED.suburb, city = EXCLUDED.city,
                region = EXCLUDED.region, property_url = EXCLUDED.property_url
            RETURNING address, suburb, (created_at >= CURRENT_TIMESTAMP - INTERVAL '1 second') as is_new
        """

        new_count = 0
        upd_count = 0
        row_placeholder = "(md5(random()::text || clock_timestamp()::text), %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)"
        single_row_sql = sql_template.format(placeholders=row_placeholder)
        for i in range(0, len(batch_params), 500):
            chunk = batch_params[i:i + 500]
            placeholders = ", ".join([row_placeholder] * len(chunk))
            flat = [v for row in chunk for v in row]
            try:
                results = db.query(sql_template.format(placeholders=placeholders), flat)
                for row in results or []:
                    label = "NEW" if row['is_new'] else "UPD"
                    addr = row['address']
                    if row.get('suburb'):
                        addr += f", {row['suburb']}"
                    logger.info(f"  [{label}] {addr}")
                    if row['is_new']:
                        new_count += 1
                    else:
                        upd_count += 1
            except Exception as e:
                # Fall back to row-by-row so a single bad row can't lose the whole chunk.
                logger.error(f"Failed to upsert properties batch ({len(chunk)} rows): {e}. Retrying row-by-row.")
                for params in chunk:
                    try:
                        res = db.query(single_row_sql, params)
                        if res:
                            row = res[0]
                            label = "NEW" if row['is_new'] else "UPD"
                            addr = row['address']
                            if row.get('suburb'):
                                addr += f", {row['suburb']}"
                            logger.info(f"  [{label}] {addr}")
                            if row['is_new']:
                                new_count += 1
                            else:
                                upd_count += 1
                    except Exception as e2:
                        logger.error(f"  Failed to upsert property (fingerprint={params[5]}): {e2}")
        logger.info(f"Upserted properties: {new_count} new, {upd_count} updated ({len(batch_params)} total rows)")

    async def run_discovery(self):
        logger.info(f"Starting Discovery Mode for region: {self.region}")
        if self.force_run:
            state = {}
        else:
            state = await self.get_state() or {}
        last_ta_idx = state.get('ta_idx', 0)
        last_sub_idx = state.get('sub_idx', 0)
        last_page = state.get('page_num', 1)

        # Suburb-level progress tracking: persist target suburbs, load completed ones
        if self.suburbs_filter and self.task_id:
            await self._init_suburb_progress(self.suburbs_filter)
        _, done_suburbs, total_suburbs, _, _ = await self._load_suburb_progress()
        if done_suburbs is None:
            done_suburbs = []

        # When restricting to a single TA, the TA index no longer matches the
        # unfiltered TA list from older runs — reset it so resume starts at index 0.
        if self.ta_slug:
            last_ta_idx = 0

        target_url = f"{self.base_url}{self.region_path}"
        page = await self.context.new_page()

        try:
            if not await self.safe_goto(page, target_url): return

            content = await page.content()
            ta_links = PropertyValueParser.parse_ta_links(content, self.region)
            # Restrict to the configured TA slug (e.g. north-shore-city)
            if self.ta_slug:
                ta_links = [l for l in ta_links if self._ta_slug(l) == self.ta_slug]
                if not ta_links:
                    logger.error(f"No TA matched slug '{self.ta_slug}'. Found: {[self._ta_slug(l) for l in ta_links]}")
                logger.info(f"After TA filter ({self.ta_slug}): {len(ta_links)} Territorial Authorities")
            logger.info(f"Found {len(ta_links)} Territorial Authorities. Resuming from TA index {last_ta_idx}")

            for i, ta_link in enumerate(ta_links):
                if i < last_ta_idx: continue
                
                ta_name = ta_link.strip('/').split('/')[-2].replace('-', ' ').title()
                logger.info(f"Drilling into TA: {ta_name} (Index {i})")

                if not await self.safe_goto(page, self.base_url + ta_link): continue

                ta_content = await page.content()
                suburb_links = PropertyValueParser.parse_suburb_links(ta_content, self.region)
                logger.info(f"Found {len(suburb_links)} suburbs in TA: {ta_name}")

                # Apply suburb filter if specified
                # Use partial match: extracted name like "birkenhead north shore" should still match "birkenhead"
                if self.suburbs_filter:
                    filtered = []
                    for link in suburb_links:
                        extracted = self._extract_suburb_name(link).lower()
                        if any(sub in extracted or extracted in sub for sub in self.suburbs_filter):
                            filtered.append(link)
                    suburb_links = filtered
                    logger.info(f"After suburb filter: {len(suburb_links)} suburbs remaining")
                    if not suburb_links:
                        continue

                for j, sub_link in enumerate(suburb_links):
                    # Skip suburbs already fully scraped (persisted progress)
                    extracted_name = self._extract_suburb_name(sub_link).lower()
                    if extracted_name and extracted_name in done_suburbs:
                        logger.info(f"  Skipping already-completed suburb: {extracted_name}")
                        continue
                    if i == last_ta_idx and j < last_sub_idx: continue
                    
                    if self.should_stop():
                        logger.info("Stopping discovery due to time limit.")
                        return

                    parts = sub_link.strip('/').split('/')
                    suburb_name = parts[-2].rsplit('-', 1)[0].replace('-', ' ').title() if len(parts) >= 3 else "Unknown"
                    
                    # Page resumption only for the first suburb we hit
                    resume_page = last_page if (i == last_ta_idx and j == last_sub_idx) else 1
                    
                    completed = await self._scrape_suburb_properties(page, self.base_url + sub_link, suburb_name, ta_name, i, j, resume_page)

                    # Persist suburb completion so resume skips it next cycle
                    if completed and self.task_id and extracted_name:
                        await self._mark_suburb_done(extracted_name)

                    if self.should_stop(): return

                    # Update state after each suburb (next suburb, page 1)
                    if self.task_id:
                        new_state = json.dumps({"ta_idx": i, "sub_idx": j + 1, "page_num": 1})
                        await self.set_status_by_id(self.task_id, "running", new_state)

            if self.task_id:
                # With a suburb filter, only complete once every target suburb is done
                if self.suburbs_filter:
                    _, done_suburbs, total_suburbs, _, _ = await self._load_suburb_progress()
                    if self._all_targets_done(self.suburbs_filter, done_suburbs):
                        await self.set_status_by_id(self.task_id, "complete", json.dumps({"ta_idx": 0, "sub_idx": 0, "page_num": 1}))
                    else:
                        logger.info(f"Discovery cycle ended; {len(done_suburbs)}/{total_suburbs} target suburbs complete. Waiting for next run.")
                else:
                    await self.set_status_by_id(self.task_id, "complete", json.dumps({"ta_idx": 0, "sub_idx": 0, "page_num": 1}))

        except Exception as e:
            logger.error(f"Discovery failed: {e}")
        finally:
            await page.close()

    async def _scrape_suburb_properties(self, page, suburb_url, suburb_name, ta_name, ta_idx, sub_idx, start_page=1):
        """Scrape all pages of a suburb. Returns True when the suburb is fully scraped, False if stopped early."""
        logger.info(f"Scraping suburb: {suburb_name} from page {start_page}")
        current_url = f"{suburb_url}?page={start_page}" if start_page > 1 else suburb_url
        page_num = start_page
        stopped_early = False
        seen_urls = set()  # URLs already upserted in this suburb, to detect circular/repeated pages

        while current_url:
            if self.should_stop(): 
                stopped_early = True
                # Save current page progress before stopping
                if self.task_id:
                    new_state = json.dumps({"ta_idx": ta_idx, "sub_idx": sub_idx, "page_num": page_num})
                    await self.set_status_by_id(self.task_id, "running", new_state)
                break
            
            if not await self.safe_goto(page, current_url): break
                
            content = await page.content()
            property_links = PropertyValueParser.parse_property_links(content, self.region)
            logger.info(f"  Page {page_num}: Found {len(property_links)} real property links")

            # Only upsert links not already seen in this suburb. If a page only
            # repeats previously-seen links (propertyvalue serves circular pages
            # beyond the real last page), we have reached the end of the list.
            new_links = [l for l in property_links if l not in seen_urls]
            if not new_links:
                logger.info(f"  Page {page_num}: no new properties (end of suburb listing reached). Stopping pagination.")
                current_url = None
                continue
            seen_urls.update(new_links)

            properties_to_save = []
            for prop_path in new_links:
                # Extract clean address from URL slug (remove postcode and property ID)
                addr_slug = prop_path.strip('/').split('/')[-1].split('?')[0]
                
                # Remove the suburb/city/postcode/ID suffix to get just the street address
                # Format: "street-address-suburb-city-postcode-propertyid"
                # We want: "street-address"
                parts = addr_slug.split('-')
                
                # Find where the address part ends (usually before the postcode which is 4 digits)
                address_parts = []
                for i, part in enumerate(parts):
                    # Stop if we hit a 4-digit postcode
                    if part.isdigit() and len(part) == 4:
                        break
                    # Stop if we hit the suburb name (case-insensitive match)
                    if suburb_name and part.lower() in suburb_name.lower().split():
                        break
                    address_parts.append(part)
                
                # If we couldn't parse it properly, use first 3-5 parts as address
                if len(address_parts) < 2:
                    address_parts = parts[:min(5, len(parts))]
                
                # Smart format: detect unit numbers (e.g., "1 10" -> "1/10")
                clean_address = self._format_address(address_parts)
                
                properties_to_save.append({
                    'address': clean_address,
                    'property_url': self.base_url + prop_path,
                    'suburb': suburb_name,
                    'city': ta_name
                })

            if properties_to_save:
                await self._save_properties_batch(properties_to_save)

            # Update page progress and heartbeat
            if self.task_id:
                new_state = json.dumps({"ta_idx": ta_idx, "sub_idx": sub_idx, "page_num": page_num})
                await self.set_status_by_id(self.task_id, "running", new_state)

            next_href = PropertyValueParser.parse_next_page(content)
            if next_href:
                current_url = self.base_url + next_href if next_href.startswith('/') else next_href
                page_num += 1
                logger.info(f"  Moving to page {page_num}...")
            else:
                current_url = None

        # All pages processed for this suburb - advance to next suburb
        # This ensures breakpoint resume continues with the next suburb even
        # if should_stop() fires in the outer loop before the state update.
        if not stopped_early and self.task_id:
            new_state = json.dumps({"ta_idx": ta_idx, "sub_idx": sub_idx + 1, "page_num": 1})
            await self.set_status_by_id(self.task_id, "running", new_state)

        return not stopped_early

    async def run_backfill(self):
        logger.info(f"Starting Backfill Mode for region: {self.region}")

        processed_count = 0

        # Buffered writers: accumulate rows in memory and flush with execute_batch
        # (single transaction per flush) instead of one transaction per row.
        FLUSH = 100
        heartbeat_every = 25
        update_buffer = []        # main UPDATE (with last_sold_date)
        update_node_buffer = []   # no-date UPDATE variant
        history_buffer = []       # property_history INSERTs
        backfilled_buffer = []    # mark backfilled_at

        history_insert_sql = """
            INSERT INTO property_history
            (property_id, event_date, event_description, interval_since_last_event)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (property_id, event_date, event_description) DO NOTHING
        """

        def flush_updates():
            if update_buffer:
                db.execute_batch(update_sql_main, update_buffer)
                update_buffer.clear()
            if update_node_buffer:
                db.execute_batch(update_sql_no_date, update_node_buffer)
                update_node_buffer.clear()

        def flush_history():
            if history_buffer:
                db.execute_batch(history_insert_sql, history_buffer)
                history_buffer.clear()

        def flush_backfilled():
            if backfilled_buffer:
                db.execute_batch("UPDATE properties SET backfilled_at = NOW() WHERE id = %s", backfilled_buffer)
                backfilled_buffer.clear()

        def flush_all():
            flush_updates()
            flush_history()
            flush_backfilled()

        update_sql_main = None
        update_sql_no_date = None

        if self.task_id and not self.simulate:
            remaining_at_start = self._count_unbackfilled()
            self._save_remaining(remaining_at_start)
            logger.info(f"Remaining properties to backfill at start: {remaining_at_start}")
            if remaining_at_start == 0:
                if await self._discovery_complete():
                    logger.info("No properties need backfilling and discovery is complete. Marking task complete.")
                    await self.set_status_by_id(self.task_id, "complete")
                else:
                    logger.info("No properties need backfilling yet, but discovery has not finished all suburbs. Staying resumable.")
                return

        while not self.should_stop():
            properties = []
            if not self.simulate:
                try:
                    if self.address_filter:
                        clause, params = self._address_match_clause()
                        sql = """
                            SELECT id, address, suburb, property_url FROM properties
                            WHERE region = %s AND {}
                            ORDER BY id LIMIT 1
                        """.format(clause)
                        properties = db.query(sql, (self.region,) + params)
                    elif self.suburbs_filter:
                        sql = """
                            SELECT id, address, suburb, property_url FROM properties
                            WHERE (backfilled_at IS NULL
                                   OR property_history IS NULL
                                   OR has_rental_history IS NULL)
                              AND region = %s AND {} 
                            ORDER BY random() ASC LIMIT 50
                        """.format(SUBURB_PARTIAL_MATCH_SQL)
                        properties = db.query(sql, (self.region, self.suburbs_filter))
                    else:
                        sql = """
                            SELECT id, address, suburb, property_url FROM properties
                            WHERE (backfilled_at IS NULL
                                   OR property_history IS NULL
                                   OR has_rental_history IS NULL)
                              AND region = %s
                            ORDER BY random() ASC LIMIT 50
                        """
                        properties = db.query(sql, (self.region,))
                except Exception as e:
                    logger.warning(f"Database query failed: {e}")

            if not properties:
                logger.info("No properties found for backfill.")
                if self.task_id:
                    self._save_remaining(0)
                    if await self._discovery_complete():
                        await self.set_status_by_id(self.task_id, "complete")
                    else:
                        logger.info("Discovery has not finished all suburbs. Staying resumable.")
                break

            logger.info(f"Processing batch of {len(properties)} properties...")

            for prop in properties:
                if self.should_stop(): break
                
                db_suburb = prop.get('suburb')
                logger.info(f"Backfilling details for: {prop['address']}{', ' + db_suburb if db_suburb else ''}")
                
                # Update heartbeat occasionally (every heartbeat_every properties)
                if self.task_id and processed_count % heartbeat_every == 0:
                    await self.set_status_by_id(self.task_id, "running")
                
                page = await self.context.new_page()
                try:
                    if not await self.safe_goto(page, prop['property_url']):
                        continue

                    # Wait for React-rendered story-content to appear (description)
                    # Falls back gracefully if not found within timeout
                    try:
                        await page.wait_for_selector('[testid="story-content"]', timeout=8000)
                    except Exception:
                        pass  # Continue anyway — REDUX_DATA still provides other fields

                    content = await page.content()
                    data = PropertyValueParser.parse_detail_data(content)

                    if self.simulate:
                        logger.info(f"  [SIM] Beds: {data['bedrooms']}, Baths: {data['bathrooms']}, Year: {data['year_built']}")
                        continue

                    last_sold_date_sql = self._to_sql_date(data.get('last_sold_date'))

                    # Try to update with last_sold_date first
                    update_sql_main = """
                        UPDATE properties
                        SET bedrooms = %s, bathrooms = %s, car_spaces = %s,
                            floor_size = %s, land_area_numeric = %s,
                            year_built = %s, property_type = %s,
                            capital_value = %s, land_value = %s,
                            improvement_value = %s,
                            images = %s, description = %s,
                            estimated_value_low = %s, estimated_value_high = %s,
                            last_sold_price = %s, last_sold_date = %s,
                            suburb_median_price = %s, suburb_median_rent = %s,
                            suburb_days_on_market = %s,
                            latitude = %s, longitude = %s,
                            cover_image_url = %s,
                            postcode = COALESCE(%s, postcode),
                            suburb = COALESCE(%s, suburb),
                            property_history = %s,
                            has_rental_history = %s
                        WHERE id = %s
                    """
                    
                    try:
                        update_buffer.append((
                            data['bedrooms'], data['bathrooms'], data.get('car_spaces'),
                            str(data['floor_area']) if data['floor_area'] else None,
                            data['land_area'],
                            data['year_built'], data.get('property_type'),
                            data.get('capital_value'), data.get('land_value'),
                            data.get('improvement_value'),
                            json.dumps(data['images']),
                            data.get('description'),
                            data.get('estimated_value_low'), data.get('estimated_value_high'),
                            data.get('last_sold_price'), last_sold_date_sql,
                            data.get('suburb_median_price'), data.get('suburb_median_rent'),
                            data.get('suburb_days_on_market'),
                            data.get('latitude'), data.get('longitude'),
                            data['images'][0] if data['images'] else None,
                            data.get('postcode'), data.get('suburb'),
                            data.get('property_history'),
                            data.get('has_rental_history', False),
                            prop['id']
                        ))
                    except Exception as date_error:
                        # If date parsing fails, retry without last_sold_date
                        if "parsing as type date" in str(date_error):
                            logger.warning(f"Date parsing error for {prop['address']}. Updating without last_sold_date.")
                            update_sql_no_date = """
                                UPDATE properties
                                SET bedrooms = %s, bathrooms = %s, car_spaces = %s,
                                    floor_size = %s, land_area_numeric = %s,
                                    year_built = %s, property_type = %s,
                                    capital_value = %s, land_value = %s,
                                    improvement_value = %s,
                                    images = %s, description = %s,
                                    estimated_value_low = %s, estimated_value_high = %s,
                                    last_sold_price = %s,
                                    suburb_median_price = %s, suburb_median_rent = %s,
                                    suburb_days_on_market = %s,
                                    latitude = %s, longitude = %s,
                                    cover_image_url = %s,
                                    postcode = COALESCE(%s, postcode),
                                    suburb = COALESCE(%s, suburb),
                                    property_history = %s,
                                    has_rental_history = %s
                                WHERE id = %s
                            """
                            update_node_buffer.append((
                                data['bedrooms'], data['bathrooms'], data.get('car_spaces'),
                                str(data['floor_area']) if data['floor_area'] else None,
                                data['land_area'],
                                data['year_built'], data.get('property_type'),
                                data.get('capital_value'), data.get('land_value'),
                                data.get('improvement_value'),
                                json.dumps(data['images']),
                                data.get('description'),
                                data.get('estimated_value_low'), data.get('estimated_value_high'),
                                data.get('last_sold_price'),
                                data.get('suburb_median_price'), data.get('suburb_median_rent'),
                                data.get('suburb_days_on_market'),
                                data.get('latitude'), data.get('longitude'),
                                data['images'][0] if data['images'] else None,
                                data.get('postcode'), data.get('suburb'),
                                data.get('property_history'),
                                data.get('has_rental_history', False),
                                prop['id']
                            ))
                        else:
                            raise

                    if data.get('history'):
                        for ev in data['history']:
                            event_date_sql = self._to_sql_date(ev['event_date'])
                            if event_date_sql:
                                history_buffer.append([prop['id'], event_date_sql, ev['event_description'], ev['event_interval']])

                    backfilled_buffer.append((prop['id'],))

                    parsed_suburb = data.get('suburb') or db_suburb
                    processed_count += 1
                    logger.info(f"  Successfully updated {prop['address']}{', ' + parsed_suburb if parsed_suburb else ''} (#{processed_count})")

                    # Flush buffered writes periodically to bound memory usage
                    if len(update_buffer) + len(update_node_buffer) + len(history_buffer) + len(backfilled_buffer) >= FLUSH:
                        flush_updates()
                        flush_history()
                        flush_backfilled()
                    
                except Exception as e:
                    logger.error(f"Failed to backfill {prop['address']}: {e}")
                    backfilled_buffer.append((prop['id'],))
                finally:
                    await page.close()

        flush_all()  # persist any remaining buffered writes

        if self.should_stop():
            elapsed_h = (time.monotonic() - self.start_time) / 3600
            logger.info(f"⏱️ Time limit reached ({elapsed_h:.1f}h). Processed {processed_count} properties. Exiting for breakpoint resume.")
            if self.task_id and not self.simulate:
                remaining = self._count_unbackfilled()
                self._save_remaining(remaining)
                if remaining == 0 and await self._discovery_complete():
                    await self.set_status_by_id(self.task_id, "complete")
                else:
                    logger.info(f"Backfill resume checkpoint saved: {remaining} properties remaining.")

    @staticmethod
    def _to_sql_date(date_str):
        if not date_str:
            return None
        from datetime import datetime
        s = str(date_str).strip()
        if re.match(r'^\d{4}-\d{2}-\d{2}$', s):
            return s
        for fmt in (
            "%d %b %Y",
            "%d %B %Y",
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%Y/%m/%d",
        ):
            try:
                return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        if re.match(r'^\d{4}$', s):
            return f"{s}-01-01"
        logger.warning(f"Could not parse date: {date_str}. Setting to NULL.")
        return None

    @staticmethod
    def _format_address(address_parts):
        if not address_parts:
            return ""
        
        if len(address_parts) >= 2:
            first = address_parts[0]
            second = address_parts[1]
            
            p1 = r'^[a-zA-Z]{0,2}\d+[a-zA-Z]?$'
            p2 = r'^\d+[a-zA-Z]?$'
            if re.match(p1, first) and re.match(p2, second):
                unit_part = f"{first}/{second}"
                rest_parts = address_parts[2:]
                formatted_rest = ' '.join(rest_parts).title()
                return f"{unit_part} {formatted_rest}".strip()
        
        return ' '.join(address_parts).title()

    @staticmethod
    def _extract_suburb_name(sub_link):
        parts = sub_link.strip('/').split('/')
        if len(parts) >= 3:
            segment = parts[-2] if parts[-1].isdigit() else parts[-1]
            sub_parts = segment.split('-')
            if len(sub_parts) > 1 and sub_parts[-1].isdigit() and len(sub_parts[-1]) == 4:
                return " ".join(sub_parts[:-1])
            return segment.replace('-', ' ').strip()
        return ""

    async def run_refresh(self):
        # Refresh follows a similar sequential logic as backfill
        pass

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["discovery", "backfill", "refresh"], default="discovery")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--simulate", action="store_true")
    parser.add_argument("--region", default="auckland", choices=["auckland", "wellington"])
    parser.add_argument("--task_id", type=int, help="Task ID for progress tracking")
    parser.add_argument("--suburbs", type=str, default=None,
                        help="Comma-separated suburb names to filter (e.g. 'Northcross,Torbay,Beach Haven')")
    parser.add_argument("--max_runtime", type=float, default=5.5, help="Max runtime in hours")
    parser.add_argument("--ta", type=str, default=None,
                        help="Territorial Authority slug to restrict discovery to (e.g. north-shore-city, auckland)")
    parser.add_argument("--address", type=str, default=None,
                        help="Target a single property address (e.g. '850A Beach Road, Waiake') in backfill mode")
    args = parser.parse_args()

    engine = PropertyValueEngine(args.mode, args.force, args.simulate, args.region, args.task_id, args.suburbs, args.max_runtime, args.ta, args.address)
    asyncio.run(engine.run())
