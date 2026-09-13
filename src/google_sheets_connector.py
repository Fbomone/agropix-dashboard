import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

from config.settings import CREDENTIALS_PATH

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


class GoogleSheetsConnector:
    def __init__(self):
        if not CREDENTIALS_PATH.exists():
            raise FileNotFoundError(
                f"No se encontro credentials.json en {CREDENTIALS_PATH}"
            )
        creds = Credentials.from_service_account_file(
            str(CREDENTIALS_PATH), scopes=SCOPES
        )
        self.gc = gspread.authorize(creds)

    def read_tab(self, sheet_id: str, tab_name: str) -> pd.DataFrame:
        ws = self.gc.open_by_key(sheet_id).worksheet(tab_name)
        values = ws.get_all_values(value_render_option="UNFORMATTED_VALUE")

        if not values:
            return pd.DataFrame()

        headers = self._dedupe([str(h).strip() for h in values[0]])
        # indice = numero de fila en el Sheet (header en la fila 1), para poder
        # señalar celdas problemáticas aunque se descarten filas vacías
        df = pd.DataFrame(values[1:], columns=headers, index=range(2, len(values) + 1))

        df = df.loc[:, [c for c in df.columns if c and not c.startswith("col_")]]
        df = df.replace("", pd.NA).dropna(how="all")
        return df

    @staticmethod
    def _dedupe(headers):
        seen, out = {}, []
        for i, h in enumerate(headers):
            if not h:
                out.append(f"col_{i}")
                continue
            if h in seen:
                seen[h] += 1
                out.append(f"{h}_{seen[h]}")
            else:
                seen[h] = 0
                out.append(h)
        return out