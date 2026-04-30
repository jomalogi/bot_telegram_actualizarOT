import os
import asyncio
import logging
import re
import threading
import queue
from typing import Dict, Any, Optional
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

AGENDA_URL = "https://moduloagenda.cable.net.co/"
AGENDA_INDEX_URL = "https://moduloagenda.cable.net.co/MGW/MGW/Agendamiento/index.php"
AGENDA_USER = os.getenv("AGENDA_USER", "")
AGENDA_PASS = os.getenv("AGENDA_PASS", "")
SESSION_FILE = os.getenv("SESSION_FILE", "/app/data/session.json")

# Cola para pasar el PIN entre threads (usado por /pin command)
_pin_queue = queue.Queue()

# Archivo compartido para PIN (usado por api_server en otro contenedor)
PIN_FILE = os.path.join(os.path.dirname(SESSION_FILE), "pin.txt")


def set_pin(pin: str):
    """Llamado desde bot.py cuando el admin envía /pin"""
    # Poner en cola (para el thread de espera)
    while not _pin_queue.empty():
        try:
            _pin_queue.get_nowait()
        except:
            pass
    _pin_queue.put(pin)
    # También escribir al archivo compartido (para compatibilidad con api_server)
    try:
        with open(PIN_FILE, 'w') as f:
            f.write(pin)
        logger.info(f"PIN en cola y archivo: {pin}")
    except Exception as e:
        logger.error(f"Error escribiendo PIN en archivo: {e}")
        logger.info(f"PIN en cola: {pin}")


def _esperar_pin_sync(timeout: int = 600) -> Optional[str]:
    """Espera el PIN de la cola O del archivo compartido"""
    # Limpiar cola y archivo antes de esperar
    while not _pin_queue.empty():
        try:
            _pin_queue.get_nowait()
        except:
            pass
    try:
        if os.path.exists(PIN_FILE):
            os.remove(PIN_FILE)
    except:
        pass

    logger.info(f"Esperando PIN (cola + archivo, timeout={timeout}s)...")
    import time
    start = time.time()
    while time.time() - start < timeout:
        # Check 1: cola (del comando /pin en bot.py)
        try:
            pin = _pin_queue.get_nowait()
            logger.info(f"PIN recibido de la cola: {pin}")
            # Limpiar archivo si existe
            try:
                os.remove(PIN_FILE)
            except:
                pass
            return pin
        except queue.Empty:
            pass

        # Check 2: archivo (del endpoint /api/sms_pin en api_server)
        try:
            if os.path.exists(PIN_FILE):
                with open(PIN_FILE, 'r') as f:
                    pin = f.read().strip()
                if pin and pin.isdigit():
                    logger.info(f"PIN recibido del archivo: {pin}")
                    os.remove(PIN_FILE)
                    return pin
        except:
            pass

        time.sleep(1)  # Polling cada 1 segundo

    logger.warning("Timeout esperando PIN")
    return None


