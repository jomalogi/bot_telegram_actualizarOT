# 🤖 Bot de Actualización de OT - Claro

Bot de Telegram que automatiza la actualización de órdenes de trabajo (OT) en el Módulo de Gestión de Claro.

## Arquitectura

- **Python 3.11** con `python-telegram-bot` (v20)
- **Playwright** + Chromium headless para automatizar la web
- **API Flask** para recibir PIN por SMS desde iPhone
- **iPhone Shortcut** para interceptar SMS y reenviar el PIN automáticamente
- **SQLite** para control de usuarios autorizados y log de operaciones
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
2. Usa el comando `/mychatid` para ver tu ID
3. O visita `https://api.telegram.org/botTU_TOKEN/getUpdates`

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
API_PORT=5050
API_KEY=claro2026
DB_PATH=/app/data/bot.db
```

> ⚠️ **Ya no se necesitan credenciales de correo**. El PIN se recibe por SMS
> a través de un Shortcut de iPhone que lo envía automáticamente al API.

---

## Paso 4: Configurar el Shortcut de iPhone (Automatización SMS → API)

El iPhone intercepta automáticamente el SMS con el código de acceso y lo envía al servidor.

### Crear la Automatización en iPhone:

1. Abre la app **Atajos** (Shortcuts) en tu iPhone
2. Ve a la pestaña **Automatización**
3. Toca **+** → **Crear automatización personal**
4. Selecciona **Mensaje** → "El mensaje contiene: `codigo de acceso`"
5. Selecciona **Ejecutar inmediatamente** (sin preguntar)
6. Agrega la acción **Obtener contenido de URL** con:

```
URL: http://TU_IP_SERVIDOR:5050/api/sms_pin?api_key=claro2026
Método: POST
Cuerpo: JSON
  - text: [Atajo de Mensaje]  (variable del SMS recibido)
```

### Endpoint del API:

```
POST http://186.147.60.119:5050/api/sms_pin?api_key=claro2026

Body (JSON):
{
  "text": "Tu codigo de acceso es: 849415"
}

Respuesta exitosa:
{
  "ok": true,
  "pin": "849415",
  "mensaje": "PIN 849415 enviado al bot"
}
```

El API extrae automáticamente los dígitos del PIN del texto del SMS y lo pasa al bot.

---

## Paso 5: Construir y levantar el contenedor

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

## Paso 6: Agregar tu usuario como administrador

```bash
# Primero obtén tu Chat ID escribiéndole /mychatid al bot
# Luego agrégalo:
docker exec -it claro_bot_agenda python add_admin.py 123456789 "Johan Lopez"
```

---

## Uso del Bot

### Comandos para usuarios autorizados:

| Comando | Descripción |
|---------|-------------|
| `/start` o `/help` | Información del bot |
| `/actualizar` | Iniciar proceso de actualización de orden |
| `/mychatid` | Ver tu Chat ID de Telegram |
| `469126875` | Enviar el número de orden directamente |

### Comandos solo para administrador:

| Comando | Descripción |
|---------|-------------|
| `/pin <código>` | Enviar PIN manualmente (backup si falla el iPhone) |
| `/reset` | Forzar cierre de sesión para nuevo login |
| `/adduser 123456 Nombre` | Agregar usuario autorizado |
| `/removeuser 123456` | Remover usuario |
| `/listusers` | Ver todos los usuarios autorizados |

---

## Flujo del Bot

```
Usuario envía número de orden (ej: 469126875 o 7392149)
         ↓
Bot hace login en moduloagenda.cable.net.co
         ↓
Selecciona SMS como canal OTP
         ↓
Se envía SMS al celular del admin
         ↓
  ┌─────────────────────────────────────────┐
  │  📱 iPhone Shortcut (automático)         │
  │  Detecta SMS → Extrae PIN → POST al API │
  │  http://servidor:5050/api/sms_pin        │
  └─────────────────────────────────────────┘
         ↓
Bot recibe el PIN automáticamente
         ↓
Ingresa el PIN y completa el login
         ↓
  ┌──────────────────────────────────────┐
  │ ¿La orden tiene 7 dígitos?            │
  │  SÍ → Selecciona "Llamada de servicio"│
  │  NO → Continúa con flujo normal       │
  └──────────────────────────────────────┘
         ↓
Ingresa la orden en el formulario → Consultar
         ↓
Hace clic en "Actualizar"
         ↓
  ┌──────────────────────────────────────┐
  │         ¿Resultado?                   │
  └──────────────────────────────────────┘
     ↓              ↓              ↓
   ✅ Éxito      ⚠️ Error       🔴 Cerrada
  "Orden        "No es posible   "La orden se
 actualizada    actualizar.      encuentra
correctamente"  Valida con       cerrada en RR"
                supervisor."
```

---

## API de Datos (para Power BI)

El servidor API expone endpoints para consultar datos:

| Endpoint | Formato | Descripción |
|----------|---------|-------------|
| `/csv/operaciones` | CSV | Log de todas las operaciones |
| `/csv/usuarios` | CSV | Lista de usuarios autorizados |
| `/csv/reporte` | CSV | Reporte combinado con nombre de usuario |
| `/json/operaciones` | JSON | Operaciones en formato JSON |
| `/json/usuarios` | JSON | Usuarios en formato JSON |
| `/json/estadisticas` | JSON | Estadísticas resumidas |

Todos requieren `?api_key=claro2026`. Ejemplo:
```
http://186.147.60.119:5050/csv/reporte?api_key=claro2026&desde=2026-04-01
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
```

---

## Solución de problemas

### El bot no responde
- Verifica que `TELEGRAM_BOT_TOKEN` sea correcto
- `docker logs claro_bot_agenda`

### No llega el PIN automáticamente
- Verifica que el Shortcut de iPhone esté configurado correctamente
- Prueba manualmente: `curl -X POST "http://186.147.60.119:5050/api/sms_pin?api_key=claro2026" -H "Content-Type: application/json" -d '{"text":"Tu codigo de acceso es: 123456"}'`
- Como backup, el admin puede enviar `/pin 123456` directamente en Telegram

### Error de login en la web
- Verifica `AGENDA_USER` y `AGENDA_PASS`
- Usa `/reset` para forzar un nuevo login
- Revisa si el usuario está bloqueado (máx 3 intentos OTP)

### La orden aparece "cerrada en RR"
- Significa que la orden ya fue cerrada en el sistema RR y no se puede actualizar
- Contacta a la persona responsable para reabrir la orden
