import os
import json
import hashlib
import sqlite3
import shutil
from datetime import datetime
from config import write_dir, get_active_db_path

def validate_db_file(file_path: str) -> tuple[bool, str]:
    """
    Validates if the file at file_path is a valid Award Tracker SQLite database.
    Checks file existence, size, SQLite header, and core tables.
    """
    if not file_path or not os.path.exists(file_path):
        return False, "Database file does not exist."
    
    if os.path.getsize(file_path) == 0:
        return False, "Database file is empty."
    
    try:
        with open(file_path, "rb") as f:
            header = f.read(16)
            if not header.startswith(b"SQLite format 3\x00"):
                return False, "File is not a valid SQLite database."
    except Exception as e:
        return False, f"Could not read file header: {str(e)}"
    
    try:
        conn = sqlite3.connect(file_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = set(row[0] for row in cursor.fetchall())
        
        required_tables = {"account", "provider", "person", "settings"}
        missing = required_tables - tables
        if missing:
            conn.close()
            return False, f"Database is missing required tables: {', '.join(missing)}"

        required_cols = {
            "settings": {"key", "value"},
            "account": {"username", "balance"},
            "person": {"name"},
            "provider": {"name"}
        }

        for tbl, expected_cols in required_cols.items():
            cursor.execute(f"PRAGMA table_info('{tbl}')")
            existing_cols = set(row[1] for row in cursor.fetchall())
            missing_cols = expected_cols - existing_cols
            if missing_cols:
                conn.close()
                return False, f"Table '{tbl}' is missing required columns: {', '.join(missing_cols)}"

        conn.close()
        return True, ""
    except Exception as e:
        return False, f"Database verification failed: {str(e)}"

def get_db_fingerprint(file_path: str) -> dict:
    """
    Calculates file fingerprint (mtime, size, SHA-256 hash).
    """
    if not os.path.exists(file_path):
        return {"mtime": 0, "size": 0, "sha256": ""}
    
    mtime = os.path.getmtime(file_path)
    size = os.path.getsize(file_path)
    
    hasher = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        sha256_hex = hasher.hexdigest()
    except Exception:
        sha256_hex = ""
        
    return {
        "mtime": mtime,
        "size": size,
        "sha256": sha256_hex
    }

def get_meta_path(db_path: str = None) -> str:
    """
    Returns the metadata lock file path adjacent to the database or in write_dir.
    """
    if not db_path:
        db_path = get_active_db_path()
    return db_path + ".meta"

def update_db_meta(db_path: str = None) -> dict:
    """
    Updates the .meta file with current database fingerprint.
    """
    if not db_path:
        db_path = get_active_db_path()
        
    fingerprint = get_db_fingerprint(db_path)
    meta_data = {
        "db_path": db_path,
        "last_updated": datetime.now().isoformat(),
        "fingerprint": fingerprint
    }
    
    meta_path = get_meta_path(db_path)
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta_data, f, indent=2)
    except Exception:
        pass
        
    return meta_data

def check_db_conflict(db_path: str = None) -> dict:
    """
    Checks if the database file on disk has been modified externally since
    the last recorded fingerprint in the .meta file.
    Only active when using a custom database location (e.g. cloud sync folder).
    """
    from config import get_active_db_path, write_dir
    if not db_path:
        db_path = get_active_db_path()

    default_db_path = os.path.abspath(os.path.join(write_dir, 'awardtracker.db'))
    # Conflict checking is only relevant when database is stored in a custom/cloud sync directory
    if os.path.abspath(db_path) == default_db_path:
        return {"has_conflict": False, "reason": "Default local storage in use."}
        
    if not os.path.exists(db_path):
        return {"has_conflict": False, "reason": "Database file does not exist yet."}
        
    meta_path = get_meta_path(db_path)
    current_fp = get_db_fingerprint(db_path)
    
    if not os.path.exists(meta_path):
        # First time checking or no meta file present; initialize it
        update_db_meta(db_path)
        return {"has_conflict": False, "reason": "Initial metadata created."}
        
    try:
        with open(meta_path, "r", encoding="utf-8") as f:
            saved_meta = json.load(f)
            
        saved_fp = saved_meta.get("fingerprint", {})
        
        # Compare SHA-256
        if saved_fp.get("sha256") and current_fp.get("sha256"):
            if saved_fp.get("sha256") != current_fp.get("sha256"):
                saved_mt = saved_fp.get("mtime", 0)
                curr_mt = current_fp.get("mtime", 0)
                return {
                    "has_conflict": True,
                    "saved_mtime": datetime.fromtimestamp(saved_mt).strftime("%Y-%m-%d %H:%M:%S") if saved_mt else "Unknown",
                    "current_mtime": datetime.fromtimestamp(curr_mt).strftime("%Y-%m-%d %H:%M:%S") if curr_mt else "Unknown",
                    "saved_hash": saved_fp.get("sha256"),
                    "current_hash": current_fp.get("sha256")
                }
    except Exception:
        pass
        
    return {"has_conflict": False}

