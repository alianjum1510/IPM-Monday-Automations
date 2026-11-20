import json
from types import SimpleNamespace

import pytest
import requests

from app.features.vendor_search import monday, prompts, research, settings

from .conftest import BOARD, vendor


# ---- research -------------------------------------------------------------------------------

def http_error(status, message='x'):
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps({'error': {'message': message}}).encode()
    return requests.HTTPError(response=response)


@pytest.fixture
def no_wait(monkeypatch):
    waits = []
    monkeypatch.setattr(research, 'sleep', waits.append)
    return waits


def answering(*outcomes):
    """A fake _post that raises or returns each outcome in turn."""
    calls = []

    def post(prompt, web_search=True):
        outcome = outcomes[len(calls)]
        calls.append(prompt)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    post.calls = calls
    return post


def test_the_request_uses_web_search_and_the_configured_model(monkeypatch):
    sent = {}

    def fake_post(url, json, headers, timeout):
        sent.update(url=url, json=json, headers=headers)
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"output_text": "{}"}'
        return response

    monkeypatch.setenv('VENDOR_SEARCH_MODEL', 'test-model')
    monkeypatch.setattr(research.requests, 'post', fake_post)
    research.ask('prompt', 'find')
    assert sent['json']['tools'] == [{'type': 'web_search'}]
    assert sent['json']['model'] == 'test-model'
    assert sent['headers']['Authorization'] == 'Bearer test-openai-key'


def test_the_model_falls_back_to_the_enrichment_model(monkeypatch):
    monkeypatch.delenv('VENDOR_SEARCH_MODEL', raising=False)
    monkeypatch.setenv('OPENAI_MODEL', 'enrichment-model')
    assert settings.model() == 'enrichment-model'


@pytest.mark.parametrize('error', [http_error(429), http_error(500), http_error(503), requests.Timeout(),
                                   requests.ConnectionError()])
def test_temporary_failures_are_retried(monkeypatch, no_wait, error):
    post = answering(error, error, {'output_text': '{"candidates": []}'})
    monkeypatch.setattr(research, '_post', post)
    assert research.find('iPhone', []) == ([], 0)
    assert no_wait == [2, 5]


def test_three_retries_then_it_gives_up(monkeypatch, no_wait):
    monkeypatch.setattr(research, '_post', answering(*[http_error(429)] * 4))
    with pytest.raises(research.ResearchError, match='after 4 attempt'):
        research.find('iPhone', [])
    assert no_wait == [2, 5, 10]


def test_a_bad_request_is_not_retried(monkeypatch, no_wait):
    monkeypatch.setattr(research, '_post', answering(http_error(400, 'web_search not supported')))
    with pytest.raises(research.ResearchError, match='HTTP 400 - web_search not supported'):
        research.find('iPhone', [])
    assert no_wait == []


@pytest.mark.parametrize('text', [
    '{"candidates": [{"name": "A"}]}',
    'Here you go:\n```json\n{"candidates": [{"name": "A"}]}\n```',
    'Result: {"candidates": [{"name": "A"}]} - done',
])
def test_the_answer_is_read_with_or_without_a_fence(monkeypatch, text):
    monkeypatch.setattr(research, '_post', answering({'output_text': text, 'output': [{'type': 'web_search_call'}]}))
    assert research.find('iPhone', []) == ([{'name': 'A'}], 1)


def test_an_answer_that_is_not_json_is_an_error(monkeypatch):
    monkeypatch.setattr(research, '_post', answering({'output_text': 'Sorry, I cannot help.'}))
    with pytest.raises(research.ResearchError, match='not JSON'):
        research.find('iPhone', [])


def test_step_one_is_capped_at_ten_candidates(monkeypatch):
    many = {'candidates': [{'name': f'V{n}'} for n in range(15)] + ['not a dict']}
    monkeypatch.setattr(research, '_post', answering({'output_text': json.dumps(many)}))
    candidates, _ = research.find('iPhone', [])
    assert len(candidates) == 10


def test_text_is_read_from_output_parts_when_output_text_is_missing():
    data = {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '{"a": 1}'}]}]}
    assert research.extract_text(data) == '{"a": 1}'


def test_prompts_name_the_product_the_area_and_the_known_vendors():
    find = prompts.find_prompt('iPhone', [{'name': 'Tech World', 'website': 'tech-world.de'}])
    assert 'PRODUCT: iPhone' in find
    assert '- Tech World (tech-world.de)' in find
    check = prompts.check_prompt('iPhone', {'name': 'A', 'website': 'https://a.de'})
    assert '"name": "A"' in check
    assert 'Bundesweit' in check and 'Thüringen' in check
    assert 'Never guess' in check
    assert 'site:linkedin.com/company' in check, 'tells the model where to find LinkedIn'
    assert 'northdata.de' in check and 'employees_source_url' in check, 'where to find employees, with the source'
    for example in ('51-200', 'DE123456789', '"employees": 250', '1990'):
        assert example not in check, f'no example value the model could copy: {example}'
    assert '"product_terms"' in check and "company's own website" in check.lower()
    assert '"contact_person_role"' in check and 'without the job title' in check


# ---- monday ---------------------------------------------------------------------------------

@pytest.fixture
def created(monkeypatch):
    """create_vendor's calls: `attempts` holds the values each try sent; `rejections` the errors to answer, per try."""
    calls = SimpleNamespace(attempts=[], rejections=[])

    def graphql(query, variables):
        if 'move_item_to_group' in query:
            return {'move_item_to_group': {'id': variables['itemId']}}
        calls.attempts.append(json.loads(variables['values']))
        errors = calls.rejections.pop(0) if calls.rejections else None
        if errors:
            raise monday.MondayError(errors)
        return {'create_item': {'id': '7'}}

    monkeypatch.setattr(monday, 'graphql', graphql)
    return calls


