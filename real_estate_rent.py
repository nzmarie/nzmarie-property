from playwright.sync_api import sync_playwright, TimeoutError
import time
import random
import os
from dotenv import load_dotenv
import traceback
import logging
import json
import re

# Load environment variables
load_dotenv()

# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("real_estate_rent.log"),
        logging.StreamHandler()
    ]
)

# Create logger
logger = logging.getLogger(__name__)

from config.supabase_config import insert_real_estate_rent, create_supabase_client, upsert_real_estate_rent_detail
from utils.address_helper import parse_nz_address

# Function to create scraping progress table if it doesn't exist
def create_scraping_progress_table():
    """
    Create a table to track scraping progress.
    """
    supabase = create_supabase_client()
    try:
        # Check if the scraping_progress table exists by trying to select from it
        response = supabase.table('scraping_progress').select('*').limit(1).execute()
        logger.info("Scraping progress table already exists.")
    except Exception as e:
        logger.error(f"Scraping progress table may not exist: {e}")
        logger.info("Please ensure the scraping_progress table exists in your Supabase database with the following structure:")
        logger.info("- id (int, primary key)")
        logger.info("- last_processed_id (text)")
        logger.info("- batch_size (int)")
        logger.info("- updated_at (timestamp)")

# Function to get the last processed page from the progress table
def get_last_processed_page():
    """
    Get the last processed page number from the progress table for rent real estate.
    """
    supabase = create_supabase_client()
    try:
        # Try to get the record with id=4 for rent real estate
        response = supabase.table('scraping_progress').select('last_processed_id, status').eq('id', 4).execute()
        if response.data and len(response.data) > 0:
            record = response.data[0]
            status = record.get('status', 'idle')
            last_processed_id = record.get('last_processed_id')
            
            # If status is complete, we should start from the beginning
            if status == 'complete':
                logger.info("Task was completed previously. Starting from the beginning.")
                return 0
            
            # Return the page number if it's not None or empty
            if last_processed_id:
                page_num = int(last_processed_id)
                logger.info(f"Resuming from page: {page_num}")
                return page_num
            else:
                # If last_processed_id is None or empty, it means we're starting from the beginning
                logger.info("Starting from the beginning (empty last_processed_id)")
                return 0
        
        # If no record with id=4, it means we're starting from the beginning
        logger.info("Starting from the beginning (no progress records found for rent)")
        return 0
    except Exception as e:
        logger.error(f"Error getting last processed page: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")
        return 0

# Function to update the last processed page in the progress table
def update_last_processed_page(last_page):
    """
    Update the last processed page number in the progress table for rent real estate.
    """
    supabase = create_supabase_client()
    try:
        # First, try to update the existing record with id=4 for rent real estate
        response = supabase.table('scraping_progress').update({
            'last_processed_id': str(last_page),
            'batch_size': 1000,  # Default batch size
            'updated_at': 'now()'
        }).eq('id', 4).execute()
        
        # Check if the update was successful
        if response.data:
            logger.info(f"Updated last processed page to: {last_page}")
        else:
            # If no record was updated, insert a new one with id=4
            data = {
                'id': 4,  # Use ID 4 for rent real estate progress
                'last_processed_id': str(last_page),
                'batch_size': 1000,  # Default batch size
                'updated_at': 'now()'
            }
            response = supabase.table('scraping_progress').insert(data).execute()
            
            if response.data:
                logger.info(f"Inserted new record with last processed page: {last_page}")
            else:
                logger.error(f"Failed to insert/update last processed page: {last_page}")
    except Exception as e:
        logger.error(f"Error updating last processed page: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")

