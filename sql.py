# insert_unique_tableA_pyodbc.py
# 目的: (col1:int, col2:text) が未登録の行だけ tableA に追加（pyodbc版）
# 前提: 一意制約・一時/常設テーブル作成なし、CSVは小～中規模、tableAは大きい
# 使い方:
#   pip install pyodbc
#   Python側はこのファイルを実行
#   ODBCドライバは「PostgreSQL Unicode(x64)」等をインストール/設定しておく

import csv
from dataclasses import dataclass
from typing import Iterable, List, Set, Tuple, Optional
import pyodbc

# ============ 接続設定（どちらか一方を使う） ============
# 1) DSN接続の場合（ODBCデータソース名を作っているとき）
USE_DSN = False
DSN_NAME = "PostgresDSN"   # ODBCデータソースの名前
USER = "youruser"
PASSWORD = "yourpass"

# 2) 直接接続文字列（DSN不要）
CONN_STR = (
    "DRIVER={PostgreSQL Unicode(x64)};"
    "SERVER=localhost;"
    "PORT=5432;"
    "DATABASE=yourdb;"
    "UID=youruser;"
    "PWD=yourpass;"
    # SSL使うなら: "SSLmode=require;"
)

CSV_PATH = "input.csv"   # ヘッダ: col1,col2,col3,col4,col5
BATCH_SIZE = 5000        # INSERTのバッチサイズ
NORMALIZE_COL2 = True    # True: col2 を trim + lower 正規化して判定
FETCH_CHUNK = 20000      # 既存キー取得時のチャンク（大きいtableA向け）
# =======================================================

@dataclass(frozen=True, eq=True)
class Key:
    col1: int
    col2: str  # 正規化後

def norm_col2(s: Optional[str]) -> str:
    if s is None:
        return ""
    return s.strip().lower() if NORMALIZE_COL2 else s

def read_csv_rows(path: str) -> List[Tuple[int, str, Optional[str], Optional[str], Optional[str]]]:
    rows: List[Tuple[int, str, Optional[str], Optional[str], Optional[str]]] = []
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for i, rec in enumerate(r, start=1):
            try:
                c1 = int(rec["col1"])
            except Exception as e:
                raise ValueError(f"Row {i}: col1 を int に変換できません: {rec.get('col1')}") from e
            c2 = rec.get("col2", "")
            c3 = rec.get("col3") or None
            c4 = rec.get("col4") or None
            c5 = rec.get("col5") or None
            rows.append((c1, c2, c3, c4, c5))
    return rows

def dedup_in_csv(rows: Iterable[Tuple[int, str, Optional[str], Optional[str], Optional[str]]]
                 ) -> List[Tuple[int, str, Optional[str], Optional[str], Optional[str]]]:
    """CSV内の (col1,col2) 重複を先勝ちで間引く"""
    seen: Set[Key] = set()
    out: List[Tuple[int, str, Optional[str], Optional[str], Optional[str]]] = []
    for c1, c2, c3, c4, c5 in rows:
        k = Key(c1, norm_col2(c2))
        if k in seen:
            continue
        seen.add(k)
        out.append((c1, c2, c3, c4, c5))
    return out

def fetch_existing_keys(cnxn) -> Set[Key]:
    """tableAの既存 (col1,col2) をチャンクで取得してメモリに保持"""
    keys: Set[Key] = set()
    cur = cnxn.cursor()
    # 正規化ロジックに合わせてSQL側も同じ式で取得
    if NORMALIZE_COL2:
        cur.execute("SELECT col1, lower(trim(col2)) FROM tableA")
    else:
        cur.execute("SELECT col1, col2 FROM tableA")

    while True:
        rows = cur.fetchmany(FETCH_CHUNK)
        if not rows:
            break
        for c1, c2 in rows:
            keys.add(Key(int(c1), c2 if c2 is not None else ""))
    cur.close()
    return keys

def filter_new_rows(csv_rows: Iterable[Tuple[int, str, Optional[str], Optional[str], Optional[str]]],
                    existing: Set[Key]):
    for c1, c2, c3, c4, c5 in csv_rows:
        if Key(c1, norm_col2(c2)) not in existing:
            yield (c1, c2, c3, c4, c5)

def batched(iterable, size):
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch

def insert_rows(cnxn, rows: List[Tuple[int, str, Optional[str], Optional[str], Optional[str]]]) -> int:
    if not rows:
        return 0
    # pyodbcのパラメータプレースホルダは "?"
    sql = "INSERT INTO tableA (col1, col2, col3, col4, col5) VALUES (?, ?, ?, ?, ?)"
    cur = cnxn.cursor()

    # ※ pyodbc の fast_executemany は PostgreSQL ODBC では効果が限定的／非推奨な場合があります
    #    （主にSQL Server向け最適化）。通常の executemany で十分なことが多いです。
    total = 0
    for chunk in batched(rows, BATCH_SIZE):
        cur.executemany(sql, chunk)
        total += len(chunk)
    cur.close()
    return total

def connect():
    if USE_DSN:
        return pyodbc.connect(
            f"DSN={DSN_NAME};UID={USER};PWD={PASSWORD};", autocommit=False
        )
    else:
        return pyodbc.connect(CONN_STR, autocommit=False)

def main():
    # 1) CSV読み込み & CSV内重複除去
    csv_rows = read_csv_rows(CSV_PATH)
    csv_rows = dedup_in_csv(csv_rows)

    with connect() as cnxn:
        # 2) 既存キーを1回だけ取得
        existing = fetch_existing_keys(cnxn)
        # 3) 未登録だけ抽出
        to_insert = list(filter_new_rows(csv_rows, existing))
        # 4) まとめてINSERT（トランザクション内）
        inserted = insert_rows(cnxn, to_insert)
        cnxn.commit()

    print(f"CSV行数: {len(csv_rows)}, 新規挿入: {inserted}, 既存スキップ: {len(csv_rows) - inserted}")

if __name__ == "__main__":
    main()