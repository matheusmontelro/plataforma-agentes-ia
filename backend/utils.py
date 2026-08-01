# Funções auxiliares: parse de datas, formatação, etc.
from datetime import datetime

def parse_date(date_str):
    return datetime.strptime(date_str, "%d/%m/%Y")