# Function to check if another instance is already running
def is_already_running():
    """
    Check rent scraper status with immediate decision (no waiting):
    - If 'running': exit immediately 
    - If 'idle': proceed with execution
    - If 'complete' or 'stop': exit (task finished or stopped)
    """
    supabase = create_supabase_client()
    try:
        # Get the status for rent scraper (id=4)
        response = supabase.table('scraping_progress').select('updated_at, status').eq('id', 4).execute()
        if response.data and len(response.data) > 0:
            status = response.data[0].get('status', 'idle')
            updated_at = response.data[0].get('updated_at', '')
            
            logger.info(f"Rent scraper status: {status} (updated: {updated_at})")
            
            if status == 'running':
                if updated_at:
                    from datetime import datetime, timezone
                    try:
                        if isinstance(updated_at, str):
                            try:
                                from dateutil.parser import parse
                                updated_dt = parse(updated_at)
                            except ImportError:
                                logger.warning("dateutil not available, assuming stale lock")
                                return False
                        else:
                            updated_dt = updated_at

                        if updated_dt:
                            now = datetime.now(timezone.utc)
                            if updated_dt.tzinfo is None:
                                updated_dt = updated_dt.replace(tzinfo=timezone.utc)
                            
                            diff = (now - updated_dt).total_seconds()
                            if diff > 2700: # 45 minutes
                                logger.info(f"Rent scraper has a stale lock (last updated {diff / 60:.1f}m ago). Proceeding.")
                                return False
                    except Exception as e:
                        logger.warning(f"Error checking lock staleness: {e}. Assuming stale.")
                        return False

                logger.info("Another rent scraper instance is running. Exiting immediately.")
                return True
            
            elif status == 'idle':
                logger.info("Rent scraper status is idle. Proceeding with execution.")
                return False
            
            elif status == 'complete':
                logger.info("Rent scraper task is completed. No execution needed.")
                return True
            
            elif status == 'stop':
                logger.info("Rent scraper task was manually stopped. Exiting.")
                return True
            
            else:
                logger.warning(f"Unknown status '{status}', proceeding with execution")
                return False
                
        return False
    except Exception as e:
        logger.error(f"Error checking rent scraper status: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")
        # In case of error, assume not running to avoid blocking legitimate runs
        return False

# Function to update the lock timestamp
def update_lock_timestamp():
    """
    Update the lock timestamp to indicate the process is running.
    """
    supabase = create_supabase_client()
    try:
        # Update the updated_at timestamp for rent scraper (id=4)
        response = supabase.table('scraping_progress').update({
            'updated_at': 'now()',
            'status': 'running'
        }).eq('id', 4).execute()
        
        if response.data:
            logger.info("Rent scraper lock timestamp updated successfully.")
        else:
            logger.warning("Failed to update rent scraper lock timestamp.")
    except Exception as e:
        logger.error(f"Error updating rent scraper lock timestamp: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")

def mark_complete():
    """
    Mark the rent scraper task as complete.
    """
    supabase = create_supabase_client()
    try:
        response = supabase.table('scraping_progress').update({
            'status': 'complete',
            'updated_at': 'now()'
        }).eq('id', 4).execute()
        
        if response.data:
            logger.info("Rent scraper task marked as complete.")
        else:
            logger.warning("Failed to mark rent scraper task as complete.")
    except Exception as e:
        logger.error(f"Error marking rent scraper task as complete: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")

def trigger_next_workflow():
    """
    Trigger the next workflow run using GitHub API.
    """
    import os
    github_token = os.getenv('GITHUB_TOKEN')
    github_repo = os.getenv('GITHUB_REPOSITORY')
    
    if not github_token or not github_repo:
        logger.warning("GitHub token or repository not available. Cannot trigger next workflow.")
        return
    
    try:
        import requests
        
        url = f"https://api.github.com/repos/{github_repo}/actions/workflows/real_estate_rent.yml/dispatches"
        headers = {
            'Authorization': f'token {github_token}',
            'Accept': 'application/vnd.github.v3+json'
        }
        data = {
            'ref': 'main'
        }
        
        response = requests.post(url, headers=headers, json=data)
        
        if response.status_code == 204:
            logger.info("Successfully triggered next workflow run.")
        else:
            logger.warning(f"Failed to trigger next workflow. Status: {response.status_code}")
            
    except Exception as e:
        logger.error(f"Error triggering next workflow: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")

def handle_dialog(dialog):
    """
    Handle dialog boxes that may appear during scraping.
    """
    try:
        print(f"Dialog message: {dialog.message}")
        dialog.accept()
    except Exception as e:
        logger.error(f"Error handling dialog: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")

