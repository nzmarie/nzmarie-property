import unittest
from scrapers.property_value_parser import PropertyValueParser

class TestPropertyValueParser(unittest.TestCase):
    def test_parse_property_links_filters_pagination(self):
        html = """
        <a href="/auckland/manukau-city/half-moon-bay-2012/1-anna-watson-road-8971200">Real</a>
        <a href="/auckland/manukau-city/half-moon-bay-2012/202281?page=2">Next Page</a>
        <a href="/auckland/manukau-city/half-moon-bay-2012/202281?Page=3">Next Page Upper</a>
        """
        links = PropertyValueParser.parse_property_links(html, "auckland")
        self.assertEqual(len(links), 1)
        self.assertIn("/auckland/manukau-city/half-moon-bay-2012/1-anna-watson-road-8971200", links)

    def test_parse_next_page_excludes_carousel(self):
        html = """
        <div class="pagination">
            <a href="?page=2" rel="next">></a>
        </div>
        <div class="carousel">
            <a href="#" class="carousel-control-next">Next</a>
        </div>
        """
        next_href = PropertyValueParser.parse_next_page(html)
        self.assertEqual(next_href, "?page=2")

    def test_parse_suburb_links(self):
        html = """
        <a href="/auckland/auckland/7">TA Link</a>
        <a href="/auckland/auckland/parnell-1052/200610">Suburb Link</a>
        """
        links = PropertyValueParser.parse_suburb_links(html, "auckland")
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0], "/auckland/auckland/parnell-1052/200610")

    def test_extract_images(self):
        from bs4 import BeautifulSoup
        html = """
        <div class="carousel-inner">
            <div class="carousel-item"><img src="img1.jpg"></div>
            <div class="carousel-item"><img data-src="img2.jpg"></div>
        </div>
        """
        soup = BeautifulSoup(html, 'html.parser')
        imgs = PropertyValueParser.extract_images(soup)
        self.assertEqual(imgs, ["img1.jpg", "img2.jpg"])

    def test_extract_history(self):
        from bs4 import BeautifulSoup
        html = """
        <div class="d-flex flex-row w-100 align-items-center pr-3 mb-2">
            <div testid="pt-year-0">2024</div>
            <strong testid="pt-description-0">Sold for $1,000,000</strong>
            <div testid="pt-interval-0">5 years</div>
        </div>
        """
        soup = BeautifulSoup(html, 'html.parser')
        history = PropertyValueParser.extract_history(soup)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['event_date'], "2024")
        self.assertEqual(history[0]['event_description'], "Sold for $1,000,000")
        self.assertEqual(history[0]['event_interval'], "5 years")

    def test_clean_area(self):
        self.assertEqual(PropertyValueParser._clean_area("200 m2"), 200.0)
        self.assertEqual(PropertyValueParser._clean_area("1.5 ha"), 15000.0)
        self.assertEqual(PropertyValueParser._clean_area("1,234 sqm"), 1234.0)
        self.assertEqual(PropertyValueParser._clean_area(500), 500.0)
        self.assertEqual(PropertyValueParser._clean_area(None), None)

    def test_parse_detail_data_html(self):
        """Test parse_detail_data extracts all fields from rendered HTML (React SPA, no __NEXT_DATA__)."""
        html = """
        <html><body>
            <div class="PropertyAttributes_propertyAttributes__1hayQ">
                <div><span testid="bed">4</span></div>
                <div><span testid="bath">2</span></div>
                <div><span testid="car">2</span></div>
                <div><span class="land"><span>500 m<sup>2</sup></span></span></div>
                <div><span class="floor"><span>180 m<sup>2</sup></span></span></div>
            </div>
            <div class="PropertyAttributes_typeZone__32h6q">
                <div class="PropertyAttributes_propertyType__13hPB">
                    <div>Property Type</div><div>Residential</div>
                </div>
                <div class="PropertyAttributes_propertyType__13hPB">
                    <div testid="yearBuiltLabel">Year Built</div>
                    <div testid="yearBuiltValue">1995</div>
                </div>
            </div>
            <div class="RatingValuation_RatingsGroup__LQFDR">
                <div class="capitalValueLabel RatingValuation_Label__1Et5D">Capital Value</div>
                <div class="capitalValueValue RatingValuation_Value__2j3Na">$1,050,000</div>
            </div>
            <div class="RatingValuation_RatingsGroup__LQFDR">
                <div class="landValueLabel RatingValuation_Label__1Et5D">Land Value</div>
                <div class="landValueValue RatingValuation_Value__2j3Na">$400,000</div>
            </div>
            <div class="RatingValuation_RatingsGroup__LQFDR">
                <div class="improvementValueLabel RatingValuation_Label__1Et5D">Improvement Value</div>
                <div class="improvementValueValue RatingValuation_Value__2j3Na">$650,000</div>
            </div>
            <div testid="story-content">
                <p testid="paragraph1">A beautiful residential property.</p>
            </div>
            <div testid="pt-year-0">2020</div>
            <strong testid="pt-description-0">Sold for $900,000</strong>
            <div testid="pt-interval-0">3 years</div>
        </body></html>
        """
        data = PropertyValueParser.parse_detail_data(html)
        
        self.assertEqual(data["bedrooms"], 4)
        self.assertEqual(data["bathrooms"], 2)
        self.assertEqual(data["car_spaces"], 2)
        self.assertEqual(data["floor_area"], 180.0)
        self.assertEqual(data["land_area"], 500.0)
        self.assertEqual(data["year_built"], 1995)
        self.assertEqual(data["property_type"], "Residential")
        self.assertEqual(data["capital_value"], 1050000.0)
        self.assertEqual(data["land_value"], 400000.0)
        self.assertEqual(data["improvement_value"], 650000.0)
        self.assertIn("beautiful residential property", data["description"])
        self.assertEqual(len(data["history"]), 1)
        self.assertEqual(data["history"][0]["event_description"], "Sold for $900,000")



if __name__ == '__main__':
    unittest.main()
