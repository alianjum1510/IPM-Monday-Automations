"""
Turns the model's `KEY: value` block into a plain dict.

The model is asked for one field per line, but it does wrap long NOTES over
several lines, so a line without a recognised KEY is appended to the field
that came before it.

Uses the `regex` module rather than `re` where a pattern needs `\\p{L}` (any
letter, umlauts included) - `re` has no Unicode property classes.
"""
import re

import regex

KEY_LINE = re.compile(r'^\s*\*{0,2}([A-Z][A-Z0-9_&]{2,})\*{0,2}\s*:\s*(.*)$')

# Values the model uses to say "nothing found" - all normalise to empty.
EMPTY_VALUES = {
    '',
    'n/a',
    'na',
    'none',
    'null',
    'unknown',
    'not found',
    'not available',
    'not applicable',
    'not found after extensive search',
    'no',
}

# `NOT_FOUND_KEEPS_NO` fields where a literal "No" is a real answer.
NO_IS_A_VALUE = {'HANDELSREGISTER_VERIFIED'}

# Fields where a trailing "(handelsregister.de)" is the point, not noise.
#
# The prompt asks these to name their source, and Comments is where that
# verification trail lives. Everywhere else a source citation is contamination:
# "Contact Name" is a name, not a name plus where it was found.
KEEP_CITATIONS = {
    'VAT_CONFIDENCE',
    'HRB_CONFIDENCE',
    'COMPANY_STATUS',
    'CONFIDENCE',
    'VERIFICATION_SOURCE',
    'REGISTRY_SOURCE',
    'NOTES',
}

# Fields that hold the value and nothing else.
#
# The model likes to annotate the name and address it settled on -
# "Muster GmbH (verified on handelsregister.de)", "Badstraße 1, 12345 Berlin -
# Hauptsitz; formerly Hauptstraße 3", or a sentence on the next line. Those
# cells are what a human reads and what gets mailed to, so the annotation is
# cut off and moved to Comments rather than written into the cell.
NAME_FIELD = 'CORRECT_NAME'
ADDRESS_FIELDS = {
    'CORRECT_ADDRESS',
    'ADDRESS_LINE_1',
    'ADDRESS_LINE_2',
    'ADDRESS_LINE_3',
    'POSTAL_CODE',
    'CITY',
    'STATE',
    'DISTRICT',
    'COUNTRY',
}


def is_value_only(key):
    return key == NAME_FIELD or key in ADDRESS_FIELDS


# Where the cut-off remarks travel, as `[{key, text}]`. KEY_LINE only accepts a
# key starting with a letter, so the model cannot write to it.
REMOVED_REMARKS = '__REMOVED_REMARKS__'


def _words(alternatives):
    """A whole word, umlauts included - `\\b` would treat "früher" as two words."""
    return regex.compile(r'(?<![\p{L}\d])(?:' + alternatives + r')(?![\p{L}\d])', regex.IGNORECASE)


# Words that only appear when the model is talking ABOUT the value.
REMARK = _words('|'.join([
    r'verif\w*', 'confirm\\w*', 'unverified', 'unconfirmed', 'sources?', 'according', 'laut', 'gem(?:ä|ae)ß',
    'per', 'formerly', 'former', 'previously', 'früher', 'frueher', 'ehemals', 'vormals', 'now', 'aka',
    'also known', 'note[sd]?', 'hinweis', 'see also', 'siehe', 'found', 'listed', 'registered', 'registry',
    'handelsregister', 'unternehmensregister', 'impressum', 'northdata', 'creditsafe', 'companyhouse',
    'linkedin', 'website', 'homepage', 'google', 'as of', 'likely', 'probably', 'possibly', 'may', 'might',
    'unclear', 'uncertain', r'alternative\w*', 'or', 'headquarters?', 'hq', '(?:haupt|firmen|gesellschafts)?sitz',
    'branch', 'niederlassung', 'filiale', '(?:registered|head|main) office', 'moved', 'relocated', 'umgezogen',
    'renamed', 'umfirmiert', 'changed', 'since', 'seit', 'parent', 'subsidiary', r'tochter\w*', r'mutter\w*',
    'based on', r'search\w*', r'match\w*', 'input', 'provided', 'original', 'typo', 'correct(?:ed|ion)?',
    'spelling', 'incorrect', 'differs?', 'confidence',
]))

# English prose. German addresses never contain these words, so a segment that
# does is a sentence about the address. Not applied to the name on its own:
# "The Coca-Cola Company GmbH" is a name.
PROSE = _words('the|is|was|were|are|has|have|had|which|this|that|its|but|not|company|appears?|seems?')

