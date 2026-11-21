import asyncio
import functools
import logging
from pathlib import Path

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from .catalog import CATALOG, PAYMENT_METHODS
from .i18n import DEFAULT_LANG, normalize_lang, t
from .keyboards import (admin_keyboard, ai_mode_keyboard, confirm_keyboard, main_keyboard,
                        offers_keyboard, operators_keyboard, payment_keyboard)
from .ai import generate_reply
from .text import edit_long, esc, send_long
from .voice import synthesize_piper, transcribe_groq

log = logging.getLogger(__name__)

HTML = ParseMode.HTML
RATE_LIMIT = 5
RATE_WINDOW = 10.0
HANDLER_TIMEOUT = 120.0
MAX_PHOTO_BYTES = 5 * 1024 * 1024

_rates: dict[int, list[float]] = {}
_locks: dict[int, asyncio.Lock] = {}


def _lock_for(user_id):
    lock = _locks.get(user_id)
    if lock is None:
        if len(_locks) > 5000:
            _locks.clear()
        lock = _locks[user_id] = asyncio.Lock()
    return lock


def _rate_ok(user_id):
    now = asyncio.get_running_loop().time()
    bucket = _rates.setdefault(user_id, [])
    while bucket and now - bucket[0] > RATE_WINDOW:
        bucket.pop(0)
    if len(bucket) >= RATE_LIMIT:
        return False
    bucket.append(now)
    return True


def db_of(context):
    return context.application.bot_data["db"]


def lang_of(update, context):
    if context.user_data.get("lang"):
        return context.user_data["lang"]
    user = update.effective_user
    return normalize_lang(user.language_code if user else None)


def is_admin(update, context):
    user = update.effective_user
    return bool(user and user.id == context.application.bot_data["admin_id"])


def guarded(func):
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        db = db_of(context)
        if not await asyncio.to_thread(db.mark_update, update.update_id):
            log.info("Doublon ignoré update_id=%s", update.update_id)
            return
        user = update.effective_user
        if not user:
            return
        lang = lang_of(update, context)
        if not _rate_ok(user.id):
            if update.callback_query:
                await update.callback_query.answer(t(lang, "too_fast"), show_alert=False)
            else:
                await update.message.reply_text(t(lang, "too_fast"))
            return
        async with _lock_for(user.id):
            try:
                await asyncio.wait_for(func(update, context), timeout=HANDLER_TIMEOUT)
            except asyncio.TimeoutError:
                log.warning("Timeout handler %s user=%s", func.__name__, user.id)
                target = update.callback_query.message if update.callback_query else update.message
                if target:
                    await target.reply_text(t(lang, "timeout"))
    return wrapper


@guarded
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = lang_of(update, context)
    context.user_data["lang"] = lang
    db = db_of(context)
    await asyncio.to_thread(db.register_customer, update.effective_user, lang)
    context.user_data.pop("selected_offer", None)
    context.user_data.pop("active_order_id", None)
    await send_long(update.message, t(lang, "welcome"), main_keyboard(lang))


@guarded
async def help_command(update, context):
    await update.message.reply_text(
        "/start — menu\n/cancel — annuler\n/cgu — conditions\n"
        "Écris un message ou envoie un vocal pour HMB AI.", parse_mode=HTML)


@guarded
async def cgu(update, context):
    lang = lang_of(update, context)
    await send_long(update.message, t(lang, "cgu"), main_keyboard(lang))


@guarded
async def cancel(update, context):
    lang = lang_of(update, context)
    context.user_data.pop("selected_offer", None)
    context.user_data.pop("active_order_id", None)
    await update.message.reply_text(t(lang, "cancelled"), reply_markup=main_keyboard(lang))


@guarded
async def lang_command(update, context):
    current = lang_of(update, context)
    new = "en" if current == "fr" else "fr"
    context.user_data["lang"] = new
    await asyncio.to_thread(db_of(context).set_lang, update.effective_user.id, new)
    await update.message.reply_text(t(new, "menu"), reply_markup=main_keyboard(new))


async def _reply_mode(update, context):
    cached = context.user_data.get("reply_mode")
    if cached:
        return cached
    mode = await asyncio.to_thread(db_of(context).get_reply_mode, update.effective_user.id)
    mode = mode or "text"
    context.user_data["reply_mode"] = mode
    return mode


