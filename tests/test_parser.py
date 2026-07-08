import unittest
import sys
import os
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.property_value_parser import PropertyValueParser


class TestPropertyValueParserLegacy(unittest.TestCase):
    """Tests originally written against PropertyValueEngine methods
    that have since been refactored into PropertyValueParser."""

    def setUp(self):
        self.sample_html = """
        <html>
            <body>
                <div class="carousel-inner">
                    <div class="carousel-item active">
                        <img src="https://example.com/img1.jpg" alt="Photo 1">
                    </div>
                    <div class="carousel-item">
                        <img src="https://example.com/img2.jpg" alt="Photo 2">
                    </div>
                </div>
                <div class="d-flex flex-row w-100 align-items-center pr-3 mb-2">
                    <div testid="pt-year-0">2022</div>
                    <strong testid="pt-description-0">Sold for $497,500</strong>
                    <div testid="pt-interval-0">4 years</div>
                </div>
                <div class="d-flex flex-row w-100 align-items-center pr-3 mb-2">
                    <div testid="pt-year-1">2018</div>
                    <strong testid="pt-description-1">Listed for Rent: $550pw</strong>
                    <div testid="pt-interval-1">2 years</div>
                </div>
            </body>
        </html>
        """
        self.soup = BeautifulSoup(self.sample_html, 'html.parser')

    def test_extract_images(self):
        images = PropertyValueParser.extract_images(self.soup)
        self.assertEqual(len(images), 2)
        self.assertIn("https://example.com/img1.jpg", images)
        self.assertIn("https://example.com/img2.jpg", images)

    def test_extract_history(self):
        events = PropertyValueParser.extract_history(self.soup)
        self.assertGreaterEqual(len(events), 1)
        dates = [e['event_date'] for e in events]
        self.assertTrue(any("2022" in d for d in dates),
                        f"Expected 2022 in history dates, got: {dates}")
        descriptions = [e['event_description'] for e in events]
        self.assertTrue(any("Sold for $497,500" in d for d in descriptions),
                        f"Expected sale description, got: {descriptions}")

    def test_extract_images_empty_html(self):
        soup = BeautifulSoup("<html></html>", 'html.parser')
        images = PropertyValueParser.extract_images(soup)
        self.assertIsInstance(images, list)
        self.assertEqual(len(images), 0)

    def test_extract_history_empty_html(self):
        soup = BeautifulSoup("<html></html>", 'html.parser')
        events = PropertyValueParser.extract_history(soup)
        self.assertIsInstance(events, list)
        self.assertEqual(len(events), 0)


if __name__ == "__main__":
    unittest.main()
