"""
Dry run: the real search for a product, printed - nothing is written to monday.

Reads the board (to skip vendors already there), calls OpenAI for real (this
costs the same as a real run: usually 4 calls), and prints the vendor items it
WOULD create, column by column. No item is created and no status is changed.

  MONDAY_API_TOKEN=... OPENAI_API_KEY=... python -m app.features.vendor_search.dry_run "iPhone"
  ... python -m app.features.vendor_search.dry_run "iPhone" --board 5107912125
"""
import argparse
import json
import logging
import sys
import time

from . import mapping, service, settings


def main(argv=None):
    parser = argparse.ArgumentParser(description='Vendor Search dry run - writes nothing to monday.')
    parser.add_argument('product', help='the product, as it would be typed as the request name')
    parser.add_argument('--board', type=int, default=next(iter(settings.BOARDS)), help='board id to read')
    args = parser.parse_args(argv)

    missing = [key for key, value in (('MONDAY_API_TOKEN', settings.monday_token()),
                                      ('OPENAI_API_KEY', settings.openai_key())) if not value]
    if missing:
        sys.exit(f'Set {", ".join(missing)} first.')

    logging.basicConfig(level=logging.INFO, format='%(message)s')
    print(f'Dry run: product "{args.product}", board {args.board}, model {settings.model()} - nothing is written.\n')

    started = time.monotonic()
    best, stats, label = service.select(args.board, args.product.strip())

    for number, vendor in enumerate(best, 1):
        print(f'--- Vendor {number}: {mapping.item_name(vendor)} ---')
        print(f"  product page: {vendor.get('product_evidence_url')}")
        print(f"  address source: {vendor.get('address_source_url')}")
        for column, value in mapping.column_values(vendor, label).items():
            print(f'  {column}: {json.dumps(value, ensure_ascii=False)}')
        print()

    result = settings.RESEARCH_COMPLETED if best else settings.MANUAL_RESEARCH
    print(f'Request would be set to: {result}')
    print(f'Seconds: {round(time.monotonic() - started)}')
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