def column_error(column_id):
    return [{'message': 'invalid', 'extensions': {'code': 'ColumnValueException',
                                                  'error_data': {'column_id': column_id}}}]


def test_a_rejected_column_is_dropped_and_the_item_retried(created):
    from app.features.vendor_search import mapping
    values = mapping.column_values(vendor('A'), 'iPhone')
    created.rejections = [column_error(settings.COMPANY_EMAIL)]

    item_id, dropped = monday.create_vendor(BOARD, 'A', values)

    assert item_id == '7'
    assert dropped == [settings.COMPANY_EMAIL]
    assert settings.COMPANY_EMAIL not in created.attempts[1]
    assert len(created.attempts[1]) == len(values) - 1


def test_a_rejection_naming_no_column_retries_with_the_core_columns(created):
    """What monday did to Company Enrichment's email: error_data was empty."""
    from app.features.vendor_search import mapping
    values = mapping.column_values(vendor('A'), 'iPhone')
    created.rejections = [[{'message': 'email is not valid', 'extensions': {'error_data': {}}}]]

    item_id, _ = monday.create_vendor(BOARD, 'A', values)

    assert item_id == '7'
    assert set(created.attempts[1]) == set(settings.CORE_COLUMNS)
    assert created.attempts[1][settings.SEARCH_SOURCE] == {'label': 'Research Completed'}


def test_search_source_is_never_dropped(created):
    created.rejections = [column_error(settings.SEARCH_SOURCE)]
    with pytest.raises(monday.MondayError):
        monday.create_vendor(BOARD, 'A', {settings.SEARCH_SOURCE: {'label': 'AI Bot'}})
    assert len(created.attempts) == 1


def test_items_are_created_in_group_1_then_moved_to_group_2_with_new_labels_allowed(monkeypatch):
    sent = []

    def graphql(query, variables):
        sent.append((query, variables))
        if 'move_item_to_group' in query:
            return {'move_item_to_group': {'id': variables['itemId']}}
        return {'create_item': {'id': '9'}}

    monkeypatch.setattr(monday, 'graphql', graphql)
    monday.create_vendor(BOARD, 'A', {settings.SEARCH_SOURCE: {'label': 'AI Bot'}})
    (create, created_with), (move, moved_with) = sent
    assert 'create_item' in create and 'create_labels_if_missing: true' in create
    assert created_with['groupId'] == 'topics'
    assert 'move_item_to_group' in move and moved_with == {'itemId': '9', 'groupId': 'new_group'}


def test_a_failed_move_keeps_the_created_item(monkeypatch):
    def graphql(query, variables):
        if 'move_item_to_group' in query:
            raise monday.MondayError([{'message': 'boom'}])
        return {'create_item': {'id': '9'}}

    monkeypatch.setattr(monday, 'graphql', graphql)
    assert monday.create_vendor(BOARD, 'A', {settings.SEARCH_SOURCE: {'label': 'AI Bot'}}) == ('9', [])


def test_the_request_is_filled_in_place_with_the_same_column_retry(monkeypatch):
    sent = []

    def graphql(query, variables):
        sent.append((query, variables))
        if len(sent) == 1:
            raise monday.MondayError(column_error(settings.COMPANY_EMAIL))
        return {'change_multiple_column_values': {'id': variables['itemId']}}

    monkeypatch.setattr(monday, 'graphql', graphql)
    values = {settings.SEARCH_SOURCE: {'label': 'Research Completed'}, settings.COMPANY_EMAIL: {'email': 'x'}}

    item_id, dropped = monday.fill_request(BOARD, 100, values)

    assert item_id == '100' and dropped == [settings.COMPANY_EMAIL]
    query, variables = sent[-1]
    assert 'change_multiple_column_values' in query and 'create_labels_if_missing: true' in query
    assert variables['itemId'] == '100'
    assert settings.COMPANY_EMAIL not in json.loads(variables['values'])


def test_dropdown_labels_are_read_from_both_settings_formats():
    assert monday._dropdown_labels(json.dumps({'labels': [{'id': 1, 'name': 'iPhone'}]})) == ['iPhone']
    assert monday._dropdown_labels(json.dumps({'labels': {'1': 'iPhone'}})) == ['iPhone']
    assert monday._dropdown_labels('not json') == []


def test_monday_errors_raise_with_the_errors_kept(monkeypatch):
    def fake_post(url, json, headers, timeout):
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"errors": [{"message": "bad", "extensions": {"error_data": {"column_id": "x"}}}]}'
        return response

    monkeypatch.setattr(monday.requests, 'post', fake_post)
    with pytest.raises(monday.MondayError) as raised:
        monday.graphql('query { me { id } }', {})
    assert monday._rejected_column(raised.value) == 'x'


def test_filling_the_request_renames_it_and_the_name_survives_the_core_column_retry(monkeypatch):
    sent = []

    def graphql(query, variables):
        sent.append(json.loads(variables['values']))
        if len(sent) == 1:
            raise monday.MondayError([{'message': 'email is not valid', 'extensions': {'error_data': {}}}])
        return {'change_multiple_column_values': {'id': variables['itemId']}}

    monkeypatch.setattr(monday, 'graphql', graphql)
    from app.features.vendor_search import mapping
    monday.fill_request(BOARD, 100, mapping.column_values(vendor('A'), 'iPhone'), 'A')

    assert sent[0]['name'] == 'A'
    assert sent[1]['name'] == 'A'
    assert set(sent[1]) == set(settings.CORE_COLUMNS) | {'name'}
