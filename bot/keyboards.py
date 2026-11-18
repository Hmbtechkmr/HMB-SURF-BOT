from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from .catalog import CATALOG, PAYMENT_METHODS

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍️ Voir le catalogue", callback_data="catalog")],
        [InlineKeyboardButton("🤖 Parler à HMB AI", callback_data="ai")],
        [InlineKeyboardButton("☎️ Assistance", callback_data="support")],
    ])

def operators_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟠 ORANGE", callback_data="operator:ORANGE")],
        [InlineKeyboardButton("🔵 CAMTEL", callback_data="operator:CAMTEL")],
        [InlineKeyboardButton("⬅️ Menu principal", callback_data="home")],
    ])

def offers_keyboard(operator):
    rows = []
    for offer in CATALOG[operator]["offers"]:
        rows.append([InlineKeyboardButton(
            f'{offer["price"]} FCFA — {offer["details"]} / {offer["validity"]}',
            callback_data=f'offer:{operator}:{offer["code"]}'
        )])
    rows.append([InlineKeyboardButton("⬅️ Retour", callback_data="catalog")])
    return InlineKeyboardMarkup(rows)

def payment_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟠 Orange Money", callback_data="payment:OM")],
        [InlineKeyboardButton("📱 Mobile Money", callback_data="payment:MM")],
        [InlineKeyboardButton("⬅️ Annuler", callback_data="cancel_order")],
    ])

def admin_keyboard(order_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Valider", callback_data=f"admin:approve:{order_id}"),
        InlineKeyboardButton("❌ Refuser", callback_data=f"admin:reject:{order_id}"),
    ]])
