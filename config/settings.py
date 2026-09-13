import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
CREDENTIALS_PATH = BASE_DIR / "credentials.json"
PRECIOS_PATH = BASE_DIR / "precios_lista.json"

CRM_SHEET_ID = os.getenv("CRM_SHEET_ID", "")
VENTAS_SHEET_ID = os.getenv("VENTAS_SHEET_ID", "")
CRM_TAB = os.getenv("CRM_TAB", "Trabajos")
VENTAS_TAB = os.getenv("VENTAS_TAB", "Ventas")

COHERE_API_KEY = os.getenv("COHERE_API_KEY", "")