async def deliver_answer(update, context, answer, lang, detected=None):
    """Envoie la réponse selon le mode choisi : vocal ou texte, jamais les deux."""
    mode = await _reply_mode(update, context)
    settings = context.application.bot_data["settings"]
    if mode == "voice" and settings.voice_reply_enabled:
        try:
            path, _ = await asyncio.to_thread(synthesize_piper, answer, detected or lang, settings)
            with open(path, "rb") as audio:
                try:
                    await update.message.reply_voice(voice=audio, caption=t(lang, "voice_caption"))
                except Exception:
                    log.warning("reply_voice refusé, repli sur sendAudio")
                    audio.seek(0)
                    await update.message.reply_audio(audio=audio, title="HMB AI")
            return
        except Exception:
            log.exception("TTS indisponible")
            await update.message.reply_text(t(lang, "voice_unavailable"))
    await send_long(update.message, esc(answer))


@guarded
async def callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    lang = lang_of(update, context)
    data = q.data or ""
    db = db_of(context)

    if data == "home":
        await edit_long(q, t(lang, "menu"), main_keyboard(lang))
    elif data == "catalog":
        await edit_long(q, t(lang, "choose_operator"), operators_keyboard(lang))
    elif data == "ai":
        mode = await _reply_mode(update, context)
        await edit_long(q, t(lang, "ai_mode_prompt", mode=t(lang, f"mode_{mode}")),
                        ai_mode_keyboard(lang))
    elif data.startswith("mode:"):
        mode = data.split(":", 1)[1]
        if mode not in ("text", "voice"):
            return
        context.user_data["reply_mode"] = mode
        await asyncio.to_thread(db.set_reply_mode, update.effective_user.id, mode)
        await edit_long(q, t(lang, "mode_voice_set" if mode == "voice" else "mode_text_set"),
                        main_keyboard(lang))
    elif data in ("support", "human"):
        await edit_long(q, t(lang, "support_intro"))
        context.user_data["support_mode"] = True
    elif data.startswith("operator:"):
        operator = data.split(":", 1)[1]
        if operator not in CATALOG:
            await edit_long(q, t(lang, "unknown_operator"))
            return
        item = CATALOG[operator]
        await edit_long(q, t(lang, "choose_offer", label=esc(item["label"]), app=esc(item["app"])),
                        offers_keyboard(operator, lang))
    elif data.startswith("offer:"):
        _, operator, code = data.split(":", 2)
        offer = next((x for x in CATALOG.get(operator, {}).get("offers", []) if x["code"] == code), None)
        if not offer:
            await edit_long(q, t(lang, "offer_gone"))
            return
        context.user_data["selected_offer"] = (operator, offer)
        await edit_long(q, t(lang, "summary", operator=esc(operator), details=esc(offer["details"]),
                            validity=esc(offer["validity"]), price=offer["price"]),
                        payment_keyboard(lang))
    elif data.startswith("payment:"):
        method_code = data.split(":", 1)[1]
        method = PAYMENT_METHODS.get(method_code)
        selected = context.user_data.get("selected_offer")
        if not method or not selected:
            await edit_long(q, t(lang, "session_expired"))
            return
        operator, offer = selected
        user = update.effective_user
        existing = await asyncio.to_thread(db.active_order, user.id, offer["code"])
        if existing:
            order_id, order_code = existing["id"], existing["code"]
            await asyncio.to_thread(db.set_payment_method, order_id, method["label"])
        else:
            order_id, order_code = await asyncio.to_thread(db.create_order, (
                user.id, user.username, user.full_name, operator, offer["code"],
                f"{offer['details']} — {offer['validity']}", offer["price"]))
            await asyncio.to_thread(db.set_payment_method, order_id, method["label"])
        context.user_data["active_order_id"] = order_id
        await edit_long(q, t(lang, "payment_info", code=esc(order_code), method=esc(method["label"]),
                            number=esc(method["number"]), beneficiary=esc(method["beneficiary"]),
                            price=offer["price"],
                            ttl=context.application.bot_data["settings"].order_ttl_minutes))
    elif data == "cancel_order":
        context.user_data.pop("selected_offer", None)
        context.user_data.pop("active_order_id", None)
        await edit_long(q, t(lang, "cancelled"), main_keyboard(lang))
    elif data.startswith("conf:"):
        await _confirmed(update, context, data)


