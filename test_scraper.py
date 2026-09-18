import json
from scraper import scrape_shopify_products, detect_platform

# Test with a Shopify store URL (replace with your desired store)
TEST_URL = "https://shoplocken.co"

# Test 1: Confirm the site is detected as Shopify
platform = detect_platform(TEST_URL)
print(f"Detected platform: {platform}\n")

# Test 2: Scrape products and check product_url is populated
products = scrape_shopify_products(TEST_URL, max_pages=1)

print(f"Found {len(products)} product(s)\n")

for product in products[:3]:  # just preview the first 3
    print(json.dumps(product, indent=2))
    print("-" * 40)


