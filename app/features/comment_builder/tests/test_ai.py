"""Write with AI, Summarize and Autofill: same requests to OpenAI, same answers and errors as the original server."""
import json

import pytest

from app.core.testing import session_auth
from app.features.comment_builder import service

from .conftest import client, post

OPTIONS = {
    'escalation': ['Yes', 'No'],
    'categories': ['W-Quote', 'W-Order', 'W-Inv', 'General'],
    'mainCategory': ['Quote', 'Order', 'Pay', 'Inv'],
    'subCategory': ['DOCS', 'TERMS', 'CREDIT'],
    'nextStep': ['Chase Payment', 'Send Proposal'],
}


def autofill_body(**extra):
    return {'comment': 'keine Mahnungen verschicken!', 'options': OPTIONS, 'today': '2026-11-02',
            'weekday': 'Monday', 'dealName': 'Muster GmbH', 'dealStage': 'Won', **extra}


# ---------- Write with AI ----------


def test_write_asks_openai_with_the_write_prompt(openai):
    openai.content = '  • Called the customer.  '
    res = post('/api/ai/write', {'prompt': ' Called Muster GmbH about the offer '})

    assert res.status_code == 200
    assert res.json() == {'text': '• Called the customer.'}
    assert openai.last == {
        'model': 'gpt-4o-mini',
        'temperature': 0.4,
        'max_tokens': 450,
        'messages': [
            {'role': 'system', 'content': service.PROMPTS['write']['system']},
            {'role': 'user', 'content': 'Called Muster GmbH about the offer'},
        ],
    }
    assert openai.requests[-1]['headers']['Authorization'] == 'Bearer test-openai-key'


def test_write_cuts_the_prompt_at_4000_characters(openai):
    post('/api/ai/write', {'prompt': 'x' * 5000})
    assert len(openai.last['messages'][1]['content']) == 4000


@pytest.mark.parametrize('body', [{}, {'prompt': '   '}, {'prompt': None}])
def test_write_without_a_prompt_is_400(openai, body):
    res = post('/api/ai/write', body)
    assert res.status_code == 400
    assert res.json() == {'error': 'Describe what the update should say.'}
    assert openai.requests == []


# ---------- Summarize ----------


def test_summarize_asks_openai_with_the_summarize_prompt(openai):
    openai.content = '• Offer sent'
    res = post('/api/ai/summarize', {'text': 'Long forwarded email ' * 1000})

    assert res.json() == {'text': '• Offer sent'}
    assert openai.last['max_tokens'] == 250
    assert openai.last['messages'][0]['content'] == service.PROMPTS['summarize']['system']
    assert len(openai.last['messages'][1]['content']) == 12000


def test_summarize_without_text_is_400(openai):
    res = post('/api/ai/summarize', {'text': ''})
    assert res.status_code == 400
    assert res.json() == {'error': 'This update has no text to summarize.'}


# ---------- Autofill ----------


def test_autofill_keeps_only_allowed_values_in_the_forms_spelling(openai):
    openai.content = json.dumps({
        'escalation': 'no', 'categories': 'w-inv', 'mainCategory': 'PAY', 'subCategory': 'docs',
        'nextStep': 'Invent a step', 'dueDate': '2026-11-06', 'transcript': 'https://example.com/call/1',
    })
    res = post('/api/ai/autofill', autofill_body())

    assert res.status_code == 200
    assert res.json() == {'fields': {
        'escalation': 'No', 'categories': 'W-Inv', 'mainCategory': 'Pay', 'subCategory': 'DOCS',
        'dueDate': '2026-11-06', 'transcript': 'https://example.com/call/1',
    }}


def test_autofill_sends_the_team_rules_and_the_request(openai):
    openai.content = '{}'
    post('/api/ai/autofill', autofill_body(examples=[{'comment': str(i)} for i in range(12)]))

    sent = openai.last
    assert sent['model'] == 'gpt-4o-mini'
    assert sent['temperature'] == 0.1
    assert sent['max_tokens'] == 300
    assert sent['response_format'] == {'type': 'json_object'}
    assert sent['messages'][0] == {'role': 'system', 'content': service.AUTOFILL_GUIDE}
    request = json.loads(sent['messages'][1]['content'])
    assert request['allowedValues'] == OPTIONS
    assert request['today'] == '2026-11-02'
    assert request['deal'] == {'name': 'Muster GmbH', 'stage': 'Won'}
    assert len(request['examplesFromThisDeal']) == 8
    assert request['comment'] == 'keine Mahnungen verschicken!'


@pytest.mark.parametrize('main, said, expected', [
    ('Order', 'W-Quote', 'W-Order'),   # frei Haus on a "Quote In Progress" deal: the model kept W-Quote
    ('Quote', 'W-Inv', 'W-Quote'),
    ('Pay', 'General', 'W-Inv'),
    ('Order', '', 'W-Order'),          # filled even when the model left it out
])
def test_autofill_derives_catagories_from_the_main_category(openai, main, said, expected):
    openai.content = json.dumps({'mainCategory': main, 'categories': said, 'subCategory': 'TERMS'})
    assert post('/api/ai/autofill', autofill_body()).json()['fields']['categories'] == expected


def test_autofill_categories_for_any_other_main_category_is_general(openai):
    options = {**OPTIONS, 'mainCategory': [*OPTIONS['mainCategory'], 'Mdm']}
    openai.content = json.dumps({'mainCategory': 'MDM', 'categories': 'W-Order'})
    assert post('/api/ai/autofill', autofill_body(options=options)).json()['fields']['categories'] == 'General'


