"""Review categories, how much they are worth, and what a good review must check.

rpm / evergreen / topics are 1-5 scores taken from your category table:
  Very high = 5, High = 4  |  stars as given  |  Massive = 5, Huge = 4
Tune `weight_boost` to steer the channel (1.0 = neutral, 1.3 = more of this, 0.5 = less).
"""

CATEGORIES = [
    {
        "id": "credit-cards", "emoji": "💳", "name": "Credit cards / financial products",
        "rpm": 5, "evergreen": 5, "topics": 4, "weight_boost": 1.0,
        "news_queries": ["new credit card launch", "credit card new rewards program",
                         "buy now pay later app launch"],
        "appstore_genre": None,
        "subpage_words": ["rates", "fees", "rewards", "apr", "terms", "pricing", "compare"],
        "checklist": ["APR range and how it is disclosed", "annual and foreign transaction fees",
                      "rewards structure and caps", "credit score needed / soft-pull pre-approval",
                      "issuer bank and where the full terms are"],
    },
    {
        "id": "insurance", "emoji": "🛡️", "name": "Insurance",
        "rpm": 5, "evergreen": 5, "topics": 4, "weight_boost": 1.0,
        "news_queries": ["insurtech launch", "new insurance app", "insurance startup raises"],
        "appstore_genre": None,
        "subpage_words": ["coverage", "claims", "quote", "pricing", "how-it-works", "faq", "states"],
        "checklist": ["types of coverage offered", "how quotes work and what data is required",
                      "claims process", "states where it is available",
                      "underwriter / licensed carrier named on the site"],
    },
    {
        "id": "banking-apps", "emoji": "💰", "name": "Finance apps / banking",
        "rpm": 5, "evergreen": 5, "topics": 4, "weight_boost": 1.0,
        "news_queries": ["fintech app launch", "neobank launch", "new high yield savings account",
                         "banking app new feature"],
        "appstore_genre": 6015,
        "subpage_words": ["fees", "rates", "savings", "checking", "security", "pricing", "faq"],
        "checklist": ["APY / rates and whether they are promotional", "monthly, ATM and overdraft fees",
                      "FDIC insurance and the partner bank if it is a fintech",
                      "how to deposit and withdraw cash", "customer support options"],
    },
    {
        "id": "investing", "emoji": "📈", "name": "Investing platforms",
        "rpm": 5, "evergreen": 5, "topics": 4, "weight_boost": 1.0,
        "news_queries": ["investing app launch", "robo advisor new", "brokerage launches",
                         "crypto exchange US launch"],
        "appstore_genre": 6015,
        "subpage_words": ["pricing", "fees", "invest", "accounts", "security", "disclosures"],
        "checklist": ["fees and commissions", "account minimums", "SIPC/FINRA membership",
                      "available assets and account types (IRA etc.)", "risk disclosures"],
    },
    {
        "id": "real-estate", "emoji": "🏠", "name": "Real estate services",
        "rpm": 4, "evergreen": 5, "topics": 4, "weight_boost": 1.0,
        "news_queries": ["real estate platform launch", "proptech startup", "new mortgage app",
                         "home buying app launch"],
        "appstore_genre": None,
        "subpage_words": ["pricing", "fees", "how-it-works", "sell", "buy", "mortgage", "faq"],
        "checklist": ["commissions or fees and who pays them", "markets/states covered",
                      "licensing (brokerage, NMLS for lenders)", "how the process works step by step",
                      "data accuracy and listing sources"],
    },
    {
        "id": "legal", "emoji": "⚖️", "name": "Legal services / platforms",
        "rpm": 4, "evergreen": 5, "topics": 4, "weight_boost": 1.0,
        "news_queries": ["online legal services launch", "legal tech startup", "AI legal app"],
        "appstore_genre": None,
        "subpage_words": ["pricing", "plans", "attorney", "how-it-works", "faq", "states"],
        "checklist": ["prices and what each package includes", "whether real attorneys review work",
                      "states covered", "refund policy", "the 'not a law firm' disclaimer, if any"],
    },
    {
        "id": "saas", "emoji": "💻", "name": "SaaS / business software",
        "rpm": 4, "evergreen": 5, "topics": 5, "weight_boost": 1.0,
        "news_queries": ["SaaS launch", "startup launches platform for businesses",
                         "new software for small business"],
        "appstore_genre": 6000,
        "subpage_words": ["pricing", "plans", "features", "integrations", "security", "customers"],
        "checklist": ["pricing tiers and the real cost per user", "free plan or trial limits",
                      "key features vs main competitors", "integrations", "data security/compliance"],
    },
    {
        "id": "ai-tools", "emoji": "🤖", "name": "AI tools",
        "rpm": 4, "evergreen": 4, "topics": 5, "weight_boost": 1.1,
        "news_queries": ["AI tool launch", "new AI app", "AI startup launches", "generative AI product launch"],
        "appstore_genre": 6007,
        "subpage_words": ["pricing", "plans", "features", "privacy", "use-cases", "faq"],
        "checklist": ["what it actually does vs the marketing", "pricing and credit/usage limits",
                      "free tier", "privacy: is your data used for training", "who it is useful for"],
    },
    {
        "id": "business-tools", "emoji": "📊", "name": "Business tools",
        "rpm": 4, "evergreen": 5, "topics": 5, "weight_boost": 1.0,
        "news_queries": ["small business tool launch", "payroll app launch", "invoicing app new",
                         "accounting software launch"],
        "appstore_genre": 6000,
        "subpage_words": ["pricing", "plans", "features", "integrations", "support"],
        "checklist": ["pricing and add-on costs", "setup effort", "core features",
                      "integrations (accounting, banking)", "support and contract terms"],
    },
    {
        "id": "marketing", "emoji": "📣", "name": "Marketing platforms",
        "rpm": 4, "evergreen": 5, "topics": 5, "weight_boost": 1.0,
        "news_queries": ["marketing platform launch", "email marketing tool new", "SEO tool launch",
                         "social media management tool launch"],
        "appstore_genre": None,
        "subpage_words": ["pricing", "plans", "features", "integrations", "templates"],
        "checklist": ["pricing by contacts/seats", "free plan limits", "main features",
                      "integrations", "how easy it is to start"],
    },
    {
        "id": "vpn-security", "emoji": "🔐", "name": "Cybersecurity / VPNs",
        "rpm": 4, "evergreen": 5, "topics": 4, "weight_boost": 1.0,
        "news_queries": ["VPN launch", "password manager new", "cybersecurity app launch",
                         "identity theft protection service"],
        "appstore_genre": 6007,
        "subpage_words": ["pricing", "privacy", "no-logs", "features", "servers", "security", "audit"],
        "checklist": ["price after the intro deal / renewal price", "no-logs claims and independent audits",
                      "jurisdiction / company location", "device limits", "money-back guarantee"],
    },
    {
        "id": "hosting", "emoji": "☁️", "name": "Cloud / hosting",
        "rpm": 4, "evergreen": 5, "topics": 4, "weight_boost": 1.0,
        "news_queries": ["web hosting launch", "cloud platform launch developers",
                         "website builder launch"],
        "appstore_genre": None,
        "subpage_words": ["pricing", "plans", "features", "hosting", "domains", "support"],
        "checklist": ["intro price vs renewal price", "what each plan includes (sites, storage, SSL, backups)",
                      "uptime guarantee", "support channels", "money-back guarantee"],
    },
    {
        "id": "freelancing", "emoji": "💼", "name": "Freelancing platforms",
        "rpm": 4, "evergreen": 5, "topics": 4, "weight_boost": 1.0,
        "news_queries": ["freelance platform launch", "gig marketplace new", "creator economy platform launch"],
        "appstore_genre": 6000,
        "subpage_words": ["fees", "pricing", "how-it-works", "payments", "trust", "faq"],
        "checklist": ["service fees for freelancers and clients", "how and when payouts happen",
                      "payment protection / disputes", "who it suits (beginners vs experts)",
                      "competition on the platform"],
    },
]

BY_ID = {c["id"]: c for c in CATEGORIES}


def weight(cat_id):
    """0..1 money+evergreen weight of a category."""
    c = BY_ID.get(cat_id)
    if not c:
        return 0.4
    raw = (c["rpm"] * 0.5 + c["evergreen"] * 0.3 + c["topics"] * 0.2) / 5
    return min(1.0, raw * c.get("weight_boost", 1.0))


def describe_for_ai():
    return "\n".join(f"- {c['id']}: {c['name']}" for c in CATEGORIES)