async def _confirmed(update, context, data):
    q = update.callback_query
    lang = lang_of(update, context)
    _, action, raw_id = data.split(":")
    db = db_of(context)
    order = await asyncio.to_thread(db.get_order, int(raw_id))
    if not order:
        await edit_long(q, "Commande introuvable.")
        return
    if action == "refund":
        if await asyncio.to_thread(db.set_status, order["id"], "refunded",
                                   "approved") or await asyncio.to_thread(
                db.set_status, order["id"], "refunded", "delivered"):
            await context.bot.send_message(
                order["user_id"], t(lang, "refunded", code=esc(order["code"])), parse_mode=HTML)
            await edit_long(q, f"↩️ Commande {esc(order['code'])} remboursée.")
        else:
            await edit_long(q, f"Remboursement impossible (statut {order['status']}).")
    elif action == "cancel":
        if await asyncio.to_thread(db.set_status, order["id"], "cancelled", "awaiting_proof"):
            await context.bot.send_message(
                order["user_id"], t(lang, "cancelled"), parse_mode=HTML)
            await edit_long(q, f"Commande {esc(order['code'])} annulée.")
        else:
            await edit_long(q, f"Annulation impossible (statut {order['status']}).")@guarded
async def payment_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = lang_of(update, context)
    order_id = context.user_data.get("active_order_id")
    if not order_id:
        await update.message.reply_text(t(lang, "proof_prompt"), reply_markup=main_keyboard(lang))
        return
    photo = update.message.photo[-1]
    if photo.file_size and photo.file_size > MAX_PHOTO_BYTES:
        await update.message.reply_text(t(lang, "proof_big"))
        return
    db = db_of(context)
    order = await asyncio.to_thread(db.get_order, order_id)
    if not order:
        await update.message.reply_text(t(lang, "proof_waiting"))
        return
    if order["status"] == "pending":
        await update.message.reply_text(t(lang, "proof_already", code=esc(order["code"])), parse_mode=HTML)
        return
    if order["status"] != "awaiting_proof":
        await update.message.reply_text(t(lang, "proof_waiting"))
        return
    user = update.effective_user
    caption = (
        f"🧾 COMMANDE {esc(order['code'])}\nClient : {esc(user.full_name)}\n"
        f"Username : @{esc(user.username or 'non défini')}\nID : {user.id}\n"
        f"Opérateur : {esc(order['operator'])}\nOffre : {esc(order['offer_label'])}\n"
        f"Montant : {order['amount']} FCFA\nPaiement : {esc(order['payment_method'])}"
    )
    await context.bot.send_photo(
        chat_id=context.application.bot_data["admin_id"],
        photo=photo.file_id, caption=caption[:1024], parse_mode=HTML,
        reply_markup=admin_keyboard(order_id))
    await asyncio.to_thread(db.set_status, order_id, "pending", "awaiting_proof")
    await update.message.reply_text(t(lang, "proof_sent", code=esc(order["code"])),
                                    parse_mode=HTML, reply_markup=main_keyboard(lang))
    context.user_data.pop("active_order_id", None)
    context.user_data.pop("selected_offer", None)


@guarded
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
    lang = await asyncio.to_thread(db.get_lang, order["user_id"]) or DEFAULT_LANG

    if action == "reject":
        if not await asyncio.to_thread(db.set_status, order_id, "rejected", "pending"):
            await q.answer("Commande déjà traitée.", show_alert=True)
            return
        await q.answer("Refusé.")
        await context.bot.send_message(order["user_id"],
                                       t(lang, "rejected", code=esc(order["code"])), parse_mode=HTML)
        await q.edit_message_caption(caption=f"❌ {esc(order['code'])} refusée.")
        return

    code = await asyncio.to_thread(db.reserve_stock, order["offer_code"], order_id)
    if not await asyncio.to_thread(db.set_status, order_id, "approved", "pending"):
        await q.answer("Commande déjà traitée.", show_alert=True)
        return
    await q.answer("Validé.")
    if code:
        await asyncio.to_thread(db.set_stock_code, order_id, code)
        await context.bot.send_message(
            order["user_id"],
            t(lang, "approved_code", code=esc(code), ref=esc(order["code"])), parse_mode=HTML)
        await q.edit_message_caption(caption=f"✅ {esc(order['code'])} validée, code livré automatiquement.")
        remaining = await asyncio.to_thread(db.stock_count, order["offer_code"])
        settings = context.application.bot_data["settings"]
        if remaining <= settings.low_stock_threshold:
            await context.bot.send_message(
                context.application.bot_data["admin_id"],
                f"⚠️ Stock bas sur {order['offer_code']} : {remaining} restant(s).")
    else:
        await context.bot.send_message(order["user_id"],
                                       t(lang, "approved", code=esc(order["code"])), parse_mode=HTML)
        await q.edit_message_caption(
            caption=f"✅ {esc(order['code'])} validée — aucun stock, livraison manuelle.")


