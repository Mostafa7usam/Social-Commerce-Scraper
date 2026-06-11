import json
from scraper import scrape_instagram_apify

# Test with a test URL (replace with your desired URL)
TEST_URL = "locken.co"
APIFY_TOKEN = 'apify_api_CzYokXbkgSiq8nhZ5jAKDX4EqojmLb3G6FnX'

#` Test 4: Scrape Instagram using Apify (if applicable)
instagram_data = scrape_instagram_apify(TEST_URL, APIFY_TOKEN)
print(f"Instagram Data: {json.dumps(instagram_data, indent=2)}\n")      