def scroll_to_bottom(page):
    """
    Scroll to the bottom of the page to load all content.
    Handles navigation that might occur during scrolling.
    """
    try:
        print("Starting to simulate mouse scrolling...")
        last_height = page.evaluate("document.body.scrollHeight")
        scroll_attempts = 0
        max_scroll_attempts = 50
        
        while scroll_attempts < max_scroll_attempts:
            print(f"  - Current page height: {last_height}, continuing to scroll...")
            
            # Check if page is still valid before scrolling
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            except Exception as e:
                if "Execution context was destroyed" in str(e) or "context" in str(e).lower():
                    logger.warning("Page context destroyed during scroll, page may have navigated")
                    break
                raise
            
            time.sleep(random.uniform(1, 2))  # Wait for page to load
            
            # Check if page is still valid before evaluating
            try:
                new_height = page.evaluate("document.body.scrollHeight")
            except Exception as e:
                if "Execution context was destroyed" in str(e) or "context" in str(e).lower():
                    logger.warning("Page context destroyed during height check, page may have navigated")
                    break
                raise
            
            if new_height == last_height:
                print("  - Reached bottom of page")
                break
            last_height = new_height
            scroll_attempts += 1

            # Check if pagination navigation appeared
            try:
                if page.query_selector('nav[aria-label="Pagination"]') or page.query_selector('div[class*="pagination"]'):
                    print("  - Detected pagination navigation, stopping scroll")
                    break
            except Exception:
                pass  # Ignore selector errors
                
    except Exception as e:
        logger.error(f"Error scrolling to bottom: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")

def simulate_user_behavior(page):
    """
    Simulate user behavior to avoid anti-scraping mechanisms.
    """
    try:
        scroll_to_bottom(page)
        
        # Randomly click on property cards
        print("Simulating viewing property cards...")
        card_selectors = [
            'div[class*="listing-tile"]',
            'div[class*="property-card"]',
            'div[class*="search-result"]'
        ]
        for selector in card_selectors:
            cards = page.query_selector_all(selector)
            if cards:
                for _ in range(min(3, len(cards))):
                    card = random.choice(cards)
                    try:
                        card.scroll_into_view_if_needed()
                        card.hover()
                        print(f"  - Hovering over a property card")
                        time.sleep(random.uniform(0.5, 1.5))
                    except Exception as e:
                        logger.warning(f"Error hovering over card: {e}")
                        pass
                break

        # Additional scrolling operations
        print("Simulating additional scroll operations")
        for i in range(10):
            scroll_distance = random.randint(500, 1500)
            page.evaluate(f"window.scrollBy(0, {scroll_distance})")
            print(f"  - Scrolling down {scroll_distance} pixels")
            time.sleep(random.uniform(1, 2))

        # Scroll to bottom again
        print("Scrolling to bottom of page again")
        scroll_to_bottom(page)
    except Exception as e:
        logger.error(f"Error simulating user behavior: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")

def fetch_property_links_rent(page, url):
    """
    Fetch property detail page links from a rent listing page.
    Returns list of relative URL strings like /residential/rent/...
    """
    max_retries = 3
    for attempt in range(max_retries):
        try:
            logger.info(f"Loading page {url} (attempt {attempt + 1}/{max_retries})")
            # domcontentloaded avoids hangs waiting for persistent analytics/ads network
            page.goto(url, wait_until="domcontentloaded", timeout=90000)
            
            # Wait for property cards to be visible
            try:
                page.wait_for_selector('a[href*="/residential/rent/"]', timeout=15000)
            except Exception:
                logger.warning("Property links selector not found, continuing anyway")
            
            # Small delay to ensure page is fully rendered
            time.sleep(random.uniform(2, 4))
            
            # Simulate user behavior to load all content
            simulate_user_behavior(page)
            
            links = page.evaluate("""
                () => {
                    const anchors = document.querySelectorAll('a[href*="/residential/rent/"]:not([href*="map"])');
                    return Array.from(anchors).map(el => el.getAttribute('href')).filter(Boolean);
                }
            """)
            unique_links = list(set([
                l for l in links
                if l and '/residential/rent/' in l and '?' not in l and re.search(r'/\d{6,}/', l)
            ]))
            logger.info(f"Found {len(unique_links)} rental property links on page.")
            return unique_links
            
        except Exception as e:
            logger.warning(f"Attempt {attempt + 1} failed for {url}: {e}")
            if attempt < max_retries - 1:
                time.sleep(random.uniform(5, 10))
            else:
                logger.error(f"All attempts failed for {url}: {e}")
                return []
    
    return []

