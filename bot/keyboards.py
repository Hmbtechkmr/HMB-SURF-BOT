from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from .catalog import CATALOG

def operators_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟠 ORANGE", callback_data="operator:ORANGE")],
        [InlineKeyboardButton("🔵 CAMTEL", callback_data="operator:CAMTEL")],
    ])

def offers_keyboard(operator: str):
    rows = []
    for offer in CATALOG[operator]["offers"]:
        rows.append([InlineKeyboardButton(
            f'{offer["price"]} FCFA — {offer["details"]} / {offer["validity"]}',
            callback_data=f'offer:{operator}:{offer["code"]}'
        )])
    rows.append([InlineKeyboardButton("⬅️ Retour", callback_data="catalog")])
    return InlineKeyboardMarkup(rows)

def admin_keyboard(order_id: int):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Valider", callback_data=f"admin:approve:{order_id}"),
        InlineKeyboardButton("❌ Refuser", callback_data=f"admin:reject:{order_id}"),
    ]])