@guarded
async def deliver(update, context):
    if not is_admin(update, context):
        await update.message.reply_text("Réservé à l'administrateur.")
        return
    if not context.args:
        await update.message.reply_text("Utilisation : /deliver CODE")
        return
    db = db_of(context)
    order = await asyncio.to_thread(db.get_order_by_code, context.args[0])
    if not order or order["status"] != "approved":
        await update.message.reply_text("Commande introuvable ou non validée.")
        return
    await asyncio.to_thread(db.set_status, order["id"], "delivered", "approved")
    lang = await asyncio.to_thread(db.get_lang, order["user_id"]) or DEFAULT_LANG
    await context.bot.send_message(order["user_id"],
                                   t(lang, "delivered", code=esc(order["code"])), parse_mode=HTML)
    await update.message.reply_text(f"{order['code']} livrée.")


@guarded
async def cancelorder(update, context):
    if not is_admin(update, context):
        await update.message.reply_text("Réservé à l'administrateur.")
        return
    if not context.args:
        await update.message.reply_text("Utilisation : /cancelorder CODE")
        return
    db = db_of(context)
    order = await asyncio.to_thread(db.get_order_by_code, context.args[0])
    if not order:
        await update.message.reply_text("Commande introuvable.")
        return
    await update.message.reply_text(
        f"Annuler {order['code']} ({order['status']}) ?",
        reply_markup=confirm_keyboard("cancel", order["id"]))


@guarded
async def refund(update, context):
    if not is_admin(update, context):
        await update.message.reply_text("Réservé à l'administrateur.")
        return
    if not context.args:
        await update.message.reply_text("Utilisation : /refund CODE")
        return
    db = db_of(context)
    order = await asyncio.to_thread(db.get_order_by_code, context.args[0])
    if not order:
        await update.message.reply_text("Commande introuvable.")
        return
    await update.message.reply_text(
        f"Rembourser {order['code']} ({order['status']}) ?",
        reply_markup=confirm_keyboard("refund", order["id"]))


@guarded
async def note(update, context):
    if not is_admin(update, context):
        await update.message.reply_text("Réservé à l'administrateur.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Utilisation : /note CODE texte")
        return
    db = db_of(context)
    order = await asyncio.to_thread(db.get_order_by_code, context.args[0])
    if not order:
        await update.message.reply_text("Commande introuvable.")
        return
    await asyncio.to_thread(db.add_note, order["id"], " ".join(context.args[1:]))
    await update.message.reply_text(f"Note enregistrée sur {order['code']}.")


@guarded
async def client(update, context):
    if not is_admin(update, context):
        await update.message.reply_text("Réservé à l'administrateur.")
        return
    if not context.args or not context.args[0].lstrip("-").isdigit():
        await update.message.reply_text("Utilisation : /client USER_ID")
        return
    data, orders, revenue = await asyncio.to_thread(db_of(context).client_summary, int(context.args[0]))
    if not data:
        await update.message.reply_text("Client inconnu.")
        return
    lines = [f"👤 {esc(data['full_name'])} (@{esc(data['username'] or '—')}) — {data['user_id']}",
             f"Langue : {data['lang'] or '—'} | Total validé : {revenue} FCFA"]
    for o in orders:
        lines.append(f"{o['code']} | {o['offer_label'][:40]} | {o['amount']} F | {o['status']}")
    await update.message.reply_text("\n".join(lines) or "Aucune commande", parse_mode=HTML)


@guarded
async def addstock(update, context):
    if not is_admin(update, context):
        await update.message.reply_text("Réservé à l'administrateur.")
        return
    if not context.args:
        await update.message.reply_text("Utilisation : /addstock CODE_OFFRE puis les codes, un par ligne.")
        return
    offer_code = context.args[0]
    valid = {o["code"] for item in CATALOG.values() for o in item.get("offers", [])}
    if offer_code not in valid:
        await update.message.reply_text(f"Code d'offre inconnu. Exemples : {', '.join(list(valid)[:5])}")
        return
    body = update.message.text.partition(offer_code)[2]
    codes = [c.strip() for c in body.splitlines() if c.strip()]
    if not codes:
        await update.message.reply_text("Aucun code détecté.")
        return
    added = await asyncio.to_thread(db_of(context).add_stock, offer_code, codes)
    remaining = await asyncio.to_thread(db_of(context).stock_count, offer_code)
    await update.message.reply_text(f"{added} code(s) ajoutés sur {offer_code}. Stock : {remaining}.")


