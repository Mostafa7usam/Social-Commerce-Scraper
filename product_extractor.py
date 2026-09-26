import csv
import json
import os
import requests

# Reuse the same config values as scraper.py
SUPABASE_URL = 'https://seajrglfquchnppqxrhl.supabase.co'
SUPABASE_KEY = 'sb_publishable_fLxoXW0T5Nck7gXYYWN79Q_FJgEOA6D'

supabase_headers = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json'
}

# Path to the CSV of shop URLs to process. No header row, one URL per row.
INSTAGRAM_URLS_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instagram_urls.csv')


def load_shop_urls_from_csv(csv_path=INSTAGRAM_URLS_CSV):
    """
    Reads a headerless, single-column CSV of Instagram shop URLs
    (e.g. https://www.instagram.com/brava_cairo) into a set of URLs used
    to filter which shops get processed. Assumes each URL matches its
    corresponding instagram_url value in Supabase exactly (no case or
    trailing-slash normalization is applied).
    Returns an empty set (and prints a warning) if the file is missing
    or contains no usable rows.
    """
    if not os.path.exists(csv_path):
        print(f"✗ CSV not found at {csv_path}\n")
        return set()

    urls = set()
    with open(csv_path, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            url = row[0].strip()
            if url:
                urls.add(url)

    print(f"Loaded {len(urls)} shop URL(s) from {csv_path}\n")
    return urls


def fetch_scraper_results_with_products(allowed_urls=None):
    """
    Step 1: GET rows from scraper_results where products_json is not null,
            scoped server-side to only the shops in allowed_urls (if given)
            via an 'instagram_url=in.(...)' filter. Assumes the CSV's URLs
            match Supabase's stored instagram_url values exactly (no
            normalization applied), so the DB only ever scans/returns rows
            for the shops we actually need instead of the whole table —
            this is what avoids the statement timeout (error 57014).
    Step 2: Group the returned rows by shop (instagram_url) and keep only
            the one with the latest date_added, discarding older scrapes
            of the same shop.
    Returns: a list of scraper_results rows (id, instagram_url, date_added,
             products_json), one per shop, representing its most recent scrape.
    """
    params = {
        'select': 'id,instagram_url,date_added,products_json',
        'products_json': 'not.is.null'
    }

    if allowed_urls is not None:
        if not allowed_urls:
            # Nothing to fetch — avoid sending a malformed empty in.() filter.
            return []
        quoted = ','.join(f'"{u}"' for u in allowed_urls)
        params['instagram_url'] = f'in.({quoted})'

    response = requests.get(
        f'{SUPABASE_URL}/rest/v1/scraper_results',
        headers=supabase_headers,
        params=params
    )
    if not response.ok:
        print(f"✗ Fetch error: {response.status_code} {response.text}\n")
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


def process_products_to_supabase(csv_path=INSTAGRAM_URLS_CSV):
    """
    Main entry point — full refresh of scraper_products, scoped to the
    shops listed in instagram_urls.csv.
    Step 1: Load the allowed shop URLs from the CSV.
    Step 2: Wipe the entire scraper_products table (clear_scraper_products()),
            same as before.
    Step 3: Fetch every scraper_results row with products_json, then filter
            in Python down to only the shops whose instagram_url is in the CSV.
    Step 4: For each remaining shop's row, parse its products_json string into
            a Python list of product dicts.
    Step 5: Map each product's fields (product_title, product_description,
            price, product_url, src) onto the scraper_products column names,
            tagging each with its parent scraper_result_id.
    Step 6: Bulk insert that shop's product rows (insert_products_batch()).
    Skips any row with missing/empty/invalid products_json rather than failing.
    """
    allowed_urls = load_shop_urls_from_csv(csv_path)
    if not allowed_urls:
        print("✗ No shop URLs loaded — aborting so we don't wipe scraper_products for nothing.\n")
        return

    clear_scraper_products()

    results = fetch_scraper_results_with_products(allowed_urls=allowed_urls)
    print(f"Found {len(results)} scraper_results row(s) with products_json for the listed shops\n")

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