def scrape_rent_property_detail(page, relative_url):
    """
    Scrape detailed information (including images) from a rental property detail page.
    """
    import json as _json
    base_url = "https://www.realestate.co.nz"
    full_url = f"{base_url}{relative_url}" if relative_url.startswith('/') else relative_url

    data = {
        "property_url": full_url,
        "original_link": full_url,
        "status": "for Rent",
        "listing_date_raw": None,
        "listing_date_parsed": None,
        "listing_number": None,
        "price_display": None,
        "address": None,
        "agent_name": None,
        "description": None,
        "region": "auckland",
        "latitude": None,
        "longitude": None,
    }

    try:
        if not relative_url.startswith('/'):
            logger.warning(f"Invalid relative URL: {relative_url}")
            return None

        time.sleep(random.uniform(2, 4))
        logger.info(f"Navigating to rental detail page: {full_url}")
        page.goto(full_url, wait_until="domcontentloaded", timeout=90000)
        # Wait for description to render
        try:
            page.wait_for_selector('[data-test="description-content__description"]', timeout=15000)
        except Exception:
            pass

        addr_selectors = ['h1.p-h1', 'h1', '[data-test="address-display"]']
        for sel in addr_selectors:
            if page.locator(sel).first.is_visible():
                address = page.locator(sel).first.inner_text().strip()
                if address and 'results in' not in address.lower():
                    data['address'] = address
                    break

        if data.get('address'):
            parsed = parse_nz_address(data['address'])
            data['address'] = parsed['street_address']
            data['suburb'] = parsed['suburb']
            data['city'] = parsed['city']

        if not data.get('address'):
            logger.warning(f"No valid address found for {full_url}")
            return None

        try:
            price_el = page.locator('[data-test="price-display"]').first
            if price_el.is_visible():
                data['price_display'] = price_el.inner_text().strip()
        except Exception:
            pass

        try:
            date_el = page.locator('[data-test="description__listed-date"]').first
            if date_el.is_visible():
                data['listing_date_raw'] = date_el.inner_text().strip()
                import re as _re
                from datetime import datetime as _dt
                m = _re.search(r'(\d{1,2}\s+\w+\s+\d{4})', data['listing_date_raw'])
                if m:
                    try:
                        data['listing_date_parsed'] = _dt.strptime(m.group(1), "%d %B %Y").strftime("%Y-%m-%d")
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            num_el = page.locator('[data-test="description__listing-number"]').first
            if num_el.is_visible():
                raw = num_el.inner_text().strip()
                m = re.search(r'(\d+)', raw)
                if m:
                    data['listing_number'] = m.group(1)
        except Exception:
            pass

        try:
            desc_el = page.locator('[data-test="description-content__description"]').first
            if desc_el.is_visible():
                data['description'] = desc_el.inner_text().strip()
        except Exception:
            pass

        try:
            agent_el = page.locator('[data-test="agent-name"], .agent-name').first
            if agent_el.is_visible():
                data['agent_name'] = agent_el.inner_text().strip()
            office_el = page.locator('[data-test="office-name"]').first
            if office_el.is_visible():
                office_name = office_el.inner_text().strip()
                data['agent_name'] = f"{data['agent_name']} ({office_name})" if data['agent_name'] else office_name
        except Exception:
            pass

        try:
            features = page.evaluate("""
                () => {
                    const results = {};
                    const container = document.querySelector('div[data-test="features-icons"]');
                    if (!container) return results;
                    const items = container.querySelectorAll(':scope > div');
                    items.forEach(item => {
                        const titleEl = item.querySelector('svg title');
                        const span = item.querySelector('span');
                        if (!titleEl || !span) return;
                        const label = titleEl.textContent.trim();
                        const value = span.textContent.trim();
                        if (label === 'Bedroom')    results['bedrooms']   = value;
                        if (label === 'Bathroom')   results['bathrooms']  = value;
                        if (label === 'Floor area') results['floor_area'] = value;
                        if (label === 'Land area')  results['land_area']  = value;
                        if (['Apartment','House','Townhouse','Unit','Section','Lifestyle','Rural'].includes(label)) {
                            results['property_type'] = label;
                        }
                        if (label === 'Garage')     results['garage']      = value;
                        if (label === 'Other park') results['other_park']  = value;
                    });
                    return results;
                }
            """)
            if features.get('bedrooms'):
                m = re.search(r'\d+', features['bedrooms'])
                if m: data['bedroom_count'] = int(m.group())
            if features.get('bathrooms'):
                m = re.search(r'\d+', features['bathrooms'])
                if m: data['bathroom_count'] = int(m.group())
            if features.get('floor_area'):
                m = re.search(r'([\d,.]+)', features['floor_area'])
                if m: data['floor_area'] = int(float(m.group(1).replace(',', '')))
            if features.get('land_area'):
                val = features['land_area']
                m = re.search(r'([\d,.]+)', val)
                if m:
                    num = float(m.group(1).replace(',', ''))
                    data['land_area'] = int(num * 10000) if 'ha' in val.lower() else int(num)
            if features.get('property_type'):
                data['property_type'] = features['property_type']

            total_car = 0
            has_car = False
            if features.get('garage'):
                m = re.search(r'\d+', features['garage'])
                if m:
                    total_car += int(m.group())
                    has_car = True
            if features.get('other_park'):
                m = re.search(r'\d+', features['other_park'])
                if m:
                    total_car += int(m.group())
                    has_car = True
            if has_car:
                data['car_spaces'] = total_car
        except Exception:
            pass

        try:
            image_urls = page.evaluate(r"""
                () => {
                    const imgs = document.querySelectorAll('div[data-test="image"] img');
                    const urls = [];
                    imgs.forEach(img => {
                        const src = img.getAttribute('src') || '';
                        if (src && !src.startsWith('data:') && src.includes('mediaserver.realestate.co.nz')) {
                            const highRes = src.replace(/\.crop\.\d+x\d+/, '.crop.1200x685');
                            urls.push(highRes);
                        }
                    });
                    return urls;
                }
            """)
            if image_urls:
                data['cover_image_url'] = image_urls[0]
                data['images'] = _json.dumps(image_urls)
        except Exception as e:
            logger.warning(f"Error extracting images: {e}")

        return data

    except Exception as e:
        logger.error(f"Error scraping rental detail {full_url}: {e}")
        return None

