from playwright.sync_api import sync_playwright, TimeoutError
import time
import random
import os
from dotenv import load_dotenv
import traceback
import logging

# Load environment variables
load_dotenv()

from config.supabase_config import insert_real_estate, create_supabase_client, upsert_real_estate_detail, upsert_real_estate_rent_detail
import re
import json
from bs4 import BeautifulSoup

# Set up logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("real_estate_auckland.log"),
        logging.StreamHandler()
    ]
)

# Create logger
logger = logging.getLogger(__name__)

# Function to scrape property details from the detail page
def scrape_property_detail(page, relative_url, region='auckland', mode='buy'):
    """
    Scrape detailed information from a property detail page.
    """
    base_url = "https://www.realestate.co.nz"
    full_url = f"{base_url}{relative_url}"
    
    data = {
        "property_url": full_url,
        "original_link": full_url,
        "status": "for Sale" if mode == 'buy' else "for Rent",
        "listing_date_raw": None,
        "listing_date_parsed": None,
        "listing_number": None,
        "price_display": None,
        "address": None,
        "agent_name": None,
        "description": None,
        "region": region,
        "latitude": None,
        "longitude": None
    }
    
    try:
        # Check URL validity
        if not relative_url.startswith('/'):
            logger.warning(f"Invalid relative URL: {relative_url}")
            return None

        # Navigate to detail page — wait for description to render
        time.sleep(random.uniform(2, 4))
        logger.info(f"Navigating to detail page: {full_url}")
        page.goto(full_url, wait_until="domcontentloaded", timeout=45000)
        # Wait for description section to be present (React-rendered)
        try:
            page.wait_for_selector('[data-test="description-content__description"]', timeout=8000)
        except Exception:
            pass  # Continue anyway — other fields still available

        # 1. Address
        address = None
        addr_selectors = ['h1.p-h1', 'h1', '[data-test="address-display"]']
        for sel in addr_selectors:
            if page.locator(sel).first.is_visible():
                address = page.locator(sel).first.inner_text().strip()
                if address:
                    break

        if not address or 'results in' in address.lower() or 'real estate for sale' in address.lower():
            logger.warning(f"Invalid address found for {full_url}: {address}")
            return None

        data['address'] = address

        # 2. Price
        try:
            price_el = page.locator('[data-test="price-display"]').first
            if price_el.is_visible():
                data['price_display'] = price_el.inner_text().strip()
        except Exception:
            pass

        # 3. Listing date + listing number
        try:
            date_el = page.locator('[data-test="description__listed-date"]').first
            if date_el.is_visible():
                data['listing_date_raw'] = date_el.inner_text().strip()
                # Parse "Listed on 8 November 2025" → datetime
                import re as _re
                from datetime import datetime
                m = _re.search(r'(\d{1,2}\s+\w+\s+\d{4})', data['listing_date_raw'])
                if m:
                    try:
                        data['listing_date_parsed'] = datetime.strptime(m.group(1), "%d %B %Y").strftime("%Y-%m-%d")
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"Error finding listing date: {e}")

        try:
            num_el = page.locator('[data-test="description__listing-number"]').first
            if num_el.is_visible():
                raw = num_el.inner_text().strip()
                import re as _re
                m = _re.search(r'(\d+)', raw)
                if m:
                    data['listing_number'] = m.group(1)
        except Exception:
            pass

        # 4. Description
        try:
            desc_el = page.locator('[data-test="description-content__description"]').first
            if desc_el.is_visible():
                data['description'] = desc_el.inner_text().strip()
        except Exception:
            pass

        # 5. Agent / Office Name
        try:
            agent_el = page.locator('[data-test="agent-name"], .agent-name').first
            if agent_el.is_visible():
                data['agent_name'] = agent_el.inner_text().strip()

            office_el = page.locator('[data-test="office-name"]').first
            if office_el.is_visible():
                office_name = office_el.inner_text().strip()
                if data['agent_name']:
                    data['agent_name'] = f"{data['agent_name']} ({office_name})"
                else:
                    data['agent_name'] = office_name
        except Exception:
            pass

        # 5. Bedrooms, Bathrooms, Area, Property Type
        try:
            # Parse features-icons: each feature is a flex child div containing an svg+title and a span
            # HTML structure: div[data-test="features-icons"] > div.flex.items-center > svg > title + span
            features = page.evaluate("""
                () => {
                    const results = {};
                    const container = document.querySelector('div[data-test="features-icons"]');
                    if (!container) return results;
                    // Each feature item is a direct flex child
                    const items = container.querySelectorAll(':scope > div');
                    items.forEach(item => {
                        const titleEl = item.querySelector('svg title');
                        const span = item.querySelector('span');
                        if (!titleEl || !span) return;
                        const label = titleEl.textContent.trim();
                        const value = span.textContent.trim();
                        if (label === 'Bedroom')    results['bedrooms']      = value;
                        if (label === 'Bathroom')   results['bathrooms']     = value;
                        if (label === 'Floor area') results['floor_area']    = value;
                        if (label === 'Land area')  results['land_area']     = value;
                        if (label === 'Title type') results['title_type']    = value;
                        // Property type is the first icon (Apartment, House, etc.)
                        if (['Apartment','House','Townhouse','Unit','Section','Lifestyle','Rural',
                             'Commercial','Office','Retail','Industrial'].includes(label)) {
                            results['property_type'] = label;
                        }
                    });
                    return results;
                }
            """)
            
            if features.get('bedrooms') and not data.get('bedroom_count'):
                m = re.search(r'\d+', features['bedrooms'])
                if m: data['bedroom_count'] = int(m.group())

            if features.get('bathrooms') and not data.get('bathroom_count'):
                m = re.search(r'\d+', features['bathrooms'])
                if m: data['bathroom_count'] = int(m.group())

            if features.get('land_area'):
                val = features['land_area']
                m = re.search(r'([\d,.]+)', val)
                if m:
                    num = float(m.group(1).replace(',', ''))
                    data['land_area'] = int(num * 10000) if 'ha' in val.lower() else int(num)

            if features.get('floor_area'):
                val = features['floor_area']
                m = re.search(r'([\d,.]+)', val)
                if m: data['floor_area'] = int(float(m.group(1).replace(',', '')))

            if features.get('property_type'):
                data['property_type'] = features['property_type']

        except Exception as e:
            logger.warning(f"Error extracting features: {e}")


        # 7. Latitude and Longitude (JSON-LD)
        try:
            soup = BeautifulSoup(page.content(), 'html.parser')
            scripts = soup.find_all('script', type='application/ld+json')
            for script in scripts:
                try:
                    ld_data = json.loads(script.string)
                    # Check for Place or GeoCoordinates
                    if isinstance(ld_data, dict):
                        geo = ld_data.get('geo')
                        if geo and isinstance(geo, dict):
                            data['latitude'] = geo.get('latitude')
                            data['longitude'] = geo.get('longitude')
                            if data['latitude']: break
                        
                        # Sometimes it's a list of objects
                        if '@graph' in ld_data:
                            for item in ld_data['@graph']:
                                if item.get('geo'):
                                    data['latitude'] = item['geo'].get('latitude')
                                    data['longitude'] = item['geo'].get('longitude')
                                    break
                except:
                    continue
        except Exception as e:
            logger.warning(f"Error extracting geo coordinates: {e}")

        # 8. Cover Image and Gallery Images
        try:
            image_urls = page.evaluate("""
                () => {
                    const imgs = document.querySelectorAll('div[data-test="image"] > img');
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
                data['images'] = json.dumps(image_urls)
        except Exception as e:
            logger.warning(f"Error extracting images: {e}")

        return data

    except Exception as e:
        logger.error(f"Error scraping detail {full_url}: {e}")
        return None

# Function to fetch property links from the list page
def fetch_property_links(page, url, mode='buy'):
    """
    Fetch property detail links from the list page.
    """
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except Exception as e:
        logger.warning(f"Timeout or error loading list page {url}: {e}")
    
    try:
        simulate_user_behavior(page)
        
        # Determine URL pattern based on mode
        url_pattern = "/residential/sale/" if mode == 'buy' else "/residential/rent/"
        
        # Get all links
        selector = f'a[href*="{url_pattern}"]:not([href*="map"])'
        links = [el.get_attribute('href') for el in page.locator(selector).all()]
        
        # Filter and dedup - IMPORTANT: exclude links with '?' as they are usually pagination/search filters
        unique_links = list(set([
            l for l in links 
            if l and url_pattern in l and '?' not in l and re.search(r'/\d{6,}/', l)
        ]))
        
        logger.info(f"Found {len(unique_links)} property links on page.")
        return unique_links
        
    except Exception as e:
        logger.error(f"Error fetching links from {url}: {e}")
        return []

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
def get_last_processed_page(task_id):
    """
    Get the last processed page number from the progress table.
    """
    supabase = create_supabase_client()
    try:
        # Try to get the record with task_id
        response = supabase.table('scraping_progress').select('last_processed_id, status').eq('id', task_id).execute()
        if response.data and len(response.data) > 0:
            record = response.data[0]
            status = record.get('status', 'idle')
            last_processed_id = record.get('last_processed_id')
            
            if status == 'complete':
                logger.info(f"Task {task_id} was previously complete. master_scheduler already reset to idle. Resuming from page 0.")
                return 0
            
            # Return the page number if it's not None or empty
            if last_processed_id:
                page_num = int(last_processed_id)
                logger.info(f"Resuming task {task_id} from page: {page_num}")
                return page_num
            else:
                logger.info(f"Starting task {task_id} from the beginning (empty last_processed_id)")
                return 0
        
        logger.info(f"Starting task {task_id} from the beginning (no progress records found)")
        return 0
    except Exception as e:
        logger.error(f"Error getting last processed page for task {task_id}: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")
        return 0

# Function to update the last processed page in the progress table
def update_last_processed_page(last_page, task_id):
    """
    Update the last processed page number in the progress table.
    """
    supabase = create_supabase_client()
    try:
        # First, try to update the existing record
        response = supabase.table('scraping_progress').update({
            'last_processed_id': str(last_page),
            'batch_size': 1000,
            'updated_at': 'now()'
        }).eq('id', task_id).execute()
        
        # Check if the update was successful
        if response.data:
            logger.info(f"Updated last processed page for task {task_id} to: {last_page}")
        else:
            # If no record was updated, insert a new one
            data = {
                'id': task_id,
                'last_processed_id': str(last_page),
                'batch_size': 1000,
                'updated_at': 'now()'
            }
            response = supabase.table('scraping_progress').insert(data).execute()
            
            if response.data:
                logger.info(f"Inserted new record for task {task_id} with last processed page: {last_page}")
            else:
                logger.error(f"Failed to insert/update last processed page for task {task_id}: {last_page}")
    except Exception as e:
        logger.error(f"Error updating last processed page for task {task_id}: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")

# Function to check if another instance is already running
def is_already_running(task_id):
    """
    Check scraper status for specific task_id.
    """
    supabase = create_supabase_client()
    try:
        response = supabase.table('scraping_progress').select('updated_at, status').eq('id', task_id).execute()
        if response.data and len(response.data) > 0:
            status = response.data[0].get('status', 'idle')
            updated_at = response.data[0].get('updated_at', '')
            
            logger.info(f"Scraper task {task_id} status: {status} (updated: {updated_at})")
            
            if status == 'running':
                if updated_at:
                    from datetime import datetime, timezone
                    try:
                        # updated_at could be a datetime object from psycopg2 or a string
                        if isinstance(updated_at, str):
                            # Handle string format from DB if necessary
                            # PostgreSQL/CockroachDB often returns: 2026-03-01 04:18:53.360241+00:00
                            # But psycopg2 usually handles this conversion.
                            # If it's a string, we attempt to parse it or just treat it as stale if it fails.
                            try:
                                from dateutil.parser import parse
                                updated_dt = parse(updated_at)
                            except ImportError:
                                # Fallback if dateutil not available
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
                                logger.info(f"Task {task_id} has a stale lock (last updated {diff / 60:.1f}m ago). Proceeding.")
                                return False
                    except Exception as e:
                        logger.warning(f"Error checking lock staleness: {e}. Assuming stale.")
                        return False

                logger.info(f"Another scraper instance (task {task_id}) is running. Exiting immediately.")
                return True
            
            elif status == 'idle':
                logger.info(f"Scraper task {task_id} status is idle. Proceeding.")
                return False
            
            elif status == 'complete':
                logger.info(f"Scraper task {task_id} was complete but gh_lock_manager already reset it. Proceeding.")
                return False
            
            elif status == 'stop':
                logger.info(f"Scraper task {task_id} was manually stopped. Exiting.")
                return True
                
        return False
    except Exception as e:
        logger.error(f"Error checking scraper status for task {task_id}: {e}")
        return False

# Function to update the lock timestamp
def update_lock_timestamp(task_id):
    """
    Update the lock timestamp to indicate the process is running.
    """
    supabase = create_supabase_client()
    try:
        supabase.table('scraping_progress').update({
            'updated_at': 'now()',
            'status': 'running'
        }).eq('id', task_id).execute()
    except Exception as e:
        logger.error(f"Error updating lock timestamp for task {task_id}: {e}")

def mark_complete(task_id):
    """
    Mark the scraper task as complete.
    """
    supabase = create_supabase_client()
    try:
        supabase.table('scraping_progress').update({
            'status': 'complete',
            'updated_at': 'now()'
        }).eq('id', task_id).execute()
        logger.info(f"Task {task_id} marked as complete.")
    except Exception as e:
        logger.error(f"Error marking task {task_id} as complete: {e}")

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
        
        url = f"https://api.github.com/repos/{github_repo}/actions/workflows/real_estate_auckland.yml/dispatches"
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
    """
    try:
        print("Starting to simulate mouse scrolling...")
        last_height = page.evaluate("document.body.scrollHeight")
        while True:
            print(f"  - Current page height: {last_height}, continuing to scroll...")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(random.uniform(1, 2))  # Wait for page to load
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                print("  - Reached bottom of page")
                break
            last_height = new_height

            # Check if pagination navigation appeared
            if page.query_selector('nav[aria-label="Pagination"]') or page.query_selector('div[class*="pagination"]'):
                print("  - Detected pagination navigation, stopping scroll")
                break
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
        print("Simulating additional scrolling operations")
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

def fetch_addresses(page, url):
    """
    Fetch addresses from the given URL.
    """
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except TimeoutError as e:
        logger.warning(f"Timeout while loading {url}. Continuing with partial page load. Error: {e}")
    except Exception as e:
        logger.error(f"Error navigating to {url}: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")
        return []

    try:
        page.wait_for_selector('button:has-text("Accept")', timeout=5000)
        page.click('button:has-text("Accept")')
        print("Clicked cookie consent button.")
    except Exception as e:
        logger.info("No cookie consent button found or unable to click it.")
        pass

    # Simulate user behavior
    simulate_user_behavior(page)

    addresses = []
    try:
        selectors = [
            'h3[data-test="standard-tile__search-result__address"]',
            '.standard-tile__search-result__address',
            'h3[class*="address"]',
            'div[class*="address"]',
            'div[class*="listing-tile"] h3',
            'div[class*="listing-tile"] div[class*="address"]'
        ]
        
        for selector in selectors:
            try:
                address_elements = page.query_selector_all(selector)
                if address_elements:
                    addresses = [element.inner_text().strip() for element in address_elements if element.inner_text().strip()]
                    if addresses:
                        print(f"Found {len(addresses)} addresses using selector: {selector}")
                        break
            except Exception as e:
                logger.warning(f"Error using selector {selector}: {e}")
                continue
        
        if not addresses:
            logger.warning(f"No address elements found on {url} using any of the selectors.")
            print("Page Title:", page.title())
            print("Current URL:", page.url)
            # Only log first 1000 characters of content to avoid huge logs
            print("HTML content:", page.content()[:1000])
    except Exception as e:
        logger.error(f"An error occurred while scraping {url}: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")

    return addresses

def check_real_estate_in_supabase(address: str) -> bool:
    """
    Check if a real estate property already exists in the Supabase database.
    """
    try:
        supabase = create_supabase_client()
        response = supabase.table('real_estate').select('id').eq('address', address).limit(1).execute()
        
        if response.data and len(response.data) > 0:
            logger.info(f"Property already exists in database: {address}")
            return True
        return False
    except Exception as e:
        logger.error(f"Error checking property in database: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")
        # If there's an error checking, we assume it doesn't exist to avoid missing data
        return False

def scrape_properties(task_config, max_pages, max_runtime_hours=5.5):
    """
    Scrape properties for a specific task configuration.
    task_config: {
        'id': int, 
        'region': str, 
        'mode': str, 
        'url_suffix': str
    }
    """
    task_id = task_config['id']
    region = task_config['region']
    mode = task_config['mode']
    url_suffix = task_config['url_suffix']
    
    base_url = os.getenv("REALESTATE_URL")
    if not base_url:
        base_url = "https://www.realestate.co.nz"
    
    main_url = f"{base_url}{url_suffix}"
    
    # Create progress table if it doesn't exist
    create_scraping_progress_table()
    
    # Check if this specific task is already running
    # Removed: is_already_running(task_id) check because it conflicts with gh_lock_manager.py 
    # which sets status to 'running' right before this script starts.

    # Update lock
    update_lock_timestamp(task_id)

    # Get the last processed page
    start_page = get_last_processed_page(task_id)
    
    # Calculate maximum runtime
    start_time = time.time()
    max_runtime_seconds = max_runtime_hours * 3600
    
    logger.info(f"Starting scraping for {region} - {mode} (Task ID: {task_id}). Max runtime: {max_runtime_hours}h")
    
    has_data_to_process = False
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
            )
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            )
            page = context.new_page()
            page.on("dialog", handle_dialog)

            page_num = start_page
            
            if start_page >= max_pages:
                logger.info(f"Task {task_id} already processed {start_page} pages (max: {max_pages}). Marking complete.")
                mark_complete(task_id)
                return

            for page_num in range(start_page + 1, max_pages + 1):
                # Check runtime
                if time.time() - start_time > max_runtime_seconds:
                    logger.info(f"Max runtime reached for task {task_id}. Stopping.")
                    update_last_processed_page(page_num - 1, task_id)
                    # Reset status to idle so it can pick up next time
                    try:
                        supabase = create_supabase_client()
                        supabase.table('scraping_progress').update({
                            'status': 'idle',
                            'updated_at': 'now()'
                        }).eq('id', task_id).execute()
                    except:
                        pass
                    return

                # Update lock to show we are still alive
                update_lock_timestamp(task_id)
                
                try:
                    url = f"{main_url}?page={page_num}"
                    print(f"\n[{region.upper()} {mode.upper()}] Scraping page {page_num}: {url}")
                    
                    links = fetch_property_links(page, url, mode=mode)
                    
                    if links:
                        has_data_to_process = True
                        print(f"Found {len(links)} links on page {page_num}")
                        
                        for link in links:
                            detail_data = scrape_property_detail(page, link, region=region, mode=mode)
                            
                            if detail_data and detail_data.get('address'):
                                if mode == 'buy':
                                    upsert_real_estate_detail(detail_data)
                                else:
                                    upsert_real_estate_rent_detail(detail_data)
                                    
                                print(f"✅ Saved: {detail_data.get('address')} | {detail_data.get('price_display')}")
                            else:
                                print(f"⚠️ Failed to scrape: {link}")
                                
                    else:
                        print(f"No links found on page {page_num}. Continuing.")
                    
                    update_last_processed_page(page_num, task_id)
                    
                    if page_num < max_pages:
                        delay = random.uniform(3, 7)
                        time.sleep(delay)
                        
                except Exception as e:
                    logger.error(f"Error processing page {page_num}: {e}")
                    update_last_processed_page(page_num, task_id)
                    continue

            # If finished loop
            if page_num >= max_pages:
                mark_complete(task_id)
                
    except Exception as e:
        logger.error(f"Error in scraping process for task {task_id}: {e}")
        logger.error(traceback.format_exc())
        # Clear lock on error
        try:
             supabase = create_supabase_client()
             supabase.table('scraping_progress').update({
                'status': 'idle',
                'updated_at': 'now()'
             }).eq('id', task_id).execute()
        except:
             pass
        raise

