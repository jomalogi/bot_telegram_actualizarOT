import os
import re
import logging
import asyncio
import threading
from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from database import Database
from agenda_automation import AgendaAutomation, set_pin

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

WAITING_ORDER = 1
db = Database()
ADMIN_ID = int(os.getenv('ADMIN_CHAT_ID', '0'))

def is_authorized(chat_id):
    return db.is_user_authorized(chat_id)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        await update.message.reply_text(f"⛔ No autorizado.\nTu Chat ID: `{chat_id}`", parse_mode='Markdown')
        return ConversationHandler.END
    await update.message.reply_text(
        "✅ *Bot de Agendamiento Claro*\n\nEnvíame el número de orden.\n\n"
        "/actualizar - Actualizar orden\n"
        "/pin <codigo> - Enviar PIN\n"
        "/cancelar - Cancelar",
        parse_mode='Markdown')
    return ConversationHandler.END

async def cmd_pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID:
        await update.message.reply_text("⛔ Solo el administrador.")
        return
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Uso: /pin <codigo>\nEjemplo: /pin 123456")
        return
    set_pin(context.args[0])
    await update.message.reply_text("✅ PIN enviado, continuando...")

async def cmd_actualizar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_chat.id):
        await update.message.reply_text("⛔ No autorizado.")
        return ConversationHandler.END
    await update.message.reply_text("📋 Ingresa el número de orden:", reply_markup=ReplyKeyboardRemove())
    return WAITING_ORDER