def check_real_estate_rent_in_supabase(address: str) -> bool:
    """
    Check if a real estate rental property already exists in the Supabase database.
    """
    try:
        supabase = create_supabase_client()
        response = supabase.table('real_estate_rent').select('id').eq('address', address).limit(1).execute()
        
        if response.data and len(response.data) > 0:
            logger.info(f"Rental property already exists in database: {address}")
            return True
        return False
    except Exception as e:
        logger.error(f"Error checking rental property in database: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")
        # If there's an error checking, we assume it doesn't exist to avoid missing data
        return False

def scrape_properties(main_url, max_pages, max_runtime_hours=5.0):
    """
    Scrape properties with progress tracking and time limit.
    
    Args:
        main_url (str): The base URL to scrape
        max_pages (int): Maximum number of pages to scrape
        max_runtime_hours (float): Maximum runtime in hours before stopping (default 5.5 hours)
    """
    # GitHub Actions already handles status management, so we don't need to check here
    # Just update lock timestamp to indicate we're running
    update_lock_timestamp()
    
    # Set up signal handlers for graceful shutdown
    import signal
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}. Cleaning up...")
        clear_lock()
        exit(0)
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # Remove Redis client
    # redis_client = create_redis_client()  # Instantiate the Redis client
    all_addresses = []
    
    # Create progress table if it doesn't exist
    create_scraping_progress_table()
    
    # Get the last processed page to resume from where we left off
    start_page = get_last_processed_page()
    
    # If we've reached the end, reset to start from beginning
    if start_page >= max_pages:
        logger.info(f"Reached end of pages ({start_page}), resetting to start from beginning")
        start_page = 0
        update_last_processed_page(0)
    
    # Calculate maximum runtime
    start_time = time.time()
    max_runtime_seconds = max_runtime_hours * 3600  # Convert hours to seconds
    
    browser = None
    context = None
    page = None
    
    # Log start of process
    logger.info(f"Starting rent property scraping process. Max runtime: {max_runtime_hours} hours")
    
    # Flag to track if we have data to process
    has_data_to_process = False
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )

            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            )
            page = context.new_page()
            page.on("dialog", handle_dialog)

            timed_out = False
            for page_num in range(start_page + 1, max_pages + 1):
                # Check if we've exceeded the maximum runtime
                elapsed_time = time.time() - start_time
                if elapsed_time > max_runtime_seconds:
                    logger.info(f"Maximum runtime of {max_runtime_hours} hours reached. Stopping...")
                    update_last_processed_page(page_num - 1)
                    supabase = create_supabase_client()
                    try:
                        supabase.table('scraping_progress').update({
                            'status': 'idle',
                            'updated_at': 'now()'
                        }).eq('id', 4).execute()
                        logger.info("Rent scraper status updated to 'idle' due to timeout.")
                    except Exception as e:
                        logger.error(f"Error updating status to 'idle': {e}")
                    timed_out = True
                    break

                update_lock_timestamp()

                try:
                    url = f"{main_url}?page={page_num}"
                    print(f"\nScraping rent page {page_num}: {url}")

                    links = fetch_property_links_rent(page, url)

                    if links:
                        has_data_to_process = True
                        print(f"Found {len(links)} rental links on page {page_num}")

                        for link in links:
                            detail_data = scrape_rent_property_detail(page, link)
                            if detail_data and detail_data.get('address'):
                                ok = upsert_real_estate_rent_detail(detail_data)
                                sub = detail_data.get('suburb') or '-'
                                ci = detail_data.get('city') or '-'
                                status = "OK" if ok else "FAIL"
                                logger.info(f"[SAVE] {status} | {detail_data.get('address')}, {sub}, {ci} | price={detail_data.get('price_display')}")
                            else:
                                logger.warning(f"[SAVE] FAIL | no address scraped | {link}")
                    else:
                        print(f"No rental links found on page {page_num}. Continuing.")

                    update_last_processed_page(page_num)

                    if page_num < max_pages:
                        delay = random.uniform(3, 7)
                        time.sleep(delay)

                except Exception as e:
                    logger.error(f"Error processing rent page {page_num}: {e}")
                    logger.error(f"Error details: {traceback.format_exc()}")
                    update_last_processed_page(page_num)
                    continue

            if not timed_out:
                mark_complete()
                logger.info("All pages processed. Task marked as complete.")
            
    except Exception as e:
        logger.error(f"Error in scraping process: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")
        # Save progress before exiting
        if 'page_num' in locals():
            update_last_processed_page(page_num)
        # Clear the lock when there's an error
        clear_lock()
        raise
    finally:
        # Always clear the lock when exiting if still running
        try:
            supabase = create_supabase_client()
            response = supabase.table('scraping_progress').select('status').eq('id', 4).execute()
            if response.data and response.data[0].get('status') == 'running':
                clear_lock()
                logger.info("Cleared running status in finally block")
        except Exception as e:
            logger.error(f"Error in finally block: {e}")
        
        # If we haven't processed any data, we can exit early
        if not has_data_to_process:
            logger.info("No data to process. Stopping early.")
        # Browser will be automatically closed by the context manager
        logger.info("Browser context closed automatically")

