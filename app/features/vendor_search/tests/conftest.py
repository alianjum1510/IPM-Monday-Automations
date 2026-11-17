"""
Vendor Search with monday and OpenAI replaced by in-memory fakes - nothing here
reaches a real board or the OpenAI API.

  board  FakeBoard: the Vendor Mining Board's items, the mutations made to it
  ai     FakeAI: the answers step 1 (find) and step 2 (check) give
"""
import json
import re

import pytest
from fastapi.testclient import TestClient

from app.features.vendor_search import monday, research, settings
from app.features.vendor_search.router import FEATURE
from main import create_app

BOARD = 5107912125
REQUEST_ID = 100
PATH = '/vendor-search'

# This feature alone, as the deployment serves it: proves it needs no other feature.
client = TestClient(create_app([FEATURE]))


def body(board_id=BOARD, item_id=REQUEST_ID):
    return {'payload': {'inputFields': {'boardId': board_id, 'itemId': item_id}}}


def slug(name):
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def candidate(name, **overrides):
    """A step 1 candidate."""
    return {
        'name': name,
        'website': f'https://www.{slug(name)}.de',
        'city': 'München',
        'postal_code': '80331',
        'country': 'Germany',
        'vendor_type': 'Distributor',
        'product_evidence_url': f'https://www.{slug(name)}.de/products/iphone',
        **overrides,
    }


def vendor(name, **overrides):
    """A step 2 answer that passes every check."""
    return {
        'company_name': name,
        'legal_name': f'{name} GmbH',
        'complete_address': 'Marienplatz 1, 80331 München, Germany',
        'postal_code': '80331',
        'city': 'München',
        'country_code': 'DE',
        'based_in_germany': True,
        'address_source_url': f'https://www.{slug(name)}.de/impressum',
        'sells_exact_product': True,
        'product_evidence_url': f'https://www.{slug(name)}.de/products/iphone',
        'vat_id': 'DE123456789',
        'year_founded': 1998,
        'employees': 250,
        'description': f'{name} distributes smartphones.',
        'website': f'https://www.{slug(name)}.de',
        'linkedin': f'https://www.linkedin.com/company/{slug(name)}',
        'company_email': f'info@{slug(name)}.de',
        'company_phone': '+49 89 1234567',
        'contact_person': 'Anna Schmidt, Head of Sales',
        'contact_person_phone': '089 7654321',
        'vendor_type': 'Distributor',
        'delivery_regions': ['Bundesweit'],
        'certifications': ['ISO 9001'],
        **overrides,
    }


