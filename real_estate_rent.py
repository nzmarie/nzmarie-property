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

from config.supabase_config import insert_real_estate_rent, create_supabase_client

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
    """
    try:
        print("Starting simulated mouse scroll operation...")
        last_height = page.evaluate("document.body.scrollHeight")
        while True:
            print(f"  - Current page height: {last_height}, continuing to scroll down...")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(random.uniform(1, 2))  # Wait for page to load
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                print("  - Reached bottom of page")
                break
            last_height = new_height

            # Check if pagination navigation appeared
            if page.query_selector('nav[aria-label="Pagination"]') or page.query_selector('div[class*="pagination"]'):
                print("  - Pagination navigation detected, stopping scroll")
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

def fetch_addresses(page, url):
    """
    Fetch addresses and coordinates from the given URL using the Shoebox JSON.
    """
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except TimeoutError as e:
        logger.warning(f"Timeout while loading {url}. Continuing with partial page load. Error: {e}")
    except Exception as e:
        logger.error(f"Error navigating to {url}: {e}")
        return []

    try:
        # 1. Try to extract from Shoebox JSON (Most robust)
        content = page.content()
        shoebox_match = re.search(r'<script type="fastboot/shoebox" id="shoebox-ember-data-storefront">([\s\S]*?)</script>', content)
        if shoebox_match:
            try:
                raw_data = json.loads(shoebox_match.group(1))
                listings = []
                queries = raw_data.get('queries', {})
                for q_key, q_val in queries.items():
                    if isinstance(q_val, str):
                        try:
                            data = json.loads(q_val)
                            if 'data' in data and isinstance(data['data'], list):
                                for item in data['data']:
                                    if item.get('type') == 'listing':
                                        attrs = item.get('attributes', {})
                                        addr_obj = attrs.get('address', {})
                                        if addr_obj:
                                            addr_str = addr_obj.get('display-address') or addr_obj.get('full-address')
                                            if addr_str and isinstance(addr_str, str):
                                                listings.append({
                                                    'address': addr_str,
                                                    'latitude': addr_obj.get('latitude'),
                                                    'longitude': addr_obj.get('longitude')
                                                })
                        except: continue
                if listings:
                    print(f"Found {len(listings)} listings via Shoebox JSON")
                    return listings
            except Exception as e:
                logger.warning(f"Error parsing Shoebox JSON: {e}")

        # 2. Fallback to HTML selectors (Existing logic)
        addresses = []
        selectors = [
            'h3[data-test="standard-tile__search-result__address"]',
            '.standard-tile__search-result__address',
            'h3[class*="address"]',
            'div[class*="address"]',
            'div[class*="listing-tile"] h3'
        ]
        
        for selector in selectors:
            address_elements = page.query_selector_all(selector)
            if address_elements:
                raw_addresses = [el.inner_text().strip() for el in address_elements if el.inner_text().strip()]
                addresses = [{
                    'address': addr, 'latitude': None, 'longitude': None
                } for addr in raw_addresses if 'results in' not in addr.lower()]
                if addresses:
                    print(f"Found {len(addresses)} addresses via HTML selector")
                    break
        return addresses
    except Exception as e:
        logger.error(f"An error occurred while scraping {url}: {e}")
        return []

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

def scrape_properties(main_url, max_pages, max_runtime_hours=5.2):
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

            for page_num in range(start_page + 1, max_pages + 1):
                # Check if we've exceeded the maximum runtime
                elapsed_time = time.time() - start_time
                if elapsed_time > max_runtime_seconds:
                    logger.info(f"Maximum runtime of {max_runtime_hours} hours reached. Stopping...")
                    # Save progress before exiting
                    update_last_processed_page(page_num - 1)
                    # Update status to 'idle' for normal timeout, allowing next action to continue
                    supabase = create_supabase_client()
                    try:
                        supabase.table('scraping_progress').update({
                            'status': 'idle',
                            'updated_at': 'now()'
                        }).eq('id', 4).execute()
                        logger.info("Rent scraper status updated to 'idle' due to 5.5 hour timeout.")
                    except Exception as e:
                        logger.error(f"Error updating status to 'idle': {e}")
                    break
                
                # Update lock timestamp periodically to indicate we're still running
                update_lock_timestamp()
                
                try:
                    url = f"{main_url}?page={page_num}"
                    print(f"\nScraping page {page_num}: {url}")
                    
                    addresses = fetch_addresses(page, url)
                    if addresses:
                        # If we have data, set the flag
                        has_data_to_process = True
                        all_addresses.extend(addresses)
                        print(f"Found {len(addresses)} addresses on page {page_num}")
                        for item in addresses:
                            addr = item['address']
                            lat = item['latitude']
                            lng = item['longitude']
                            print(f"  - {addr} ({lat}, {lng})")
                            try:
                                # Use Supabase to check for duplicates
                                if not check_real_estate_rent_in_supabase(addr):
                                    # Insert into Supabase
                                    insert_real_estate_rent(addr, "To Rent", latitude=lat, longitude=lng)
                                    print(f"Added new rental property to database: {addr}")
                                else:
                                    print(f"Rental property {addr} already exists. Skipping...")
                            except Exception as e:
                                logger.error(f"Error processing address {addr}: {e}")
                                continue
                    else:
                        print(f"No addresses found on page {page_num}. Continuing to next page.")
                    
                    # Update progress after successfully processing a page
                    update_last_processed_page(page_num)
                    
                    if page_num < max_pages:
                        delay = random.uniform(5, 10)
                        print(f"Waiting for {delay:.2f} seconds before next request...")
                        time.sleep(delay)
                
                except Exception as e:
                    logger.error(f"Error processing page {page_num}: {e}")
                    logger.error(f"Error details: {traceback.format_exc()}")
                    # Save progress and continue with next page instead of stopping
                    update_last_processed_page(page_num)
                    continue

            # If we've processed all pages but still have time, continue running
            # But only if we have processed data
            while has_data_to_process and (time.time() - start_time) < max_runtime_seconds:
                logger.info("Processed all available pages. Waiting before next cycle.")
                time.sleep(60)  # Wait for 1 minute before checking again
                update_lock_timestamp()  # Update lock timestamp to indicate we're still running

        # Mark as complete if we finished processing all available data
        # regardless of time elapsed (unless we hit timeout during processing)
        if has_data_to_process:
            try:
                supabase = create_supabase_client()
                supabase.table('scraping_progress').update({
                    'status': 'complete',
                    'updated_at': 'now()'
                }).eq('id', 4).execute()
                logger.info("Rent scraper task marked as complete.")
            except Exception as e:
                logger.error(f"Error marking rent scraper task as complete: {e}")
        else:
            logger.info("No data processed, keeping current status")
            
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
    """
    Main function to start the scraping process.
    """
    try:
        logger.info("Rent Real Estate Scraper")
        logger.info("========================")
        

        
        base_url = os.getenv("REALESTATE_URL") or "https://www.realestate.co.nz"
        # Ensure base URL is just the domain
        base_url = base_url.replace('/residential/sale', '').replace('/residential/rental', '').rstrip('/')
        
        main_url = f"{base_url}/residential/rental"
        
        # GitHub Actions already handles status management
        # Removed: is_already_running() check

        max_pages = 412
        scrape_properties(main_url, max_pages)
        mark_complete()
        logger.info("Scraping process completed successfully")
    except Exception as e:
        logger.error(f"Error in main function: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")
        # Clear the lock on error in main execution
        clear_lock()
        raise

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Unexpected error in script execution: {e}")
        logger.error(f"Error details: {traceback.format_exc()}")
        # Clear the lock on error in main execution
        clear_lock()
        exit(1)
