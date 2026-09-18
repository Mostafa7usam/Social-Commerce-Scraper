import csv
import json
from unittest import result
from urllib import response
import requests
import os
import sqlite3
from datetime import datetime

# ============================================================================
# CONFIGURATION - Update these variables before running
# ============================================================================
APIFY_TOKEN = 'apify_api_CzYokXbkgSiq8nhZ5jAKDX4EqojmLb3G6FnX'
INPUT_CSV = 'instagram_urls.csv'
DB_FILE = 'scraper.db'
MAX_SHOPIFY_PAGES = 10
REQUEST_TIMEOUT = 10
SUPABASE_URL = 'https://seajrglfquchnppqxrhl.supabase.co'
SUPABASE_KEY = 'sb_publishable_fLxoXW0T5Nck7gXYYWN79Q_FJgEOA6D'
# ============================================================================


# HELPER: Scrape Instagram profile via Apify API
def scrape_instagram_apify(username, apify_token):
    """Scrape Instagram profile data using Apify Actor (clean version)"""

    url = "https://api.apify.com/v2/acts/dSCLg0C3YEZ83HzYX/run-sync-get-dataset-items"

    payload = {
        "usernames": [username]
    }

    headers = {
        "Authorization": f"Bearer {apify_token}",
        "Content-Type": "application/json"
    }

    try:
        print("Apify URL:", url)
        print("Payload:", payload)

        response = requests.post(url, json=payload, headers=headers, timeout=120)

        print("Status:", response.status_code)

        response.raise_for_status()

        items = response.json()

        if not items:
            print("No results returned from actor")
            return None

        return items[0]

    except Exception as e:
        print(f"Apify scraping error: {e}")
        return None


# HELPER: Detect e-commerce platform from URL
def detect_platform(url):
    """Detect if URL is Shopify, Magento, WooCommerce, etc."""
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        content = response.text.lower()

        if 'shopify.com' in content or 'cdn.shopify.com' in content or '/cdn/shop/' in content:
            return 'Shopify'
        elif 'magento' in content:
            return 'Magento'
        elif 'woocommerce' in content or 'wp-content/plugins/woocommerce' in content:
            return 'WooCommerce'
        elif 'bigcommerce' in content:
            return 'BigCommerce'
        else:
            return 'Other'
    except:
        return 'Unknown'


# HELPER: Extract actual store URL from Linktree
def extract_shopify_from_linktree(linktree_url):
    """Find and extract Shopify store URL from Linktree page"""
    try:
        response = requests.get(linktree_url, timeout=REQUEST_TIMEOUT)
        content = response.text

        # Look for .myshopify.com domain in the page
        import re
        shopify_matches = re.findall(r'https://[\w-]+\.myshopify\.com', content)
        if shopify_matches:
            return shopify_matches[0]

        # Look for shopify store URLs in hrefs
        links = re.findall(r'href=["\']([^"\']*shopify[^"\']*)["\']', content)
        if links:
            return links[0]

        return None
    except:
        return None


# HELPER: Scrape Shopify products
def scrape_shopify_products(shopify_url, max_pages=MAX_SHOPIFY_PAGES):
    """Scrape all products from Shopify store"""
    products = []

    # Ensure URL ends with /products.json for API access
    base_url = shopify_url.rstrip('/').replace('/products.json', '')
    api_url = f"{base_url}/products.json"

    for page in range(1, max_pages + 1):
        try:
            response = requests.get(f"{api_url}?page={page}&limit=250", timeout=REQUEST_TIMEOUT)
            if response.status_code == 200:
                data = response.json()
                page_products = data.get('products', [])

                if not page_products:
                    break

                for product in page_products:
                    handle = product.get('handle', '')
                    products.append({
                        'product_url': f"{base_url}/products/{handle}" if handle else '',
                        'product_title': product.get('title', ''),
                        'product_description': product.get('body_html', ''),
                        'price': product['variants'][0].get('price', '') if product.get('variants') else '',
                        'compare_at_price': product['variants'][0].get('compare_at_price', '') if product.get('variants') else '',
                        'src': product['images'][0].get('src', '') if product.get('images') else ''
                    })
        except:
            break

    return products


