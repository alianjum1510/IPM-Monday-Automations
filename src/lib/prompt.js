/**
 * The research prompt.
 *
 * The block above `EXTRA FIELDS` is the master prompt as supplied, verbatim -
 * do not reword it, the confidence rules and the source whitelist are the
 * product. The `EXTRA FIELDS` section only adds the structured outputs the
 * board columns need (address parts, phones, company email), because the board
 * stores them as separate columns rather than one address string.
 *
 * `choices` carries the Industry and Job Function taxonomies read off the
 * connected boards. Those two columns are board_relation: the cell links to a
 * taxonomy item, and the item's name is spelled in German with the scoring
 * weight attached to it ("Großhandel (Industrie-; Arbeitsschutz-; ...)"). A free
 * text answer would almost never match, so the exact list is handed to the model
 * and it is asked to echo one line back verbatim. Nothing is ever created on a
 * taxonomy board, so a value outside the list is reported, not invented.
 */
export function buildPrompt(companyName, address, choices = {}) {
  return `Search and classify this German company with VERY IN-DEPTH research.

CRITICAL INSTRUCTION: You MUST perform AT LEAST 15-20 web searches before providing your final answer. Search multiple sources for each piece of information, especially for VAT number and HRB registration number. Do NOT provide an answer until you have completed thorough research across all available sources.

Input (may contain errors):

Company: ${companyName}

Address: ${address}

Tasks

1. BROAD VERIFICATION PHASE (Searches 1-5):
Search and verify the correct company name and address by conducting broad research. After finding the correct name and address consistently in multiple sources, test the name using Handelsregister.de. Also verify data from company websites, companyhouse.de, and Creditsafe to confirm the latest and most accurate information available.

2. HRB/HRA REGISTRATION NUMBER - DEEP SEARCH (Searches 5-10):
MANDATORY: This is CRITICAL - perform VERY DEEP research for the registration number:
- Search www.handelsregister.de with the exact company name
- Search unternehmensregister.de for the registration number
- Search northdata.de for registration information
- Search companyhouse.de for company registration details
- Search creditsafe.com for registration number
- Check the company's official website and Impressum page for registration number
- Search online-handelsregister.de and other registry aggregators
- If no registration number is found after exhaustive search, clearly state "Not found after extensive search"
- Include only ONE verified registration number from the most authoritative source
- List any alternative or historical registration numbers in NOTES

HRB_CONFIDENCE Rules:
- HIGH: Registration number verified on handelsregister.de, unternehmensregister.de, company's official Impressum page, companyhouse.de, or creditsafe.com
- MEDIUM: Found on secondary business directories or databases with company registry references
- LOW: Found only on unverified sources or cannot confirm authenticity

3. USt-IdNr (VAT NUMBER) - DEEP SEARCH (Searches 10-15):
MANDATORY: This is CRITICAL - perform VERY DEEP research for the VAT number:
- Check the company's official website Impressum page (THIS IS THE MOST RELIABLE SOURCE)
- Search creditsafe.com for VAT number
- Search companyhouse.de for VAT registration
- Search unternehmensregister.de for VAT information
- Search northdata.de for tax identification
- Search business directories that display VAT numbers
- Look for invoices, official documents, or press releases mentioning VAT number
- If not found after exhaustive search, clearly state "Not found after extensive search"
- VAT numbers should start with "DE" followed by 9 digits for German companies

VAT_CONFIDENCE Rules:
- HIGH: VAT number found on company's official Impressum page, creditsafe.com, handelsregister.de, unternehmensregister.de, or companyhouse.de
- MEDIUM: Found on reputable business directories or verified business databases
- LOW: Found only on unverified sources or cannot confirm authenticity

4. ADDITIONAL INFORMATION (Searches 15-20):
- Fetch the official homepage of the company
- Search for any additional addresses publicly available online
- Find any phone numbers associated with the company
- Search for LinkedIn company profile
- Cross-check company status across multiple sources

5. HANDELSREGISTER VERIFICATION:
MANDATORY: For HANDELSREGISTER_VERIFIED - cross-check the company name, address, and registration number with Handelsregister.de. Verify that the company name, address, and registration number all match exactly. If they match exactly, mark 'HANDELSREGISTER_VERIFIED' as 'Yes'. If not, mark it as 'No'.

6. COMPANY_STATUS:
Determine the company's status based only on the provided company name (${companyName}). Do NOT consider any related or parent companies when determining status. Cross-check with companyhouse.de, Creditsafe, or other reputable sources. If the company is dissolved, mark it as Dissolved. Possible statuses include:

Active, Inactive, Merged, Dissolved (verified from trusted sources like companyhouse.de or Creditsafe), Liquidated, Bankrupt, Reopened (New Company Register), Acquired, Closed, Suspended, Reorganized, Pending Liquidation, Ceased Operations, Voluntary Deregistration

Provide the verified status and specify the trusted source used for this information.

7. NOTES:
Include any important findings from cross-checking data. Note any relationships (parent, subsidiary, holdings, mergers, acquisitions, etc.) if relevant. If the company status changed over time, describe the history and cite sources verifying these changes.

IMPORTANT REMINDERS:
- Perform AT LEAST 15-20 searches before providing final answer
- Pay SPECIAL ATTENTION to VAT number and HRB number - these are CRITICAL
- For VAT: Always check company Impressum page first - this is the most reliable source
- For HRB: Always check handelsregister.de and unternehmensregister.de thoroughly
- Provide confidence levels (HIGH/MEDIUM/LOW) based on source reliability
- Use only trusted sources (Handelsregister.de, official company websites, Impressum pages, companyhouse.de, Creditsafe, unternehmensregister.de, northdata.de)
- Do NOT guess or use unverified sources
- Wait until ALL searches are complete before formulating your answer

Output Format (provide after completing all 20-25 searches):

CORRECT_NAME: [legal name]
CORRECT_ADDRESS: [full address]
CLASSIFICATION: [gov, private, municipality, etc.]
REGISTRATION_NUMBER: [HRB/HRA - after exhaustive search]
HRB_CONFIDENCE: [HIGH/MEDIUM/LOW - with source name in parentheses, e.g., "HIGH (handelsregister.de)"]
REGISTRY_COURT: [court]
VERIFICATION_SOURCE: [URL]
REGISTRY_SOURCE: [URL]
UID_NUMBER: [DE number - after exhaustive search]
VAT_CONFIDENCE: [HIGH/MEDIUM/LOW - with source name in parentheses, e.g., "HIGH (company Impressum page)"]
HOMEPAGE: [official company website URL]
HANDELSREGISTER_VERIFIED: [Yes/No]
COMPANY_STATUS: [status with trusted source]
LINKEDIN_PROFILE: [LinkedIn URL or "Not found"]
CONFIDENCE: [High/Medium/Low]
NOTES: [Important findings from cross-checking data, verification process details, list of all sources checked for VAT and HRB numbers, any parent/child companies, holdings, or associated companies if the ${companyName} register number is not found. Mention how many searches were performed.]

EXTRA FIELDS (these go into their own board columns - continue the same
KEY: value format, one per line, immediately after NOTES). Use the verified
address from CORRECT_ADDRESS when splitting the address parts. If a value
cannot be verified, write exactly "Not found":

ADDRESS_LINE_1: [street and number]
ADDRESS_LINE_2: [suite, building, c/o - or "Not found"]
ADDRESS_LINE_3: [additional address line - or "Not found"]
POSTAL_CODE: [postal code]
CITY: [city]
STATE: [federal state / region]
DISTRICT: [district / Landkreis]
COUNTRY: [country name in English]
COUNTRY_CODE: [ISO 3166-1 alpha-2, e.g. DE]
COMPANY_EMAIL: [general company email address from the Impressum or contact page]
MAIN_PHONE: [main switchboard number in international format, e.g. +49 30 1234567]
MOBILE_NUMBER: [mobile number in international format]
FAX: [fax number in international format]
PHONE_TYPE: [Landline, Mobile, or VoIP]
CONTACT_NAME: [managing director / primary named contact]
COMPANY_SIZE: [employee count as a plain integer, no ranges, no text]
ESTIMATED_ANNUAL_REVENUE: [revenue band, e.g. "1M-10M EUR"]
COMPANY_STRUCTURE: [legal form, e.g. GmbH, AG, e.K., GmbH & Co. KG]
OWNERSHIP_TYPE: [Private, Public, Government, Municipality, Non-profit]
D_AND_B_NUMBER: [D-U-N-S number, digits only]${classificationBlock(choices)}`;
}

