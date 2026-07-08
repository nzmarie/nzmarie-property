from bs4 import BeautifulSoup
import logging
import re

logger = logging.getLogger(__name__)

class PropertyValueParser:
    @staticmethod
    def parse_ta_links(html, region):
        """Parse Territorial Authority links from the region page."""
        soup = BeautifulSoup(html, 'html.parser')
        links = [a.get('href', '') for a in soup.select(f'a[href*="/{region}/"]')]
        ta_links = list(set([
            l for l in links
            if l.split('/')[-1].isdigit()
            and len(l.strip('/').split('/')) == 3
        ]))
        return ta_links

    @staticmethod
    def parse_suburb_links(html, region):
        """Parse suburb links from a TA page."""
        soup = BeautifulSoup(html, 'html.parser')
        links = [a.get('href', '') for a in soup.select(f'a[href*="/{region}/"]')]
        suburb_links = list(set([
            l for l in links
            if l.split('/')[-1].isdigit()
            and len(l.strip('/').split('/')) == 4
        ]))
        return suburb_links

    @staticmethod
    def parse_property_links(html, region):
        """Parse property detail links from a suburb list page."""
        soup = BeautifulSoup(html, 'html.parser')
        all_links = [a.get('href', '') for a in soup.select(f'a[href*="/{region}/"]')]
        property_links = list(set([
            l for l in all_links 
            if l and "?page=" not in l.lower() 
            and not l.split('/')[-1].split('?')[0].isdigit() 
            and len(l.strip('/').split('/')) >= 4
        ]))
        return property_links

    @staticmethod
    def parse_next_page(html):
        """Find the 'Next' button link."""
        soup = BeautifulSoup(html, 'html.parser')
        def is_real_next(tag):
            if tag.name != 'a': return False
            href = tag.get('href', '')
            if not href or href == '#': return False
            classes = " ".join(tag.get('class', []))
            if 'carousel' in classes or 'carousel' in tag.get('data-slide', ''): return False
            text = tag.get_text(strip=True)
            return '>' in text or 'Next' in text or tag.get('rel') == ['next']

        next_link = (
            soup.select_one('.pagination a[rel="next"]') or
            soup.select_one('.pager a[rel="next"]') or
            soup.find(is_real_next)
        )
        return next_link.get('href') if next_link else None

    @staticmethod
    def parse_detail_data(html):
        """Extract structured property data from rendered HTML using testid attributes.
        
        propertyvalue.co.nz is a React SPA (not Next.js SSR), so __NEXT_DATA__ does NOT exist.
        All data must be extracted from the rendered DOM using testid selectors.
        """
        soup = BeautifulSoup(html, 'html.parser')
        data = {
            "bedrooms": None, "bathrooms": None, "car_spaces": None,
            "floor_area": None, "land_area": None, "year_built": None,
            "property_type": None, "capital_value": None, "land_value": None,
            "improvement_value": None,
            "estimated_value_low": None, "estimated_value_high": None,
            "last_sold_price": None, "last_sold_date": None,
            "suburb_median_price": None, "suburb_median_rent": None,
            "suburb_days_on_market": None,
            "latitude": None, "longitude": None,
            "images": [], "history": [], "description": None
        }

        # 1. Core property attributes (bed/bath/car/land/floor) via testid
        data["bedrooms"] = PropertyValueParser._extract_int_by_testid(soup, 'bed')
        data["bathrooms"] = PropertyValueParser._extract_int_by_testid(soup, 'bath')
        data["car_spaces"] = PropertyValueParser._extract_int_by_testid(soup, 'car')
        data["year_built"] = PropertyValueParser._extract_int_by_testid(soup, 'yearBuiltValue')

        # Land area and floor area (contain nested <span> with <sup>2</sup>)
        data["land_area"] = PropertyValueParser._extract_area_by_class(soup, 'land')
        data["floor_area"] = PropertyValueParser._extract_area_by_class(soup, 'floor')

        # 2. Property Type (no testid, use label-value pair structure)
        data["property_type"] = PropertyValueParser._extract_property_type(soup)

        # 3. Rating Valuation values (Capital Value, Land Value, Improvement Value)
        rv = PropertyValueParser._extract_rating_valuation(soup)
        data["capital_value"] = rv.get('capital_value')
        data["land_value"] = rv.get('land_value')
        data["improvement_value"] = rv.get('improvement_value')

        # 4. Description from story-content section
        data["description"] = PropertyValueParser.extract_story_content(soup)

        # 5. Images
        data["images"] = PropertyValueParser.extract_images(soup)

        # 6. Property History (using testid patterns)
        data["history"] = PropertyValueParser.extract_history(soup)

        # 7. Estimated value range
        ev = PropertyValueParser.extract_estimated_value(soup)
        data["estimated_value_low"] = ev.get('low')
        data["estimated_value_high"] = ev.get('high')

        # 8. Last sold info (from Quick Facts section)
        ls = PropertyValueParser.extract_last_sold(soup)
        data["last_sold_price"] = ls.get('price')
        data["last_sold_date"] = ls.get('date')

        # 9. Suburb insights
        si = PropertyValueParser.extract_suburb_insights(soup)
        data["suburb_median_price"] = si.get('median_price')
        data["suburb_median_rent"] = si.get('median_rent')
        data["suburb_days_on_market"] = si.get('days_on_market')

        # 10. GPS coordinates from embedded map
        coords = PropertyValueParser.extract_coordinates(soup)
        data["latitude"] = coords.get('latitude')
        data["longitude"] = coords.get('longitude')

        return data

    @staticmethod
    def _extract_int_by_testid(soup, testid_value):
        """Extract integer value from element with given testid attribute."""
        el = soup.find(attrs={'testid': testid_value})
        if el:
            text = el.get_text(strip=True)
            match = re.search(r'(\d+)', text)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _extract_area_by_class(soup, class_name):
        """Extract area in m² from element with given class (land or floor).
        Handles nested <span>153 m<sup>2</sup></span> structure."""
        el = soup.find('span', class_=class_name)
        if el:
            text = el.get_text(strip=True)
            return PropertyValueParser._clean_area(text)
        return None

    @staticmethod
    def _extract_property_type(soup):
        """Extract Property Type from label-value pair structure.
        HTML: <div class='...propertyType...'><div>Property Type</div><div>Residential</div></div>"""
        type_zone = soup.find('div', class_=re.compile(r'PropertyAttributes_typeZone'))
        if type_zone:
            pairs = type_zone.find_all('div', class_=re.compile(r'propertyType'))
            for pair in pairs:
                divs = pair.find_all('div', recursive=False)
                if len(divs) >= 2:
                    label = divs[0].get_text(strip=True).lower()
                    if 'property type' in label:
                        return divs[1].get_text(strip=True)
        return None

    @staticmethod
    def _extract_rating_valuation(soup):
        """Extract Capital Value, Land Value, Improvement Value from Rating Valuation section.
        Uses CSS class selectors: .capitalValueValue, .landValueValue, .improvementValueValue."""
        result = {}
        value_map = {
            'capital_value': 'capitalValueValue',
            'land_value': 'landValueValue',
            'improvement_value': 'improvementValueValue',
        }
        for key, css_class in value_map.items():
            el = soup.find('div', class_=css_class)
            if el:
                text = el.get_text(strip=True)
                # Parse "$1,050,000" -> 1050000
                cleaned = text.replace('$', '').replace(',', '').strip()
                try:
                    result[key] = float(cleaned)
                except ValueError:
                    result[key] = None
            else:
                result[key] = None
        return result

    @staticmethod
    def _clean_area(area_val):
        """Clean area string (e.g., '200 m²', '1 ha') and return float in m²."""
        if not area_val: return None
        if isinstance(area_val, (int, float)): return float(area_val)
        
        try:
            s = str(area_val).lower().replace(',', '')
            num = float(re.search(r"(\d+\.?\d*)", s).group(1))
            if 'ha' in s:
                return num * 10000.0
            return num
        except Exception:
            return None

    @staticmethod
    def extract_story_content(soup):
        """Extract property description from testid='story-content' element (About section)."""
        story_el = soup.find(attrs={'testid': 'story-content'})
        if story_el:
            text = story_el.get_text(separator=' ', strip=True)
            # Clean up excessive whitespace
            text = re.sub(r'\s+', ' ', text).strip()
            if text:
                return text
        # Fallback: try to find "About" section heading and grab the paragraph after it
        about_heading = soup.find(string=re.compile(r'About\s+', re.IGNORECASE))
        if about_heading and about_heading.parent:
            next_sib = about_heading.parent.find_next_sibling()
            if next_sib and next_sib.name in ('p', 'div', 'span'):
                text = next_sib.get_text(separator=' ', strip=True)
                text = re.sub(r'\s+', ' ', text).strip()
                if text:
                    return text
        return None

    @staticmethod
    def extract_images(soup):
        """Extract property images from street view and gallery."""
        images = []
        # Street view image (always present on property pages)
        street_view = soup.find('img', src=re.compile(r'maps\.googleapis\.com'))
        if street_view:
            src = street_view.get('src')
            if src:
                images.append(src)
        # Carousel/gallery images
        items = soup.select('div.carousel-inner div.carousel-item img')
        for img in items:
            src = img.get('src') or img.get('data-src')
            if src and src not in images:
                images.append(src)
        return images

    @staticmethod
    def extract_history(soup):
        """Extract property history events using testid patterns.
        
        HTML structure per event:
          <div testid="pt-year-{idx}">2025</div>
          <strong testid="pt-description-{idx}">Property Built</strong>
          <div testid="pt-interval-{idx}">5 years ago</div>
        """
        property_history = []
        # Find all year elements (indexed 0, 1, 2, ...)
        year_els = soup.find_all(attrs={'testid': re.compile(r'^pt-year-\d+$')})
        for year_el in year_els:
            testid = year_el.get('testid', '')
            # Extract index from testid (e.g., 'pt-year-0' -> 0)
            match = re.search(r'pt-year-(\d+)', testid)
            if not match:
                continue
            idx = match.group(1)
            
            event_date = year_el.get_text(strip=True)
            
            desc_el = soup.find(attrs={'testid': f'pt-description-{idx}'})
            event_description = desc_el.get_text(strip=True) if desc_el else "Unknown"
            
            interval_el = soup.find(attrs={'testid': f'pt-interval-{idx}'})
            event_interval = interval_el.get_text(strip=True) if interval_el else ""

            property_history.append({
                'event_date': event_date,
                'event_description': event_description,
                'event_interval': event_interval
            })
        return property_history

    # -----------------------------------------------------------------------
    # Enhanced detail page parsers
    # -----------------------------------------------------------------------

    @staticmethod
    def extract_estimated_value(soup):
        """Extract estimated value range from the valuation section.

        Example page text: '$900,000 – $1,000,000'
        Returns dict with 'low' and 'high' as floats.
        """
        result = {'low': None, 'high': None}
        # Look for the value range container (CSS class pattern from PropertyValue SPA)
        value_el = soup.find('div', class_=re.compile(r'estimatedValue|valueRange|EstimatedValue'))
        if not value_el:
            # Fallback: search text pattern like "$900,000 – $1,000,000"
            text_block = soup.find(string=re.compile(r'\$[\d,]+\s*\u2013\s*\$[\d,]+'))
            if text_block:
                value_el = text_block
        if value_el:
            text = value_el.get_text(strip=True) if hasattr(value_el, 'get_text') else str(value_el)
            amounts = re.findall(r'\$([\d,]+)', text)
            if len(amounts) >= 2:
                try:
                    result['low'] = float(amounts[0].replace(',', ''))
                    result['high'] = float(amounts[1].replace(',', ''))
                except ValueError:
                    pass
        return result

    @staticmethod
    def extract_last_sold(soup):
        """Extract last sold price and date from Quick Facts / property attributes.

        Example page text: 'Last Sold: 4 Apr 2001 for $207,500'
        """
        result = {'price': None, 'date': None}

        # Try testid-based approach first
        sold_el = soup.find(attrs={'testid': 'lastSoldValue'}) or \
                  soup.find(attrs={'testid': 'lastSold'})
        if sold_el:
            text = sold_el.get_text(strip=True)
        else:
            # Fallback: look for 'Last Sold' label in the Quick Facts bar
            label = soup.find(string=re.compile(r'last\s*sold', re.IGNORECASE))
            if label and label.parent:
                # Get the sibling or parent container text
                container = label.parent.find_next_sibling() or label.parent.parent
                text = container.get_text(strip=True) if container else ''
            else:
                text = ''

        if text:
            # Extract price
            price_match = re.search(r'\$([\d,]+)', text)
            if price_match:
                try:
                    result['price'] = float(price_match.group(1).replace(',', ''))
                except ValueError:
                    pass
            # Extract date (e.g., '4 Apr 2001' or '2001')
            date_match = re.search(r'(\d{1,2}\s+\w+\s+\d{4})', text)
            if date_match:
                result['date'] = date_match.group(1)
            else:
                year_match = re.search(r'(\d{4})', text)
                if year_match:
                    result['date'] = year_match.group(1)

        return result

    @staticmethod
    def extract_suburb_insights(soup):
        """Extract suburb market stats from the Suburb Insights section.

        Returns dict with median_price, median_rent (weekly), days_on_market.
        """
        result = {'median_price': None, 'median_rent': None, 'days_on_market': None}

        # Median Sale Price
        price_el = soup.find(attrs={'testid': re.compile(r'medianSalePrice|medianPrice')})
        if not price_el:
            price_el = soup.find(string=re.compile(r'Median Sale Price', re.IGNORECASE))
        if price_el:
            container = price_el.parent if hasattr(price_el, 'parent') else None
            if container:
                text = container.parent.get_text(strip=True)
                m = re.search(r'\$([\d,]+[Kk]?)', text)
                if m:
                    result['median_price'] = PropertyValueParser._parse_price_short(m.group(1))

        # Median Rent (weekly)
        rent_el = soup.find(attrs={'testid': re.compile(r'medianRent')})
        if not rent_el:
            rent_el = soup.find(string=re.compile(r'Median Rent', re.IGNORECASE))
        if rent_el:
            container = rent_el.parent if hasattr(rent_el, 'parent') else None
            if container:
                text = container.parent.get_text(strip=True)
                m = re.search(r'\$([\d,]+)', text)
                if m:
                    try:
                        result['median_rent'] = float(m.group(1).replace(',', ''))
                    except ValueError:
                        pass

        # Average Days on Market
        dom_el = soup.find(attrs={'testid': re.compile(r'daysOnMarket|avgDays')})
        if not dom_el:
            dom_el = soup.find(string=re.compile(r'Days on Market', re.IGNORECASE))
        if dom_el:
            container = dom_el.parent if hasattr(dom_el, 'parent') else None
            if container:
                text = container.parent.get_text(strip=True)
                m = re.search(r'(\d+)\s*days?', text, re.IGNORECASE)
                if m:
                    result['days_on_market'] = int(m.group(1))

        return result

    @staticmethod
    def _parse_price_short(price_str):
        """Parse price with optional K suffix: '$960K' -> 960000, '$1,050,000' -> 1050000."""
        if not price_str:
            return None
        s = price_str.replace('$', '').replace(',', '').strip()
        multiplier = 1
        if s.upper().endswith('K'):
            multiplier = 1000
            s = s[:-1]
        try:
            return float(s) * multiplier
        except ValueError:
            return None

    @staticmethod
    def extract_coordinates(soup):
        """Extract GPS coordinates from embedded Google Maps iframe or link.

        Returns dict with 'latitude' and 'longitude' as floats.
        """
        result = {'latitude': None, 'longitude': None}

        # Strategy 1: Google Maps embed iframe
        iframe = soup.find('iframe', src=re.compile(r'maps\.google'))
        if iframe:
            src = iframe.get('src', '')
            m = re.search(r'[?&]ll=(-?\d+\.\d+),(-?\d+\.\d+)', src)
            if not m:
                m = re.search(r'center=(-?\d+\.\d+),(-?\d+\.\d+)', src)
            if m:
                try:
                    result['latitude'] = float(m.group(1))
                    result['longitude'] = float(m.group(2))
                    return result
                except ValueError:
                    pass

        # Strategy 2: Google Maps link in anchor tag
        map_link = soup.find('a', href=re.compile(r'maps\.google'))
        if map_link:
            href = map_link.get('href', '')
            m = re.search(r'[?&]ll=(-?\d+\.\d+),(-?\d+\.\d+)', href)
            if m:
                try:
                    result['latitude'] = float(m.group(1))
                    result['longitude'] = float(m.group(2))
                    return result
                except ValueError:
                    pass

        # Strategy 3: data attributes or inline script with coordinates
        coord_script = soup.find('script', string=re.compile(r'latitude|latLng|coords'))
        if coord_script:
            text = coord_script.string
            lat_m = re.search(r'"?lat(?:itude)?"?\s*[:=]\s*(-?\d+\.\d+)', text)
            lng_m = re.search(r'"?(?:lng|lon|longitude)"?\s*[:=]\s*(-?\d+\.\d+)', text)
            if lat_m and lng_m:
                try:
                    result['latitude'] = float(lat_m.group(1))
                    result['longitude'] = float(lng_m.group(1))
                except ValueError:
                    pass

        return result
