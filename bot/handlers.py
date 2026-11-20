import asyncio
import logging
from pathlib import Path
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from .catalog import CATALOG, PAYMENT_METHODS
from .keyboards import (
    main_keyboard, operators_keyboard, offers_keyboard, payment_keyboard, admin_keyboard
)
from .ai import generate_reply
from .voice import transcribe_groq, synthesize_piper

log = logging.getLogger(__name__)


def is_admin(update, context):
    return bool(update.effective_user and update.effective_user.id == context.application.bot_data["admin_id"])


def db_of(context):
    return context.application.bot_data["db"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    db = db_of(context)
    await asyncio.to_thread(db.register_customer, update.effective_user)
    context.user_data.pop("selected_offer", None)
    context.user_data.pop("active_order_id", None)
    await update.message.reply_text(
        "👑 *BIENVENUE SUR HMB SURF BOT*\n\n"
        "Choisis une rubrique ci-dessous. Pour parler à notre assistant, écris-lui directement.\n\n"
        "Créateur : *HAMZA alliance HMB*",
        parse_mode=ParseMode.MARKDOWN, reply_markup=main_keyboard()
    )


async def help_command(update, context):
    await update.message.reply_text(
        "• /start — Menu principal\n• /cancel — Annuler la commande en cours\n"
        "• Écris un message ou envoie un vocal pour parler à HMB AI.\n"
        "Pour une vérification de paiement ou une assistance humaine, choisis Assistance."
    )


async def cancel(update, context):
    context.user_data.pop("selected_offer", None)
    context.user_data.pop("active_order_id", None)
    await update.message.reply_text("Commande annulée.", reply_markup=main_keyboard())


async def setwebhook(update, context):
    """/setwebhook — repose le webhook Telegram sans redéployer."""
    if not is_admin(update, context):
        await update.message.reply_text("Accès réservé à l'administrateur.")
        return
    try:
        await context.application.bot_data["set_webhook"]()
        info = await context.bot.get_webhook_info()
        await update.message.reply_text(
            f"Webhook reposé.\nURL : {info.url}\nPending : {info.pending_update_count}\n"
            f"Erreur : {info.last_error_message or 'aucune'}"
        )
    except Exception as exc:
        log.exception("Échec de la repose du webhook")
        await update.message.reply_text(f"Échec : {exc}")


async def voicetest(update, context):
    """/voicetest — vérifie la synthèse Piper sans envoyer de vocal."""
    if not is_admin(update, context):
        await update.message.reply_text("Accès réservé à l'administrateur.")
        return
    settings = context.application.bot_data["settings"]
    status = await update.message.reply_text("Synthèse en cours…")
    local_path = None
    try:
        local_path = await asyncio.to_thread(
            synthesize_piper, "Bonjour, la synthèse vocale fonctionne.", "fr", settings
        )
        with open(local_path, "rb") as audio:
            await update.message.reply_voice(voice=audio, caption="Test Piper")
        await status.delete()
    except Exception as exc:
        log.exception("Test Piper échoué")
        await status.edit_text(f"Échec Piper : {exc}"[:400])
    finally:
        if local_path:
            Path(local_path).unlink(missing_ok=True)


async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    db = db_of(context)
    if data == "home":
        await q.edit_message_text("Menu principal — HMB SURF BOT", reply_markup=main_keyboard())
    elif data == "catalog":
        await q.edit_message_text("Choisis ton opérateur :", reply_markup=operators_keyboard())
    elif data == "ai":
        await q.edit_message_text("🤖 HMB AI est prêt. Écris ton message ou envoie un vocal.")
    elif data == "support":
        await q.edit_message_text(
            "☎️ Assistance HMB\nExplique ton problème ici. L'administrateur pourra prendre le relais."
        )
        context.user_data["support_mode"] = True
    elif data.startswith("operator:"):
        operator = data.split(":", 1)[1]
        if operator not in CATALOG:
            await q.edit_message_text("Opérateur inconnu.")
            return
        item = CATALOG[operator]
        await q.edit_message_text(
            f"*{item['label']}*\nApplication : {item['app']}\n\nChoisis une offre :",
            parse_mode=ParseMode.MARKDOWN, reply_markup=offers_keyboard(operator)
        )
    elif data.startswith("offer:"):
        _, operator, code = data.split(":", 2)
        offer = next((x for x in CATALOG.get(operator, {}).get("offers", []) if x["code"] == code), None)
        if not offer:
            await q.edit_message_text("Cette offre n'est plus disponible.")
            return
        context.user_data["selected_offer"] = (operator, offer)
        await q.edit_message_text(
            f"🧾 Récapitulatif\nOpérateur : {operator}\nOffre : {offer['details']}\n"
            f"Validité : {offer['validity']}\nMontant : *{offer['price']} FCFA*\n\n"
            "Choisis ton moyen de paiement :",
            parse_mode=ParseMode.MARKDOWN, reply_markup=payment_keyboard()
        )
    elif data.startswith("payment:"):
        method_code = data.split(":", 1)[1]
        method = PAYMENT_METHODS.get(method_code)
        selected = context.user_data.get("selected_offer")
        if not method or not selected:
            await q.edit_message_text("Session expirée. Recommence avec /start.")
            return
        operator, offer = selected
        user = update.effective_user
        order_id = await asyncio.to_thread(db.create_order, (
            user.id, user.username, user.full_name, operator, offer["code"],
            f"{offer['details']} — {offer['validity']}", offer["price"]
        ))
        await asyncio.to_thread(db.set_payment_method, order_id, method["label"])
        context.user_data["active_order_id"] = order_id
        await q.edit_message_text(
            f"💳 *Paiement de la commande #{order_id}*\n\n"
            f"Méthode : *{method['label']}*\nNuméro : `{method['number']}`\n"
            f"Bénéficiaire : *{method['beneficiary']}*\nMontant : *{offer['price']} FCFA*\n\n"
            "Après le paiement, envoie la capture d'écran ici. "
            "L'administrateur vérifiera avant toute livraison.",
            parse_mode=ParseMode.MARKDOWN
        )
    elif data == "cancel_order":
        context.user_data.pop("selected_offer", None)
        context.user_data.pop("active_order_id", None)
        await q.edit_message_text("Commande annulée.", reply_markup=main_keyboard())


async def payment_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    order_id = context.user_data.get("active_order_id")
    if not order_id:
        await update.message.reply_text("Commence par /start, choisis une offre et un moyen de paiement.")
        return
    db = db_of(context)
    order = await asyncio.to_thread(db.get_order, order_id)
    if not order or order["status"] != "awaiting_proof":
        await update.message.reply_text("Cette commande n'attend plus de preuve. Contacte l'assistance.")
        return
    user = update.effective_user
    caption = (
        f"🧾 COMMANDE #{order_id}\nClient : {user.full_name}\n"
        f"Username : @{user.username or 'non défini'}\nID : {user.id}\n"
        f"Opérateur : {order['operator']}\nOffre : {order['offer_label']}\n"
        f"Montant : {order['amount']} FCFA\nPaiement : {order['payment_method']}"
    )
    await context.bot.send_photo(
        chat_id=context.application.bot_data["admin_id"],
        photo=update.message.photo[-1].file_id,
        caption=caption,
        reply_markup=admin_keyboard(order_id)
    )
    await asyncio.to_thread(db.set_status, order_id, "pending", "awaiting_proof")
    await update.message.reply_text(
        f"✅ Preuve envoyée à l'administrateur. Commande #{order_id}. "
        "Attends la vérification du paiement."
    )
    context.user_data.pop("active_order_id", None)
    context.user_data.pop("selected_offer", None)


async def admin_decision(update, context):
    q = update.callback_query
    if not is_admin(update, context):
        await q.answer("Action réservée à l'administrateur.", show_alert=True)
        return
    _, action, raw_id = q.data.split(":")
    order_id = int(raw_id)
    db = db_of(context)
    order = await asyncio.to_thread(db.get_order, order_id)
    if not order:
        await q.answer("Commande introuvable.", show_alert=True)
        return
    target = "approved" if action == "approve" else "rejected"
    if not await asyncio.to_thread(db.set_status, order_id, target, "pending"):
        await q.answer("Commande déjà traitée.", show_alert=True)
        return
    await q.answer("Décision enregistrée.")
    if target == "approved":
        await context.bot.send_message(order["user_id"],
            f"✅ Paiement validé pour la commande #{order_id}. La livraison sera effectuée manuellement par l'administrateur.")
        await q.edit_message_caption(caption=f"✅ Commande #{order_id} validée — livraison manuelle à effectuer.")
    else:
        await context.bot.send_message(order["user_id"],
            f"❌ Paiement non validé pour la commande #{order_id}. Contacte l'assistance.")
        await q.edit_message_caption(caption=f"❌ Commande #{order_id} refusée.")


async def deliver(update, context):
    if not is_admin(update, context):
        await update.message.reply_text("Commande réservée à l'administrateur.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Utilisation : /deliver ID_COMMANDE")
        return
    db = db_of(context)
    order_id = int(context.args[0])
    order = await asyncio.to_thread(db.get_order, order_id)
    if not order or order["status"] != "approved":
        await update.message.reply_text("Commande introuvable ou paiement non validé.")
        return
    await asyncio.to_thread(db.set_status, order_id, "delivered", "approved")
    await context.bot.send_message(order["user_id"], f"📦 Commande #{order_id} marquée comme livrée. Merci.")
    await update.message.reply_text(f"Commande #{order_id} marquée comme livrée.")


async def admin(update, context):
    if not is_admin(update, context):
        await update.message.reply_text("Accès réservé à l'administrateur.")
        return
    await update.message.reply_text(
        "👑 Administration HMB\n/stats — statistiques\n/orders — dernières commandes\n"
        "/deliver ID — marquer livrée\n/broadcast texte — message à tous les clients\n"
        "/setwebhook — réparer la réception Telegram\n/voicetest — tester la synthèse vocale"
    )


async def stats(update, context):
    if not is_admin(update, context):
        await update.message.reply_text("Accès réservé à l'administrateur.")
        return
    s = await asyncio.to_thread(db_of(context).stats)
    await update.message.reply_text(
        f"📊 STATISTIQUES\nClients : {s['customers']}\nCommandes : {s['orders']}\n"
        f"En attente : {s['pending']}\nValidées/livrées : {s['approved']}\n"
        f"Montant validé : {s['revenue']} FCFA"
    )


async def orders(update, context):
    if not is_admin(update, context):
        await update.message.reply_text("Accès réservé à l'administrateur.")
        return
    rows = await asyncio.to_thread(db_of(context).recent_orders, 10)
    if not rows:
        await update.message.reply_text("Aucune commande.")
        return
    lines = ["📋 10 DERNIÈRES COMMANDES"]
    for o in rows:
        lines.append(f"#{o['id']} | {o['operator']} | {o['amount']} F | {o['status']} | ID {o['user_id']}")
    await update.message.reply_text("\n".join(lines))


async def broadcast(update, context):
    if not is_admin(update, context):
        await update.message.reply_text("Accès réservé à l'administrateur.")
        return
    message = " ".join(context.args).strip()
    if not message:
        await update.message.reply_text("Utilisation : /broadcast Votre message")
        return
    ids = await asyncio.to_thread(db_of(context).customer_ids)
    sent = 0
    for user_id in ids:
        try:
            await context.bot.send_message(user_id, message)
            sent += 1
        except Exception:
            log.warning("Broadcast impossible pour user_id=%s", user_id)
        # Respecte la limite d'envoi Telegram.
        await asyncio.sleep(0.05)
    await update.message.reply_text(f"Message envoyé à {sent}/{len(ids)} clients.")


async def _answer_ai(update, context, text):
    settings = context.application.bot_data["settings"]
    db = db_of(context)
    user = update.effective_user
    await asyncio.to_thread(db.register_customer, user)
    rows = await asyncio.to_thread(db.history, user.id)
    history = [dict(x) for x in rows]
    await asyncio.to_thread(db.add_message, user.id, "user", text)
    try:
        answer = await generate_reply(
            settings.groq_api_key, settings.groq_chat_model, history, text,
        )
    except Exception:
        log.exception("Erreur IA")
        answer = "Je rencontre un problème technique avec l'assistant IA. Réessaie plus tard ou utilise Assistance."
    await asyncio.to_thread(db.add_message, user.id, "assistant", answer)
    await update.message.reply_text(answer)
    return answer


async def text_message(update, context):
    if context.user_data.get("support_mode"):
        admin_id = context.application.bot_data["admin_id"]
        user = update.effective_user
        await context.bot.send_message(
            admin_id, f"☎️ DEMANDE D'ASSISTANCE\nClient : {user.full_name}\nID : {user.id}\n"
                      f"Message : {update.message.text}"
        )
        context.user_data["support_mode"] = False
        await update.message.reply_text("Ton message a été transmis à l'administrateur.")
        return
    if not context.application.bot_data["settings"].ai_enabled:
        await update.message.reply_text("HMB AI est momentanément indisponible. Utilise Assistance.")
        return
    await _answer_ai(update, context, update.message.text)


async def voice_message(update, context):
    settings = context.application.bot_data["settings"]
    if not settings.groq_api_key:
        await update.message.reply_text("La compréhension des vocaux n'est pas encore configurée. Écris ton message.")
        return
    voice = update.message.voice or update.message.audio
    if voice.duration and voice.duration > settings.max_voice_seconds:
        await update.message.reply_text(f"Vocal trop long. Limite : {settings.max_voice_seconds} secondes.")
        return
    status = await update.message.reply_text("🎧 J'écoute ton message vocal…")
    local_path = None
    try:
        tg_file = await context.bot.get_file(voice.file_id)
        audio_bytes = await tg_file.download_as_bytearray()
        transcript, detected_language = await transcribe_groq(
            settings.groq_api_key, settings.groq_stt_model, bytes(audio_bytes),
            filename="voice.ogg" if update.message.voice else (update.message.audio.file_name or "audio.mp3")
        )
        if not transcript:
            await status.edit_text("Je n'ai pas réussi à comprendre le vocal. Réessaie ou écris ton message.")
            return
        await status.edit_text(f"📝 J'ai compris : {transcript}")
        answer = await _answer_ai(update, context, transcript)
        if settings.voice_reply_enabled:
            try:
                # Piper est synchrone : exécuté dans un thread pour ne pas bloquer la boucle.
                local_path = await asyncio.to_thread(
                    synthesize_piper, answer, detected_language, settings
                )
                with open(local_path, "rb") as audio:
                    await update.message.reply_voice(voice=audio, caption="🔊 Réponse vocale HMB AI")
            except Exception:
                log.exception("Piper TTS indisponible")
                await update.message.reply_text("La réponse vocale n'est pas disponible pour le moment ; la réponse texte reste disponible.")
    except Exception:
        log.exception("Erreur traitement vocal")
        await status.edit_text("Impossible de traiter ce vocal pour le moment. Tu peux écrire ton message.")
    finally:
        if local_path:
            Path(local_path).unlink(missing_ok=True)
