import json
import re
import time

import requests

from src.config.env import env
from src.lib.logger import log

RESPONSES_URL = 'https://api.openai.com/v1/responses'

# Matches the retry ladder the previous deployment logged: 1s, 2s, 4s.
RETRY_DELAYS_MS = [1000, 2000, 4000]


def _post(body, timeout_ms):
    """POSTs to the Responses API; an HTTP error status raises, with the response attached."""
    res = requests.post(
        RESPONSES_URL,
        json=body,
        headers={
            'Authorization': f'Bearer {env.openai.api_key}',
            'Content-Type': 'application/json',
        },
        timeout=timeout_ms / 1000,
    )
    res.raise_for_status()
    return res.json()


def _response_of(error):
    """The HTTP response an error carries. Test it with `is not None`: a 4xx/5xx Response is falsy."""
    return getattr(error, 'response', None)


def _body_of(response):
    try:
        return json.dumps(response.json())
    except ValueError:
        return json.dumps(response.text)


def research(prompt):
    """
    Runs the research prompt through the Responses API with the web_search tool.

    The prompt demands 15-20 live searches against handelsregister.de, Impressum
    pages and so on, so the tool is the point - without it the model answers from
    memory and every HIGH confidence it reports is fiction.

    Returns {'text', 'searched', 'search_count'}.
    """
    use_web_search = True
    attempt = 0

    while True:
        try:
            body = {'model': env.openai.model, 'input': prompt}
            if use_web_search:
                body.update({'tools': [{'type': 'web_search'}], 'tool_choice': 'auto'})

            data = _post(body, env.openai.timeout_ms)
            return {'text': _extract_text(data), 'searched': use_web_search, 'search_count': _count_searches(data)}
        except requests.RequestException as error:
            response = _response_of(error)
            status = response.status_code if response is not None else None
            message = _body_of(response) if response is not None else '""'

            if use_web_search and status == 400 and re.search(r'web_search|tool', message, re.IGNORECASE):
                log(f'OpenAI: model {env.openai.model} rejected the web_search tool - retrying without it')
                use_web_search = False
                attempt += 1
                continue

            if status == 429 and attempt < len(RETRY_DELAYS_MS):
                delay = RETRY_DELAYS_MS[attempt]
                log(f'OpenAI 429 — retry {attempt + 1}/{len(RETRY_DELAYS_MS)} after {delay}ms')
                time.sleep(delay / 1000)
                attempt += 1
                continue

            raise


def classify_country(address):
    """
    Which country an address is in, as an ISO code, or '' when the model cannot
    tell. For the addresses country_from_input() could not place - no country name,
    no postal prefix - so the city, postal code format and region decide it.

    One short answer and no web search: this runs before the research, on every
    such lead, and must not cost what the research costs. A failure here never
    fails the run - the research is then told to work the country out itself.
    """
    try:
        data = _post(
            {
                'model': env.openai.country_model or env.openai.model,
                'input': (
                    'Which country is this address in? Use its unique identifiers - the city, the '
                    'postal code format, the street naming, the state or region.\n\n'
                    f'Address: {address}\n\n'
                    'Reply with only the ISO 3166-1 alpha-2 code (e.g. DE), or UNKNOWN if the '
                    'address does not identify one country.'
                ),
            },
            30000,
        )

        match = re.search(r'\b[A-Z]{2}\b', _extract_text(data).strip().upper())
        code = match.group(0) if match else ''
        return '' if code == 'UN' else code
    except Exception as error:
        response = _response_of(error)
        reason = response.status_code if response is not None else error
        log(f'OpenAI: country classification failed ({reason}) - research will determine it')
        return ''


def _extract_text(data):
    output_text = (data or {}).get('output_text')
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    chunks = []
    for item in (data or {}).get('output') or []:
        for part in (item or {}).get('content') or []:
            if (part or {}).get('type') == 'output_text' and part.get('text'):
                chunks.append(part['text'])
    return '\n'.join(chunks)


def _count_searches(data):
    return len([item for item in (data or {}).get('output') or [] if (item or {}).get('type') == 'web_search_call'])