async def _procesar(update: Update, context: ContextTypes.DEFAULT_TYPE, orden: str):
    bot = context.bot
    msg = await update.message.reply_text(
        f"⏳ Procesando orden *{orden}*...", parse_mode='Markdown')

    # Capturar el loop actual ANTES de lanzar el thread
    main_loop = asyncio.get_event_loop()
    resultado_container = [None]
    finished = threading.Event()

    def notify_pin_sync(mensaje: str):
        future = asyncio.run_coroutine_threadsafe(
            bot.send_message(chat_id=ADMIN_ID, text=mensaje, parse_mode='Markdown'),
            main_loop
        )
        try:
            future.result(timeout=15)
            logger.info("Notificacion PIN enviada")
        except Exception as e:
            logger.error(f"Error notificando PIN: {e}")

    def run_automation():
        logger.info(f"Thread automatizacion iniciado para orden {orden}")
        try:
            automation = AgendaAutomation()
            resultado_container[0] = automation.procesar_orden_sync(
                orden, notify_callback_sync=notify_pin_sync)
            logger.info(f"Automatizacion completada: {resultado_container[0]}")
        except Exception as e:
            logger.error(f"Error en thread automatizacion: {e}", exc_info=True)
            resultado_container[0] = {
                'exito': False, 'motivo': str(e), 'codigo': 'error_general'}
        finally:
            finished.set()

    t = threading.Thread(target=run_automation, daemon=True)
    t.start()
    logger.info(f"Thread lanzado para orden {orden}")

    # Esperar con polling cada 0.5s sin bloquear el event loop
    while not finished.is_set():
        await asyncio.sleep(0.5)

    resultado = resultado_container[0] or {
        'exito': False, 'motivo': 'Sin resultado', 'codigo': 'error'}

    # Registrar operación en base de datos
    try:
        chat_id = update.effective_chat.id
        if resultado['exito']:
            db.log_operacion(
                chat_id, orden, 'exito',
                f"suscriptor={resultado.get('suscriptor','N/A')}, "
                f"fecha={resultado.get('fecha','N/A')}, "
                f"franja={resultado.get('franja','N/A')}"
            )
        else:
            db.log_operacion(
                chat_id, orden, 'error',
                f"codigo={resultado.get('codigo','')}, "
                f"motivo={resultado.get('motivo','')}"
            )
        logger.info(f"Operación registrada en BD: orden={orden}, exito={resultado['exito']}")
    except Exception as e:
        logger.error(f"Error registrando operación en BD: {e}")

    try:
        if resultado['exito']:
            await msg.edit_text(
                f"✅ *Orden {orden}*\n\nLa acción se realizó correctamente.\n\n"
                f"👤 {resultado.get('suscriptor','N/A')}\n"
                f"📅 {resultado.get('fecha','N/A')} | 🕐 {resultado.get('franja','N/A')}",
                parse_mode='Markdown')
        else:
            motivo = resultado.get('motivo','Error desconocido')
            # Escapar caracteres especiales de Markdown
            for ch in ['_', '*', '`', '[', ']', '(', ')']:
                motivo = motivo.replace(ch, f'\\{ch}')
            if resultado.get('codigo') == 'orden_cerrada_rr':
                await msg.edit_text(
                    f"🔴 *Orden {orden}*\n\n"
                    f"La orden se encuentra cerrada en RR, no es posible actualizar.",
                    parse_mode='Markdown')
            elif resultado.get('codigo') in ('no_actualizar', 'error_actualizacion'):
                await msg.edit_text(
                    f"⚠️ *Orden {orden}*\n\nNo es posible actualizar.\n"
                    f"El botón Actualizar no está disponible para esta orden.\n\n"
                    f"🔄 *Se ha forzado el cierre de sesión automáticamente.*\n\n"
                    f"🔴 Valida con supervisor.",
                    parse_mode='Markdown')
            else:
                await msg.edit_text(f"❌ *Error orden {orden}*\n\n{motivo}", parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error editando mensaje: {e}")

async def procesar_orden(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_chat.id):
        await update.message.reply_text("⛔ No autorizado.")
        return ConversationHandler.END
    orden = update.message.text.strip()
    if not orden.isdigit():
        await update.message.reply_text("❌ Solo dígitos. Intenta nuevamente:")
        return WAITING_ORDER
    asyncio.create_task(_procesar(update, context, orden))
    return ConversationHandler.END

async def mensaje_directo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not is_authorized(chat_id):
        await update.message.reply_text(f"⛔ No autorizado.\nTu Chat ID: `{chat_id}`", parse_mode='Markdown')
        return
    texto = update.message.text.strip()

    # Auto-detectar SMS de PIN reenviado desde iPhone
    # Patrones: "Tu codigo de acceso es: 849415", "codigo de acceso es: 123456", etc.
    pin_match = re.search(r'(?:codigo|código|clave|pin|code).*?(\d{4,6})\s*$', texto, re.IGNORECASE)
    if pin_match and chat_id == ADMIN_ID:
        pin = pin_match.group(1)
        set_pin(pin)
        logger.info(f"PIN auto-detectado desde SMS reenviado: {pin}")
        await update.message.reply_text(f"🔑 PIN detectado automáticamente: `{pin}`\n✅ Enviado al sistema.", parse_mode='Markdown')
        return

    if texto.isdigit() and len(texto) >= 6:
        asyncio.create_task(_procesar(update, context, texto))
    else:
        await update.message.reply_text("📋 Envíame el número de orden o usa /actualizar")

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelado.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

async def cmd_adduser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID:
        await update.message.reply_text("⛔ Solo el administrador.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /adduser <chat_id> <nombre>")
        return
    try:
        new_id = int(context.args[0])
        nombre = ' '.join(context.args[1:]) or f"Usuario_{new_id}"
        db.add_user(new_id, nombre)
        await update.message.reply_text(f"✅ {nombre} ({new_id}) agregado.")
    except ValueError:
        await update.message.reply_text("❌ chat_id debe ser número.")

async def cmd_removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID:
        await update.message.reply_text("⛔ Solo el administrador.")
        return
    if not context.args:
        await update.message.reply_text("Uso: /removeuser <chat_id>")
        return
    try:
        db.remove_user(int(context.args[0]))
        await update.message.reply_text("✅ Usuario eliminado.")
    except ValueError:
        await update.message.reply_text("❌ chat_id debe ser número.")

async def cmd_listusers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID:
        await update.message.reply_text("⛔ Solo el administrador.")
        return
    users = db.list_users()
    if not users:
        await update.message.reply_text("No hay usuarios.")
        return
    texto = "👥 *Usuarios:*\n\n" + "\n".join(f"• `{u['chat_id']}` - {u['nombre']}" for u in users)
    await update.message.reply_text(texto, parse_mode='Markdown')

async def cmd_mychatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await update.message.reply_text(
        f"Tu Chat ID: `{update.effective_chat.id}`\n@{u.username or 'sin username'}",
        parse_mode='Markdown')

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.id != ADMIN_ID:
        await update.message.reply_text("⛔ Solo el administrador.")
        return
    session_file = os.getenv('SESSION_FILE', '/app/data/session.json')
    try:
        if os.path.exists(session_file):
            os.remove(session_file)
            await update.message.reply_text("🔄 Sesión eliminada. El próximo comando hará login nuevo (pedirá PIN).")
        else:
            await update.message.reply_text("ℹ️ No hay sesión guardada.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

def main():
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN no configurado")
    app = Application.builder().token(token).concurrent_updates(True).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler('actualizar', cmd_actualizar)],
        states={WAITING_ORDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, procesar_orden)]},
        fallbacks=[CommandHandler('cancelar', cancelar)],
    )
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('help', start))
    app.add_handler(CommandHandler('pin', cmd_pin, block=False))
    app.add_handler(CommandHandler('mychatid', cmd_mychatid))
    app.add_handler(CommandHandler('adduser', cmd_adduser))
    app.add_handler(CommandHandler('removeuser', cmd_removeuser))
    app.add_handler(CommandHandler('listusers', cmd_listusers))
    app.add_handler(CommandHandler('reset', cmd_reset))
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mensaje_directo))
    logger.info("Bot iniciado...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
