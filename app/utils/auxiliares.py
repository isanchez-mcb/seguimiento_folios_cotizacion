import pandas as pd

def standarNum(df, columnas):
    for col in columnas:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df

def regexNum(df, columnas):
    patron_numerico = r'^-?\d+(\.\d+)?$'
    for col in columnas:
        df.loc[df[col].astype(str).str.fullmatch(patron_numerico, na=False), col] = ''

def regexString(df, coincidencias):
    for col, patron in coincidencias.items():
        df.loc[df[col].astype(str).str.contains(patron, na=False, case=False), col] = ''

def dropRows(df, lista, column='PRODUCTO'):
    return df[~df[column].isin(lista)]

def standarNumString(value):
    try:
        return pd.to_numeric(value)
    except (ValueError, TypeError):
        return value
        
def safe_concat(df_list):
    valid_dfs = [df for df in df_list if df is not None]
    if not valid_dfs:
        return pd.DataFrame()
    else:
        return pd.concat(valid_dfs, ignore_index=True)
