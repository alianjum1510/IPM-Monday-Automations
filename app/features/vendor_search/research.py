"""
The two OpenAI calls, through the Responses API with the web_search tool -
the same API Company Enrichment uses, with its own small client so the two
features never depend on each other.

  match_product(product, labels) -> [label, ...]  is it a product already on the board? (no web search)
  find(product, existing)  -> [candidate, ...]   step 1
  check(product, candidate) -> vendor dict        step 2

A rate limit, a server error, a timeout or a dropped connection is retried
(settings.RETRY_DELAYS_SECONDS). Anything else, or the last retry failing,
raises ResearchError. Without web search the answers would come from the
model's memory, so a model that rejects the tool is an error, not a fallback.
"""
import json
import logging
import re
import time

import requests

from . import prompts, settings

log = logging.getLogger('vendor_search')

RESPONSES_URL = 'https://api.openai.com/v1/responses'
RETRY_STATUSES = {408, 409, 429, 500, 502, 503, 504}

# Replaced in tests so retries do not wait.
sleep = time.sleep


class ResearchError(Exception):
    pass


def _post(prompt, web_search=True):
    body = {'model': settings.model(), 'input': prompt}
    if web_search:
        body.update(tools=[{'type': 'web_search'}], tool_choice='auto')
    res = requests.post(
        RESPONSES_URL,
        json=body,
        headers={'Authorization': f'Bearer {settings.openai_key()}', 'Content-Type': 'application/json'},
        timeout=settings.openai_timeout_seconds(),
    )
    res.raise_for_status()
    return res.json()


def ask(prompt, step, web_search=True):
    """The model's answer text, and how many web searches it made. Retries what is worth retrying."""
    delays = list(settings.RETRY_DELAYS_SECONDS)
    attempt = 0
    while True:
        attempt += 1
        try:
            data = _post(prompt, web_search)
            return extract_text(data), count_searches(data)
        except requests.RequestException as error:
            response = getattr(error, 'response', None)
            status = response.status_code if response is not None else None
            retryable = status in RETRY_STATUSES or isinstance(error, (requests.Timeout, requests.ConnectionError))
            reason = f'HTTP {status}' if status else type(error).__name__
            if retryable and delays:
                delay = delays.pop(0)
                log.warning(f'OpenAI {step}: {reason} - retry {attempt} after {delay}s',
                            extra={'payload': {'step': step, 'attempt': attempt, 'reason': reason}})
                sleep(delay)
                continue
            detail = _error_detail(response)
            raise ResearchError(f'OpenAI {step} failed after {attempt} attempt(s): {reason}{detail}') from error


def _error_detail(response):
    if response is None:
        return ''
    try:
        message = (response.json().get('error') or {}).get('message')
    except (ValueError, AttributeError):
        message = None
    return f' - {message}' if message else ''


def extract_text(data):
    output_text = (data or {}).get('output_text')
    if isinstance(output_text, str) and output_text.strip():
        return output_text
    chunks = []
    for item in (data or {}).get('output') or []:
        for part in (item or {}).get('content') or []:
            if (part or {}).get('type') == 'output_text' and part.get('text'):
                chunks.append(part['text'])
    return '\n'.join(chunks)


def count_searches(data):
    return len([item for item in (data or {}).get('output') or [] if (item or {}).get('type') == 'web_search_call'])


def parse_json(text):
    """The JSON object in the answer - bare, or inside a ``` fence, or with words around it."""
    text = str(text or '').strip()
    fenced = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    start, end = text.find('{'), text.rfind('}')
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for chunk in candidates:
        try:
            value = json.loads(chunk)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise ResearchError('the answer was not JSON')


def match_product(product, labels):
    """
    The labels among `labels` (products already on the board) that name the same
    product as the request - a typo, plural or translation of it. No web search:
    one short answer. Only labels from the list are returned.
    """
    text, _ = ask(prompts.match_prompt(product, labels), 'match', web_search=False)
    found = parse_json(text).get('matches')
    if not isinstance(found, list):
        raise ResearchError('the answer has no "matches" list')
    return [label for label in labels if label in found]


def match_job_titles(roles, titles):
    """
    {role: title} for the contacts' job titles, each matched to a title in `titles`
    (the Job Functions board) - or left out when none fits. No web search: one
    short answer. Only titles from the list are returned.
    """
    text, _ = ask(prompts.job_title_prompt(roles, titles), 'job titles', web_search=False)
    found = parse_json(text).get('matches')
    if not isinstance(found, dict):
        raise ResearchError('the answer has no "matches" object')
    return {role: found[role] for role in roles if found.get(role) in titles}


def find(product, existing):
    """Step 1: up to settings.MAX_CANDIDATES candidates, best first. Returns (candidates, searches)."""
    text, searches = ask(prompts.find_prompt(product, existing), 'find')
    found = parse_json(text).get('candidates')
    if not isinstance(found, list):
        raise ResearchError('the answer has no "candidates" list')
    candidates = [c for c in found if isinstance(c, dict)][:settings.MAX_CANDIDATES]
    return candidates, searches


def check(product, candidate):
    """Step 2: one candidate verified in depth. Returns (vendor, searches)."""
    text, searches = ask(prompts.check_prompt(product, candidate), 'check')
    return parse_json(text), searches
