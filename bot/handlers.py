from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .catalog import CATALOG
from .keyboards import operators_keyboard, offers_keyboard, admin_keyboard

def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    return bool(update.effective_user and update.effective_user.id == context.application.bot_data["admin_id"])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Bienvenue sur *HMB SURF BOT* 👑\n"
        "Catalogue et commandes HMB.\n\n"
        "Créateur : *HAMZA alliance HMB*\n\n"
        "Choisis ton opérateur :",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=operators_keyboard()
    )

async def show_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    await q.edit_message_text("Choisis ton opérateur :", reply_markup=operators_keyboard())

async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data == "catalog":
        await q.edit_message_text("Choisis ton opérateur :", reply_markup=operators_keyboard())
        return
    if data.startswith("operator:"):
        operator = data.split(":", 1)[1]
        if operator not in CATALOG:
            await q.edit_message_text("Opérateur inconnu.")
            return
        offers = CATALOG[operator]["offers"]
        lines = [f"*{CATALOG[operator]['label']}*", f"Application : {CATALOG[operator]['app']}", "", "Choisis une offre :"]
        await q.edit_message_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN,
                                  reply_markup=offers_keyboard(operator))
        return
    if data.startswith("offer:"):
        _, operator, code = data.split(":", 2)
        offer = next((x for x in CATALOG.get(operator, {}).get("offers", []) if x["code"] == code), None)
        if not offer:
            await q.edit_message_text("Cette offre n'est plus disponible.")
            return
        context.user_data["selected_offer"] = (operator, offer)
        await q.edit_message_text(
            f"*Récapitulatif de ta commande*\nOpérateur : {operator}\n"
            f"Offre : {offer['details']}\nValidité : {offer['validity']}\n"
            f"Montant : *{offer['price']} FCFA*\n\n"
            "Pour continuer, envoie la preuve de paiement en photo. "
            "L'administrateur vérifiera le paiement avant toute livraison.",
            parse_mode=ParseMode.MARKDOWN
        )

async def payment_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    selected = context.user_data.get("selected_offer")
    if not selected:
        await update.message.reply_text("Choisis d'abord une offre avec /start.")
        return
    operator, offer = selected
    user = update.effective_user
    order_id = context.application.bot_data["db"].create_order((
        user.id, user.username, user.full_name, operator, offer["code"],
        f'{offer["details"]} — {offer["validity"]}', offer["price"]
    ))
    photo_id = update.message.photo[-1].file_id
    caption = (
        f"🧾 *Nouvelle commande #{order_id}*\n"
        f"Client : {user.full_name}\n"
        f"Nom Telegram : @{user.username or 'non défini'}\n"
        f"ID : `{user.id}`\nOpérateur : {operator}\n"
        f"Offre : {offer['details']} ({offer['validity']})\n"
        f"Montant : *{offer['price']} FCFA*"
    )
    await context.bot.send_photo(
        chat_id=context.application.bot_data["admin_id"],
        photo=photo_id,
        caption=caption,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=admin_keyboard(order_id)
    )
    await update.message.reply_text(
        f"Ta preuve a été envoyée à l'administrateur. Numéro de commande : #{order_id}. "
        "Attends la vérification du paiement."
    )
    context.user_data.pop("selected_offer", None)

async def admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not is_admin(update, context):
        await q.answer("Action réservée à l'administrateur.", show_alert=True)
        return
    await q.answer()
    _, action, raw_id = q.data.split(":")
    order_id = int(raw_id)
    status = "approved" if action == "approve" else "rejected"
    order = context.application.bot_data["db"].get_order(order_id)
    if not order:
        await q.edit_message_caption(caption="Commande introuvable.")
        return
    if not context.application.bot_data["db"].set_status(order_id, status):
        await q.answer("Cette commande a déjà été traitée.", show_alert=True)
        return
    if status == "approved":
        await context.bot.send_message(order["user_id"],
            f"✅ Paiement validé pour la commande #{order_id}. L'administrateur va procéder à la livraison manuelle.")
        await q.edit_message_caption(caption=f"✅ Commande #{order_id} validée. Livraison manuelle à effectuer.")
    else:
        await context.bot.send_message(order["user_id"],
            f"❌ Le paiement de la commande #{order_id} n'a pas été validé. Contacte l'administrateur.")
        await q.edit_message_caption(caption=f"❌ Commande #{order_id} refusée.")

async def deliver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update, context):
        await update.message.reply_text("Commande réservée à l'administrateur.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Utilisation : /deliver ID_COMMANDE")
        return
    order = context.application.bot_data["db"].get_order(int(context.args[0]))
    if not order or order["status"] != "approved":
        await update.message.reply_text("Commande introuvable ou paiement non validé.")
        return
    await context.application.bot_data["db"].set_status(order["id"], "delivered", expected_status="approved")
    await context.bot.send_message(order["user_id"],
        f"📦 Ta commande #{order['id']} est indiquée comme livrée. Merci.")
    await update.message.reply_text(f"Commande #{order['id']} marquée comme livrée.")