@pytest.mark.parametrize('options', [
    {**OPTIONS, 'mainCategory': ['Quotation', 'Order']},        # not a code: the model's answer stands
    {**OPTIONS, 'categories': ['W-Quote', 'W-Inv', 'General']},  # the form has no W-Order
])
def test_autofill_keeps_the_models_catagories_when_it_cannot_be_derived(openai, options):
    main = options['mainCategory'][0]
    openai.content = json.dumps({'mainCategory': main if main == 'Quotation' else 'Order', 'categories': 'W-Quote'})
    assert post('/api/ai/autofill', autofill_body(options=options)).json()['fields']['categories'] == 'W-Quote'


def test_autofill_rules_cover_frei_haus_and_the_deal_stage():
    guide = service.AUTOFILL_GUIDE
    assert '"Lieferung in die Schweiz ab 500 € frei Haus, ohne MwSt." → ORDER + TAX' in guide
    assert 'deal.stage (e.g. "Quote In Progress"' in guide
    assert 'QUOTE, TEND, LEAD → W-Quote | ORDER, PO → W-Order' in guide, "the line the code's table mirrors"


@pytest.mark.parametrize('answer', [
    {'dueDate': '06.11.2026'},
    {'dueDate': 'next week'},
    {'transcript': 'not a link'},
    {'transcript': 'ftp://example.com'},
])
def test_autofill_drops_a_bad_due_date_or_transcript(openai, answer):
    openai.content = json.dumps(answer)
    assert post('/api/ai/autofill', autofill_body()).json() == {'fields': {}}


def test_autofill_survives_an_answer_that_is_not_json(openai):
    openai.content = 'Sorry, I cannot.'
    assert post('/api/ai/autofill', autofill_body()).json() == {'fields': {}}


def test_autofill_without_a_comment_is_400(openai):
    res = post('/api/ai/autofill', autofill_body(comment=' '))
    assert res.status_code == 400
    assert res.json() == {'error': 'Write the comment first.'}


# ---------- shared rules ----------


def test_an_openai_error_is_a_502_with_its_message(openai):
    openai.status, openai.error = 401, 'Incorrect API key provided'
    res = post('/api/ai/write', {'prompt': 'x'})
    assert res.status_code == 502
    assert res.json() == {'error': 'OpenAI error: Incorrect API key provided'}


def test_an_openai_error_without_a_message_names_the_status(openai):
    openai.status = 500
    assert post('/api/ai/summarize', {'text': 'x'}).json() == {'error': 'OpenAI error: 500'}


def test_invalid_json_is_400(openai):
    res = client.post('/api/ai/write', content=b'{not json', headers=session_auth())
    assert res.status_code == 400
    assert res.json() == {'error': 'Invalid JSON.'}


def test_a_body_over_64_kb_is_413(openai):
    res = post('/api/ai/summarize', {'text': 'x' * (65 * 1024)})
    assert res.status_code == 413
    assert res.json() == {'error': 'Request too large.'}
    assert openai.requests == []


def test_the_api_takes_posts_only():
    assert client.get('/api/ai/write', headers=session_auth()).status_code == 405


def test_30_calls_a_minute_per_user_then_429(openai):
    for _ in range(30):
        assert post('/api/ai/write', {'prompt': 'x'}).status_code == 200
    res = post('/api/ai/write', {'prompt': 'x'})
    assert res.status_code == 429
    assert res.json() == {'error': 'Too many AI requests. Please wait a minute.'}
    assert len(openai.requests) == 30


def test_the_ip_limit_holds_across_users(openai):
    for user in range(30):
        assert post('/api/ai/write', {'prompt': 'x'}, user_id=user).status_code == 200
    assert post('/api/ai/write', {'prompt': 'x'}, user_id=999).status_code == 429


def test_the_enrichments_model_setting_does_not_change_this_feature(openai, monkeypatch):
    monkeypatch.setenv('OPENAI_MODEL', 'gpt-4o')
    post('/api/ai/write', {'prompt': 'x'})
    assert openai.last['model'] == 'gpt-4o-mini'

    monkeypatch.setenv('COMMENT_BUILDER_OPENAI_MODEL', 'gpt-4.1-mini')
    post('/api/ai/write', {'prompt': 'x'})
    assert openai.last['model'] == 'gpt-4.1-mini'


def test_without_the_openai_key_it_is_a_500_and_nothing_is_sent(openai, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY')
    res = post('/api/ai/write', {'prompt': 'x'})
    assert res.status_code == 500
    assert 'OPENAI_API_KEY' in res.json()['error']
    assert openai.requests == []


def test_the_comment_and_the_answer_are_never_logged(openai, caplog):
    caplog.set_level('DEBUG')
    openai.content = 'SECRET-ANSWER-TEXT'
    post('/api/ai/write', {'prompt': 'SECRET-PROMPT-TEXT'})

    everything = json.dumps([(r.getMessage(), getattr(r, 'payload', None)) for r in caplog.records], default=str)
    assert 'SECRET-PROMPT-TEXT' not in everything
    assert 'SECRET-ANSWER-TEXT' not in everything
    [line] = [r for r in caplog.records if r.getMessage().startswith('POST /api/ai/write -> comment_builder 200')]
    assert line.payload['jwt'] == {'user_id': 2, 'account_id': 1, 'app_id': 11727119, 'exp': line.payload['jwt']['exp']}
