# 🤖 Bot de Agendamiento Claro

Bot de Telegram que automatiza la actualización de órdenes de trabajo en el Módulo de Gestión de Claro.

## Arquitectura

- **Python 3.11** con `python-telegram-bot` (v20)
- **Playwright** + Chromium headless para automatizar la web
- **IMAP** para leer el OTP del correo Microsoft
- **SQLite** para control de usuarios autorizados
- Docker con nombre: `claro_bot_agenda`

---

## Paso 1: Crear el Bot en Telegram

1. Abre Telegram y busca **@BotFather**
2. Envía el comando `/newbot`
3. Ponle un nombre: `Claro Agendamiento`
4. Ponle un username (debe terminar en `bot`): `claro_agenda_bot`
5. Copia el **Token** que te da BotFather

---

## Paso 2: Obtener tu Chat ID

1. Busca tu bot en Telegram y escríbele `/start`
2. Temporalmente, usa este método: ve a `https://api.telegram.org/botTU_TOKEN/getUpdates`
3. O activa el bot primero (paso 3), agrégalo al servidor, y usa `/mychatid`

---

## Paso 3: Configurar variables de entorno

```bash
cd claro_bot_agenda
cp .env.example .env
nano .env
```

Edita el archivo `.env`:

```env
TELEGRAM_BOT_TOKEN=1234567890:AAAA...TU_TOKEN
ADMIN_CHAT_ID=TU_CHAT_ID_NUMERICO
AGENDA_USER=38101385
AGENDA_PASS=Cal1vall--
EMAIL_HOST=outlook.office365.com
EMAIL_PORT=993
EMAIL_USER=johan.lopez@claro.com.co
EMAIL_PASS=TU_CONTRASEÑA_EMAIL
```

> ⚠️ **Importante sobre EMAIL_PASS**: Si tu cuenta corporativa tiene MFA activado,
> necesitas una **App Password** (contraseña de aplicación) en lugar de tu contraseña normal.
> En Outlook/Microsoft 365: Ve a Mi Cuenta → Seguridad → Contraseñas de aplicación.

---

## Paso 4: Construir y levantar el contenedor

```bash
cd claro_bot_agenda

# Construir imagen (primera vez o cuando cambie el código)
docker-compose build

# Levantar en segundo plano
docker-compose up -d

# Ver logs en tiempo real
docker-compose logs -f
```

---

## Paso 5: Agregar tu usuario como administrador

```bash
# Primero obtén tu Chat ID escribiéndole /mychatid al bot
# Luego agrégalo:
docker exec -it claro_bot_agenda python add_admin.py 123456789 "Johan Lopez"
```

---

## Uso del Bot

### Comandos disponibles para usuarios autorizados:

| Comando | Descripción |
|---------|-------------|
| `/start` o `/help` | Información del bot |
| `/actualizar` | Iniciar proceso de actualización de orden |
| `/mychatid` | Ver tu Chat ID de Telegram |
| `469126875` | También puedes enviar el número directamente |

### Comandos solo para administrador:

| Comando | Descripción |
|---------|-------------|
| `/adduser 123456 Nombre` | Agregar usuario autorizado |
| `/removeuser 123456` | Remover usuario |
| `/listusers` | Ver todos los usuarios autorizados |

---

## Flujo del Bot

```
Usuario envía número de orden
         ↓
Bot hace login en moduloagenda.cable.net.co
         ↓
Selecciona EMAIL como canal OTP
         ↓
Lee automáticamente el PIN del correo johan.lopez@claro.com.co
         ↓
Ingresa el PIN y completa el login
         ↓
Ingresa la orden en el formulario → Consultar
         ↓
Hace clic en "Actualizar"
         ↓
  ┌──────────────────────────────────┐
  │ ¿Apareció "La acción se realizó  │
  │  correctamente"?                 │
  └──────────────────────────────────┘
         ↓                    ↓
      SÍ ✅                   NO ⚠️
"Orden actualizada"    "No es posible actualizar.
 correctamente"         Valida con supervisor."
```

---

## Mantenimiento

```bash
# Ver logs
docker logs claro_bot_agenda -f

# Reiniciar
docker restart claro_bot_agenda

# Reconstruir tras cambios de código
docker-compose down && docker-compose build && docker-compose up -d

# Ver base de datos de usuarios
docker exec -it claro_bot_agenda python add_admin.py --list
```

---

## Solución de problemas

### El bot no responde
- Verifica que `TELEGRAM_BOT_TOKEN` sea correcto
- `docker logs claro_bot_agenda`

### No puede leer el OTP del correo
- Verifica credenciales IMAP en `.env`
- Confirma que IMAP esté habilitado en tu cuenta Exchange
- Puede requerir App Password si hay MFA

### Error de login en la web
- Verifica `AGENDA_USER` y `AGENDA_PASS`
- Revisa si el usuario está bloqueado (máx 3 intentos OTP)
