import imaplib
import email
import re
import time
import os
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

EMAIL_HOST = os.getenv('EMAIL_HOST', 'outlook.office365.com')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '993'))
EMAIL_USER = os.getenv('EMAIL_USER', '')
EMAIL_PASS = os.getenv('EMAIL_PASS', '')


def get_otp_from_email(timeout_seconds: int = 90, check_interval: int = 3) -> Optional[str]:
    start_time = time.time()
    marca_tiempo = datetime.now(timezone.utc)
    logger.info(f"Esperando OTP en correo {EMAIL_USER}...")
    while time.time() - start_time < timeout_seconds:
        try:
            pin = _buscar_pin_en_correo(marca_tiempo)
            if pin:
                logger.info(f"OTP encontrado: {pin}")
                return pin
        except Exception as e:
            logger.warning(f"Error leyendo correo: {e}")
        time.sleep(check_interval)
    logger.error("Timeout esperando OTP en correo")
    return None


def _buscar_pin_en_correo(desde_cuando: datetime) -> Optional[str]:
    if not EMAIL_USER or not EMAIL_PASS:
        raise ValueError("EMAIL_USER y EMAIL_PASS no configurados")
    mail = imaplib.IMAP4_SSL(EMAIL_HOST, EMAIL_PORT)
    try:
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select('INBOX')
        fecha_busqueda = desde_cuando.strftime("%d-%b-%Y")
        _, mensajes = mail.search(None, f'(SINCE "{fecha_busqueda}" UNSEEN)')
        ids = mensajes[0].split()
        if not ids:
            _, mensajes = mail.search(None, f'(SINCE "{fecha_busqueda}")')
            ids = mensajes[0].split()
        if not ids:
            return None
        for msg_id in reversed(ids[-10:]):
            _, data = mail.fetch(msg_id, '(RFC822)')
            raw = data[0][1]
            msg = email.message_from_bytes(raw)
            cuerpo = _extraer_cuerpo(msg)
            patrones = [
                r'(?:PIN|OTP|c[oó]digo|clave)[:\s]+(\d{4,8})',
                r'es[:\s]+(\d{6})\b',
                r'\b(\d{6})\b',
                r'\b(\d{4})\b',
            ]
            for patron in patrones:
                match = re.search(patron, cuerpo, re.IGNORECASE)
                if match:
                    return match.group(1)
        return None
    finally:
        try:
            mail.logout()
        except Exception:
            pass


def _extraer_cuerpo(msg) -> str:
    cuerpo = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == 'text/plain':
                try:
                    cuerpo += part.get_payload(decode=True).decode('utf-8', errors='ignore')
                except Exception:
                    pass
            elif ct == 'text/html' and not cuerpo:
                try:
                    html = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    cuerpo += re.sub(r'<[^>]+>', ' ', html)
                except Exception:
                    pass
    else:
        try:
            cuerpo = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
        except Exception:
            cuerpo = str(msg.get_payload())
    return cuerpo
