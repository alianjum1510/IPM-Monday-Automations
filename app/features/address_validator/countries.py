# HERE returns ISO 3166-1 alpha-3 codes ("DEU"); monday's country column takes
# alpha-2 plus a name ({"countryCode": "DE", "countryName": "Germany"}).
# English names, as monday shows them. A code not listed is not written.
_TABLE = """
AFG AF Afghanistan
ALA AX Åland Islands
ALB AL Albania
DZA DZ Algeria
ASM AS American Samoa
AND AD Andorra
AGO AO Angola
AIA AI Anguilla
ATA AQ Antarctica
ATG AG Antigua and Barbuda
ARG AR Argentina
ARM AM Armenia
ABW AW Aruba
AUS AU Australia
AUT AT Austria
AZE AZ Azerbaijan
BHS BS Bahamas
BHR BH Bahrain
BGD BD Bangladesh
BRB BB Barbados
BLR BY Belarus
BEL BE Belgium
BLZ BZ Belize
BEN BJ Benin
BMU BM Bermuda
BTN BT Bhutan
BOL BO Bolivia
BES BQ Bonaire, Sint Eustatius and Saba
BIH BA Bosnia and Herzegovina
BWA BW Botswana
BVT BV Bouvet Island
BRA BR Brazil
IOT IO British Indian Ocean Territory
VGB VG British Virgin Islands
BRN BN Brunei
BGR BG Bulgaria
BFA BF Burkina Faso
BDI BI Burundi
CPV CV Cabo Verde
KHM KH Cambodia
CMR CM Cameroon
CAN CA Canada
CYM KY Cayman Islands
CAF CF Central African Republic
TCD TD Chad
CHL CL Chile
CHN CN China
CXR CX Christmas Island
CCK CC Cocos (Keeling) Islands
COL CO Colombia
COM KM Comoros
COG CG Congo
COD CD Congo (Democratic Republic)
COK CK Cook Islands
CRI CR Costa Rica
CIV CI Côte d'Ivoire
HRV HR Croatia
CUB CU Cuba
CUW CW Curaçao
CYP CY Cyprus
CZE CZ Czech Republic
DNK DK Denmark
DJI DJ Djibouti
DMA DM Dominica
DOM DO Dominican Republic
ECU EC Ecuador
EGY EG Egypt
SLV SV El Salvador
GNQ GQ Equatorial Guinea
ERI ER Eritrea
EST EE Estonia
SWZ SZ Eswatini
ETH ET Ethiopia
FLK FK Falkland Islands
FRO FO Faroe Islands
FJI FJ Fiji
FIN FI Finland
FRA FR France
GUF GF French Guiana
PYF PF French Polynesia
ATF TF French Southern Territories
GAB GA Gabon
GMB GM Gambia
GEO GE Georgia
DEU DE Germany
GHA GH Ghana
GIB GI Gibraltar
GRC GR Greece
GRL GL Greenland
GRD GD Grenada
GLP GP Guadeloupe
GUM GU Guam
GTM GT Guatemala
GGY GG Guernsey
GIN GN Guinea
GNB GW Guinea-Bissau
GUY GY Guyana
HTI HT Haiti
HMD HM Heard Island and McDonald Islands
HND HN Honduras
HKG HK Hong Kong
HUN HU Hungary
ISL IS Iceland
IND IN India
IDN ID Indonesia
IRN IR Iran
IRQ IQ Iraq
IRL IE Ireland
IMN IM Isle of Man
ISR IL Israel
ITA IT Italy
JAM JM Jamaica
JPN JP Japan
JEY JE Jersey
JOR JO Jordan
KAZ KZ Kazakhstan
KEN KE Kenya
KIR KI Kiribati
KWT KW Kuwait
KGZ KG Kyrgyzstan
LAO LA Laos
LVA LV Latvia
LBN LB Lebanon
LSO LS Lesotho
LBR LR Liberia
LBY LY Libya
LIE LI Liechtenstein
LTU LT Lithuania
LUX LU Luxembourg
MAC MO Macao
MDG MG Madagascar
MWI MW Malawi
MYS MY Malaysia
MDV MV Maldives
MLI ML Mali
MLT MT Malta
MHL MH Marshall Islands
MTQ MQ Martinique
MRT MR Mauritania
MUS MU Mauritius
MYT YT Mayotte
MEX MX Mexico
FSM FM Micronesia
MDA MD Moldova
MCO MC Monaco
MNG MN Mongolia
MNE ME Montenegro
MSR MS Montserrat
MAR MA Morocco
MOZ MZ Mozambique
MMR MM Myanmar
NAM NA Namibia
NRU NR Nauru
NPL NP Nepal
NLD NL Netherlands
NCL NC New Caledonia
NZL NZ New Zealand
NIC NI Nicaragua
NER NE Niger
NGA NG Nigeria
NIU NU Niue
NFK NF Norfolk Island
PRK KP North Korea
MKD MK North Macedonia
MNP MP Northern Mariana Islands
NOR NO Norway
OMN OM Oman
PAK PK Pakistan
PLW PW Palau
PSE PS Palestine
PAN PA Panama
PNG PG Papua New Guinea
PRY PY Paraguay
PER PE Peru
PHL PH Philippines
PCN PN Pitcairn
POL PL Poland
PRT PT Portugal
PRI PR Puerto Rico
QAT QA Qatar
REU RE Réunion
ROU RO Romania
RUS RU Russia
RWA RW Rwanda
BLM BL Saint Barthélemy
SHN SH Saint Helena
KNA KN Saint Kitts and Nevis
LCA LC Saint Lucia
MAF MF Saint Martin
SPM PM Saint Pierre and Miquelon
VCT VC Saint Vincent and the Grenadines
WSM WS Samoa
SMR SM San Marino
STP ST Sao Tome and Principe
SAU SA Saudi Arabia
SEN SN Senegal
SRB RS Serbia
SYC SC Seychelles
SLE SL Sierra Leone
SGP SG Singapore
SXM SX Sint Maarten
SVK SK Slovakia
SVN SI Slovenia
SLB SB Solomon Islands
SOM SO Somalia
ZAF ZA South Africa
SGS GS South Georgia and the South Sandwich Islands
KOR KR South Korea
SSD SS South Sudan
ESP ES Spain
LKA LK Sri Lanka
SDN SD Sudan
SUR SR Suriname
SJM SJ Svalbard and Jan Mayen
SWE SE Sweden
CHE CH Switzerland
SYR SY Syria
TWN TW Taiwan
TJK TJ Tajikistan
TZA TZ Tanzania
THA TH Thailand
TLS TL Timor-Leste
TGO TG Togo
TKL TK Tokelau
TON TO Tonga
TTO TT Trinidad and Tobago
TUN TN Tunisia
TUR TR Turkey
TKM TM Turkmenistan
TCA TC Turks and Caicos Islands
TUV TV Tuvalu
UGA UG Uganda
UKR UA Ukraine
ARE AE United Arab Emirates
GBR GB United Kingdom
USA US United States
UMI UM United States Minor Outlying Islands
URY UY Uruguay
VIR VI U.S. Virgin Islands
UZB UZ Uzbekistan
VUT VU Vanuatu
VAT VA Vatican City
VEN VE Venezuela
VNM VN Vietnam
WLF WF Wallis and Futuna
ESH EH Western Sahara
YEM YE Yemen
ZMB ZM Zambia
ZWE ZW Zimbabwe
"""

ALPHA3 = {
    alpha3: {"countryCode": alpha2, "countryName": name}
    for alpha3, alpha2, name in (line.split(" ", 2) for line in _TABLE.strip().splitlines())
}


def country_value(alpha3):
    """monday's country column value for a HERE countryCode, or "" when unknown."""
    value = ALPHA3.get(str(alpha3 or "").strip().upper())
    return dict(value) if value else ""