def create_emergency_backup(db_path: str = None, prefix: str = "awardtracker_pre_import") -> str:
    """
    Creates an emergency safety backup in the default %appdata%/AwardTracker/backups directory.
    """
    if not db_path:
        db_path = get_active_db_path()
        
    backup_dir = os.path.join(write_dir, "backups")
    os.makedirs(backup_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"{prefix}_{timestamp}.db"
    backup_path = os.path.join(backup_dir, backup_filename)
    
    if os.path.exists(db_path):
        shutil.copy2(db_path, backup_path)
        
    return backup_path

def smart_merge_databases(source_db_path: str, target_db_path: str) -> dict:
    """
    Smart merges source_db_path into target_db_path.
    Matches accounts by (provider_id, username/account_number) or (provider_id, person_id, display_name).
    Keeps the entry with the newer last_updated date, merges account history and certificates.
    """
    valid_source, msg_src = validate_db_file(source_db_path)
    if not valid_source:
        return {"status": "error", "message": f"Source DB invalid: {msg_src}"}
        
    valid_target, msg_tgt = validate_db_file(target_db_path)
    if not valid_target:
        return {"status": "error", "message": f"Target DB invalid: {msg_tgt}"}
        
    # Backup target before merging
    create_emergency_backup(target_db_path, prefix="awardtracker_pre_merge")
    
    stats = {"people_added": 0, "accounts_updated": 0, "accounts_inserted": 0, "history_added": 0, "certs_added": 0}
    
    conn_src = sqlite3.connect(source_db_path)
    conn_tgt = sqlite3.connect(target_db_path)
    
    conn_src.row_factory = sqlite3.Row
    conn_tgt.row_factory = sqlite3.Row
    
    cur_src = conn_src.cursor()
    cur_tgt = conn_tgt.cursor()
    
    try:
        # Helper to insert row into target table dynamically
        def insert_row_dynamic(table_name, row, person_id_override=None, acc_id_override=None):
            keys = [k for k in row.keys() if k != 'id']
            vals = []
            for k in keys:
                if k == 'person_id' and person_id_override is not None:
                    vals.append(person_id_override)
                elif k == 'account_id' and acc_id_override is not None:
                    vals.append(acc_id_override)
                else:
                    vals.append(row[k])
            cols_str = ", ".join(keys)
            placeholders = ", ".join(["?"] * len(keys))
            sql = f"INSERT INTO {table_name} ({cols_str}) VALUES ({placeholders})"
            cur_tgt.execute(sql, vals)
            return cur_tgt.lastrowid

        # 1. Merge Persons
        cur_src.execute("SELECT * FROM person")
        for p in cur_src.fetchall():
            cur_tgt.execute("SELECT id FROM person WHERE name = ?", (p["name"],))
            row = cur_tgt.fetchone()
            if not row:
                insert_row_dynamic("person", p)
                stats["people_added"] += 1
        conn_tgt.commit()
        
        # Build map of person name -> target person_id
        cur_tgt.execute("SELECT id, name FROM person")
        tgt_person_map = {row["name"]: row["id"] for row in cur_tgt.fetchall()}
        
        cur_src.execute("SELECT id, name FROM person")
        src_person_name_by_id = {row["id"]: row["name"] for row in cur_src.fetchall()}
        
        # 2. Merge Accounts
        cur_src.execute("SELECT * FROM account")
        src_accounts = cur_src.fetchall()
        
        for sa in src_accounts:
            src_p_name = src_person_name_by_id.get(sa["person_id"]) if "person_id" in sa.keys() else None
            tgt_person_id = tgt_person_map.get(src_p_name, sa["person_id"]) if src_p_name and "person_id" in sa.keys() else sa.get("person_id")
            
            sa_user = sa["username"] if "username" in sa.keys() else ""
            
            # Find matching account in target
            cur_tgt.execute(
                "SELECT * FROM account WHERE provider_id = ? AND username = ?",
                (sa["provider_id"], sa_user)
            )
            ta = cur_tgt.fetchone()
            
            target_acc_id = None
            if ta:
                target_acc_id = ta["id"]
                # Compare last_updated
                sa_updated = str(sa["last_updated"] or "") if "last_updated" in sa.keys() else ""
                ta_updated = str(ta["last_updated"] or "") if "last_updated" in ta.keys() else ""
                
                if sa_updated > ta_updated:
                    update_cols = [k for k in sa.keys() if k not in ("id", "person_id", "provider_id", "username")]
                    set_str = ", ".join([f"{k} = ?" for k in update_cols])
                    vals = [sa[k] for k in update_cols] + [target_acc_id]
                    cur_tgt.execute(f"UPDATE account SET {set_str} WHERE id = ?", vals)
                    stats["accounts_updated"] += 1
            else:
                target_acc_id = insert_row_dynamic("account", sa, person_id_override=tgt_person_id)
                stats["accounts_inserted"] += 1
                
            conn_tgt.commit()
            
            # 3. Merge Account History
            if target_acc_id:
                cur_src.execute("SELECT * FROM account_history WHERE account_id = ?", (sa["id"],))
                for sh in cur_src.fetchall():
                    cur_tgt.execute(
                        "SELECT id FROM account_history WHERE account_id = ? AND recorded_at = ?",
                        (target_acc_id, sh["recorded_at"])
                    )
                    if not cur_tgt.fetchone():
                        insert_row_dynamic("account_history", sh, acc_id_override=target_acc_id)
                        stats["history_added"] += 1
                conn_tgt.commit()
                
            # 4. Merge Certificates
            if target_acc_id:
                cur_src.execute("SELECT * FROM certificate WHERE account_id = ?", (sa["id"],))
                for sc in cur_src.fetchall():
                    cert_code = sc["certificate_code"] if "certificate_code" in sc.keys() and sc["certificate_code"] is not None else ""
                    cert_exp = str(sc["expiration_date"]) if "expiration_date" in sc.keys() and sc["expiration_date"] is not None else ""
                    cur_tgt.execute(
                        "SELECT id FROM certificate WHERE account_id = ? AND name = ? AND (certificate_code = ? OR expiration_date = ?)",
                        (target_acc_id, sc["name"], cert_code, cert_exp)
                    )
                    if not cur_tgt.fetchone():
                        insert_row_dynamic("certificate", sc, acc_id_override=target_acc_id)
                        stats["certs_added"] += 1
                conn_tgt.commit()
                
        update_db_meta(target_db_path)
        return {"status": "success", "stats": stats}
    except Exception as e:
        conn_tgt.rollback()
        return {"status": "error", "message": f"Smart merge failed: {str(e)}"}
    finally:
        conn_src.close()
        conn_tgt.close()

def open_native_folder_picker() -> str:
    """
    Opens native OS folder selection dialog using tkinter.
    Returns selected directory path, or empty string if cancelled.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        selected_path = filedialog.askdirectory(title="Select Award Tracker Database Folder")
        root.destroy()
        return selected_path or ""
    except Exception as e:
        print(f"Error opening native folder picker: {e}")
        return ""

