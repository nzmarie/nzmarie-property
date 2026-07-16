import re

# NZ street type words (full forms after normalization)
STREET_TYPES = {
    'road', 'street', 'avenue', 'drive', 'lane', 'court', 'place',
    'terrace', 'crescent', 'close', 'grove', 'parade', 'square',
    'highway', 'point', 'mount', 'way', 'rise', 'view', 'track',
    'boulevard', 'esplanade', 'quay', 'strand',
}


def get_canonical_address(address):
    """
    Normalization algorithm for NZ addresses: 
    Removes postcodes, standardizes suffixes, align units, and cleans noise.
    """
    if not address:
        return None
        
    lower_addr = address.lower()
    
    # Check for invalid addresses
    if any(k in lower_addr for k in ["withheld", "hidden", "unknown", "address upon request"]):
        return None
    
    # 1. Basic cleaning: replace commas with spaces and strip
    addr = lower_addr.replace(",", " ").strip()
    
    # 2. Remove trailing 4-digit postcode (e.g., "Auckland 1010" -> "Auckland")
    addr = re.sub(r'\s\d{4}$', '', addr)
    
    # 3. Suffix Full-Name Mapping
    # We use a dictionary for common NZ street suffixes
    replacements = {
        r'\brd\b': 'road',
        r'\bst\b': 'street',
        r'\bave\b': 'avenue',
        r'\bhwy\b': 'highway',
        r'\bpl\b': 'place',
        r'\bdr\b': 'drive',
        r'\bct\b': 'court',
        r'\bter\b': 'terrace',
        r'\bln\b': 'lane',
        r'\bcres\b': 'crescent',
        r'\bmt\b': 'mount',
        r'\bpt\b': 'point',
        r'\bcl\b': 'close',
        r'\bgr\b': 'grove',
        r'\bpde\b': 'parade',
        r'\bsq\b': 'square',
        r'\btce\b': 'terrace'
    }
    for pattern, replacement in replacements.items():
        addr = re.sub(pattern, replacement, addr)
        
    # 4. Standardize Unit/Flat numbering (e.g., "Unit 1 35 Street" -> "1/35 Street")
    # Handle "Unit X, Y Street" or "Flat X, Y Street" or "1 of 23 Street"
    addr = re.sub(r'\b(?:unit|flat|u|f)\s*([a-z0-9]+)\s*(?:of|/|,)?\s*', r'\1/', addr)
    addr = re.sub(r'\s*/\s*', '/', addr) # Clean up spaces around slashes
    
    # 5. Remove city noise (Auckland/Wellington) if it's at the end or preceded by space
    # Often scrapers add " Auckland" at the end.
    addr = re.sub(r'\b(auckland|wellington|christchurch|hamilton|tauranga)\b', '', addr)
    
    # 6. Final cleanup: Keep only alphanumeric and slashes
    addr = re.sub(r'[^a-z0-9/ ]', ' ', addr)
    
    # 7. Normalize whitespace
    return " ".join(addr.split())


def get_street_fingerprint(address):
    """Extract street-level fingerprint: only unit/number + street name, no suburb/city.

    Examples:
        '2/11 Aeroview Drive Beach Haven Auckland 0626' -> '2/11 aeroview drive'
        '45 Victoria St, Auckland 1010'                  -> '45 victoria street'
        'Unit 5, 10 Main Road, Takapuna 0622'           -> '5/10 main road'
    """
    base = get_canonical_address(address)
    if not base:
        return None

    parts = base.split()
    result = []
    for p in parts:
        result.append(p)
        # Stop after the first street-type word (need at least 2 parts for number+street)
        if p in STREET_TYPES and len(result) >= 2:
            break

    return ' '.join(result) if result else base


def get_fingerprint_variants(address):
    """Return a list of fingerprint variants for cross-matching.

    Handles unit number ambiguity:
      '2/11 aeroview drive' -> ['2/11 aeroview drive', '11 aeroview drive', '2 aeroview drive']
    """
    street_fp = get_street_fingerprint(address)
    if not street_fp:
        return []

    variants = [street_fp]

    # If address contains '/', produce variants without unit and with only unit
    if '/' in street_fp:
        parts = street_fp.split('/', 1)
        unit_part = parts[0].strip()
        rest = parts[1].strip()
        # Variant: without unit number (main building)
        if rest:
            variants.append(rest)
        # Variant: unit number as prefix (e.g., '2 aeroview drive')
        if unit_part and rest:
            # Only if unit_part looks like a number
            if re.match(r'^\d+[a-z]?$', unit_part):
                variants.append(f"{unit_part} {rest}")

    return variants