@guarded
async def stock(update, context):
    if not is_admin(update, context):
        await update.message.reply_text("Réservé à l'administrateur.")
        return
    db = db_of(context)
    rows = []
    for operator, item in CATALOG.items():
        for offer in item.get("offers", []):
            rows.append(f"{offer['code']} ({offer['details'][:30]}) : "
                        f"{await asyncio.to_thread(db.stock_count, offer['code'])}")
    await update.message.reply_text("📦 Stock\n" + "\n".join(rows))


@guarded
async def addfaq(update, context):
    if not is_admin(update, context):
        await update.message.reply_text("Réservé à l'administrateur.")
        return
    text = update.message.text.partition(" ")[2]
    if "|" not in text:
        await update.message.reply_text("Utilisation : /addfaq question | réponse")
        return
    question, answer = text.split("|", 1)
    if await asyncio.to_thread(db_of(context).faq_add, question, answer):
        await update.message.reply_text("FAQ enregistrée.")
    else:
        await update.message.reply_text("Question vide.")


@guarded
async def admin(update, context):
    if not is_admin(update, context):
        await update.message.reply_text("Réservé à l'administrateur.")
        return
    await update.message.reply_text(
        "👑 Administration\n/stats /orders /stock /client ID\n"
        "/deliver CODE /cancelorder CODE /refund CODE /note CODE texte\n"
        "/addstock CODE /addfaq question | réponse\n"
        "/broadcast texte /backup /diag /setwebhook /voicetest")


@guarded
async def stats(update, context):
    if not is_admin(update, context):
        await update.message.reply_text("Réservé à l'administrateur.")
        return
    s = await asyncio.to_thread(db_of(context).stats)
    await update.message.reply_text(
        f"📊 Clients : {s['customers']}\nCommandes : {s['orders']}\n"
        f"En attente : {s['pending']}\nValidées/livrées : {s['approved']}\n"
        f"Montant validé : {s['revenue']} FCFA")


@guarded
async def orders(update, context):
    if not is_admin(update, context):
        await update.message.reply_text("Réservé à l'administrateur.")
        return
    rows = await asyncio.to_thread(db_of(context).recent_orders, 10)
    if not rows:
        await update.message.reply_text("Aucune commande.")
        return
    lines = ["📋 10 dernières"]
    for o in rows:
        lines.append(f"{o['code']} | {o['operator']} | {o['amount']} F | {o['status']} | {o['user_id']}")
    await update.message.reply_text("\n".join(lines))


@guarded
async def broadcast(update, context):
    if not is_admin(update, context):
        await update.message.reply_text("Réservé à l'administrateur.")
        return
    message = update.message.text.partition(" ")[2].strip()
    if not message:
        await update.message.reply_text("Utilisation : /broadcast texte")
        return
    db = db_of(context)
    ids = await asyncio.to_thread(db.customer_ids)
    sent = 0
    for user_id in ids:
        try:
            await context.bot.send_message(user_id, esc(message), parse_mode=HTML)
            sent += 1
        except Exception:
            log.warning("Broadcast échoué user=%s", user_id)
        await asyncio.sleep(0.05)
    await update.message.reply_text(f"Envoyé à {sent}/{len(ids)}.")


@guarded
async def backup(update, context):
    if not is_admin(update, context):
        await update.message.reply_text("Réservé à l'administrateur.")
        return
    db = db_of(context)
    await asyncio.to_thread(db.checkpoint)
    path = Path(db.path)
    with open(path, "rb") as handle:
        await update.message.reply_document(handle, filename="hmb_surf_bot.sqlite3",
                                            caption="Sauvegarde de la base")


@guarded
async def diag(update, context):
    if not is_admin(update, context):
        await update.message.reply_text("Réservé à l'administrateur.")
        return
    settings = context.application.bot_data["settings"]
    db = db_of(context)
    info = await context.bot.get_webhook_info()
    pending = (await asyncio.to_thread(db.stats))["pending"]
    size = Path(db.path).stat().st_size if Path(db.path).exists() else 0
    await update.message.reply_text(
        f"Modèle : {settings.groq_chat_model}\nWebhook : {'ok' if info.url else 'absent'}\n"
        f"Pending : {info.pending_update_count}\nErreur : {info.last_error_message or 'aucune'}\n"
        f"En attente : {pending}\nBase : {size} octets\nFAQ : {await asyncio.to_thread(db.faq_count)}")


