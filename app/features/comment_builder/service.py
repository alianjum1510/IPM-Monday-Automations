"""
Comment Builder's three AI actions, as plain functions (no HTTP here):

  write(prompt)     "Write with AI": a CRM update drafted from a short description
  summarize(text)   "Summarize": 2-4 bullets from an update (often a forwarded email)
  autofill(body)    "Autofill": the comment form's fields, classified with the team's rules

All three call OpenAI chat completions with OPENAI_API_KEY and
COMMENT_BUILDER_OPENAI_MODEL (default gpt-4o-mini). The prompts and
AUTOFILL_GUIDE are the team's rules, from the original Comment Builder
server - change them only on purpose. Changed since (2026-11-03): the deal
stage and frei Haus rules and two examples in AUTOFILL_GUIDE, and Catagories
is derived from the main category in code.

Synchronous (urllib, 120 s timeout): the router runs them in the thread pool.
An OpenAI failure raises ViewError(502) with OpenAI's message, which the page shows.
"""
import json
import re
import urllib.error
import urllib.request

from app.core.config import setting
from app.core.views import ViewError

DEFAULT_MODEL = "gpt-4o-mini"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_TIMEOUT_SECONDS = 120

# key -> accepted names. MONDAY_CLIENT_SECRET is checked by app/core/security.py for every View feature.
REQUIRED_SETTINGS = {"OPENAI_API_KEY": ("OPENAI_API_KEY",)}
# Not OPENAI_MODEL: Company Enrichment reads that one, and its model must not change this feature's.
OPTIONAL_SETTINGS = ("COMMENT_BUILDER_OPENAI_MODEL",)


def js_str(v):
    """String(v) as JavaScript would write it, for values that come from request JSON."""
    if isinstance(v, str):
        return v
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, (int, float)):
        return str(v)
    return json.dumps(v, ensure_ascii=False)


def as_dict(v):
    return v if isinstance(v, dict) else {}