def force_clear_lock():
    """
    Force clear lock to allow script to run.
    """
    supabase = create_supabase_client()
    try:
        from datetime import datetime, timezone
        # Set timestamp to 2 hours ago to ensure it's considered expired
        old_time = datetime.now(timezone.utc).replace(hour=datetime.now(timezone.utc).hour-2)
        supabase.table('scraping_progress').update({
            'updated_at': old_time.isoformat(),
            'status': 'idle'
        }).eq('id', 4).execute()
        logger.info("Force cleared rent scraper lock")
        return True
    except Exception as e:
        logger.error(f"Error force clearing lock: {e}")
        return False

def clear_lock():
    """
    Clear the lock to indicate the process has paused or stopped due to an error.
    """
    supabase = create_supabase_client()
    try:
        response = supabase.table('scraping_progress').update({
            'status': 'idle',
            'updated_at': 'now()'
        }).eq('id', 4).execute()
        
        logger.info("Lock cleared successfully, status set to idle.")
    except Exception as e:
        logger.error(f"Error clearing lock: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")

def main():
    import argparse
    arg_parser = argparse.ArgumentParser(description='Rent Real Estate Scraper')
    arg_parser.add_argument('--task_id', type=int, default=4, help='Task ID (default: 4)')
    args = arg_parser.parse_args()

    try:
        logger.info("Rent Real Estate Scraper")
        logger.info("========================")

        base_url = os.getenv("REALESTATE_URL") or "https://www.realestate.co.nz"
        base_url = base_url.replace('/residential/sale', '').replace('/residential/rental', '').rstrip('/')
        main_url = f"{base_url}/residential/rental"

        max_pages = 412
        scrape_properties(main_url, max_pages)
        logger.info("Scraping process completed (status managed internally)")
    except Exception as e:
        logger.error(f"Error in main function: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")
        clear_lock()
        raise

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Unexpected error in script execution: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")
        clear_lock()
        exit(1)