# HELPER: Scrape website content
def scrape_website(url):
    """Scrape main content from website"""
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        # Simple text extraction (can be enhanced with BeautifulSoup)
        return response.text[:5000]  # First 5000 chars
    except:
        return ''

def process_instagram_csv(input_csv, apify_token):
    """Main function to process Instagram URLs from CSV and store in Supabase"""

    supabase_headers = {
        'apikey': SUPABASE_KEY,
        'Authorization': f'Bearer {SUPABASE_KEY}',
        'Content-Type': 'application/json'
    }

    def save_to_supabase(result):
        response = requests.post(
            f'{SUPABASE_URL}/rest/v1/scraper_results',
            headers=supabase_headers,
            json=result
        )
        if response.status_code == 201:
            print("  ✓ Saved to Supabase")
        else:
            print(f"  ✗ Supabase error: {response.text}")

    try:
        with open(input_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            for row in reader:
                instagram_url = row.get('instagram_url', '').strip()
                if not instagram_url:
                    continue

                print(f"\nProcessing: {instagram_url}")
                result = {
                    'date_added': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'instagram_url': instagram_url,
                    'username': '',
                    'followers': '',
                    'posts': '',
                    'platform': 'Unknown',
                    'store_url': '',
                    'products_count': 0,
                    'products_json': '',
                    'website_content': '',
                    'status': 'failed',
                    'error': ''
                }

                try:
                    # STEP 1: Extract username
                    username = instagram_url.rstrip('/').split('/')[-1]
                    result['username'] = username
                    print(f"  Username: {username}")

                    # STEP 2: Scrape Instagram profile
                    ig_data = scrape_instagram_apify(username, apify_token)
                    if ig_data:
                        result['followers'] = ig_data.get('followersCount', '')
                        result['posts'] = ig_data.get('postsCount', '')
                        print(f"  Followers: {result['followers']}, Posts: {result['posts']}")

                    # STEP 3: Get external URL (bio link)
                    external_url = ig_data.get('externalUrl', '') if ig_data else ''
                    if not external_url:
                        print("  No external URL found")
                        result['status'] = 'no_url'
                        save_to_supabase(result)
                        continue

                    result['store_url'] = external_url
                    print(f"  External URL: {external_url}")

                    # STEP 4: Handle Linktree
                    actual_url = external_url
                    if 'linktr.ee' in external_url or 'linktree.com' in external_url:
                        print("  Linktree detected - extracting store URL...")
                        shopify_url = extract_shopify_from_linktree(external_url)
                        if shopify_url:
                            actual_url = shopify_url
                            print(f"  Found store: {shopify_url}")

                    # STEP 5: Detect platform
                    platform = detect_platform(actual_url)
                    result['platform'] = platform
                    print(f"  Platform: {platform}")

                    # STEP 6: Scrape Shopify products if applicable
                    if platform == 'Shopify':
                        print("  Scraping Shopify products...")
                        products = scrape_shopify_products(actual_url)
                        if products:
                            result['products_count'] = len(products)
                            result['products_json'] = json.dumps(products)
                            print(f"  Found {len(products)} products")
                        else:
                            print("  No products found")

                    # STEP 7: Scrape website content
                    print("  Scraping website content...")
                    content = scrape_website(actual_url)
                    result['website_content'] = content[:1000] if content else ''

                    result['status'] = 'success'
                    print("  ✓ Success")

                except Exception as e:
                    result['error'] = str(e)
                    print(f"  ✗ Error: {e}")

                # Save result to Supabase
                save_to_supabase(result)

    except FileNotFoundError:
        print(f"Error: Input file '{input_csv}' not found")

    print(f"\n✓ All results saved to Supabase")


if __name__ == '__main__':
    process_instagram_csv(INPUT_CSV, APIFY_TOKEN)

#if __name__ == '__main__':
#    process_instagram_csv(INPUT_CSV, DB_FILE, APIFY_TOKEN)
