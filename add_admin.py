#!/usr/bin/env python3
"""
Script para agregar el primer usuario administrador a la base de datos.
Ejecutar DENTRO del contenedor o con el mismo .env cargado.

Uso:
  docker exec -it claro_bot_agenda python add_admin.py <CHAT_ID> <NOMBRE>

Ejemplo:
  docker exec -it claro_bot_agenda python add_admin.py 123456789 "Johan Lopez"
"""
import sys
import os
sys.path.insert(0, '/app')

from database import Database

def main():
    if len(sys.argv) < 3:
        print("Uso: python add_admin.py <chat_id> <nombre>")
        print("Ejemplo: python add_admin.py 123456789 'Johan Lopez'")
        sys.exit(1)

    try:
        chat_id = int(sys.argv[1])
    except ValueError:
        print("Error: chat_id debe ser un número entero")
        sys.exit(1)

    nombre = ' '.join(sys.argv[2:])
    
    db = Database()
    db.add_user(chat_id, nombre)
    print(f"✅ Usuario '{nombre}' con chat_id {chat_id} agregado correctamente.")
    
    # Mostrar todos los usuarios
    users = db.list_users()
    print(f"\nUsuarios autorizados ({len(users)}):")
    for u in users:
        print(f"  - {u['chat_id']}: {u['nombre']} (desde {u['fecha']})")

if __name__ == '__main__':
    main()
