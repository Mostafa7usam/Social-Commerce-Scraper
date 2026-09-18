import json
import requests

from product_extractor import (
    SUPABASE_URL,
    supabase_headers,
    clear_scraper_products,
    insert_products_batch
)

# Set this to the instagram_url of the shop you want to test
TEST_INSTAGRAM_URL = "https://www.instagram.com/haxel.me/"

# If True, only prints what WOULD be inserted (no writes to Supabase)
DRY_RUN = False


def fetch_single_scraper_result(instagram_url):
    """
    GETs scraper_results filtered to a single instagram_url, sorted by
    date_added descending, limited to 1 row — i.e. the most recent scrape
    for that one shop. Returns that row as a dict, or None if no match.
    Unlike fetch_scraper_results_with_products() in populate_scraper_products.py
    (which fetches + dedupes ALL shops), this targets exactly one shop for testing.
    """
    response = requests.get(
        f'{SUPABASE_URL}/rest/v1/scraper_results',
        headers=supabase_headers,
        params={
            'select': 'id,instagram_url,date_added,products_json',
            'instagram_url': f'eq.{instagram_url}',
            'order': 'date_added.desc',
            'limit': 1
        }
    )
    response.raise_for_status()
    rows = response.json()
    return rows[0] if rows else None


def main():
    """
    Test entry point — runs the same logic as process_products_to_supabase()
    but scoped to one shop, so you can verify correctness safely.
    Step 1: Fetch the latest scraper_results row for TEST_INSTAGRAM_URL.
    Step 2: Parse its products_json into a list of product dicts.
    Step 3: Map each product's fields onto the scraper_products column names
            (same mapping used in populate_scraper_products.py).
    Step 4: Print a preview of the first 3 rows that would be inserted.
    Step 5: If DRY_RUN is True, stop here — nothing is written to Supabase.
            If DRY_RUN is False, delete only this shop's existing rows in
            scraper_products (via clear_scraper_products(scraper_result_id=...))
            and insert the fresh ones (via insert_products_batch()).
    """
    print(f"Fetching latest scraper_results row for: {TEST_INSTAGRAM_URL}\n")
    row = fetch_single_scraper_result(TEST_INSTAGRAM_URL)

    if not row:
        print("No matching row found. Check TEST_INSTAGRAM_URL matches exactly what's in Supabase.")
        return

    result_id = row.get('id')
    raw_json = row.get('products_json')
    print(f"Found result id={result_id}, date_added={row.get('date_added')}")

    if not raw_json:
        print("This row has no products_json — nothing to test.")
        return

    try:
        products = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
    except (json.JSONDecodeError, TypeError) as e:
        print(f"✗ Bad JSON: {e}")
        return

    print(f"Parsed {len(products)} product(s)\n")

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

    print("Preview of first 3 rows that would be inserted:")
    for row in product_rows[:3]:
        print(json.dumps(row, indent=2))
        print("-" * 40)

    if DRY_RUN:
        print("\nDRY_RUN is True — nothing was written to Supabase.")
        print("Set DRY_RUN = False to actually insert these rows.")
    else:
        clear_scraper_products(scraper_result_id=result_id)
        insert_products_batch(product_rows)


if __name__ == '__main__':
    main()