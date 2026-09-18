import json
import requests

# Reuse the same config values as scraper.py
SUPABASE_URL = 'https://seajrglfquchnppqxrhl.supabase.co'
SUPABASE_KEY = 'sb_publishable_fLxoXW0T5Nck7gXYYWN79Q_FJgEOA6D'

supabase_headers = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json'
}


def fetch_scraper_results_with_products():
    """
    Step 1: GET all rows from scraper_results where products_json is not null.
    Step 2: Group those rows by shop (using instagram_url as the shop identifier).
    Step 3: Within each group, keep only the row with the latest date_added,
            discarding older scrapes of the same shop.
    Returns: a list of scraper_results rows (id, instagram_url, date_added,
             products_json), one per shop, representing its most recent scrape.
    """
    response = requests.get(
        f'{SUPABASE_URL}/rest/v1/scraper_results',
        headers=supabase_headers,
        params={
            'select': 'id,instagram_url,date_added,products_json',
            'products_json': 'not.is.null'
        }
    )
    response.raise_for_status()
    all_rows = response.json()

    # Keep only the latest row per shop (instagram_url), by date_added
    latest_by_shop = {}
    for row in all_rows:
        shop_key = row.get('instagram_url')
        if not shop_key:
            continue

        existing = latest_by_shop.get(shop_key)
        if existing is None or row.get('date_added', '') > existing.get('date_added', ''):
            latest_by_shop[shop_key] = row

    return list(latest_by_shop.values())


def clear_scraper_products(scraper_result_id=None):
    """
    Deletes rows from scraper_products via a DELETE request to Supabase.
    - If scraper_result_id is passed: only deletes rows whose scraper_result_id
      matches (i.e. just one shop's products). Used for scoped/test cleanup.
    - If scraper_result_id is None: deletes every row in the table (id > 0
      matches all rows, since PostgREST requires some filter on DELETE).
      Used before a full refresh so old/removed products don't linger.
    Prints a success message with the scope, or the error response if it fails.
    """
    if scraper_result_id is not None:
        params = {'scraper_result_id': f'eq.{scraper_result_id}'}
    else:
        params = {'id': 'gt.0'}  # PostgREST requires a filter; this matches all rows

    response = requests.delete(
        f'{SUPABASE_URL}/rest/v1/scraper_products',
        headers=supabase_headers,
        params=params
    )
    if response.status_code in (200, 204):
        scope = f"result id={scraper_result_id}" if scraper_result_id is not None else "all rows"
        print(f"✓ Cleared existing scraper_products rows ({scope})\n")
    else:
        print(f"✗ Clear error: {response.status_code} {response.text}\n")
        response.raise_for_status()


def insert_products_batch(rows):
    """
    Takes a list of product dicts (already shaped to match the scraper_products
    columns) and POSTs them to Supabase in a single bulk insert request
    (one HTTP call for the whole shop's products, not one call per product).
    Does nothing if rows is empty. Prints success or the error response.
    """
    if not rows:
        return
    response = requests.post(
        f'{SUPABASE_URL}/rest/v1/scraper_products',
        headers=supabase_headers,
        json=rows
    )
    if response.status_code == 201:
        print(f"  ✓ Inserted {len(rows)} product row(s)")
    else:
        print(f"  ✗ Insert error: {response.status_code} {response.text}")


def process_products_to_supabase():
    """
    Main entry point — full refresh of scraper_products.
    Step 1: Wipe the entire scraper_products table (clear_scraper_products()).
    Step 2: Fetch the latest scraper_results row per shop
            (fetch_scraper_results_with_products()).
    Step 3: For each shop's row, parse its products_json string into a
            Python list of product dicts.
    Step 4: Map each product's fields (product_title, product_description,
            price, product_url, src) onto the scraper_products column names,
            tagging each with its parent scraper_result_id.
    Step 5: Bulk insert that shop's product rows (insert_products_batch()).
    Skips any row with missing/empty/invalid products_json rather than failing.
    """
    clear_scraper_products()

    results = fetch_scraper_results_with_products()
    print(f"Found {len(results)} scraper_results row(s) with products_json\n")

    for row in results:
        result_id = row.get('id')
        raw_json = row.get('products_json')

        if not raw_json:
            continue

        try:
            products = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
        except (json.JSONDecodeError, TypeError) as e:
            print(f"  ✗ Skipping result id={result_id}, bad JSON: {e}")
            continue

        if not products:
            continue

        print(f"Processing result id={result_id} ({len(products)} product(s))")

        product_rows = []
        for product in products:
            product_rows.append({
                'scraper_result_id': result_id,
                'product_title': product.get('product_title', ''),
                'product_description': product.get('product_description', ''),
                'price': product.get('price', ''),
                'product_url': product.get('product_url', ''),
                'product_image_src': product.get('src', '')
            })

        insert_products_batch(product_rows)

    print("\n✓ Done populating scraper_products")


if __name__ == '__main__':
    process_products_to_supabase()