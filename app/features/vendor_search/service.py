"""
Vendor Search, without HTTP: one request item in, up to 3 German vendor items out.

  start(board_id, item_id)   background thread (the search takes minutes; monday's call does not wait)
  run(board_id, item_id)     the whole run - returns its summary

The request's Search Source shows the progress: "AI Bot" while the bot works,
then "Research Completed" or "Manual research" (none found, or the search
failed). The code never moves the request: where it goes is up to the board's
own automations.

When vendors are found, the best one is written into the request item itself
(which is renamed from the product to the vendor); the others are created as new
items in group 1 and moved to group 2. Every vendor row is named after the vendor, with the product
in Name of Product and Search Source "Research Completed" - so no empty
request row is left on the board. Nothing found: the request keeps the product name.
"""
import concurrent.futures
import contextvars
import logging
import threading
import time

from . import mapping, matching, monday, pages, research, settings

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
    keys = ('product', 'same_product_labels', 'rounds', 'candidates', 'repeats_skipped', 'rejected', 'checked',
            'verified', 'created', 'product_category', 'product_category_by_ai', 'product_category_new',
            'catalogues', 'job_functions', 'ai_calls', 'searches', 'seconds', 'filled_request', 'result',
            'error')
    return ', '.join(f'{key}={summary[key]!r}' for key in keys if key in summary)


def _search(board_id, item_id, product):
    if not product:
        return {'created': [], 'error': 'the request has no product name'}

    best, stats, label = select(board_id, product)

    created, filled = [], False
    job_ids = _job_functions(best, stats)
    category, picked_by_ai = _product_category(board_id, item_id, product, stats) if best else ([], False)
    if best:
        for index, vendor in enumerate(best):
            name = mapping.item_name(vendor)  # the vendor's company name - the item's name
            values = mapping.column_values(vendor, label, job_ids.get(mapping.contact(vendor)[1]))
            with_category = {**values, settings.PRODUCT_CATEGORY: {'labels': category}} if category else values
            try:
                # The best vendor fills the request itself, so no empty request row is left behind.
                # The request gets the category only when the AI picked it (else it has its own).
                if index == 0 and _fill_request(board_id, item_id, name,
                                                 with_category if picked_by_ai else values, stats):
                    filled = True
                    _add_catalogue(board_id, item_id, vendor, name, stats, keep_existing=True)
                    continue
                new_id, dropped = monday.create_vendor(board_id, name, with_category)
                created.append(new_id)
                _add_catalogue(board_id, new_id, vendor, name, stats)
                if dropped:
                    stats.setdefault('dropped_columns', {})[new_id] = dropped
            except Exception as error:  # noqa: BLE001 - one vendor failing must not lose the others
                stats['rejected'].append(f'{name}: could not be created ({error})')
                log.error(f'Vendor "{name}" could not be created: {error}', extra=_ids(board_id, item_id))
    return {**stats, 'filled_request': filled, 'created': created}


def _add_catalogue(board_id, item_id, vendor, name, stats, keep_existing=False):
    """
    The vendor's catalogue link into Catalogue / Documents. No catalogue: the column
    stays empty. keep_existing (the request row): only when the column is empty, so a
    file someone attached by hand is never replaced. A failure is logged - the vendor
    row itself is already written.
    """
    link = mapping.catalogue(vendor)
    if not link:
        return
    try:
        if keep_existing and monday.has_files(item_id):
            return
        monday.add_catalogue(board_id, item_id, link, f'Catalogue - {name}')
        stats['catalogues'] = stats.get('catalogues', 0) + 1
    except Exception as error:  # noqa: BLE001
        log.warning(f'Catalogue link for "{name}" not added ({error})', extra=_ids(board_id, item_id))


def _product_category(board_id, item_id, product, stats):
    """
    (Product Category labels for every vendor row, picked by the AI?).

    The request's own category (from the purchase requirement) when it has one -
    read when the vendors are written, not at the start, so a category set during
    the search is included. Otherwise the AI picks one of the column's options for
    the product, or names a new broad category when none fits (one short question,
    no web search). ([], False) when neither works: the vendors are then written
    without a category.
    """
    try:
        category = monday.request_category(item_id)
    except Exception as error:  # noqa: BLE001 - unknown: never overwrite what the request may have
        log.warning(f'Product Category of the request not read ({error}) - vendors written without one')
        return [], False
    if category:
        category = category[:1]  # one category per vendor row, also when the request has several
        stats['product_category'] = category
        return category, False
    try:
        labels = monday.category_labels(board_id)
        if not labels:
            return [], False
        stats['ai_calls'] += 1
        picked, new = research.pick_category(product, labels)
    except Exception as error:  # noqa: BLE001 - the vendors are written without a category
        log.warning(f'Product Category not picked ({error}) - vendors written without one')
        return [], False
    if not picked:
        return [], False
    # A new category is created on the board when the vendors are written (create_labels_if_missing).
    stats.update(product_category=[picked], product_category_by_ai=True, product_category_new=new)
    return [picked], True


