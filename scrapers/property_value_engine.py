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

class PropertyValueEngine(BaseScraper):
    def __init__(self, mode="discovery", force_run=False, simulate=False, region="auckland", task_id=None, suburbs_filter=None, max_runtime=5.5):
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

        sql = """
            INSERT INTO properties (id, address, suburb, city, region, property_url, address_fingerprint, created_at)
            VALUES (md5(random()::text || clock_timestamp()::text), %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (address_fingerprint) DO UPDATE
            SET property_url = EXCLUDED.property_url
            RETURNING address, suburb, (created_at >= CURRENT_TIMESTAMP - INTERVAL '1 second') as is_new
        """
        
        try:
            for params in batch_params:
                result = db.query(sql, params)
                if result:
                    status = "[NEW]" if result[0]['is_new'] else "[UPD]"
                    sub = result[0].get('suburb')
                    logger.info(f"  {status} {result[0]['address']}{', ' + sub if sub else ''}")
        except Exception as e:
            logger.error(f"Failed to process properties batch: {e}")

    async def run_discovery(self):
        logger.info(f"Starting Discovery Mode for region: {self.region}")
        if self.force_run:
            state = {}
        else:
            state = await self.get_state() or {}
        last_ta_idx = state.get('ta_idx', 0)
        last_sub_idx = state.get('sub_idx', 0)
        last_page = state.get('page_num', 1)

        target_url = f"{self.base_url}{self.region_path}"
        page = await self.context.new_page()

        try:
            if not await self.safe_goto(page, target_url): return

            content = await page.content()
            ta_links = PropertyValueParser.parse_ta_links(content, self.region)
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
                if self.suburbs_filter:
                    suburb_links = [
                        link for link in suburb_links
                        if self._extract_suburb_name(link).lower() in self.suburbs_filter
                    ]
                    logger.info(f"After suburb filter: {len(suburb_links)} suburbs remaining")
                    if not suburb_links:
                        continue

                for j, sub_link in enumerate(suburb_links):
                    if i == last_ta_idx and j < last_sub_idx: continue
                    
                    if self.should_stop():
                        logger.info("Stopping discovery due to time limit.")
                        return

                    parts = sub_link.strip('/').split('/')
                    suburb_name = parts[-2].rsplit('-', 1)[0].replace('-', ' ').title() if len(parts) >= 3 else "Unknown"
                    
                    # Page resumption only for the first suburb we hit
                    resume_page = last_page if (i == last_ta_idx and j == last_sub_idx) else 1
                    
                    await self._scrape_suburb_properties(page, self.base_url + sub_link, suburb_name, ta_name, i, j, resume_page)
                    
                    if self.should_stop(): return

                    # Update state after each suburb (next suburb, page 1)
                    if self.task_id:
                        new_state = json.dumps({"ta_idx": i, "sub_idx": j + 1, "page_num": 1})
                        await self.set_status_by_id(self.task_id, "running", new_state)

            if self.task_id:
                await self.set_status_by_id(self.task_id, "complete", json.dumps({"ta_idx": 0, "sub_idx": 0, "page_num": 1}))

        except Exception as e:
            logger.error(f"Discovery failed: {e}")
        finally:
            await page.close()

    async def _scrape_suburb_properties(self, page, suburb_url, suburb_name, ta_name, ta_idx, sub_idx, start_page=1):
        logger.info(f"Scraping suburb: {suburb_name} from page {start_page}")
        current_url = f"{suburb_url}?page={start_page}" if start_page > 1 else suburb_url
        page_num = start_page

        while current_url:
            if self.should_stop(): 
                # Save current page progress before stopping
                if self.task_id:
                    new_state = json.dumps({"ta_idx": ta_idx, "sub_idx": sub_idx, "page_num": page_num})
                    await self.set_status_by_id(self.task_id, "running", new_state)
                break
            
            if not await self.safe_goto(page, current_url): break
                
            content = await page.content()
            property_links = PropertyValueParser.parse_property_links(content, self.region)
            logger.info(f"  Page {page_num}: Found {len(property_links)} real property links")

            properties_to_save = []
            for prop_path in property_links:
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

    async def run_backfill(self):
        logger.info(f"Starting Backfill Mode for region: {self.region}")
        
        processed_count = 0
        
        while not self.should_stop():
            properties = []
            if not self.simulate:
                try:
                    if self.suburbs_filter:
                        sql = """
                            SELECT id, address, suburb, property_url FROM properties
                            WHERE (backfilled_at IS NULL
                                   OR property_history IS NULL
                                   OR has_rental_history IS NULL)
                              AND region = %s AND LOWER(suburb) = ANY(%s)
                            ORDER BY created_at ASC LIMIT 50
                        """
                        properties = db.query(sql, (self.region, self.suburbs_filter))
                    else:
                        sql = """
                            SELECT id, address, suburb, property_url FROM properties
                            WHERE (backfilled_at IS NULL
                                   OR property_history IS NULL
                                   OR has_rental_history IS NULL)
                              AND region = %s
                            ORDER BY created_at ASC LIMIT 50
                        """
                        properties = db.query(sql, (self.region,))
                except Exception as e:
                    logger.warning(f"Database query failed: {e}")

            if not properties:
                logger.info("No properties found for backfill.")
                if self.task_id:
                    await self.set_status_by_id(self.task_id, "complete")
                break

            logger.info(f"Processing batch of {len(properties)} properties...")

            for prop in properties:
                if self.should_stop(): break
                
                db_suburb = prop.get('suburb')
                logger.info(f"Backfilling details for: {prop['address']}{', ' + db_suburb if db_suburb else ''}")
                
                # Update heartbeat occasionally (every property)
                if self.task_id:
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
                    update_sql = """
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
                        db.execute(update_sql, (
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
                            db.execute(update_sql_no_date, (
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
                        history_sql = """
                            INSERT INTO property_history
                            (property_id, event_date, event_description, interval_since_last_event)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (property_id, event_date, event_description) DO NOTHING
                        """
                        history_params = []
                        for ev in data['history']:
                            event_date_sql = self._to_sql_date(ev['event_date'])
                            if event_date_sql:
                                history_params.append([prop['id'], event_date_sql, ev['event_description'], ev['event_interval']])
                        if history_params:
                            db.execute_batch(history_sql, history_params)

                    db.execute("UPDATE properties SET backfilled_at = NOW() WHERE id = %s", (prop['id'],))

                    parsed_suburb = data.get('suburb') or db_suburb
                    processed_count += 1
                    logger.info(f"  Successfully updated {prop['address']}{', ' + parsed_suburb if parsed_suburb else ''} (#{processed_count})")
                    
                except Exception as e:
                    logger.error(f"Failed to backfill {prop['address']}: {e}")
                    db.execute("UPDATE properties SET backfilled_at = NOW() WHERE id = %s", (prop['id'],))
                finally:
                    await page.close()

        if self.should_stop():
            elapsed_h = (time.monotonic() - self.start_time) / 3600
            logger.info(f"⏱️ Time limit reached ({elapsed_h:.1f}h). Processed {processed_count} properties. Exiting for breakpoint resume.")

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
    args = parser.parse_args()

    engine = PropertyValueEngine(args.mode, args.force, args.simulate, args.region, args.task_id, args.suburbs, args.max_runtime)
    asyncio.run(engine.run())
