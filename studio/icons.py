"""Icons (Google Material Icons font, Apache 2.0, bundled in assets/fonts) picked from keywords.

The script writer may name an icon for each segment; otherwise one is guessed from the caption and
narration. Only names in ICONS can be drawn.
"""
import re

from PIL import Image, ImageDraw, ImageFont

from . import config

FONT_FILE = config.ASSETS_DIR / "fonts" / "MaterialIcons-Regular.ttf"

ICONS = {   # name -> codepoint (from MaterialIcons-Regular.codepoints)
    "attach_money": 0xe227, "payments": 0xef63, "savings": 0xe2eb, "lock": 0xe897,
    "shield": 0xe9e0, "verified_user": 0xe8e8, "security": 0xe32a, "bolt": 0xea0b,
    "speed": 0xe9e4, "support_agent": 0xf0e2, "smartphone": 0xe32c, "account_balance": 0xe84f,
    "credit_card": 0xe870, "warning": 0xe002, "check_circle": 0xe86c, "cancel": 0xe5c9,
    "thumb_up": 0xe8dc, "thumb_down": 0xe8db, "star": 0xe838, "schedule": 0xe8b5,
    "redeem": 0xe8b1, "auto_awesome": 0xe65f, "smart_toy": 0xf06c, "trending_up": 0xe8e5,
    "show_chart": 0xe6e1, "health_and_safety": 0xe1d5, "home": 0xe88a, "gavel": 0xe90e,
    "balance": 0xeaf6, "mail": 0xe158, "campaign": 0xef49, "cloud": 0xe2bd, "dns": 0xe875,
    "public": 0xe80b, "group": 0xe7ef, "person": 0xe7fd, "rocket_launch": 0xeb9b,
    "help": 0xe887, "visibility": 0xe8f4, "search": 0xe8b6, "receipt_long": 0xef6e,
    "percent": 0xeb58, "sell": 0xf05b, "workspace_premium": 0xe7af, "emoji_events": 0xea23,
    "block": 0xe14b, "lightbulb": 0xe0f0, "bar_chart": 0xe26b, "devices": 0xe1b1,
    "laptop": 0xe31e, "vpn_key": 0xe0da, "wifi": 0xe63e, "apartment": 0xea40,
    "work": 0xe8f9, "storefront": 0xea12, "shopping_cart": 0xe8cc, "school": 0xe80c,
    "favorite": 0xe87d, "forum": 0xe0bf, "reviews": 0xf054, "event": 0xe878, "build": 0xe869,
    "tune": 0xe429, "privacy_tip": 0xf0dc, "policy": 0xea17, "fingerprint": 0xe90d,
    "key": 0xe73c, "fact_check": 0xf0c5, "travel_explore": 0xe2db, "description": 0xe873,
    "check": 0xe5ca, "close": 0xe5cd, "priority_high": 0xe645, "local_fire_department": 0xef55,
    "new_releases": 0xe031, "verified": 0xef76, "zoom_in": 0xe8ff,
}

# keyword (regex, matched on lowercase text) -> icon. First match wins, so order = priority.
KEYWORDS = [
    (r"hidden fee|catch|warning|watch out|red flag|risk|beware|careful|downside|complain", "warning"),
    (r"\bfree\b|no fee|\$0|zero fee|bonus|reward|cash ?back|perk", "redeem"),
    (r"price|pricing|cost|\bfee|\$|per month|/mo|subscription|plan\b|plans\b|cheap|expensive", "payments"),
    (r"apy|interest|savings|save money|saving", "savings"),
    (r"\d+(\.\d+)? ?%|percent|\brate\b|rates\b", "percent"),
    (r"credit card|debit card|\bcard\b", "credit_card"),
    (r"\bbank|banking|fdic|deposit|checking", "account_balance"),
    (r"invest|stock|portfolio|returns|crypto|trading|etf|market", "trending_up"),
    (r"insur|coverage|claim|policy holder|premium", "health_and_safety"),
    (r"encrypt|secur|protect|safe\b|safety|fraud|scam", "shield"),
    (r"privacy|tracking|data collection|logs?\b", "privacy_tip"),
    (r"vpn|server|connection|wi-?fi", "vpn_key"),
    (r"password|login|sign[- ]?in|2fa|two-factor|authentic", "fingerprint"),
    (r"legal|lawyer|attorney|law\b|contract|will\b|llc|court|lawsuit", "gavel"),
    (r"licen[cs]e|regulat|compliance|registered|verified|legit|trust", "verified_user"),
    (r"\bai\b|artificial intelligence|gpt|chatbot|machine learning", "auto_awesome"),
    (r"host|domain|website builder|uptime|cloud|storage", "cloud"),
    (r"email|newsletter|inbox", "mail"),
    (r"marketing|campaign|ads\b|advertis|seo|social media", "campaign"),
    (r"house|home|mortgage|rent|real estate|property|apartment", "home"),
    (r"freelanc|job|hire|hiring|gig|client|career|work\b", "work"),
    (r"shop|store|ecommerce|e-commerce|checkout|cart", "storefront"),
    (r"app\b|mobile|phone|ios|android", "smartphone"),
    (r"support|customer service|help desk|live chat|agent", "support_agent"),
    (r"fast|speed|quick|instant|seconds|minutes", "bolt"),
    (r"review|rating|stars?\b|trustpilot|reddit|users say|people say", "reviews"),
    (r"team|users|people|community|members|families", "group"),
    (r"launch|new\b|startup|funding|raised", "rocket_launch"),
    (r"feature|tool|dashboard|integrat|automat", "tune"),
    (r"compare|versus|\bvs\b|competitor|alternative", "balance"),
    (r"verdict|worth it|score|winner|best", "emoji_events"),
    (r"terms|fine print|disclos|small print", "receipt_long"),
    (r"question|\?$|faq", "help"),
    (r"pro\b|pros\b|strength|good|great|love", "thumb_up"),
    (r"con\b|cons\b|weak|bad|missing|lack", "thumb_down"),
]


def available():
    return FONT_FILE.exists()


def pick(seg):
    """Icon name for a segment: the writer's choice if valid, else keyword match, else None."""
    named = (seg.get("icon") or "").strip().lower().replace(" ", "_")
    if named in ICONS:
        return named
    for text in (seg.get("callout", ""), seg.get("caption", ""), seg.get("text", "")):
        t = (text or "").lower()
        for pattern, icon in KEYWORDS:
            if re.search(pattern, t):
                return icon
    return None


_fonts = {}


def glyph(name, size, color):
    """Transparent RGBA image of one icon, tightly cropped."""
    if name not in ICONS or not available():
        return None
    if size not in _fonts:
        _fonts[size] = ImageFont.truetype(str(FONT_FILE), size)
    im = Image.new("RGBA", (int(size * 1.4), int(size * 1.4)), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((im.width / 2, im.height / 2), chr(ICONS[name]), font=_fonts[size],
                            fill=(*color[:3], 255), anchor="mm")
    box = im.getbbox()
    return im.crop(box) if box else None


def badge(name, size, bg, fg, shape="circle"):
    """Icon centred on a filled circle or rounded square."""
    g = glyph(name, int(size * 0.58), fg)
    if g is None:
        return None
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if shape == "circle":
        d.ellipse([0, 0, size - 1, size - 1], fill=(*bg[:3], 255))
    else:
        d.rounded_rectangle([0, 0, size - 1, size - 1], size // 4, fill=(*bg[:3], 255))
    im.alpha_composite(g, ((size - g.width) // 2, (size - g.height) // 2))
    return im
