"""
Vendor Search, without HTTP: one request item in, up to 3 German vendor items out.

  start(board_id, item_id)   background thread (the search takes minutes; monday's call does not wait)
  run(board_id, item_id)     the whole run - returns its summary

The request's Search Source shows the progress: "AI Bot" while the bot works,
then "Research Completed" or "Manual research" (none found, or the search
failed). The code never moves the request: where it goes is up to the board's
own automations.

When vendors are found, the best one is written into the request item itself;
the others are created as new items in group 2. Every vendor row is named after the product, with Search Source
"Research Completed" and the company in Legal Company Name - so no empty
request row is left on the board.
"""
import concurrent.futures
import contextvars
import logging
import threading
import time

from . import mapping, matching, monday, research, settings

log = logging.getLogger('vendor_search')

# Requests being searched in this process: a second trigger for one of them is ignored.
_running = set()
_running_lock = threading.Lock()


def start(board_id, item_id):
    """Runs the search on a background thread, carrying the request's log context into it."""
    context = contextvars.copy_context()
    threading.Thread(target=context.run, args=(run, board_id, item_id), daemon=True).start()


def _ids(board_id, item_id, **fields):
    return {'payload': {'board_id': str(board_id), 'item_id': str(item_id), **fields}}


def _ignored(board_id, item_id, reason):
    log.info(f'Vendor search ignored item {item_id}: {reason}', extra=_ids(board_id, item_id, ignored=reason))
    return {'result': 'ignored', 'reason': reason}


def run(board_id, item_id):
    board_id, item_id = int(board_id), int(item_id)
    if board_id not in settings.BOARDS:
        return _ignored(board_id, item_id, f'board {board_id} is not set up for Vendor Search')

    try:
        request = monday.read_request(item_id)
    except Exception as error:  # noqa: BLE001 - logged; there is nothing to mark
        log.error(f'Vendor search could not read item {item_id}: {error}', extra=_ids(board_id, item_id))
        return {'result': 'error', 'reason': str(error)}

    if request is None:
        return _ignored(board_id, item_id, 'item not found')
    if request['group_id'] != settings.REQUEST_GROUP_ID:
        return _ignored(board_id, item_id, f"not in the Vendor Search group (group {request['group_id']})")
    if request['search_source']:
        return _ignored(board_id, item_id, f"Search Source is already \"{request['search_source']}\"")

    with _running_lock:
        if item_id in _running:
            return _ignored(board_id, item_id, 'already being searched')
        _running.add(item_id)

    started = time.monotonic()
    summary = {'product': request['name'].strip()}
    try:
        monday.set_search_source(board_id, item_id, settings.AI_BOT)
        try:
            summary.update(_search(board_id, item_id, summary['product']))
        except Exception as error:  # noqa: BLE001 - the request must not stay on "AI Bot"
            summary.update(error=str(error), created=[])
            log.error(f'Vendor search failed for item {item_id}: {error}', extra=_ids(board_id, item_id, error=str(error)))

        found = summary.get('filled_request') or summary.get('created')
        result = settings.RESEARCH_COMPLETED if found else settings.MANUAL_RESEARCH
        summary.update(result=result, seconds=round(time.monotonic() - started))
        # The request is never moved by the code: the board's own automation
        # ("Research Completed -> move to group 2") decides where it goes.
        monday.set_search_source(board_id, item_id, result)
    except Exception as error:  # noqa: BLE001 - a monday write failed; log it
        summary.update(result='error', error=str(error))
        log.error(f'Vendor search could not update item {item_id}: {error}', extra=_ids(board_id, item_id, error=str(error)))
    finally:
        with _running_lock:
            _running.discard(item_id)

    log.info(f'Vendor search done: {_describe(summary)}', extra=_ids(board_id, item_id, **summary))
    return summary


def _describe(summary):
    keys = ('product', 'same_product_labels', 'candidates', 'repeats_skipped', 'rejected', 'checked', 'verified',
            'created', 'ai_calls', 'searches', 'seconds', 'filled_request', 'result', 'error')
    return ', '.join(f'{key}={summary[key]!r}' for key in keys if key in summary)


def _search(board_id, item_id, product):
    if not product:
        return {'created': [], 'error': 'the request has no product name'}

    best, stats, label = select(board_id, product)

    created, filled = [], False
    if best:
        for index, vendor in enumerate(best):
            name = mapping.item_name(vendor)  # the company - for the log; the item is named after the product
            values = mapping.column_values(vendor, label)
            try:
                # The best vendor fills the request itself, so no empty request row is left behind.
                if index == 0 and _fill_request(board_id, item_id, name, values, stats):
                    filled = True
                    continue
                new_id, dropped = monday.create_vendor(board_id, product, values)
                created.append(new_id)
                if dropped:
                    stats.setdefault('dropped_columns', {})[new_id] = dropped
            except Exception as error:  # noqa: BLE001 - one vendor failing must not lose the others
                stats['rejected'].append(f'{name}: could not be created ({error})')
                log.error(f'Vendor "{name}" could not be created: {error}', extra=_ids(board_id, item_id))
    return {**stats, 'filled_request': filled, 'created': created}


def _fill_request(board_id, item_id, name, values, stats):
    """Writes the vendor into the request item. False (logged) when that fails - it is then created as a new item."""
    try:
        _, dropped = monday.fill_request(board_id, item_id, values)
    except Exception as error:  # noqa: BLE001 - fall back to a new item
        log.error(f'Vendor "{name}" could not be written into the request - creating it as a new item: {error}',
                  extra=_ids(board_id, item_id))
        return False
    if dropped:
        stats.setdefault('dropped_columns', {})[str(item_id)] = dropped
    return True