LEGAL_FORMS = r'gmbh|mbh|ag|kg|kgaa|ohg|gbr|ug|se|mbb|e\.\s?k\.?|e\.\s?v\.?|eg|ltd\.?|inc\.?|llc|plc'

# The name so far ends on its legal form, so whatever follows is not the name.
ENDS_ON_LEGAL_FORM = regex.compile(r'(?<![\p{L}\d])(?:' + LEGAL_FORMS + r')(?:\s*\))?\s*$', regex.IGNORECASE)

# Greedy, so it finds the LAST legal form: "GmbH & Co. KG verified" keeps "& Co. KG".
AFTER_LAST_LEGAL_FORM = regex.compile(
    r'^(.*(?<![\p{L}\d])(?:' + LEGAL_FORMS + r')(?![\p{L}\d])\.?)\s+(.+)$', regex.IGNORECASE,
)

# The placeholder label echoed in front of the value: "Legal name: Muster GmbH".
LABEL_PREFIX = re.compile(r'^(?:legal|company|full|registered|verified)?\s*(?:name|address)\s*:\s*', re.IGNORECASE)

# Dash, pipe or semicolon - and a spaced hyphen, unless it is a house-number range "1 - 3".
SEPARATOR = re.compile(r'\s+[—–|]\s+|\s*;\s*|\s+-\s+(?=\D)')

# A comma, or a full stop that starts a new sentence.
SEGMENT = regex.compile(r',\s*|\.\s+(?=\p{Lu})')

# Longest plausible value; anything longer is carrying something else.
MAX_LENGTH = {'CORRECT_NAME': 120, 'CORRECT_ADDRESS': 200}
MAX_PART_LENGTH = 100

# `[text](url)` - web_search cites its sources as markdown links.
MARKDOWN_LINK = re.compile(r'\[([^\]]*)\]\(\s*<?(https?://[^)\s>]+)>?\s*\)', re.IGNORECASE)

# A parenthesised bare domain or URL: "(svg-sued.de)", "(https://x.de/impressum)".
CITATION_PAREN = re.compile(
    r'\s*\((?:https?://)?(?:www\.)?[a-z0-9-]+(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?:/[^)]*)?\)', re.IGNORECASE,
)


def _strip_tracking(value):
    """web_search stamps its own attribution onto every URL it hands back."""
    value = re.sub(r'([?&])utm_source=openai&', r'\1', value, flags=re.IGNORECASE)
    return re.sub(r'[?&]utm_source=openai\b', '', value, flags=re.IGNORECASE)


def parse_enrichment(text):
    fields = {}
    remarks = []
    current = None

    for raw_line in str(text or '').split('\n'):
        line = raw_line.strip()
        if not line:
            continue

        match = KEY_LINE.match(line)
        if match:
            current = match.group(1).upper()
            fields[current] = match.group(2).strip()
        elif current and is_value_only(current):
            # A second line under the name or address is a remark about it, not
            # more of it - the model is asked for one field per line.
            remarks.append({'key': current, 'text': line})
        elif current:
            fields[current] = f'{fields[current]} {line}'.strip()

    for key, value in list(fields.items()):
        fields[key] = _clean(key, value, remarks)

    if remarks:
        fields[REMOVED_REMARKS] = remarks

    return fields


def _clean(key, value, remarks):
    """Strips the model's bracket placeholders and normalises "not found" to ''."""
    out = str(value).strip()

    # Citations first: an unwrapped "[legal name](url)" would defeat the
    # placeholder check below.
    out = MARKDOWN_LINK.sub(r'\1', _strip_tracking(out)).strip()
    if key not in KEEP_CITATIONS:
        out = CITATION_PAREN.sub('', out).strip()

    # "[legal name]" - an unfilled placeholder, not an answer.
    if re.fullmatch(r'\[.*\]', out):
        inner = out[1:-1].strip()
        out = '' if re.match(r'(or\b|e\.g\.|legal name|full address|court|URL|status)', inner, re.IGNORECASE) else inner

    out = re.sub(r'^\*+|\*+$', '', out).strip()

    # Before the "not found" checks: "Not found — KRS 0000657029" still carries
    # a number, and the generic check below would throw it away.
    if key == 'REGISTRATION_NUMBER':
        return _registration_only(out)

    # "Not found" is an answer, not a remark to move to Comments.
    nothing = re.sub(r'\.$', '', out.lower())
    if is_value_only(key) and nothing not in EMPTY_VALUES and not nothing.startswith('not found'):
        bare, removed = _value_only(key, out)
        for text in removed:
            remarks.append({'key': key, 'text': text})
        out = bare

    lowered = re.sub(r'\.$', '', out.lower())
    if lowered in EMPTY_VALUES and not (key in NO_IS_A_VALUE and lowered == 'no'):
        return ''
    if lowered.startswith('not found'):
        return ''

    return out


