from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from .catalog import CATALOG, PAYMENT_METHODS
from .i18n import t


def main_keyboard(lang="fr"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "catalog_btn"), callback_data="catalog"),
         InlineKeyboardButton(t(lang, "ai_btn"), callback_data="ai")],
        [InlineKeyboardButton(t(lang, "support_btn"), callback_data="support")],
        [InlineKeyboardButton(t(lang, "human"), callback_data="human")],
    ])


def ai_mode_keyboard(lang="fr"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "mode_text_btn"), callback_data="mode:text")],
        [InlineKeyboardButton(t(lang, "mode_voice_btn"), callback_data="mode:voice")],
        [InlineKeyboardButton(t(lang, "back"), callback_data="home")],
    ])


def operators_keyboard(lang="fr"):
    rows = [[InlineKeyboardButton(CATALOG[key]["label"], callback_data=f"operator:{key}")]
            for key in CATALOG]
    rows.append([InlineKeyboardButton(t(lang, "back"), callback_data="home")])
    return InlineKeyboardMarkup(rows)


def offers_keyboard(operator, lang="fr"):
    rows = [[InlineKeyboardButton(f"{o['details']} — {o['price']} F",
                                  callback_data=f"offer:{operator}:{o['code']}")]
            for o in CATALOG.get(operator, {}).get("offers", [])]
    rows.append([InlineKeyboardButton(t(lang, "back"), callback_data="catalog")])
    return InlineKeyboardMarkup(rows)


def payment_keyboard(lang="fr"):
    rows = [[InlineKeyboardButton(m["label"], callback_data=f"payment:{code}")]
            for code, m in PAYMENT_METHODS.items()]
    rows.append([InlineKeyboardButton(t(lang, "cancel_btn"), callback_data="cancel_order")])
    return InlineKeyboardMarkup(rows)


def admin_keyboard(order_id, lang="fr"):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅", callback_data=f"admin:approve:{order_id}"),
        InlineKeyboardButton("❌", callback_data=f"admin:reject:{order_id}"),
    ]])


def confirm_keyboard(action, order_id, lang="fr"):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(t(lang, "confirm_btn"), callback_data=f"conf:{action}:{order_id}"),
        InlineKeyboardButton(t(lang, "back"), callback_data="home"),
    ]])
