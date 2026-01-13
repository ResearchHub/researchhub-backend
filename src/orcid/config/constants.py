ORCID_BASE_URL = "https://orcid.org"
ORCID_API_URL = "https://pub.orcid.org"
STATE_MAX_AGE = 600
APPLICATION_JSON = "application/json"
EDU_DOMAINS = (
    # Generic TLDs - Education
    ".edu",
    ".education",
    ".college",
    ".university",
    ".school",
    ".academy",
    ".institute",
    ".training",
    ".courses",
    ".study",
    # Generic TLDs - Research & Science
    ".science",
    ".research",
    ".scholar",
    ".phd",
    ".professor",
    ".mba",
    ".degree",
    # Generic TLDs - Knowledge
    ".learning",
    ".teachers",
    ".kindergarten",
    ".preschool",
    # Government (often includes research institutions)
    ".gov",
    # Americas
    ".edu.us",  # United States
    ".edu.ca",  # Canada
    ".edu.mx",  # Mexico
    ".edu.br",  # Brazil
    ".edu.ar",  # Argentina
    ".edu.cl",  # Chile
    ".edu.co",  # Colombia
    ".edu.pe",  # Peru
    ".edu.ve",  # Venezuela
    ".edu.ec",  # Ecuador
    ".edu.bo",  # Bolivia
    ".edu.py",  # Paraguay
    ".edu.uy",  # Uruguay
    ".edu.gt",  # Guatemala
    ".edu.hn",  # Honduras
    ".edu.sv",  # El Salvador
    ".edu.ni",  # Nicaragua
    ".edu.cr",  # Costa Rica
    ".edu.pa",  # Panama
    ".edu.cu",  # Cuba
    ".edu.do",  # Dominican Republic
    ".edu.pr",  # Puerto Rico
    ".edu.jm",  # Jamaica
    ".edu.tt",  # Trinidad and Tobago
    ".edu.bb",  # Barbados
    ".edu.gy",  # Guyana
    ".edu.sr",  # Suriname
    # Europe - UK & Ireland
    ".ac.uk",  # United Kingdom
    ".edu.ie",  # Ireland
    # Europe - Western
    ".edu.fr",  # France
    ".edu.de",  # Germany
    ".edu.nl",  # Netherlands
    ".edu.be",  # Belgium
    ".edu.lu",  # Luxembourg
    ".edu.ch",  # Switzerland
    ".edu.at",  # Austria
    # Europe - Southern
    ".edu.es",  # Spain
    ".edu.pt",  # Portugal
    ".edu.it",  # Italy
    ".edu.gr",  # Greece
    ".edu.mt",  # Malta
    ".edu.cy",  # Cyprus
    # Europe - Nordic
    ".edu.se",  # Sweden
    ".edu.no",  # Norway
    ".edu.dk",  # Denmark
    ".edu.fi",  # Finland
    ".edu.is",  # Iceland
    # Europe - Eastern
    ".edu.pl",  # Poland
    ".edu.cz",  # Czech Republic
    ".edu.sk",  # Slovakia
    ".edu.hu",  # Hungary
    ".edu.ro",  # Romania
    ".edu.bg",  # Bulgaria
    ".edu.hr",  # Croatia
    ".edu.si",  # Slovenia
    ".edu.rs",  # Serbia
    ".edu.ba",  # Bosnia and Herzegovina
    ".edu.mk",  # North Macedonia
    ".edu.al",  # Albania
    ".edu.me",  # Montenegro
    ".edu.xk",  # Kosovo
    # Europe - Baltic
    ".edu.ee",  # Estonia
    ".edu.lv",  # Latvia
    ".edu.lt",  # Lithuania
    # Europe - Eastern (former Soviet)
    ".edu.ru",  # Russia
    ".edu.ua",  # Ukraine
    ".edu.by",  # Belarus
    ".edu.md",  # Moldova
    ".edu.ge",  # Georgia
    ".edu.am",  # Armenia
    ".edu.az",  # Azerbaijan
    # Asia - East
    ".ac.jp",  # Japan
    ".edu.cn",  # China
    ".ac.kr",  # South Korea
    ".edu.tw",  # Taiwan
    ".edu.hk",  # Hong Kong
    ".edu.mo",  # Macau
    ".edu.mn",  # Mongolia
    # Asia - Southeast
    ".edu.sg",  # Singapore
    ".edu.my",  # Malaysia
    ".ac.id",  # Indonesia
    ".edu.ph",  # Philippines
    ".ac.th",  # Thailand
    ".edu.vn",  # Vietnam
    ".edu.mm",  # Myanmar
    ".edu.kh",  # Cambodia
    ".edu.la",  # Laos
    ".edu.bn",  # Brunei
    # Asia - South
    ".edu.in",  # India
    ".ac.in",  # India (alternate)
    ".edu.pk",  # Pakistan
    ".edu.bd",  # Bangladesh
    ".edu.lk",  # Sri Lanka
    ".edu.np",  # Nepal
    ".edu.bt",  # Bhutan
    ".edu.mv",  # Maldives
    ".edu.af",  # Afghanistan
    # Asia - Central
    ".edu.kz",  # Kazakhstan
    ".edu.uz",  # Uzbekistan
    ".edu.tm",  # Turkmenistan
    ".edu.kg",  # Kyrgyzstan
    ".edu.tj",  # Tajikistan
    # Middle East
    ".edu.tr",  # Turkey
    ".ac.il",  # Israel
    ".edu.sa",  # Saudi Arabia
    ".ac.ae",  # United Arab Emirates
    ".edu.ae",  # United Arab Emirates (alternate)
    ".edu.qa",  # Qatar
    ".edu.kw",  # Kuwait
    ".edu.bh",  # Bahrain
    ".edu.om",  # Oman
    ".edu.ye",  # Yemen
    ".edu.jo",  # Jordan
    ".edu.lb",  # Lebanon
    ".edu.sy",  # Syria
    ".edu.iq",  # Iraq
    ".edu.ir",  # Iran
    # Africa - North
    ".edu.eg",  # Egypt
    ".ac.ma",  # Morocco
    ".edu.dz",  # Algeria
    ".edu.tn",  # Tunisia
    ".edu.ly",  # Libya
    ".edu.sd",  # Sudan
    # Africa - West
    ".edu.ng",  # Nigeria
    ".edu.gh",  # Ghana
    ".edu.ci",  # Ivory Coast
    ".edu.sn",  # Senegal
    ".edu.ml",  # Mali
    ".edu.bf",  # Burkina Faso
    ".edu.ne",  # Niger
    ".edu.gn",  # Guinea
    ".edu.sl",  # Sierra Leone
    ".edu.lr",  # Liberia
    ".edu.tg",  # Togo
    ".edu.bj",  # Benin
    ".edu.gm",  # Gambia
    ".edu.gw",  # Guinea-Bissau
    ".edu.cv",  # Cape Verde
    ".edu.mr",  # Mauritania
    # Africa - East
    ".ac.ke",  # Kenya
    ".ac.tz",  # Tanzania
    ".ac.ug",  # Uganda
    ".edu.et",  # Ethiopia
    ".ac.rw",  # Rwanda
    ".edu.rw",  # Rwanda (alternate)
    ".edu.bi",  # Burundi
    ".edu.so",  # Somalia
    ".edu.dj",  # Djibouti
    ".edu.er",  # Eritrea
    ".edu.ss",  # South Sudan
    # Africa - Southern
    ".ac.za",  # South Africa
    ".edu.za",  # South Africa (alternate)
    ".ac.zw",  # Zimbabwe
    ".edu.zm",  # Zambia
    ".ac.mw",  # Malawi
    ".ac.mz",  # Mozambique
    ".ac.bw",  # Botswana
    ".edu.na",  # Namibia
    ".ac.ls",  # Lesotho
    ".ac.sz",  # Eswatini (Swaziland)
    ".ed.ao",  # Angola
    # Africa - Central
    ".edu.cm",  # Cameroon
    ".edu.cd",  # Democratic Republic of the Congo
    ".edu.cg",  # Republic of the Congo
    ".edu.ga",  # Gabon
    ".edu.gq",  # Equatorial Guinea
    ".edu.cf",  # Central African Republic
    ".edu.td",  # Chad
    # Africa - Islands
    ".ac.mu",  # Mauritius
    ".edu.mg",  # Madagascar
    ".ac.sc",  # Seychelles
    ".edu.km",  # Comoros
    ".edu.st",  # Sao Tome and Principe
    # Oceania
    ".edu.au",  # Australia
    ".ac.nz",  # New Zealand
    ".edu.nz",  # New Zealand (alternate)
    ".edu.fj",  # Fiji
    ".edu.pg",  # Papua New Guinea
    ".edu.ws",  # Samoa
    ".edu.to",  # Tonga
    ".edu.vu",  # Vanuatu
    ".edu.sb",  # Solomon Islands
    # Caribbean (additional)
    ".edu.bs",  # Bahamas
    ".edu.ht",  # Haiti
    ".edu.ag",  # Antigua and Barbuda
    ".edu.lc",  # Saint Lucia
    ".edu.vc",  # Saint Vincent and the Grenadines
    ".edu.gd",  # Grenada
    ".edu.dm",  # Dominica
    ".edu.kn",  # Saint Kitts and Nevis
)