def select(board_id, product):
    """
    Finds, checks and ranks the vendors for a product - reads the board, writes
    nothing. Returns (best vendors, stats, the Product Categories label to write).
    The dry run uses this on its own.

    Vendors already on the board for the SAME product - however it was written
    ("Euro pallets", "europallets", "eurppallets", "Europaletten") - are never
    returned again. A vendor found for a different product may be.
    """
    stats = {'repeats_skipped': 0, 'rejected': [], 'ai_calls': 0, 'searches': 0}
    board_items = monday.board_vendors(board_id)
    same_labels = _same_product_labels(product, monday.product_labels(board_id, board_items), stats)
    existing_items = [item for item in board_items if any(lbl in same_labels for lbl in item['products'])]
    known = matching.Existing(existing_items)
    stats.update(same_product_labels=same_labels, existing=len(existing_items))
    # An existing label is reused, so one product keeps one label.
    product_label = same_labels[0] if same_labels else product.strip()

    # Step 1 - find candidates.
    candidates, searches = research.find(product, known.display)
    stats['ai_calls'] += 1
    stats.update(candidates=len(candidates), searches=searches)

    queue = []
    for candidate in candidates:
        if known.repeats(candidate.get('name'), candidate.get('website')):
            stats['repeats_skipped'] += 1
            continue
        problem = matching.candidate_problem(candidate)
        if problem:
            stats['rejected'].append(f"{candidate.get('name') or '?'}: {problem}")
            continue
        if any(matching.company_key(candidate.get('name')) == matching.company_key(q.get('name')) for q in queue):
            continue
        queue.append(candidate)

    # Step 2 - check the best ones in depth, replacing any that fail.
    verified, checked = [], 0
    while queue and len(verified) < settings.VENDORS_WANTED and checked < settings.MAX_CHECKS:
        batch_size = min(settings.VENDORS_WANTED - len(verified), settings.MAX_CHECKS - checked, len(queue))
        batch = [(checked + n, queue.pop(0)) for n in range(batch_size)]
        checked += batch_size
        for rank, candidate, vendor, searches, error in _check_all(product, batch):
            stats['ai_calls'] += 1
            stats['searches'] += searches
            who = candidate.get('name') or '?'
            if error:
                stats['rejected'].append(f'{who}: check failed ({error})')
                continue
            problem = matching.germany_problem(vendor) or matching.product_problem(vendor) or _name_problem(vendor)
            names = [mapping.item_name(vendor), vendor.get('legal_name'), candidate.get('name')]
            if not problem and known.repeats(names, vendor.get('website')):
                stats['repeats_skipped'] += 1
                continue
            if problem:
                stats['rejected'].append(f'{who}: {problem}')
                continue
            known.add(names, vendor.get('website'))
            verified.append((rank, vendor))

    stats.update(checked=checked, verified=len(verified))
    best = [vendor for _rank, vendor in sorted(verified, key=lambda pair: _rank_key(*pair))]
    return best[:settings.VENDORS_WANTED], stats, product_label


def _same_product_labels(product, labels, stats):
    """
    The board's Product Categories labels that are the same product as the request.

    Written the same apart from case, spaces and punctuation: decided in code.
    A typo, plural or translation: one short AI question (no web search). If that
    question fails, the search goes on with the code's answer only.
    """
    same = [label for label in labels if matching.same_product(label, product)]
    others = [label for label in labels if label not in same]
    if not others:
        return same
    try:
        stats['ai_calls'] += 1
        return same + research.match_product(product, others)
    except Exception as error:  # noqa: BLE001 - the search must not fail on this
        log.warning(f'Same-product check failed ({error}) - using exact matches only')
        return same


def _name_problem(vendor):
    return None if mapping.item_name(vendor) else 'no company name'


def _check_all(product, batch):
    """Deep-checks a batch at the same time. Yields (rank, candidate, vendor, searches, error) in rank order."""
    def one(candidate):
        try:
            vendor, searches = research.check(product, candidate)
            return vendor, searches, None
        except Exception as error:  # noqa: BLE001 - reported as a failed check
            return None, 0, str(error)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(batch))) as pool:
        # Each check gets its own copy of the log context (one Context cannot run in two threads).
        futures = [(rank, candidate, pool.submit(contextvars.copy_context().run, one, candidate))
                   for rank, candidate in batch]
        for rank, candidate, future in futures:
            vendor, searches, error = future.result()
            yield rank, candidate, vendor, searches, error


TYPE_ORDER = {'Manufacturer': 0, 'Distributor': 1, 'Reseller': 2}


def _rank_key(rank, vendor):
    """
    Sort key, best first, in the agreed order: exact product (all have it - checked),
    verified company data, manufacturer / distributor over reseller, established,
    reachable; then step 1's own order.
    """
    verified_data = sum((
        bool(mapping.text(vendor.get('legal_name'))),
        bool(mapping.text(vendor.get('complete_address'))),
        bool(mapping.vat_id(vendor.get('vat_id'))),
    ))
    kind = TYPE_ORDER.get(mapping.vendor_type(vendor.get('vendor_type')), 3)
    year = mapping.year_founded(vendor.get('year_founded'))
    size = mapping.employees(vendor.get('employees')) or 0
    established = sum((
        bool(year and year <= time.localtime().tm_year - 5),
        size >= 10,
        size >= 100,
        bool(mapping.url(vendor.get('website'))),
        bool(mapping.linkedin(vendor.get('linkedin'))),
    ))
    reachable = bool(mapping.email(vendor.get('company_email'))) + bool(mapping.phone(vendor.get('company_phone')))
    return (-verified_data, kind, -established, -reachable, rank)
