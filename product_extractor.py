import csv
import json
import os
import time
import requests

# Reuse the same config values as scraper.py
SUPABASE_URL = 'https://seajrglfquchnppqxrhl.supabase.co'
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', 'sb_publishable_fLxoXW0T5Nck7gXYYWN79Q_FJgEOA6D')

supabase_headers = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type': 'application/json'
}

# Path to the CSV of shop URLs to process. No header row, one URL per row.
INSTAGRAM_URLS_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instagram_urls.csv')

URL_CHUNK_SIZE = 10      # shop URLs per request when fetching lightweight metadata
ID_CHUNK_SIZE = 1        # one row per request; products_json blobs are large
PAGE_SIZE = 1000         # PostgREST default max rows per response
REQUEST_TIMEOUT = 60     # seconds, client-side
MAX_RETRIES = 4          # retries on dropped connections / timeouts / 5xx


def load_shop_urls_from_csv(csv_path=INSTAGRAM_URLS_CSV):
    """
    Reads a headerless, single-column CSV of Instagram shop URLs into a set.
    Skips blank rows and any stray header row (a value equal to 'instagram_url').
    Returns an empty set (and prints a warning) if the file is missing or empty.
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
            if not url or url.lower() == 'instagram_url':
                continue
            urls.add(url)

    print(f"Loaded {len(urls)} shop URL(s) from {csv_path}\n")
    return urls


def _chunks(items, size):
    items = list(items)
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _get_paginated(params):
    """
    GETs scraper_results with pagination (Range header) and retries.
    Retries on dropped connections, timeouts and 5xx responses with
    exponential backoff. Returns the combined list of rows.
    """
    rows = []
    offset = 0
    while True:
        headers = dict(supabase_headers)
        headers['Range-Unit'] = 'items'
        headers['Range'] = f'{offset}-{offset + PAGE_SIZE - 1}'

        page = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = requests.get(
                    f'{SUPABASE_URL}/rest/v1/scraper_results',
                    headers=headers,
                    params=params,
                    timeout=REQUEST_TIMEOUT
                )
                if response.status_code >= 500:
                    raise requests.exceptions.HTTPError(
                        f"{response.status_code} {response.text[:200]}")
                if not response.ok:
                    print(f"✗ Fetch error: {response.status_code} {response.text}\n")
                    response.raise_for_status()
                page = response.json()
                break
            except (requests.exceptions.ChunkedEncodingError,
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.HTTPError) as e:
                if attempt == MAX_RETRIES:
                    print(f"✗ Giving up after {MAX_RETRIES} attempts: {e}\n")
                    raise
                wait = 2 ** attempt
                print(f"  ⚠ Attempt {attempt} failed ({type(e).__name__}); retrying in {wait}s...")
                time.sleep(wait)

        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def fetch_latest_row_ids(allowed_urls):
    """
    Step 1 (lightweight): fetch only id, instagram_url, date_added (NO products_json)
    for the given shops, in chunks of URL_CHUNK_SIZE. Then keep the newest row
    per shop by date_added.
    Returns: dict {instagram_url: {'id': ..., 'date_added': ...}}
    """
    latest = {}
    for url_chunk in _chunks(sorted(allowed_urls), URL_CHUNK_SIZE):
        quoted = ','.join(f'"{u}"' for u in url_chunk)
        params = {
            'select': 'id,instagram_url,date_added',
            'products_json': 'not.is.null',
            'instagram_url': f'in.({quoted})',
            'order': 'id.asc'  # stable ordering for pagination
        }
        for row in _get_paginated(params):
            shop = row.get('instagram_url')
            if not shop:
                continue
            existing = latest.get(shop)
            if existing is None or (row.get('date_added') or '') > (existing.get('date_added') or ''):
                latest[shop] = {'id': row['id'], 'date_added': row.get('date_added')}
    return latest


def _fetch_id_chunk(id_chunk):
    """
    Fetches products_json for a list of ids. If the request fails (timeout,
    truncated response), splits the chunk in half and retries each half,
    down to a single id. A single id that still fails is skipped with a warning.
    """
    params = {
        'select': 'id,instagram_url,date_added,products_json',
        'id': f'in.({",".join(str(i) for i in id_chunk)})'
    }
    try:
        return _get_paginated(params)
    except (requests.exceptions.RequestException, ValueError) as e:
        if len(id_chunk) == 1:
            print(f"  ✗ Skipping id={id_chunk[0]}, could not fetch products_json: {type(e).__name__}")
            return []
        mid = len(id_chunk) // 2
        print(f"  ! Chunk of {len(id_chunk)} failed, splitting...")
        return _fetch_id_chunk(id_chunk[:mid]) + _fetch_id_chunk(id_chunk[mid:])


def fetch_products_json_for_ids(ids):
    """
    Step 2 (heavy): fetch id, instagram_url, date_added, products_json for
    just the given row ids, ID_CHUNK_SIZE at a time (auto-splitting on failure).
    """
    rows = []
    for id_chunk in _chunks(ids, ID_CHUNK_SIZE):
        rows.extend(_fetch_id_chunk(id_chunk))
        print(f"  Fetched products_json for {len(rows)}/{len(ids)} row(s)")
    return rows


def fetch_scraper_results_with_products(allowed_urls):
    """
    Returns one scraper_results row per shop (the most recent scrape that has
    products_json), using the two-step approach so old blobs are never read.
    """
    if not allowed_urls:
        return []

    latest = fetch_latest_row_ids(allowed_urls)
    ids = [v['id'] for v in latest.values()]
    missing = len(allowed_urls) - len(latest)
    print(f"Resolved latest row for {len(latest)} shop(s) ({missing} listed shop(s) had no match)\n")

    if not ids:
        return []
    return fetch_products_json_for_ids(ids)


def clear_scraper_products(scraper_result_id=None):
    """
    Deletes rows from scraper_products.
    - scraper_result_id given: only that shop's products.
    - None: every row (id > 0 matches all, since PostgREST requires a filter).
    """
    if scraper_result_id is not None:
        params = {'scraper_result_id': f'eq.{scraper_result_id}'}
    else:
        params = {'id': 'gt.0'}

    response = requests.delete(
        f'{SUPABASE_URL}/rest/v1/scraper_products',
        headers=supabase_headers,
        params=params,
        timeout=REQUEST_TIMEOUT
    )
    if response.status_code in (200, 204):
        scope = f"result id={scraper_result_id}" if scraper_result_id is not None else "all rows"
        print(f"✓ Cleared existing scraper_products rows ({scope})\n")
    else:
        print(f"✗ Clear error: {response.status_code} {response.text}\n")
        response.raise_for_status()


def insert_products_batch(rows):
    """Bulk inserts a shop's product rows in one POST. No-op if rows is empty."""
    if not rows:
        return
    response = requests.post(
        f'{SUPABASE_URL}/rest/v1/scraper_products',
        headers=supabase_headers,
        json=rows,
        timeout=REQUEST_TIMEOUT
    )
    if response.status_code == 201:
        print(f"  ✓ Inserted {len(rows)} product row(s)")
    else:
        print(f"  ✗ Insert error: {response.status_code} {response.text}")


