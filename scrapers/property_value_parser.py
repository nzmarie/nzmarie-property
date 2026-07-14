import json
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
    def _parse_price_short(price_str):
        if not price_str:
            return None
        s = price_str.replace('$', '').replace(',', '').strip()
        multiplier = 1
        if s.upper().endswith('K'):
            multiplier = 1000
            s = s[:-1]
        elif s.upper().endswith('M'):
            multiplier = 1000000
            s = s[:-1]
        try:
            return float(s) * multiplier
        except ValueError:
            return None

    @staticmethod
    def parse_detail_data(html):
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
            "images": [], "history": [], "description": None,
            "suburb": None, "postcode": None,
            "property_history": None,
            "has_rental_history": False
        }

        redux_data = {}
        script = soup.find('script', string=re.compile(r'window\.REDUX_DATA\s*='))
        if script and script.string:
            m = re.search(r'window\.REDUX_DATA\s*=\s*({.*?})(?:;|$)', script.string)
            if m:
                try:
                    redux_data = json.loads(m.group(1))
                except Exception:
                    pass

        if redux_data:
            prop_details = redux_data.get('PropertyDetails', {})
            core = prop_details.get('core', {})
            additional = prop_details.get('additional', {})
            location = prop_details.get('location', {})
            estimated_range = prop_details.get('estimatedRange', {})
            rating_valuation = prop_details.get('ratingValuation', {})
            sales = prop_details.get('sales', {})
            images_data = prop_details.get('images', {})
            timeline = prop_details.get('propertyTimeline', [])

            data["bedrooms"] = core.get("beds")
            data["bathrooms"] = core.get("baths")
            data["car_spaces"] = core.get("carSpaces")
            
            yb = additional.get("yearBuilt")
            if yb:
                try:
                    data["year_built"] = int(yb)
                except ValueError:
                    pass

            fa = additional.get("floorArea")
            if fa:
                data["floor_area"] = float(fa)
                
            la = core.get("landArea")
            if la:
                data["land_area"] = float(la)

            pt = core.get("propertyType")
            if pt:
                data["property_type"] = pt.title()

            cv = rating_valuation.get("capitalValue")
            if cv:
                data["capital_value"] = float(cv)
                
            lv = rating_valuation.get("landValue")
            if lv:
                data["land_value"] = float(lv)
                
            iv = rating_valuation.get("improvementValue")
            if iv:
                data["improvement_value"] = float(iv)

            data["estimated_value_low"] = estimated_range.get("lowerBand")
            data["estimated_value_high"] = estimated_range.get("upperBand")

            last_sale = sales.get("lastSale", {})
            data["last_sold_price"] = last_sale.get("price")
            
            contract_date = last_sale.get("contractDate")
            if contract_date:
                from datetime import datetime
                try:
                    dt = datetime.strptime(contract_date, "%Y-%m-%d")
                    data["last_sold_date"] = dt.strftime("%d %b %Y").lstrip('0')
                except Exception:
                    # Try other common formats before falling back
                    parsed = False
                    for fmt in ("%Y/%m/%d", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m", "%Y/%m"):
                        try:
                            dt = datetime.strptime(contract_date, fmt)
                            data["last_sold_date"] = dt.strftime("%d %b %Y").lstrip('0')
                            parsed = True
                            break
                        except Exception:
                            continue
                    if not parsed:
                        # Last resort: if it looks like a bare year, make Jan 1
                        year_m = re.match(r'^(\d{4})$', str(contract_date).strip())
                        if year_m:
                            data["last_sold_date"] = f"1 Jan {year_m.group(1)}"
                        else:
                            # Unknown format — skip rather than storing garbage
                            data["last_sold_date"] = None

            data["latitude"] = location.get("latitude")
            data["longitude"] = location.get("longitude")

            for photo in images_data.get("propertyPhotoList", []):
                url = photo.get("largePhotoUrl") or photo.get("mediumPhotoUrl") or photo.get("thumbnailPhotoUrl")
                if url and url not in data["images"]:
                    data["images"].append(url)

            for event in timeline:
                ev_type = event.get("type", "").lower()
                ev_date = event.get("date", "")
                price_desc = event.get("priceDescription", "")
                agent = event.get("eventByCompany", "") or ""
                interval_desc = event.get("intervalDescription", "").strip()

                display_type = (
                    "SOLD" if ev_type == "sale" else
                    "Rented" if ev_type == "rent" else
                    "Listed" if ev_type == "listing" else
                    ev_type.title()
                )

                desc = ""
                if ev_type == "sale":
                    desc = f"Sold for {price_desc}"
                elif ev_type == "rent":
                    desc = f"Listed for Rent - Last price at {price_desc} per week"
                elif ev_type == "listing":
                    desc = f"Asking Price \u2014 {price_desc}"
                else:
                    desc = f"{ev_type.title()} \u2014 {price_desc}"

                data["history"].append({
                    'event_date': ev_date,
                    'event_description': desc,
                    'event_interval': interval_desc,
                    'type': display_type,
                    'price': price_desc,
                    'agent': agent
                })

        if data["bedrooms"] is None:
            data["bedrooms"] = PropertyValueParser._extract_int_by_testid(soup, 'bed')
        if data["bathrooms"] is None:
            data["bathrooms"] = PropertyValueParser._extract_int_by_testid(soup, 'bath')
        if data["car_spaces"] is None:
            data["car_spaces"] = PropertyValueParser._extract_int_by_testid(soup, 'car')
        if data["year_built"] is None:
            data["year_built"] = PropertyValueParser._extract_int_by_testid(soup, 'yearBuiltValue')
        if data["land_area"] is None:
            data["land_area"] = PropertyValueParser._extract_area_by_class(soup, 'land')
        if data["floor_area"] is None:
            data["floor_area"] = PropertyValueParser._extract_area_by_class(soup, 'floor')
        if data["property_type"] is None:
            data["property_type"] = PropertyValueParser._extract_property_type(soup)
        
        rv = PropertyValueParser._extract_rating_valuation(soup)
        if data["capital_value"] is None:
            data["capital_value"] = rv.get('capital_value')
        if data["land_value"] is None:
            data["land_value"] = rv.get('land_value')
        if data["improvement_value"] is None:
            data["improvement_value"] = rv.get('improvement_value')

        story_el = soup.find(attrs={'testid': 'story-content'})
        if story_el:
            # Extract each paragraph separately and join with newline
            paragraphs = story_el.find_all('p')
            if paragraphs:
                parts = [re.sub(r'\s+', ' ', p.get_text(separator=' ', strip=True)) for p in paragraphs if p.get_text(strip=True)]
                data["description"] = '\n\n'.join(parts)
            else:
                # Fallback: get all text if no <p> tags found
                text = story_el.get_text(separator=' ', strip=True)
                data["description"] = re.sub(r'\s+', ' ', text).strip()
        else:
            about_heading = soup.find(string=re.compile(r'About\s+', re.IGNORECASE))
            if about_heading and about_heading.parent:
                next_sib = about_heading.parent.find_next_sibling()
                if next_sib and next_sib.name in ('p', 'div', 'span'):
                    text = next_sib.get_text(separator=' ', strip=True)
                    data["description"] = re.sub(r'\s+', ' ', text).strip()

        if not data["images"]:
            data["images"] = PropertyValueParser.extract_images(soup)

        if not data["history"]:
            data["history"] = PropertyValueParser.extract_history(soup)

        ev = PropertyValueParser.extract_estimated_value(soup)
        if data["estimated_value_low"] is None:
            data["estimated_value_low"] = ev.get('low')
        if data["estimated_value_high"] is None:
            data["estimated_value_high"] = ev.get('high')

        ls = PropertyValueParser.extract_last_sold(soup)
        if data["last_sold_price"] is None:
            data["last_sold_price"] = ls.get('price')
        if data["last_sold_date"] is None:
            data["last_sold_date"] = ls.get('date')

        si = PropertyValueParser.extract_suburb_insights(soup)
        data["suburb_median_price"] = si.get('median_price')
        data["suburb_median_rent"] = si.get('median_rent')
        data["suburb_days_on_market"] = si.get('days_on_market')

        coords = PropertyValueParser.extract_coordinates(soup)
        if data["latitude"] is None:
            data["latitude"] = coords.get('latitude')
        if data["longitude"] is None:
            data["longitude"] = coords.get('longitude')

        addr2_el = soup.find(attrs={'testid': 'addressLine2'})
        if addr2_el:
            addr2_text = addr2_el.get_text(strip=True)
            if ',' in addr2_text:
                parts = [p.strip() for p in addr2_text.split(',')]
                if len(parts) >= 2:
                    data["suburb"] = parts[0]
                    data["postcode"] = parts[1]
            else:
                match = re.search(r'^(.*?)\s*(\d{4})$', addr2_text)
                if match:
                    data["suburb"] = match.group(1).strip()
                    data["postcode"] = match.group(2).strip()
                else:
                    data["suburb"] = addr2_text

        if data["history"]:
            json_entries = []
            has_rental = False
            for ev in data["history"]:
                json_entries.append({
                    "date": ev.get("event_date", ""),
                    "type": ev.get("type", ""),
                    "price": ev.get("price", ""),
                    "agent": ev.get("agent", ""),
                    "interval": ev.get("event_interval", "")
                })
                tp = ev.get("type", "").lower()
                desc = ev.get("event_description", "").lower()
                if tp == "rented" or "rent" in desc:
                    has_rental = True
            data["property_history"] = json.dumps(json_entries, ensure_ascii=False)
            data["has_rental_history"] = has_rental

        return data

    @staticmethod
    def _extract_int_by_testid(soup, testid_value):
        el = soup.find(attrs={'testid': testid_value})
        if el:
            text = el.get_text(strip=True)
            match = re.search(r'(\d+)', text)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _extract_area_by_class(soup, class_name):
        el = soup.find('span', class_=class_name)
        if el:
            text = el.get_text(strip=True)
            return PropertyValueParser._clean_area(text)
        return None

    @staticmethod
    def _extract_property_type(soup):
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
        if not area_val:
            return None
        if isinstance(area_val, (int, float)):
            return float(area_val)
        try:
            s = str(area_val).lower().replace(',', '')
            num = float(re.search(r"(\d+\.?\d*)", s).group(1))
            if 'ha' in s:
                return num * 10000.0
            return num
        except Exception:
            return None

    @staticmethod
    def extract_images(soup):
        images = []
        street_view = soup.find('img', src=re.compile(r'maps\.googleapis\.com'))
        if street_view:
            src = street_view.get('src')
            if src:
                images.append(src)
        items = soup.select('div.carousel-inner div.carousel-item img')
        for img in items:
            src = img.get('src') or img.get('data-src')
            if src and src not in images:
                images.append(src)
        return images

    @staticmethod
    def extract_history(soup):
        property_history = []
        year_els = soup.find_all(attrs={'testid': re.compile(r'^pt-year-\d+$')})
        for year_el in year_els:
            testid = year_el.get('testid', '')
            match = re.search(r'pt-year-(\d+)', testid)
            if not match:
                continue
            idx = match.group(1)
            event_date = year_el.get_text(strip=True)
            desc_el = soup.find(attrs={'testid': f'pt-description-{idx}'})
            event_description = desc_el.get_text(strip=True) if desc_el else "Unknown"
            interval_el = soup.find(attrs={'testid': f'pt-interval-{idx}'})
            event_interval = interval_el.get_text(strip=True) if interval_el else ""
            agent_el = soup.find(attrs={'testid': f'pt-eventByCom-{idx}'})
            agent = agent_el.get_text(strip=True) if agent_el else ""
            if agent.startswith("Listed by "):
                agent = agent[10:]

            ev_type = ""
            ev_price = ""
            if event_description.startswith("Sold for "):
                ev_type = "SOLD"
                ev_price = event_description[9:]
            elif "Listed for Rent" in event_description:
                ev_type = "Rented"
                if " at " in event_description:
                    ev_price = event_description.split(" at ")[-1]
            elif "Asking" in event_description:
                ev_type = "Listed"
                if "\u2014" in event_description:
                    ev_price = event_description.split("\u2014")[-1].strip()
            elif "Built" in event_description:
                ev_type = "Built"

            property_history.append({
                'event_date': event_date,
                'event_description': event_description,
                'event_interval': event_interval,
                'type': ev_type,
                'price': ev_price,
                'agent': agent
            })
        return property_history

    @staticmethod
    def extract_estimated_value(soup):
        result = {'low': None, 'high': None}
        value_el = soup.find(class_=re.compile(r'estimatedValue|valueRange|EstimatedValue'))
        if not value_el:
            text_block = soup.find(string=re.compile(r'\$[\d,.]+\s*\u2013\s*\$[\d,.]+'))
            if text_block:
                value_el = text_block
        if value_el:
            text = value_el.get_text(strip=True) if hasattr(value_el, 'get_text') else str(value_el)
            amounts = re.findall(r'\$([\d,.]+)', text)
            if len(amounts) >= 2:
                try:
                    result['low'] = PropertyValueParser._parse_price_short(amounts[0])
                    result['high'] = PropertyValueParser._parse_price_short(amounts[1])
                except ValueError:
                    pass
        return result

    @staticmethod
    def extract_last_sold(soup):
        result = {'price': None, 'date': None}
        sold_el = soup.find(attrs={'testid': 'lastSoldValue'}) or \
                  soup.find(attrs={'testid': 'lastSold'})
        if sold_el:
            text = sold_el.get_text(strip=True)
        else:
            label = soup.find(string=re.compile(r'last\s*sold', re.IGNORECASE))
            if label and label.parent:
                container = label.parent.find_next_sibling() or label.parent.parent
                text = container.get_text(strip=True) if container else ''
            else:
                text = ''
        if text:
            price_match = re.search(r'\$([\d,]+)', text)
            if price_match:
                try:
                    result['price'] = float(price_match.group(1).replace(',', ''))
                except ValueError:
                    pass
            date_match = re.search(r'(\d{1,2}\s+\w+\s+\d{4})', text)
            if date_match:
                result['date'] = date_match.group(1)
            else:
                # If only year is found, set to January 1st of that year
                year_match = re.search(r'(\d{4})', text)
                if year_match:
                    result['date'] = f"1 Jan {year_match.group(1)}"
        return result

    @staticmethod
    def extract_suburb_insights(soup):
        result = {'median_price': None, 'median_rent': None, 'days_on_market': None}
        price_el = soup.find(attrs={'testid': re.compile(r'^medianSalePrice$|^medianPrice$')})
        if not price_el:
            price_el = soup.find(string=re.compile(r'Median Sale Price', re.IGNORECASE))
        if price_el:
            container = price_el.parent if hasattr(price_el, 'parent') else None
            if container:
                text = container.parent.get_text(strip=True)
                m = re.search(r'\$([\d.,]+[KkMm]?)', text)
                if m:
                    result['median_price'] = PropertyValueParser._parse_price_short(m.group(1))
        rent_el = soup.find(attrs={'testid': re.compile(r'^medianRent$')})
        if not rent_el:
            rent_el = soup.find(string=re.compile(r'Median Rent', re.IGNORECASE))
        if rent_el:
            container = rent_el.parent if hasattr(rent_el, 'parent') else None
            if container:
                text = container.parent.get_text(strip=True)
                m = re.search(r'\$([\d.,]+[KkMm]?)', text)
                if m:
                    result['median_rent'] = PropertyValueParser._parse_price_short(m.group(1))
        dom_el = soup.find(attrs={'testid': re.compile(r'^daysOnMarket$|^avgDays$')})
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
    def extract_coordinates(soup):
        result = {'latitude': None, 'longitude': None}
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