def handle_dialog(dialog):
    try:
        dialog.accept()
    except:
        pass

def simulate_user_behavior(page):
    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        time.sleep(1)
        page.evaluate("window.scrollTo(0, 0)")
    except:
        pass

import argparse

def main():
    try:
        logger.info("Universal Real Estate Scraper Started")
        
        # Configuration Tasks
        TASKS = [
            {'id': 2, 'region': 'auckland', 'mode': 'buy', 'url_suffix': '/residential/sale/auckland'},
            {'id': 3, 'region': 'wellington', 'mode': 'buy', 'url_suffix': '/residential/sale/wellington'},
            {'id': 4, 'region': 'auckland', 'mode': 'rent', 'url_suffix': '/residential/rental/auckland'},
            {'id': 5, 'region': 'wellington', 'mode': 'rent', 'url_suffix': '/residential/rental/wellington'},
            {'id': 6, 'region': 'auckland_barfoot', 'mode': 'buy', 'url_suffix': '/residential/sale/auckland?by=best-match&k=Barfoot%20%26%20Thompson'},
        ]
        
        # Parse arguments
        parser = argparse.ArgumentParser(description='Real Estate Scraper')
        parser.add_argument('--task_id', type=int, help='Specific Task ID to run (2, 3, 4, 5)')
        parser.add_argument('--region', type=str, help='Run all tasks for a specific region (auckland, wellington)')
        parser.add_argument('--mode', type=str, help='Run all tasks for a specific mode (buy, rent)')
        args = parser.parse_args()
        
        # Filter tasks based on arguments
        tasks_to_run = []
        if args.task_id:
            tasks_to_run = [t for t in TASKS if t['id'] == args.task_id]
        elif args.region:
            tasks_to_run = [t for t in TASKS if t['region'] == args.region.lower()]
        elif args.mode:
            tasks_to_run = [t for t in TASKS if t['mode'] == args.mode.lower()]
        else:
            tasks_to_run = TASKS # Run all if no filter
            
        if not tasks_to_run:
            logger.warning("No matching tasks found for the provided arguments.")
            return

        # Get Max Pages from Env or Default
        max_pages = 500
        
        for task in tasks_to_run:
            try:
                logger.info(f"Processing Task: {task['region']} - {task['mode']} (ID: {task['id']})")
                scrape_properties(task, max_pages, max_runtime_hours=5.5)
                
            except Exception as e:
                logger.error(f"Task {task['id']} failed: {e}")
                continue
                
        logger.info("Tasks execution cycle completed.")
        
    except Exception as e:
        logger.error(f"Critical error in main: {e}")
        exit(1)

if __name__ == "__main__":
    main()