def process_products_to_supabase(csv_path=INSTAGRAM_URLS_CSV):
    """
    Full refresh of scraper_products, scoped to the shops in instagram_urls.csv.
    1. Load allowed shop URLs.
    2. Fetch the latest scraper_results row per shop (two-step, chunked).
       This happens BEFORE clearing, so a failed fetch no longer empties the table.
    3. Clear scraper_products.
    4. Parse each row's products_json, map fields, and bulk insert per shop.
    """
    allowed_urls = load_shop_urls_from_csv(csv_path)
    if not allowed_urls:
        print("✗ No shop URLs loaded — aborting so we don't wipe scraper_products for nothing.\n")
        return

    results = fetch_scraper_results_with_products(allowed_urls)
    print(f"Found {len(results)} scraper_results row(s) with products_json for the listed shops\n")

    if not results:
        print("✗ Nothing fetched — aborting so we don't wipe scraper_products for nothing.\n")
        return

    clear_scraper_products()

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

        product_rows = [{
            'scraper_result_id': result_id,
            'product_title': p.get('product_title', ''),
            'product_description': p.get('product_description', ''),
            'price': p.get('price', ''),
            'product_url': p.get('product_url', ''),
            'product_image_src': p.get('src', '')
        } for p in products]

        insert_products_batch(product_rows)

    print("\n✓ Done populating scraper_products")


if __name__ == '__main__':
    process_products_to_supabase()