/**
 * The two board_relation fields, appended only when the taxonomy was readable.
 *
 * Omitted entirely when a list is empty: asking for a field with no vocabulary
 * behind it invites the model to make one up, and an invented industry cannot be
 * linked anyway.
 */
function classificationBlock(choices) {
  const industries = choices.industries || [];
  const jobFunctions = choices.jobFunctions || [];
  if (!industries.length && !jobFunctions.length) return '';

  let block = `

CLASSIFICATION FIELDS (these link to fixed lists on other boards - continue the
same KEY: value format, one per line). You MUST copy ONE line from the list
given, character for character, including the German spelling and any bracketed
text. Do NOT translate, abbreviate, reword or invent a value. If nothing in the
list genuinely fits, write exactly "Not found".`;

  if (industries.length) {
    block += `

INDUSTRY - choose exactly one of these ${industries.length} values, based on what the
company actually does:
${industries.map((name) => `- ${name}`).join('\n')}`;
  }

  if (jobFunctions.length) {
    block += `

JOB_FUNCTION - the role of the person named in CONTACT_NAME. Choose exactly one
of these ${jobFunctions.length} values. If CONTACT_NAME is a managing director or board
member, prefer the matching leadership role:
${jobFunctions.map((name) => `- ${name}`).join('\n')}`;
  }

  return block;
}