class AgendaAutomation:

    def procesar_orden_sync(self, orden: str, notify_callback_sync=None) -> Dict[str, Any]:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self._run(orden, notify_callback_sync))
        finally:
            loop.close()

    async def _run(self, orden: str, notify_callback_sync=None) -> Dict[str, Any]:
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                      "--ignore-certificate-errors", "--disable-blink-features=AutomationControlled"]
            )

            if os.path.exists(SESSION_FILE):
                try:
                    ctx = await browser.new_context(
                        storage_state=SESSION_FILE, ignore_https_errors=True, user_agent=ua)
                    await ctx.add_init_script(
                        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
                    logger.info("Sesion cargada")
                except Exception as e:
                    logger.warning(f"Error cargando sesion: {e}")
                    ctx = await browser.new_context(ignore_https_errors=True, user_agent=ua)
                    await ctx.add_init_script(
                        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
            else:
                ctx = await browser.new_context(ignore_https_errors=True, user_agent=ua)
                await ctx.add_init_script(
                    "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")

            page = await ctx.new_page()
            page.set_default_timeout(60000)

            try:
                # Verificar sesion
                sesion_ok = False
                if os.path.exists(SESSION_FILE):
                    try:
                        await page.goto(AGENDA_INDEX_URL, wait_until="domcontentloaded", timeout=60000)
                        await asyncio.sleep(2)
                        content = await page.content()
                        if ("MGW" in page.url and "Denegado" not in content
                                and "Iniciar" not in content and "login" not in page.url.lower()):
                            sesion_ok = True
                            logger.info("Sesion activa reutilizada")
                    except Exception as e:
                        logger.warning(f"Sesion invalida: {e}")

                if not sesion_ok:
                    if os.path.exists(SESSION_FILE):
                        os.remove(SESSION_FILE)
                    res = await self._login(page, ctx, notify_callback_sync)
                    if not res["exito"]:
                        return res

                # Consultar orden
                res = await self._consultar(page, orden)
                if not res["exito"]:
                    return res

                # Actualizar
                return await self._actualizar(page, orden)

            except Exception as e:
                logger.error(f"Error general: {e}", exc_info=True)
                try:
                    os.remove(SESSION_FILE)
                except:
                    pass
                return {"exito": False, "motivo": str(e), "codigo": "error_general"}
            finally:
                await page.close()
                await ctx.close()
                await browser.close()

    async def _login(self, page: Page, ctx, notify_callback_sync=None) -> Dict[str, Any]:
        try:
            logger.info("Iniciando login...")
            await page.goto(AGENDA_URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(2)

            # Ingresar credenciales
            await page.locator("input[type='text']").first.fill(AGENDA_USER)
            await asyncio.sleep(0.3)
            await page.locator("input[type='password']").first.fill(AGENDA_PASS)
            await asyncio.sleep(0.3)
            await page.locator("input[type='submit']").first.click()
            await asyncio.sleep(4)
            logger.info(f"URL post-login: {page.url}")

            # Paso 2: Seleccionar canal SMS y enviar
            if "canalPin" in page.url:
                logger.info("Seleccionando SMS como canal...")
                try:
                    await page.locator("input[value='SMS']").check(timeout=5000)
                except:
                    # Fallback
                    radios = await page.locator("input[type='radio']").all()
                    if radios:
                        await radios[0].check()
                
                await asyncio.sleep(0.5)
                # Ensure we click the button properly, bypassing the 'input' mistake from fix_otp
                try:
                    await page.locator("button[value='enviar']").click(timeout=5000)
                except:
                    await page.evaluate(
                        "() => { const b=document.querySelectorAll(\"button[type='submit']\");"
                        " for(const x of b){if(x.value==='enviar'){x.click();return;}} }"
                    )
                
                try:
                    await page.wait_for_url("**/validarPin*", timeout=15000)
                except Exception as e:
                    logger.warning(f"Timeout esperando validarPin: {e}")
                    await asyncio.sleep(2)
                
                logger.info(f"URL tras seleccionar canal: {page.url}")

            # Paso 3: Ingresar PIN
            if "validarPin" in page.url:
                logger.info("Pagina validarPin detectada")

                # Notificar al admin
                if notify_callback_sync:
                    try:
                        notify_callback_sync(
                            "🔐 *Se requiere PIN para iniciar sesión*\n\n"
                            "Se envió un PIN por SMS a tu celular.\n\n"
                            "Responde con:\n`/pin <codigo>`\n"
                            "Ejemplo: `/pin 123456`\n\n"
                            "⏳ Tienes 10 minutos."
                        )
                        logger.info("Notificacion enviada al admin")
                    except Exception as e:
                        logger.error(f"Error notificando: {e}")

                # Esperar PIN en thread separado para no bloquear
                logger.info("Esperando PIN del admin...")
                pin = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: _esperar_pin_sync(timeout=600)
                )

                if not pin:
                    return {"exito": False,
                            "motivo": "Timeout esperando PIN (10 minutos). Intenta de nuevo.",
                            "codigo": "error_pin_timeout"}

                logger.info(f"PIN recibido: {pin}, ingresando en formulario...")

                # Buscar campo de PIN
                pin_input = None
                for sel in ["input[type='number']", "input[name='pin']",
                           "input[type='text']", "input[type='tel']"]:
                    try:
                        el = page.locator(sel).first
                        if await el.is_visible():
                            pin_input = el
                            logger.info(f"Campo PIN encontrado: {sel}")
                            break
                    except:
                        pass

                if not pin_input:
                    return {"exito": False, "motivo": "No se encontro campo PIN",
                            "codigo": "error_pin"}

                await pin_input.fill(pin)
                await asyncio.sleep(0.5)

                # Click en Validar
                try:
                    btn = page.locator("button:has-text('Validar'), input[value='Validar'], button[value='validar']").first
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                    else:
                        await page.locator("button[type='submit'], input[type='submit']").first.click()
                except:
                    await page.locator("button[type='submit'], input[type='submit']").first.click()

                await asyncio.sleep(4)
                logger.info(f"PIN validado, URL: {page.url}")

            # Paso 4: Ir al modulo de agendamiento
            await page.goto(AGENDA_INDEX_URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(2)
            content = await page.content()
            logger.info(f"URL modulo: {page.url}")

            if "Denegado" in content or "MGW" not in page.url:
                return {"exito": False, "motivo": "Acceso denegado al modulo",
                        "codigo": "error_acceso"}

            # Guardar sesion para proximas solicitudes
            try:
                os.makedirs(os.path.dirname(SESSION_FILE), exist_ok=True)
                await ctx.storage_state(path=SESSION_FILE)
                logger.info("Sesion guardada correctamente")
            except Exception as e:
                logger.warning(f"No se pudo guardar sesion: {e}")

            return {"exito": True}

        except Exception as e:
            logger.error(f"Error en login: {e}", exc_info=True)
            return {"exito": False, "motivo": str(e), "codigo": "error_login"}

    async def _consultar(self, page: Page, orden: str) -> Dict[str, Any]:
        """Paso 4 del PDF: ingresar orden y consultar"""
        try:
            logger.info(f"Consultando orden {orden}...")
            await page.goto(AGENDA_INDEX_URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(2)

            try:
                await page.wait_for_selector("input[type='text']", timeout=15000)
            except:
                pass

            inputs = await page.locator("input[type='text']").all()
            logger.info(f"Inputs encontrados: {len(inputs)}")
            if not inputs:
                return {"exito": False, "motivo": "No se encontro campo de orden",
                        "codigo": "error_consulta"}

            # Ingresar numero de orden
            await inputs[0].click(click_count=3)
            await inputs[0].fill(orden)
            await asyncio.sleep(0.5)

            # Seleccionar tipo de orden según longitud
            # 7 dígitos = "Llamada de servicio"
            # Otro = "Orden de Trabajo"
            try:
                if len(orden) == 7:
                    tipo_objetivo = "llamada"
                    logger.info(f"Orden de 7 dígitos: buscando radio 'Llamada de servicio'")
                else:
                    tipo_objetivo = "trabajo"
                    logger.info(f"Orden de {len(orden)} dígitos: buscando radio 'Orden de Trabajo'")

                # Debug: listar todos los radio buttons y sus labels
                radios_info = await page.evaluate("""() => {
                    const radios = document.querySelectorAll("input[type='radio']");
                    const info = [];
                    radios.forEach((r, i) => {
                        // Buscar label asociado
                        let labelText = '';
                        // Por atributo for
                        if (r.id) {
                            const lbl = document.querySelector("label[for='" + r.id + "']");
                            if (lbl) labelText = lbl.textContent.trim();
                        }
                        // Por parentNode
                        if (!labelText && r.parentElement) {
                            labelText = r.parentElement.textContent.trim();
                        }
                        // Por nextSibling text
                        if (!labelText && r.nextSibling) {
                            labelText = (r.nextSibling.textContent || '').trim();
                        }
                        info.push({
                            index: i, name: r.name, value: r.value,
                            id: r.id, checked: r.checked, label: labelText
                        });
                    });
                    return info;
                }""")
                logger.info(f"DEBUG radios encontrados: {radios_info}")

                # Estrategia 1: Seleccionar por label/texto usando JS
                selected = await page.evaluate("""(tipo) => {
                    const radios = document.querySelectorAll("input[type='radio']");
                    for (const r of radios) {
                        let labelText = '';
                        if (r.id) {
                            const lbl = document.querySelector("label[for='" + r.id + "']");
                            if (lbl) labelText = lbl.textContent.trim().toLowerCase();
                        }
                        if (!labelText && r.parentElement) {
                            labelText = r.parentElement.textContent.trim().toLowerCase();
                        }
                        if (!labelText && r.nextSibling) {
                            labelText = (r.nextSibling.textContent || '').trim().toLowerCase();
                        }
                        const val = (r.value || '').toLowerCase();

                        if (tipo === 'llamada' && (labelText.includes('llamada') || labelText.includes('servicio') || val.includes('llamada') || val.includes('servicio'))) {
                            r.checked = true;
                            r.click();
                            r.dispatchEvent(new Event('change', {bubbles: true}));
                            return {found: true, label: labelText, value: r.value};
                        }
                        if (tipo === 'trabajo' && (labelText.includes('trabajo') || val.includes('trabajo'))) {
                            r.checked = true;
                            r.click();
                            r.dispatchEvent(new Event('change', {bubbles: true}));
                            return {found: true, label: labelText, value: r.value};
                        }
                    }
                    return {found: false};
                }""", tipo_objetivo)

                if selected and selected.get("found"):
                    logger.info(f"Radio seleccionado por label/value: {selected}")
                else:
                    # Estrategia 2: Fallback por índice
                    logger.warning(f"No se encontró radio por label, usando fallback por índice")
                    radios = await page.locator("input[type='radio']").all()
                    if radios:
                        if tipo_objetivo == "llamada" and len(radios) >= 3:
                            await radios[2].check()
                            logger.info("Fallback: seleccionado radio índice 2 (Llamada)")
                        else:
                            await radios[0].check()
                            logger.info("Fallback: seleccionado radio índice 0 (Trabajo)")

                await asyncio.sleep(0.5)

                # Verificar selección
                check_result = await page.evaluate("""() => {
                    const radios = document.querySelectorAll("input[type='radio']");
                    for (const r of radios) {
                        if (r.checked) {
                            let labelText = '';
                            if (r.parentElement) labelText = r.parentElement.textContent.trim();
                            return {value: r.value, label: labelText, checked: true};
                        }
                    }
                    return {checked: false};
                }""")
                logger.info(f"Verificación radio seleccionado: {check_result}")

            except Exception as e:
                logger.warning(f"Error seleccionando tipo de orden: {e}", exc_info=True)
            
            await asyncio.sleep(0.3)

            # Click Consultar
            try:
                await page.locator("button[value='consultar'], button:has-text('Consultar'), input[value='Consultar']").first.click()
            except:
                await page.locator("input[type='submit']").first.click()
            await asyncio.sleep(4)
            logger.info(f"Orden consultada, URL: {page.url}")

            # Detectar si la orden está cerrada en RR (popup modal)
            try:
                content = await page.content()
                if "cerrada en RR" in content:
                    logger.warning(f"Orden {orden} cerrada en RR")
                    # Intentar cerrar el popup haciendo clic en "Aceptar"
                    try:
                        await page.locator("button:has-text('Aceptar'), input[value='Aceptar'], a:has-text('Aceptar')").first.click(timeout=3000)
                    except:
                        pass
                    return {
                        "exito": False,
                        "motivo": "La orden se encuentra cerrada en RR, no es posible actualizar.",
                        "codigo": "orden_cerrada_rr"
                    }
            except Exception as e:
                logger.warning(f"Error verificando estado cerrada en RR: {e}")

            return {"exito": True}

        except Exception as e:
            logger.error(f"Error consultando: {e}")
            return {"exito": False, "motivo": str(e), "codigo": "error_consulta"}

    async def _actualizar(self, page: Page, orden: str) -> Dict[str, Any]:
        """Paso 5 del PDF: hacer clic en Actualizar"""
        try:
            # Detectar frames
            frames = page.frames
            logger.info(f"DEBUG total frames: {len(frames)}")
            for f in frames:
                logger.info(f"DEBUG frame: name='{f.name}', url={f.url}")

            # Buscar el frame que contiene los botones de accion
            target = page
            for f in frames:
                if f == page.main_frame:
                    continue
                try:
                    has_btns = await f.evaluate("""() => {
                        const els = document.querySelectorAll('input, button');
                        return Array.from(els).map(e => e.value || e.textContent).join('|');
                    }""")
                    logger.info(f"DEBUG frame '{f.name}' elements: {has_btns[:200]}")
                    if 'ctualizar' in has_btns:
                        target = f
                        logger.info(f"Frame con Actualizar encontrado: {f.name}")
                        break
                except:
                    continue

            # Debug: buscar tabs y links
            try:
                tabs_debug = await target.evaluate("""() => {
                    const results = {tabs: [], links: [], jquery_tabs: false, ul_tabs: []};
                    // Buscar jQuery UI tabs
                    if (typeof $ !== 'undefined' && $.fn && $.fn.tabs) {
                        results.jquery_tabs = true;
                    }
                    // Buscar UL con tabs
                    document.querySelectorAll('ul').forEach(ul => {
                        const lis = ul.querySelectorAll('li');
                        if (lis.length >= 3) {
                            const texts = Array.from(lis).map(li => li.textContent.trim());
                            if (texts.some(t => t.includes('Orden') || t.includes('Visita'))) {
                                results.ul_tabs = texts;
                            }
                        }
                    });
                    // Links con texto de tab
                    document.querySelectorAll('a').forEach(a => {
                        const t = a.textContent.trim();
                        if (['Orden','Visita','Cuenta','Calidad','Confirmación','Mensaje','Bitacora','Actividades'].some(x => t.includes(x))) {
                            results.tabs.push({text: t, href: a.href, id: a.id, onclick: a.getAttribute('onclick')||'', class: a.className});
                        }
                    });
                    return results;
                }""")
                logger.info(f"DEBUG tabs: {tabs_debug}")
            except Exception as e:
                logger.warning(f"Error debug tabs: {e}")

            # Hacer clic en la pestaña "Visita" - multiples estrategias
            visita_clicked = False
            
            # Estrategia 1: jQuery UI tabs (muy comun en estas apps)
            try:
                visita_clicked = await target.evaluate("""() => {
                    // jQuery UI tabs
                    if (typeof $ !== 'undefined') {
                        const tabs = $('ul.ui-tabs-nav li a, ul.nav-tabs li a, .ui-tabs-nav a');
                        for (let i = 0; i < tabs.length; i++) {
                            if ($(tabs[i]).text().trim().includes('Visita')) {
                                $(tabs[i]).click();
                                return true;
                            }
                        }
                        // Intentar por indice (Visita suele ser la segunda tab, indice 1)
                        const allTabs = $('ul li a').filter(function() { return $(this).text().trim() === 'Visita'; });
                        if (allTabs.length > 0) {
                            allTabs[0].click();
                            return true;
                        }
                    }
                    // Vanilla JS
                    const links = document.querySelectorAll('a');
                    for (const a of links) {
                        if (a.textContent.trim() === 'Visita') {
                            a.click();
                            return true;
                        }
                    }
                    return false;
                }""")
                if visita_clicked:
                    logger.info("Clic en Visita por JS")
                    await asyncio.sleep(3)
            except Exception as e:
                logger.warning(f"Error click Visita JS: {e}")
            
            # Estrategia 2: Playwright locator directo
            if not visita_clicked:
                for sel in ["a:has-text('Visita')", "li:has-text('Visita') >> a", "text=Visita"]:
                    try:
                        tab = target.locator(sel).first
                        if await tab.is_visible(timeout=2000):
                            await tab.click()
                            logger.info(f"Clic en Visita por locator: {sel}")
                            visita_clicked = True
                            await asyncio.sleep(3)
                            break
                    except:
                        continue
            
            if not visita_clicked:
                logger.warning("No se pudo hacer clic en pestaña Visita")

            info = await self._extraer_info(page)
            logger.info(f"Info orden: {info}")

            # Tomar screenshot para depuracion
            try:
                screenshot_path = f"/app/data/debug_orden_{orden}.png"
                await target.screenshot(path=screenshot_path, full_page=True)
                logger.info(f"Screenshot guardado en {screenshot_path}")
            except Exception as e:
                logger.warning(f"Error tomando screenshot: {e}")

            # Debug: listar botones en el target frame
            try:
                all_buttons = await target.evaluate("""() => {
                    const results = [];
                    document.querySelectorAll('button, input[type="submit"], input[type="button"]').forEach(b => {
                        results.push({tag: b.tagName, text: (b.textContent||'').trim(), value: b.value||'', type: b.type||'', name: b.name||'', vis: b.offsetParent !== null});
                    });
                    return results;
                }""")
                logger.info(f"DEBUG botones target: {all_buttons}")
            except Exception as e:
                logger.warning(f"Error listando botones: {e}")

            # Buscar boton Actualizar
            btn = None
            for sel in [
                "input[value='Actualizar']", "input[value='actualizar']",
                "button[value='actualizar']", "button[value='Actualizar']",
                "button:has-text('Actualizar')", "a:has-text('Actualizar')",
            ]:
                try:
                    loc = target.locator(sel).first
                    if await loc.is_visible(timeout=1000):
                        btn = loc
                        logger.info(f"Boton encontrado: {sel}")
                        break
                except:
                    continue

            # Fallback JS en el target
            if not btn:
                try:
                    found = await target.evaluate("""() => {
                        for (const el of document.querySelectorAll('input, button, a')) {
                            const v = (el.value || '').toLowerCase();
                            const t = (el.textContent || '').toLowerCase().trim();
                            if (v.includes('actualizar') || t === 'actualizar') {
                                el.setAttribute('data-auto-act', '1');
                                return {tag: el.tagName, value: el.value, text: el.textContent.trim(), name: el.name};
                            }
                        }
                        return null;
                    }""")
                    if found:
                        logger.info(f"Boton por JS: {found}")
                        btn = target.locator("[data-auto-act='1']").first
                except Exception as e:
                    logger.warning(f"Error JS fallback: {e}")

            if not btn:
                # Capturar HTML final del body para debug
                try:
                    html_tail = await target.evaluate("() => document.body.innerHTML.slice(-1500)")
                    logger.info(f"DEBUG HTML tail: {html_tail}")
                except:
                    pass
                
                logger.warning("Boton Actualizar no disponible. Borrando sesión (reset) para la próxima solicitud.")
                try:
                    if os.path.exists(SESSION_FILE):
                        os.remove(SESSION_FILE)
                except Exception as e:
                    logger.error(f"Error borrando sesión: {e}")

                return {
                    "exito": False,
                    "motivo": "El botón Actualizar no está disponible para esta orden. Se borró la sesión automáticamente.",
                    "codigo": "no_actualizar",
                    **info
                }

            await btn.click()
            logger.info("Clic en Actualizar")
            await asyncio.sleep(3)

            # Verificar confirmacion
            try:
                await target.locator("text=/La acci[óo]n se realiz[óo] correctamente/i").first.wait_for(
                    state="visible", timeout=15000)
                try:
                    await target.locator("button:has-text('Aceptar'), input[value='Aceptar']").first.click()
                except:
                    pass
                logger.info("Actualizacion exitosa")
                return {"exito": True, "codigo": "exito", **info}
            except PlaywrightTimeout:
                return {
                    "exito": False,
                    "motivo": "No se recibio confirmacion de actualizacion",
                    "codigo": "error_actualizacion",
                    **info
                }

        except Exception as e:
            logger.error(f"Error actualizando: {e}")
            return {"exito": False, "motivo": str(e), "codigo": "error_actualizacion"}

    async def _extraer_info(self, page: Page) -> Dict[str, str]:
        """Extrae informacion del suscriptor de la pagina"""
        info = {}
        try:
            content = await page.content()
            for key, pattern in [
                ("suscriptor", r"Suscriptor[:\s]+([A-Z\s]+?)(?:<|\n|&)"),
                ("fecha", r"Fecha Programada[:\s]+([\d\-A-Z]+)"),
                ("franja", r"Franja Suscriptor[:\s]+([\d\-]+)"),
            ]:
                m = re.search(pattern, content)
                if m:
                    info[key] = m.group(1).strip()
        except:
            pass
        return info