class FakeBoard:
    """The Vendor Mining Board in memory, answering the GraphQL calls monday.py makes."""

    def __init__(self):
        self.items = {}
        self.dropdown_labels = []
        self.status_writes = []
        self.moves = []
        self.fills = []             # (item_id, values) written into an existing item
        self.created = []
        self.reject = None          # values -> list of monday errors, or None
        self.fail_status = False
        self.next_id = 1000
        self.add(REQUEST_ID, 'iPhone')

    def add(self, item_id, name, group=settings.REQUEST_GROUP_ID, search_source='', products=(), website='',
            legal_name=''):
        self.items[item_id] = {'id': item_id, 'name': name, 'group': group, 'search_source': search_source,
                               'products': list(products), 'website': website, 'legal_name': legal_name}

    def graphql(self, query, variables):
        if 'create_item' in query:
            return self._create(variables)
        if 'change_multiple_column_values' in query:
            return self._fill(variables)
        if 'move_item_to_group' in query:
            item_id = int(variables['itemId'])
            self.moves.append((item_id, variables['groupId']))
            self.items[item_id]['group'] = variables['groupId']
            return {'move_item_to_group': {'id': variables['itemId']}}
        if 'change_column_value' in query:
            if self.fail_status:
                raise monday.MondayError([{'message': 'boom'}])
            label = json.loads(variables['value'])['label']
            self.status_writes.append((int(variables['itemId']), label))
            self.items[int(variables['itemId'])]['search_source'] = label
            return {'change_column_value': {'id': variables['itemId']}}
        if 'items_page' in query:
            return {'boards': [{'items_page': {'cursor': None, 'items': [
                {'id': str(item['id']), 'name': item['name'], 'column_values': [
                    {'id': settings.PRODUCT_CATEGORIES, 'text': ', '.join(item['products'])},
                    {'id': settings.WEBSITE, 'text': item['website']},
                    {'id': settings.LEGAL_NAME, 'text': item['legal_name']},
                ]} for item in self.items.values()
            ]}}]}
        if 'settings_str' in query:
            labels = [{'id': n + 1, 'name': label} for n, label in enumerate(self.dropdown_labels)]
            return {'boards': [{'columns': [{'id': settings.PRODUCT_CATEGORIES,
                                             'settings_str': json.dumps({'labels': labels})}]}]}
        if 'items(ids' in query:
            item = self.items.get(int(variables['itemId'][0]))
            if not item:
                return {'items': []}
            return {'items': [{'id': str(item['id']), 'name': item['name'], 'board': {'id': str(BOARD)},
                               'group': {'id': item['group']},
                               'column_values': [{'id': settings.SEARCH_SOURCE, 'text': item['search_source']}]}]}
        raise AssertionError(f'unexpected query: {query}')

    def _fill(self, variables):
        values = json.loads(variables['values'])
        self._maybe_reject(values)
        item = self.items[int(variables['itemId'])]
        self.fills.append((item['id'], values))
        item.update(search_source=values.get(settings.SEARCH_SOURCE, {}).get('label', item['search_source']),
                    products=values.get(settings.PRODUCT_CATEGORIES, {}).get('labels', item['products']),
                    website=(values.get(settings.WEBSITE) or {}).get('url', item['website']),
                    legal_name=values.get(settings.LEGAL_NAME, item['legal_name']))
        return {'change_multiple_column_values': {'id': variables['itemId']}}

    def _maybe_reject(self, values):
        if self.reject:
            errors = self.reject(values)
            if errors:
                raise monday.MondayError(errors)

    def _create(self, variables):
        values = json.loads(variables['values'])
        self._maybe_reject(values)
        self.next_id += 1
        item_id = self.next_id
        self.created.append({'id': item_id, 'name': variables['name'], 'group': variables['groupId'], 'values': values})
        self.add(item_id, variables['name'], group=variables['groupId'],
                 search_source=values.get(settings.SEARCH_SOURCE, {}).get('label', ''),
                 products=values.get(settings.PRODUCT_CATEGORIES, {}).get('labels', []),
                 website=(values.get(settings.WEBSITE) or {}).get('url', ''),
                 legal_name=values.get(settings.LEGAL_NAME, ''))
        return {'create_item': {'id': str(item_id)}}

    @property
    def request_statuses(self):
        return [label for item_id, label in self.status_writes if item_id == REQUEST_ID]


FIND = 'You are a procurement researcher'
MATCH = 'A buyer asked for this product'


class FakeAI:
    """
    Answers research._post: the same-product question returns `same_products`,
    step 1 returns `candidates`, step 2 returns `vendors[name]`.
    """

    def __init__(self):
        self.candidates = []
        self.vendors = {}
        self.same_products = []     # the labels the AI calls the same product
        self.match_error = None
        self.find_error = None
        self.prompts = []
        self.web_search = []        # whether each call asked for web search

    def post(self, prompt, web_search=True):
        self.prompts.append(prompt)
        self.web_search.append(web_search)
        if prompt.startswith(MATCH):
            if self.match_error:
                raise self.match_error
            return self._answer({'matches': self.same_products})
        if prompt.startswith(FIND):
            if self.find_error:
                raise self.find_error
            return self._answer({'candidates': self.candidates})
        name = json.loads(re.search(r'COMPANY \(from an earlier search, may contain errors\): (\{.*\})', prompt)
                          .group(1))['name']
        answer = self.vendors.get(name, vendor(name))
        if isinstance(answer, Exception):
            raise answer
        return self._answer(answer)

    @staticmethod
    def _answer(value):
        return {'output_text': json.dumps(value, ensure_ascii=False), 'output': [{'type': 'web_search_call'}] * 3}

    @property
    def finds(self):
        return [p for p in self.prompts if p.startswith(FIND)]

    @property
    def matches(self):
        return [p for p in self.prompts if p.startswith(MATCH)]

    @property
    def checks(self):
        return [p for p in self.prompts if not p.startswith((FIND, MATCH))]


@pytest.fixture
def board(monkeypatch):
    fake = FakeBoard()
    monkeypatch.setattr(monday, 'graphql', fake.graphql)
    return fake


@pytest.fixture
def ai(monkeypatch):
    fake = FakeAI()
    monkeypatch.setattr(research, '_post', fake.post)
    monkeypatch.setattr(research, 'sleep', lambda seconds: None)
    return fake