@guarded
async def setwebhook(update, context):
    if not is_admin(update, context):
        await update.message.reply_text("Réservé à l'administrateur.")
        return
    await context.application.bot_data["set_webhook"]()
    info = await context.bot.get_webhook_info()
    await update.message.reply_text(f"Webhook reposé. Pending : {info.pending_update_count}")


@guarded
async def voicetest(update, context):
    if not is_admin(update, context):
        await update.message.reply_text("Réservé à l'administrateur.")
        return
    settings = context.application.bot_data["settings"]
    status = await update.message.reply_text("Synthèse…")
    try:
        path, _ = await asyncio.to_thread(synthesize_piper, "Bonjour, la synthèse fonctionne.", "fr", settings)
        with open(path, "rb") as audio:
            try:
                await update.message.reply_voice(voice=audio, caption="Test Piper")
            except Exception:
                log.warning("reply_voice refusé, repli sur sendAudio")
                audio.seek(0)
                await update.message.reply_audio(audio=audio, title="Test Piper")
        await status.delete()
    except Exception as exc:
        log.exception("Test Piper échoué")
        await status.edit_text(f"Échec : {exc}"[:400])


async def _answer_ai(update, context, text):
    """Génère la réponse sans l'envoyer : la livraison est décidée par l'appelant."""
    lang = lang_of(update, context)
    settings = context.application.bot_data["settings"]
    db = db_of(context)
    user = update.effective_user
    await asyncio.to_thread(db.register_customer, user, lang)
    await asyncio.to_thread(db.add_message, user.id, "user", text)

    cached = await asyncio.to_thread(db.faq_lookup, text)
    if cached:
        await asyncio.to_thread(db.add_message, user.id, "assistant", cached)
        return cached

    rows = await asyncio.to_thread(db.history, user.id)
    history = [dict(x) for x in rows]
    try:
        answer = await generate_reply(settings.groq_api_key, settings.groq_chat_model, history, text)
    except Exception:
        log.exception("Erreur IA")
        answer = t(lang, "error_generic")
    await asyncio.to_thread(db.add_message, user.id, "assistant", answer)
    return answer


@guarded
async def text_message(update, context):
    lang = lang_of(update, context)
    if context.user_data.get("support_mode"):
        user = update.effective_user
        await context.bot.send_message(
            context.application.bot_data["admin_id"],
            f"☎️ ASSISTANCE\n{esc(user.full_name)} (@{esc(user.username or '—')}) — {user.id}\n"
            f"{esc(update.message.text)}", parse_mode=HTML)
        context.user_data["support_mode"] = False
        await update.message.reply_text(t(lang, "support_sent"))
        return
    if not context.application.bot_data["settings"].ai_enabled:
        await update.message.reply_text(t(lang, "ai_down"), reply_markup=main_keyboard(lang))
        return
    answer = await _answer_ai(update, context, update.message.text)
    await deliver_answer(update, context, answer, lang)


@guarded
async def voice_message(update, context):
    lang = lang_of(update, context)
    settings = context.application.bot_data["settings"]
    if not settings.groq_api_key:
        await update.message.reply_text(t(lang, "ai_down"))
        return
    voice = update.message.voice or update.message.audio
    if voice.duration and voice.duration > settings.max_voice_seconds:
        await update.message.reply_text(t(lang, "voice_too_long", seconds=settings.max_voice_seconds))
        return
    status = await update.message.reply_text(t(lang, "voice_listening"))
    try:
        tg_file = await context.bot.get_file(voice.file_id)
        audio_bytes = await tg_file.download_as_bytearray()
        transcript, detected = await transcribe_groq(
            settings.groq_api_key, settings.groq_stt_model, bytes(audio_bytes),
            filename="voice.ogg" if update.message.voice else (update.message.audio.file_name or "audio.mp3"))
        if not transcript:
            await status.edit_text(t(lang, "voice_unclear"))
            return
        await status.edit_text(t(lang, "voice_understood", text=esc(transcript)), parse_mode=HTML)
        answer = await _answer_ai(update, context, transcript)
        await deliver_answer(update, context, answer, lang, detected)
    except Exception:
        log.exception("Erreur vocale")
        await status.edit_text(t(lang, "voice_failed"))