def _value_only(key, value):
    """
    Cuts the name or an address part down to the value itself.

    In order: an echoed label, bracketed remarks, a tail after a dash or
    semicolon, and a comma segment or sentence that talks about the value. Then a
    last check: if what is left still carries a URL, an email, a question or more
    text than the field ever needs, it is not trusted at all - the cell is left
    for N/A and the whole answer goes to Comments. An empty cell is recoverable,
    a name with a note glued to it gets mailed.

    The name is handled more gently than the address. "Muster (Deutschland) GmbH"
    and "Rhein - Main Bau GmbH" are real names, so a bracket or dash is only cut
    from the name when it reads as a remark or follows the legal form.

    Returns (value, removed).
    """
    is_name = key == NAME_FIELD
    removed = []
    out = LABEL_PREFIX.sub('', value, count=1)

    # "(verified on handelsregister.de)", "[Hauptsitz]".
    def drop_bracket(match):
        inner = match.group(1)
        keep = is_name and not REMARK.search(inner) and not ENDS_ON_LEGAL_FORM.search(match.string[:match.start()])
        if keep:
            return match.group(0)
        if inner.strip():
            removed.append(inner.strip())
        return ''

    out = re.sub(r'\s*[(\[]([^()\[\]]*)[)\]]', drop_bracket, out)

    # "Badstraße 115 — Hauptsitz", "Muster GmbH; formerly Alt GmbH".
    for match in SEPARATOR.finditer(out):
        head = out[:match.start()].strip()
        tail = out[match.end():].strip()
        if not head or not tail:
            continue

        remark = bool(REMARK.search(tail) or PROSE.search(tail))
        hard = match.group(0).strip() != '-'
        cut = (remark or ENDS_ON_LEGAL_FORM.search(head)) if is_name else (hard or remark)
        if cut:
            removed.append(tail)
            out = head
            break

    # "Muster GmbH verified via Impressum" - words after the legal form.
    if is_name:
        after = AFTER_LAST_LEGAL_FORM.match(out)
        if after and (REMARK.search(after.group(2)) or PROSE.search(after.group(2))):
            removed.append(after.group(2).strip())
            out = after.group(1)

    # "Badstraße 115, 71336 Waiblingen, as listed on the Impressum" and
    # "... Waiblingen. The company moved in 2021." The first segment is the
    # value itself and is never cut here - the final check handles that case.
    def talks_about(segment):
        return REMARK.search(segment) or (not is_name and PROSE.search(segment))

    for match in SEGMENT.finditer(out):
        start = match.end()
        following = SEGMENT.search(out, start)
        segment = out[start:following.start() if following else None]
        if talks_about(segment):
            removed.append(out[start:].strip())
            out = out[:match.start()]
            break

    out = re.sub(r'^[\s,;:|—–-]+|[\s,;:|—–-]+$', '', out)
    out = re.sub(r'\s{2,}', ' ', out)

    limit = MAX_LENGTH.get(key, MAX_PART_LENGTH)
    untrusted = (
        re.search(r'https?://|www\.|@|\?', out)
        or len(out) > limit
        or (not is_name and (REMARK.search(out) or PROSE.search(out)))
    )

    if untrusted:
        return '', [value]

    return out, removed


# A register prefix and its number: "HRB 12345 B", "KRS 0000657029", "FN 123456a".
REGISTER_NUMBER = re.compile(r'\b[A-Z]{2,4}[.:]?\s?\d(?:[\d\s./-]*\d)?(?:\s?[A-Za-z]\b)?')

# The model's ways of saying it found nothing.
NOTHING_FOUND = re.compile(
    r'\bnot found\b|\bno\b.*\bfound\b|^(n/?a|none|null|unknown|not available|not applicable)\b', re.IGNORECASE,
)


def _registration_only(value):
    """
    The model tacks commentary onto the number, before or after it:
    "KRS 0000657029 — no German HRB/HRA found after extensive search",
    "Not found — KRS 0000657029 (Polish register)".
    The column wants the number alone. A register prefix with a number wins
    wherever it sits; failing that, a "nothing found" statement is empty (its
    digits are search counts, not a number), and anything else is cut at the
    first dash, semicolon or parenthesis.
    """
    prefixed = REGISTER_NUMBER.search(value)
    if prefixed:
        return prefixed.group(0).strip()

    if NOTHING_FOUND.search(value):
        return ''

    parts = [re.sub(r'[\s),.]+$', '', part).strip() for part in re.split(r'\s+[—–-]\s+|[;(]', value)]
    return next((part for part in parts if re.search(r'\d', part)), '')