def _job_functions(best, stats):
    """
    {contact job title: Job Functions item id} for the vendors' contacts. Written
    the same as a title on that board: matched in code. Otherwise (another language,
    another wording): one short AI question, no web search. A title with no match
    is left out - the Job Functions column then stays empty. A failure here never
    stops the vendors being written.
    """
    roles = list(dict.fromkeys(role for role in (mapping.contact(vendor)[1] for vendor in best) if role))
    if not roles:
        return {}
    try:
        titles = monday.job_function_titles()
        by_key = {matching._fold(title): title for title in titles}
        matched = {role: by_key[matching._fold(role)] for role in roles if matching._fold(role) in by_key}
        others = [role for role in roles if role not in matched]
        if others:
            stats['ai_calls'] += 1
            matched.update(research.match_job_titles(others, list(titles)))
    except Exception as error:  # noqa: BLE001 - the vendors are written without Job Functions
        log.warning(f'Job functions not matched ({error}) - written without them')
        return {}
    stats['job_functions'] = matched
    return {role: titles[title] for role, title in matched.items()}


def _fill_request(board_id, item_id, name, values, stats):
    """
    Writes the vendor into the request item and renames it to the vendor.
    False (logged) when that fails - it is then created as a new item.
    """
    try:
        _, dropped = monday.fill_request(board_id, item_id, values, name)
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
    nothing. Returns (best vendors, stats, the product name to write).
    The dry run uses this on its own.

    Vendors already on the board for the SAME product - however it was written
    ("Euro pallets", "europallets", "eurppallets", "Europaletten") - are never
    returned again. A vendor found for a different product may be.
    """
    stats = {'repeats_skipped': 0, 'rejected': [], 'ai_calls': 0, 'searches': 0}
    board_items = monday.board_vendors(board_id)
    same_labels = _same_product_labels(product, monday.product_names(board_items), stats)
    existing_items = [item for item in board_items if any(lbl in same_labels for lbl in item['products'])]
    known = matching.Existing(existing_items)
    stats.update(same_product_labels=same_labels, existing=len(existing_items))
    # An existing label is reused, so one product keeps one label.
    product_label = same_labels[0] if same_labels else product.strip()

    stats.update(candidates=0, rounds=0)
    tried = []      # every candidate step 1 named: a 2nd round must not name them again
    tried_keys = set()
    verified, checked = [], 0
    while (len(verified) < settings.VENDORS_WANTED and checked < settings.MAX_CHECKS
           and stats['rounds'] < settings.FIND_ROUNDS):
        # Step 1 - find candidates. The 2nd round is only for a request the 1st left short of 3.
        try:
            candidates, searches = research.find(product, known.display + tried)
        except Exception as error:  # noqa: BLE001
            if not stats['rounds']:
                raise   # nothing found at all: the request goes to "Manual research"
            log.warning(f'Second search round failed ({error}) - keeping the {len(verified)} vendors found')
            break
        stats['rounds'] += 1
        stats['ai_calls'] += 1
        stats['candidates'] += len(candidates)
        stats['searches'] += searches
        queue = _new_candidates(candidates, known, tried, tried_keys, stats)
        if not queue:
            break

        # Step 2 - check the best ones in depth, replacing any that fail.
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
                problem = (matching.germany_problem(vendor) or matching.product_problem(vendor)
                           or _name_problem(vendor) or pages.product_page_problem(vendor, product))
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


def _new_candidates(candidates, known, tried, tried_keys, stats):
    """The candidates worth a deep check, in step 1's order: not on the board, not tried before, plausible."""
    queue = []
    for candidate in candidates:
        key = matching.company_key(candidate.get('name'))
        if key in tried_keys:
            continue    # named again (this round or an earlier one)
        if key:
            tried_keys.add(key)
            tried.append({'name': str(candidate.get('name')), 'website': str(candidate.get('website') or '')})
        if known.repeats(candidate.get('name'), candidate.get('website')):
            stats['repeats_skipped'] += 1
            continue
        problem = matching.candidate_problem(candidate)
        if problem:
            stats['rejected'].append(f"{candidate.get('name') or '?'}: {problem}")
            continue
        queue.append(candidate)
    return queue


def _same_product_labels(product, labels, stats):
    """
    The product names on the board that are the same product as the request.

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
    size = mapping.company_size(vendor) or 0
    established = sum((
        bool(year and year <= time.localtime().tm_year - 5),
        size >= 10,
        size >= 100,
        bool(mapping.url(vendor.get('website'))),
        bool(mapping.linkedin(vendor.get('linkedin'))),
    ))
    reachable = bool(mapping.email(vendor.get('company_email'))) + bool(mapping.phone(vendor.get('company_phone')))
    return (-verified_data, kind, -established, -reachable, rank)