def normalize_for_fuzzy(address):
    """Normalize address for fuzzy matching: street-level only, no suburb/postcode."""
    fp = get_street_fingerprint(address)
    if not fp:
        return ''
    # Remove slashes for fuzzy comparison
    return fp.replace('/', ' ')


def parse_nz_address(raw_address):
    """Parse a full NZ address string into components.

    Handles formats like:
      "3 Pearl Grove, Ashhurst, Palmerston North City"
      "2/11 Aeroview Drive, Beach Haven, Auckland"
      "45 Victoria St, Auckland 1010"

    Returns:
        dict with keys: street_address (str), suburb (str|None), city (str|None)
    """
    if not raw_address:
        return {"street_address": None, "suburb": None, "city": None}

    parts = [p.strip() for p in raw_address.split(",")]

    if len(parts) >= 3:
        street_address = parts[0]
        suburb = parts[-2]
        city = parts[-1]
    elif len(parts) == 2:
        street_address = parts[0]
        suburb = None
        city = parts[1]
    else:
        street_address = parts[0]
        suburb = None
        city = None

    return {
        "street_address": street_address,
        "suburb": suburb,
        "city": city,
    }
import re


def generate_address_fingerprint(address, suburb=None):
    """
    Generate a deterministic address fingerprint for the `properties` table.

    Rule (per data-pipeline spec):
      1. Concatenate address (street) + "|" + suburb
      2. Lowercase
      3. Strip all characters except [a-z0-9|]
         (spaces, commas, slashes, dots, etc. are all removed)

    Example:
      "145 Albany Highway" + "Albany"  ->  "145albanyhighway|albany"

    The fingerprint is NEVER None — callers must supply a valid address.
    If address is missing/empty, this returns None so the caller can
    refuse to insert (NULL fingerprint is a hard bug per spec).
    """
    if not address:
        return None
    if suburb:
        raw = f"{address}|{suburb}"
    else:
        raw = str(address)
    raw = raw.lower()
    # Keep only letters, digits, and the pipe separator
    fingerprint = re.sub(r'[^a-z0-9|]', '', raw)
    return fingerprint or None


def get_canonical_address(address):
    """
    Normalization algorithm for NZ addresses: 
    Removes postcodes, standardizes suffixes, align units, and cleans noise.
    """
    if not address:
        return None
        
    lower_addr = address.lower()
    
    # Check for invalid addresses
    if any(k in lower_addr for k in ["withheld", "hidden", "unknown", "address upon request"]):
        return None
    
    # 1. Basic cleaning: replace commas with spaces and strip
    addr = lower_addr.replace(",", " ").strip()
    
    # 2. Remove trailing 4-digit postcode (e.g., "Auckland 1010" -> "Auckland")
    addr = re.sub(r'\s\d{4}$', '', addr)
    
    # 3. Suffix Full-Name Mapping
    # We use a dictionary for common NZ street suffixes
    replacements = {
        r'\brd\b': 'road',
        r'\bst\b': 'street',
        r'\bave\b': 'avenue',
        r'\bhwy\b': 'highway',
        r'\bpl\b': 'place',
        r'\bdr\b': 'drive',
        r'\bct\b': 'court',
        r'\bter\b': 'terrace',
        r'\bln\b': 'lane',
        r'\bcres\b': 'crescent',
        r'\bmt\b': 'mount',
        r'\bpt\b': 'point',
        r'\bcl\b': 'close',
        r'\bgr\b': 'grove',
        r'\bpde\b': 'parade',
        r'\bsq\b': 'square',
        r'\btce\b': 'terrace'
    }
    for pattern, replacement in replacements.items():
        addr = re.sub(pattern, replacement, addr)
        
    # 4. Standardize Unit/Flat numbering (e.g., "Unit 1 35 Street" -> "1/35 Street")
    # Handle "Unit X, Y Street" or "Flat X, Y Street" or "1 of 23 Street"
    addr = re.sub(r'\b(?:unit|flat|u|f)\s*([a-z0-9]+)\s*(?:of|/|,)?\s*', r'\1/', addr)
    addr = re.sub(r'\s*/\s*', '/', addr) # Clean up spaces around slashes
    
    # 5. Remove city noise (Auckland/Wellington) if it's at the end or preceded by space
    # Often scrapers add " Auckland" at the end.
    addr = re.sub(r'\b(auckland|wellington|christchurch|hamilton|tauranga)\b', '', addr)
    
    # 6. Final cleanup: Keep only alphanumeric and slashes
    addr = re.sub(r'[^a-z0-9/ ]', ' ', addr)
    
    # 7. Normalize whitespace
    return " ".join(addr.split())