def to_json(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def model():
    return setting("COMMENT_BUILDER_OPENAI_MODEL") or DEFAULT_MODEL


# ---------- OpenAI ----------

PROMPTS = {
    "write": {
        "system": (
            "You write clear, professional updates for a sales team's CRM on monday.com. "
            'Write in the same language as the request. Use short paragraphs or simple bullet points ("• "). '
            "Plain text only: no markdown, no headings, no greeting or sign-off unless asked."
        ),
        "max": 450,
    },
    "summarize": {
        "system": (
            "You summarize monday.com updates (often forwarded emails) for a busy sales team. "
            'Reply in 2 to 4 short bullet points starting with "• ". Keep names, companies, dates, amounts and next steps. '
            "Ignore signatures, tracking links and quoted older emails. Same language as the update. Plain text only."
        ),
        "max": 250,
    },
}


def openai_chat(payload):
    """POST to OpenAI chat completions; the response JSON. Errors become ViewError(502) like the page expects."""
    key = setting("OPENAI_API_KEY")
    if not key:
        raise ViewError(500, "OPENAI_API_KEY is not set (Developer Center → Server-side code → Secrets).")
    req = urllib.request.Request(
        OPENAI_URL,
        data=to_json(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=OPENAI_TIMEOUT_SECONDS) as res:
            status, raw = res.status, res.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    try:
        data = as_dict(json.loads(raw.decode("utf-8")))
    except ValueError:
        data = {}
    if not 200 <= status < 300:
        raise ViewError(502, f"OpenAI error: {as_dict(data.get('error')).get('message') or status}")
    return data


def openai_content(data):
    choices = data.get("choices")
    first = as_dict(choices[0]) if isinstance(choices, list) and choices else {}
    return as_dict(first.get("message")).get("content") or ""


def chat(kind, user_text):
    data = openai_chat(
        {
            "model": model(),
            "temperature": 0.4,
            "max_tokens": PROMPTS[kind]["max"],
            "messages": [
                {"role": "system", "content": PROMPTS[kind]["system"]},
                {"role": "user", "content": user_text},
            ],
        }
    )
    return js_str(openai_content(data)).strip()


def write(prompt):
    return chat("write", prompt)


def summarize(text):
    return chat("summarize", text)


# ---------- Autofill: the team's classification rules ----------

AUTOFILL_GUIDE = """You classify comments that a sales/operations team logs on deals and leads in monday.com.
Read the comment (and the deal/lead context) and fill the form fields.

ANSWER RULES
- Every value MUST be copied exactly from "allowedValues" in the request. The rules below use codes (QUOTE, SHIP, PAY…);
  answer with the matching allowedValues entry, e.g. QUOTE → "Quote", SHIP → "Ship", PAY → "Pay", ITEM → "Item", TRADE → "Trade".
- ALWAYS fill: mainCategory (exactly one, the best match — even for short or vague comments use the deal/lead context),
  subCategory (one tag; DOCS if none fits), categories (derived from mainCategory), escalation ("Yes" or "No").
- Classify what the comment is ABOUT. The deal/lead context only breaks a tie for vague comments: the item being a
  lead, or its deal stage, is never by itself a reason for LEAD (or QUOTE).
- deal.stage (e.g. "Quote In Progress", "Lead", "Won") says where the deal is, NOT what the comment is about. A comment
  about delivery terms, frei Haus, VAT, payment, invoices, shipping or master data gets that category on any deal,
  also on a deal whose stage says Quote or Lead.
- Decide in this order: 1. MANDATORY RULES and EXAMPLES below, 2. MAIN CATEGORY PRIORITY RULES, 3. the category
  definitions, 4. only if the comment has no topic at all: the deal/lead context.
- "examplesFromThisDeal" are earlier comments on the same deal: they show the team's style, but don't copy their
  category unless the new comment is about the same thing.
- Fill nextStep, dueDate and transcript only when the comment implies them; otherwise "".
- Never invent values that are not in allowedValues.

LANGUAGE
- Comments are often in GERMAN (short ERP-style notes full of abbreviations), sometimes English. Classify by meaning;
  use the GERMAN TERMS list below. The answer values are always the allowedValues, never translated.
- One comment may hold several notes (often each starting with a date). Autofill fills one set of fields, so classify
  the most important operational note, using the priority and mandatory rules below.

MAIN CATEGORY (scope) — select exactly one:
LEAD = leads, prospects, pipeline, potential customers (the prospect itself: new interest, first contact, qualification)
ITEM = product truth: ingredients, specifications, composition, attributes
QUOTE = customer quotations, offers, RFQs
PO = customer purchase orders (sales-side PO)
ORDER = sales order processing, fulfillment execution
WH = warehouse operations, storage, picking, stock movement
SHIP = shipping execution, delivery, logistics in transit
INV = invoicing, billing, invoice corrections, credit notes
PAY = payments, reminders, dunning, financial settlement
RMA = returns, complaints, replacements
SRV = customer service, questionnaires, support, surveys, aftersales
VEND = supplier/vendor interactions
PURQ = internal purchase requisitions
PORD = purchase orders to suppliers (buy-side PO)
RCV = goods receipt, inbound deliveries
QC = quality control, inspections
CNT = contracts and agreements
PROJ = projects, implementations
FCAST = forecasting, planning
ITI = intercompany transactions
MDM = master data: material codes, account changes, governance
INVN = inventory counts, stock balances
KIT = physical kitting, assembly of materials only
HSE = health, safety, environment instructions
REG = regulatory compliance, registrations
REB = rebates, discounts, financial incentives
CARR = carriers, freight forwarders
TEND = tenders, bids
INS = insurance matters

MAIN CATEGORY PRIORITY RULES (strict precedence, apply in order):
1. Payment, reminders, dunning → PAY
2. Invoice creation/correction → INV
3. Delivery execution, shipment movement → SHIP
4. Sales order execution → ORDER
5. Customer service, questionnaires, surveys → SRV
6. Product specifications, ingredients → ITEM
7. Regulatory compliance → REG
8. Master data changes → MDM
9. Vendor interactions → VEND
If multiple apply, select the category closest to the operational transaction. Never select multiple main categories.

SUBCATEGORY TAG — select the ONE most relevant tag (the form allows only one); never leave it empty:
LEGAL = legal restrictions, contracts
COMPL = compliance, regulations, certifications
DG = dangerous goods, hazardous classification
ARTWK = artwork, design proofs, labels
PKG = packaging rules, pallet/box types, dimensions
PPE = protective equipment requirements
TERMS = commercial terms, delivery terms, payment terms
APPROVAL = formal approval needed (artwork, credit, release)
CREDIT = credit limits, finance release, risk checks
TRACE = traceability, lot numbers, expiry, FEFO/FIFO
LOG = logistics rules, delivery slots, constraints
TMS = transport management, routing, tracking, carrier ref
TAX = taxation, VAT, duties, special tax rules
MKT = marketing, promotions, campaigns
QMS = quality management, audits, quality holds
EHS = environment, health, safety
SUST = sustainability, environmental claims
TRADE = trade compliance, restrictions
HS = harmonized system (tariff codes)
ORIGIN = origin declarations, EUR.1, CoO
HAZWASTE = hazardous waste notes
TEMP = temperature requirements (cold chain, etc.)
SLED = shelf-life, expiry, best before
CALIB = calibration of tools/instruments
CONTENT = content description (ingredients, material spec)
PROMO = promotional pricing, discounts, offers
PRICEGOV = pricing rules, tenders, price restrictions
REBATE = rebates, kickbacks, credit notes
SECURITY = security requirements, restricted access
PRIVACY = data privacy, GDPR, customer info handling
DOCS = documentation requirements (invoices, CMR, SDS, CoA, questionnaires, forms, paperwork of any type)
KPI = performance tracking, service level targets
SLA = service-level agreements, time-to-service
If no tag clearly applies → DOCS.
Use DOCS only when the comment is about a document (send / attach / print a PDF, invoice, form, certificate, paperwork)
or truly no other tag fits. When a topic tag fits (TERMS, PRICEGOV, LOG, CREDIT, PKG…), use that tag instead. The
MANDATORY RULES below still decide where they apply (e.g. dunning → DOCS, master data → DOCS).

CATAGORIES (workflow) — always derived from the main category:
QUOTE, TEND, LEAD → W-Quote | ORDER, PO → W-Order | WH, INVN, RCV, KIT → W-WH | SHIP, CARR → W-Ship | INV, PAY, REB → W-Inv | anything else → General.

MANDATORY RULES (override everything above; mainCategory + subCategory):
- dunning / Mahnung / reminder (also "keine Mahnungen") → PAY + DOCS
- credit limit, credit approval, credit insurance cover or amount (VS, Kreditversicherung, Versicherungsschutz,
  @rating, Creditreform, Bonitätsindex, Höchstkredit), customer blocked (Kd. gesperrt), deliver despite open items
  (offene Posten) → PAY + CREDIT
- payment terms: Vorkasse, Skonto, Zahlungsziel → PAY + TERMS
- the insurer itself: which insurer (versichert bei AKV, Coface), insurance application, insurer cancelled the cover → INS + DOCS
- invoicing rules: fakturieren, Rechnung / RG, RG-PDF, invoice e-mail → INV + DOCS
- master data: new or changed address (Firmen-/Rechnungsadresse), new / wrong / duplicate customer number,
  "siehe Kd.-Nr.", account switched (Webshop → normal), company closed, note in the Artikelbaustein → MDM + DOCS
- customer data handling / data protection (DSGVO, GDPR, Datenschutz, Daten nicht weitergeben) → MDM + PRIVACY
- order terms: minimum order value (MBW), frei Haus thresholds, agreed prices / price conditions for an existing
  customer's orders, which articles to deliver or not (incl. articles no longer delivered, replacement / substitute
  articles: Ersatz, stattdessen, ausgelistet) → ORDER + TERMS (+ VAT / MwSt. → subCategory TAX). ITEM is only for what
  a product IS (specification, make-up), not which articles a customer gets.
- frei Haus / free-delivery threshold ("ab 500 € frei Haus") is ORDER, also when a country is named ("Lieferung nach
  Deutschland", "in die Schweiz", "nach Österreich"): ORDER + TERMS, or ORDER + TAX when VAT is mentioned (MwSt.,
  ohne MwSt., zzgl. MwSt., netto, steuerfrei). Not SHIP and not QUOTE. Exception: with Vorkasse / Skonto it is PAY + TERMS.
- price talks with a lead / prospect, price offers, a new price list or prices for a future period (e.g. "Preise 2027")
  → QUOTE + PRICEGOV. Use the deal stage to tell a lead / prospect from an existing customer.
- a call, meeting or e-mail is not SRV by itself: classify by what was discussed (e.g. a call about prices → the price
  rules above)
- order handling: partial / back-order delivery (Nachlieferung), which account handles which deliveries → ORDER + LOG
- delivery execution, shipment movement; shipping: carrier or route (DHL, GLS, MBS, Spedition), freight costs, delivery
  to a country, delivery slots → SHIP + LOG (a frei Haus threshold is not shipping: see the frei Haus rule above)
- documentation requirements (a document must be sent, attached, printed or kept: AB-PDF, RG-PDF, CMR, CoA, SDS…) →
  subCategory DOCS (mandatory), with the main category of the process it belongs to
- cartons / pallets per shipment → SHIP + PKG
- product make-up (layers, packing units, specification) → ITEM + CONTENT (packing per carton → ITEM + PKG)
- questionnaires, forms, surveys → SRV + DOCS; regulatory compliance → REG + COMPL

GERMAN TERMS
Kd. / KD = Kunde (customer) · Kd.-Nr. = customer number · RG = Rechnung (invoice) · AB = Auftragsbestätigung (order
confirmation) · MBW = Mindestbestellwert (minimum order value) · FH / frei Haus = free delivery · VS = Versicherungssumme
(credit-insurance limit) · OP / offene Posten = unpaid invoices · Mahnung = dunning · Vorkasse = prepayment ·
Skonto = early-payment discount · MwSt. = VAT · Bestellung / Auftrag = order · Angebot = quote · Anfrage = RFQ ·
Lieferung = delivery · Nachlieferung = back-order delivery · Versand = shipping · Spedition = freight forwarder ·
Fracht = freight · Palette / Pal. = pallet · Karton = carton · VE = packing unit · WA = Warenausgang (goods issue) ·
LZ = Lieferzeit · WT = Werktage · Lager = warehouse · Artikel / Art. = item · Reklamation = complaint · Retoure = return ·
gesperrt = blocked · Versicherung = insurance. Initials such as BD, IF, KL, je, pe, RS, KC, D.F are the author: ignore.

EXAMPLES (comment → mainCategory + subCategory)
"21.03.2014 MBW: 1000 €" → ORDER + TERMS
"jede Bestellung einzeln fakturieren !!" → INV + DOCS
"sollte bei einer Pos. nicht genug Ware da sein, Pos. komplett nachliefern" → ORDER + LOG
"10.04.2002 kann trotz offener Posten beliefert werden/ keine Versicherung notwendig" → PAY + CREDIT
"13.06.2025 neue Firmenadresse bzw. Rechnungsadresse / If." → MDM + DOCS
"keine Mahnungen verschicken! September 2006" → PAY + DOCS
"schließen zum 01.05.2024 / Kd. gesperrt ! IF" → PAY + CREDIT
"19.07.2023 DHL Paket nach Luxemburg 15,00 Euro KL" → SHIP + LOG
"VS 10.000 ab 15.01.14 /BD" → PAY + CREDIT
"Hr. Wetz möchte immer über frei Haus, evt. auffüllen (Latexhandschuhe)" → ORDER + TERMS
"06.12..2007 Lieferung nach Deutschland 250 € frei Haus dann aber MwSt." → ORDER + TAX
"Lieferung in die Schweiz ab 500 € frei Haus, ohne MwSt." → ORDER + TAX (also on a deal in stage "Quote In Progress")
"Lieferung nach Österreich ab 300 € frei Haus" → ORDER + TERMS
"nach Email-Adresse (RG-PDF) fragen!" → INV + DOCS
"18.06.03 versichert bei AKV. pe" → INS + DOCS
"VORKASSE - ab 500,00 Euro frei Haus" → PAY + TERMS
"16.01.15 bei Artikeln 30869-00 und -11 passen jeweils nur 24 Kartons auf die Palette." → SHIP + PKG
"20.08.19-RS : Kunde wird umgestellt von Webshop auf normaler Kunde" → MDM + DOCS
"Art. 12345-00 ausgelistet, stattdessen 12346-00 liefern" → ORDER + TERMS
"Telefonat mit Fr. Schulz wegen neuer Preisliste 2027, nächste Woche nachfassen" → QUOTE + PRICEGOV
"Kd. bekommt weiterhin 5% auf alle Bestellungen, Preise wie vereinbart" → ORDER + TERMS
"Datenschutz: Kontaktdaten des Kd. nur intern verwenden" → MDM + PRIVACY

NEXT STEP — the action the comment implies (e.g. unpaid invoice → Chase Payment, customer wants an offer → Send Proposal,
waiting for the customer → Awaiting Response, call agreed → Call Back). Empty if no action is implied.

ESCALATION — "Yes" only if the comment says it is urgent, escalated, a complaint, or at risk (German: dringend,
eskaliert, Beschwerde, Reklamation); otherwise "No". Exclamation marks or capitals alone are not an escalation.

DUE DATE — only if the comment states or implies a deadline ("by Friday", "next week", "on the 30th"; German: "bis",
"bis zum", "spätestens", "nächste Woche"). Work it out from TODAY given in the request and return YYYY-MM-DD; otherwise
empty. A date that starts or ends a note ("21.03.2014 MBW…", "/ 15.02.18 BD") or says since when something applies
("ab 15.01.14", "Stand 27.05.2025") is when the note was written or took effect — NOT a due date.

TRANSCRIPT — a URL from the comment only if it is clearly a call/meeting transcript link; otherwise empty.

Reply with JSON only: {"escalation":"","categories":"","mainCategory":"","subCategory":"","nextStep":"","dueDate":"","transcript":""}"""


# The CATAGORIES line of AUTOFILL_GUIDE, as data: main category code → workflow ("General" for every other code).
MAIN_CATEGORY_CODES = {
    "lead", "item", "quote", "po", "order", "wh", "ship", "inv", "pay", "rma", "srv", "vend", "purq", "pord", "rcv",
    "qc", "cnt", "proj", "fcast", "iti", "mdm", "invn", "kit", "hse", "reg", "reb", "carr", "tend", "ins",
}
WORKFLOW_BY_MAIN_CATEGORY = {
    "quote": "W-Quote", "tend": "W-Quote", "lead": "W-Quote",
    "order": "W-Order", "po": "W-Order",
    "wh": "W-WH", "invn": "W-WH", "rcv": "W-WH", "kit": "W-WH",
    "ship": "W-Ship", "carr": "W-Ship",
    "inv": "W-Inv", "pay": "W-Inv", "reb": "W-Inv",
}


def autofill(body):
    def as_list(v):
        return [js_str(x) for x in v][:80] if isinstance(v, list) else []

    opts = as_dict(body.get("options"))
    options = {k: as_list(opts.get(k)) for k in ("escalation", "categories", "mainCategory", "subCategory", "nextStep")}
    examples = (body.get("examples") if isinstance(body.get("examples"), list) else [])[:8]
    request = {
        "instructions": "Fill mainCategory, subCategory, categories and escalation always; copy values exactly from allowedValues.",
        "today": js_str(body.get("today") or "")[:10],
        "weekday": js_str(body.get("weekday") or "")[:12],
        "deal": {"name": js_str(body.get("dealName") or "")[:200], "stage": js_str(body.get("dealStage") or "")[:100]},
        "allowedValues": options,
        "examplesFromThisDeal": examples,
        "comment": js_str(body.get("comment") or "")[:4000],
    }
    data = openai_chat(
        {
            "model": model(),
            "temperature": 0.1,
            "max_tokens": 300,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": AUTOFILL_GUIDE},
                {"role": "user", "content": to_json(request)},
            ],
        }
    )
    try:
        raw = as_dict(json.loads(js_str(openai_content(data) or "{}")))
    except ValueError:
        raw = {}

    # Keep only exact allowed values (case-insensitive match → the form's own spelling).
    def pick(val, allowed):
        want = js_str(val or "").strip().lower()
        return next((o for o in allowed if o.lower() == want), "")

    fields = {}
    for k, allowed in options.items():
        v = pick(raw.get(k), allowed)
        if v:
            fields[k] = v
    # Catagories is "always derived from the main category" (AUTOFILL_GUIDE); the model sometimes answers a different
    # one. Only for a main category named by its code, and only when the form offers the derived value.
    main = fields.get("mainCategory", "").lower()
    if main in MAIN_CATEGORY_CODES:
        workflow = pick(WORKFLOW_BY_MAIN_CATEGORY.get(main, "General"), options["categories"])
        if workflow:
            fields["categories"] = workflow
    due = raw.get("dueDate")
    if isinstance(due, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", due):
        fields["dueDate"] = due
    transcript = js_str(raw.get("transcript") or "")
    if re.match(r"https?://", transcript, re.I):
        fields["transcript"] = transcript[:500]
    return fields
