#!/usr/bin/env python3
import os
import sys
import sqlite3
import argparse
import readline
import json
import csv
import time
from datetime import datetime

# Define standard known database profiles
DB_PROFILES = {
    "scout": {
        "path": "/Users/home/Developer/apply/JobData/scout.db",
        "desc": "JobScout main database (jobs, watchlist, applied_jobs)"
    },
    "ops": {
        "path": "/Users/home/Developer/apply/JobData/ops.db",
        "desc": "JobScout ops and execution database"
    },
    "scout-dev": {
        "path": "/Users/home/Developer/apply/JobData/scout-dev.db",
        "desc": "JobScout development / staging database"
    },
    "finance": {
        "path": "/Users/home/Developer/finance/backend/finance.db",
        "desc": "Plaid transactions, categories, budgets, and accounts"
    },
    "research": {
        "path": "/Users/home/Developer/trading/data/research.db",
        "desc": "Trading strategy research and timeseries database"
    },
    "ledger": {
        "path": "/Users/home/Developer/trading/data/ledger.db",
        "desc": "Trading account balance ledger and transactions"
    },
    "clipper": {
        "path": "/Users/home/Developer/clipper/data/clipper.db",
        "desc": "Clipper project clipboard/history tracking"
    },
    "ratatui": {
        "path": "/Users/home/Developer/ratatui-showcase/ratatui.db",
        "desc": "Ratatui showcase dashboard database"
    },
    "music": {
        "path": "/Users/home/Developer/music/catalog.sqlite",
        "desc": "Music catalog and playlist tracks tracking"
    }
}

# ANSI Escape Sequences for Premium Terse Aesthetics
CLR_CYAN = "\033[36m"
CLR_MAGENTA = "\033[35m"
CLR_YELLOW = "\033[33m"
CLR_GREEN = "\033[32m"
CLR_RED = "\033[31m"
CLR_GRAY = "\033[90m"
CLR_BOLD = "\033[1m"
CLR_RESET = "\033[0m"

# Global application state
class AgentState:
    def __init__(self):
        self.active_db_name = None
        self.active_db_path = None
        self.last_results_headers = []
        self.last_results_rows = []
        self.history_file = os.path.expanduser("~/.sqlite_agent_history")

state = AgentState()

def resolve_db_path(name_or_path):
    """Resolves a shorthand profile name or a literal path."""
    if name_or_path in DB_PROFILES:
        return DB_PROFILES[name_or_path]["path"], name_or_path
    
    # Try case-insensitive lookup
    for key, profile in DB_PROFILES.items():
        if key.lower() == name_or_path.lower():
            return profile["path"], key
            
    # Treat as raw absolute or relative path
    abs_path = os.path.abspath(os.path.expanduser(name_or_path))
    return abs_path, os.path.basename(abs_path)

def discover_databases():
    """Scans and reports which of the known databases exist on disk."""
    print(f"{CLR_BOLD}{CLR_CYAN}=== SQLite Agent — Global Autodiscovery ==={CLR_RESET}")
    found_any = False
    for name, profile in DB_PROFILES.items():
        path = profile["path"]
        exists = os.path.exists(path)
        status_str = f"{CLR_GREEN}[active]{CLR_RESET}" if exists else f"{CLR_GRAY}[absent]{CLR_RESET}"
        size_str = ""
        if exists:
            found_any = True
            try:
                size_mb = os.path.getsize(path) / (1024 * 1024)
                size_str = f" ({size_mb:.2f} MB)"
            except Exception:
                pass
        print(f"  * {CLR_BOLD}{name:<10}{CLR_RESET} : {status_str}{size_str} {CLR_GRAY}- {profile['desc']}{CLR_RESET}")
    print()
    return found_any

def get_db_connection(path):
    """Opens a connection with WAL-friendly isolation level (None) to prevent locks."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Database file not found: {path}")
    # isolation_level=None enables autocommit mode, letting transactions be managed explicitly
    conn = sqlite3.connect(path, isolation_level=None)
    conn.row_factory = sqlite3.Row
    return conn

def format_grid(headers, rows, max_col_width=45):
    """Formats headers and rows into a premium, auto-sizing terminal grid with truncation."""
    if not headers:
        return "No columns returned."
        
    # Calculate initial column widths based on headers
    widths = [len(str(h)) for h in headers]
    
    # Analyze row data to adjust column widths
    str_rows = []
    for row in rows:
        str_row = []
        for val in row:
            if val is None:
                s = "NULL"
            elif isinstance(val, (bytes, bytearray)):
                s = f"<blob: {len(val)}B>"
            else:
                s = str(val).replace("\n", " ")  # Flatten multi-line text for grid
            str_row.append(s)
        str_rows.append(str_row)
        
        for i, s in enumerate(str_row):
            if i < len(widths):
                widths[i] = max(widths[i], len(s))
                
    # Restrict column widths to max_col_width and account for truncation
    for i in range(len(widths)):
        if widths[i] > max_col_width:
            widths[i] = max_col_width

    # Build the horizontal divider
    div_parts = ["-" * (w + 2) for w in widths]
    divider = f"+{'+'.join(div_parts)}+"
    
    # Build the header line
    hdr_parts = []
    for h, w in zip(headers, widths):
        # Truncate header if it exceeds max width
        s_h = str(h)
        if len(s_h) > w:
            s_h = s_h[:w-2] + ".."
        hdr_parts.append(f" {CLR_BOLD}{CLR_CYAN}{s_h:<{w}}{CLR_RESET} ")
    header_line = f"|{'|'.join(hdr_parts)}|"
    
    # Assemble the final grid lines
    output_lines = [divider, header_line, divider]
    
    for str_row in str_rows:
        row_parts = []
        for s, w in zip(str_row, widths):
            # Format NULLs in distinct gray color
            if s == "NULL":
                display_s = f"{CLR_GRAY}NULL{CLR_RESET}"
                padding_len = w - 4
                row_parts.append(f" {display_s}{' ' * padding_len} ")
            else:
                if len(s) > w:
                    s = s[:w-3] + "..."
                row_parts.append(f" {s:<{w}} ")
        output_lines.append(f"|{'|'.join(row_parts)}|")
        
    output_lines.append(divider)
    return "\n".join(output_lines)

def execute_sql(db_path, sql_query, params=()):
    """Executes a query, measures timing, and updates global state."""
    start_time = time.perf_counter()
    conn = None
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        cursor.execute(sql_query, params)
        
        # Check if query returns rows (SELECT, PRAGMA)
        if cursor.description:
            headers = [col[0] for col in cursor.description]
            rows_raw = cursor.fetchall()
            # Convert sqlite3.Row to standard lists/tuples
            rows = [list(r) for r in rows_raw]
            
            # Store in global state for exports
            state.last_results_headers = headers
            state.last_results_rows = rows
            
            elapsed = time.perf_counter() - start_time
            print(format_grid(headers, rows))
            print(f"{CLR_GRAY}({len(rows)} rows returned in {elapsed*1000:.2f}ms){CLR_RESET}\n")
        else:
            # Query did not return rows (INSERT, UPDATE, DELETE, CREATE, etc.)
            changes = conn.total_changes
            elapsed = time.perf_counter() - start_time
            print(f"{CLR_GREEN}Success.{CLR_RESET} Database updated. Changes: {CLR_BOLD}{changes}{CLR_RESET}")
            print(f"{CLR_GRAY}(Execution completed in {elapsed*1000:.2f}ms){CLR_RESET}\n")
            
            state.last_results_headers = []
            state.last_results_rows = []
            
    except Exception as e:
        print(f"{CLR_RED}Database Error: {e}{CLR_RESET}\n")
    finally:
        if conn:
            conn.close()

def inspect_schema(db_path, table_name=None):
    """Prints the schema information of a specific table or lists all tables."""
    conn = None
    try:
        conn = get_db_connection(db_path)
        cursor = conn.cursor()
        
        if table_name:
            # Describe columns
            cursor.execute(f"PRAGMA table_info({table_name});")
            cols = cursor.fetchall()
            if not cols:
                print(f"{CLR_RED}Table '{table_name}' not found or has no columns.{CLR_RESET}\n")
                return
                
            headers = ["cid", "name", "type", "notnull", "dflt_value", "pk"]
            rows = [[c["cid"], c["name"], c["type"], c["notnull"], c["dflt_value"], c["pk"]] for c in cols]
            
            print(f"{CLR_BOLD}{CLR_CYAN}Table Schema: {table_name}{CLR_RESET}")
            print(format_grid(headers, rows))
            
            # Check for indexes
            cursor.execute(f"PRAGMA index_list({table_name});")
            indexes = cursor.fetchall()
            if indexes:
                idx_headers = ["seq", "name", "unique", "origin", "partial"]
                idx_rows = [[i["seq"], i["name"], i["unique"], i["origin"], i["partial"]] for i in indexes]
                print(f"\n{CLR_BOLD}{CLR_CYAN}Active Indexes:{CLR_RESET}")
                print(format_grid(idx_headers, idx_rows))
            print()
        else:
            # List all tables with row counts
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
            tables = [r["name"] for r in cursor.fetchall()]
            if not tables:
                print(f"{CLR_YELLOW}No user tables found in this database.{CLR_RESET}\n")
                return
                
            headers = ["table_name", "row_count"]
            rows = []
            for t in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {t};")
                    count = cursor.fetchone()[0]
                except Exception:
                    count = "ERROR"
                rows.append([t, count])
                
            print(f"{CLR_BOLD}{CLR_CYAN}Database Tables Overview:{CLR_RESET}")
            print(format_grid(headers, rows))
            print()
            
    except Exception as e:
        print(f"{CLR_RED}Schema Inspection Error: {e}{CLR_RESET}\n")
    finally:
        if conn:
            conn.close()

def export_last_results(format_type, output_path):
    """Exports the last SELECT query results to JSON, CSV, or Markdown."""
    if not state.last_results_headers:
        print(f"{CLR_RED}Export Error: No recent query results in memory to export.{CLR_RESET}\n")
        return
        
    try:
        format_type = format_type.lower()
        if format_type == "json":
            # Map headers to rows
            data = []
            for row in state.last_results_rows:
                data.append(dict(zip(state.last_results_headers, row)))
            with open(output_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
                
        elif format_type == "csv":
            with open(output_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(state.last_results_headers)
                writer.writerows(state.last_results_rows)
                
        elif format_type == "markdown":
            # Formats standard markdown table
            lines = []
            lines.append("| " + " | ".join(state.last_results_headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(state.last_results_headers)) + " |")
            for row in state.last_results_rows:
                str_vals = [str(v) if v is not None else "NULL" for v in row]
                lines.append("| " + " | ".join(str_vals) + " |")
            with open(output_path, "w") as f:
                f.write("\n".join(lines) + "\n")
                
        else:
            print(f"{CLR_RED}Export Error: Unsupported format '{format_type}'. Use JSON, CSV, or markdown.{CLR_RESET}\n")
            return
            
        print(f"{CLR_GREEN}Exported successfully to: {CLR_BOLD}{output_path}{CLR_RESET}\n")
    except Exception as e:
        print(f"{CLR_RED}Export Error: Failed to write output file: {e}{CLR_RESET}\n")

# Interactive Autocomplete and REPL Helper
class SQLiteCompleter:
    def __init__(self, db_path):
        self.db_path = db_path
        self.tables = []
        self.columns = {}
        self.keywords = [
            "SELECT", "FROM", "WHERE", "JOIN", "ON", "GROUP BY", "ORDER BY",
            "LIMIT", "INSERT", "UPDATE", "DELETE", "PRAGMA", "schema", "tables",
            "export", "db", "exit", "quit", "help", "DESC", "ASC", "COUNT"
        ]
        self.load_schema_metadata()
        
    def load_schema_metadata(self):
        if not self.db_path or not os.path.exists(self.db_path):
            return
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            self.tables = [r[0] for r in cursor.fetchall()]
            for t in self.tables:
                cursor.execute(f"PRAGMA table_info({t});")
                self.columns[t] = [r[1] for r in cursor.fetchall()]
        except Exception:
            pass
        finally:
            if conn:
                conn.close()

    def complete(self, text, state_idx):
        buffer = readline.get_line_buffer()
        tokens = buffer.split()
        
        # Determine suggestions
        candidates = []
        if not tokens or buffer.endswith(" "):
            # Ssuggest keywords or tables depending on context
            if tokens and tokens[-1].upper() == "FROM":
                candidates = self.tables
            elif tokens and tokens[-1].upper() == "SELECT":
                candidates = self.keywords
            else:
                candidates = self.keywords + list(DB_PROFILES.keys())
        else:
            word = tokens[-1]
            if tokens[-1].startswith("."):
                # Handle commands
                candidates = [".help", ".tables", ".schema", ".exit", ".db"]
            elif len(tokens) > 1 and tokens[-2].upper() == "FROM":
                candidates = [t for t in self.tables if t.lower().startswith(word.lower())]
            else:
                # Fuzzy keyword or profile match
                candidates = [k for k in self.keywords if k.lower().startswith(word.lower())]
                candidates += [t for t in self.tables if t.lower().startswith(word.lower())]
                candidates += [p for p in DB_PROFILES.keys() if p.lower().startswith(word.lower())]
                
        try:
            return candidates[state_idx]
        except IndexError:
            return None

def start_repl(initial_db_name=None):
    """Launches the interactive SQLite agent console."""
    print(f"{CLR_BOLD}{CLR_CYAN}SQLite Agent CLI Core v1.0.0{CLR_RESET}")
    print(f"{CLR_GRAY}History file loaded from ~/.sqlite_agent_history{CLR_RESET}\n")
    
    # Load history
    if os.path.exists(state.history_file):
        try:
            readline.read_history_file(state.history_file)
        except Exception:
            pass
            
    # Set up initial database
    active_name = initial_db_name or "scout"
    path, resolved_name = resolve_db_path(active_name)
    if os.path.exists(path):
        state.active_db_name = resolved_name
        state.active_db_path = path
    else:
        # Fallback to the first existing database
        for name, profile in DB_PROFILES.items():
            if os.path.exists(profile["path"]):
                state.active_db_name = name
                state.active_db_path = profile["path"]
                break
                
    if not state.active_db_path:
        print(f"{CLR_RED}No default database is available or found on disk.{CLR_RESET}")
        print("Please choose one manually or specify a file path on startup.\n")
    else:
        print(f"Connected to profile: {CLR_BOLD}{CLR_GREEN}{state.active_db_name}{CLR_RESET}")
        print(f"File: {CLR_GRAY}{state.active_db_path}{CLR_RESET}\n")
        
    # Configure autocompleter
    completer = SQLiteCompleter(state.active_db_path)
    readline.set_completer(completer.complete)
    readline.parse_and_bind("tab: complete")
    
    # REPL loop
    while True:
        try:
            db_label = f"[{CLR_GREEN}{state.active_db_name}{CLR_RESET}]" if state.active_db_name else f"[{CLR_RED}none{CLR_RESET}]"
            prompt = f"{CLR_BOLD}sqlite-agent{CLR_RESET} {db_label} > "
            line = input(prompt).strip()
            
            if not line:
                continue
                
            # Internal REPL commands
            if line.startswith(".") or line.lower() in ["exit", "quit"]:
                cmd_parts = line.lstrip(".").split()
                primary_cmd = cmd_parts[0].lower() if cmd_parts else ""
                
                if primary_cmd in ["exit", "quit"]:
                    break
                elif primary_cmd == "help":
                    show_help_menu()
                elif primary_cmd == "tables":
                    if state.active_db_path:
                        inspect_schema(state.active_db_path)
                    else:
                        print(f"{CLR_RED}Error: No active database selected.{CLR_RESET}\n")
                elif primary_cmd == "schema":
                    if len(cmd_parts) < 2:
                        inspect_schema(state.active_db_path)
                    else:
                        inspect_schema(state.active_db_path, cmd_parts[1])
                elif primary_cmd == "db":
                    if len(cmd_parts) < 2:
                        print(f"Active database profile: {CLR_BOLD}{CLR_GREEN}{state.active_db_name}{CLR_RESET}\n")
                    else:
                        target = cmd_parts[1]
                        try:
                            t_path, t_name = resolve_db_path(target)
                            if os.path.exists(t_path):
                                state.active_db_name = t_name
                                state.active_db_path = t_path
                                completer = SQLiteCompleter(state.active_db_path)
                                readline.set_completer(completer.complete)
                                print(f"Switched to database: {CLR_BOLD}{CLR_GREEN}{state.active_db_name}{CLR_RESET}\n")
                            else:
                                print(f"{CLR_RED}Error: Database file does not exist: {t_path}{CLR_RESET}\n")
                        except Exception as e:
                            print(f"{CLR_RED}Error resolving database: {e}{CLR_RESET}\n")
                elif primary_cmd == "export":
                    if len(cmd_parts) < 3:
                        print(f"{CLR_RED}Usage: .export <format> <filename>  (e.g., .export json output.json){CLR_RESET}\n")
                    else:
                        export_last_results(cmd_parts[1], cmd_parts[2])
                else:
                    print(f"{CLR_RED}Unknown REPL command '.{primary_cmd}'. Type .help for guidance.{CLR_RESET}\n")
                    
            elif line.lower() == "help":
                show_help_menu()
            elif line.lower() == "tables":
                inspect_schema(state.active_db_path)
            elif line.lower().startswith("schema"):
                parts = line.split()
                if len(parts) < 2:
                    inspect_schema(state.active_db_path)
                else:
                    inspect_schema(state.active_db_path, parts[1])
            elif line.lower().startswith("db "):
                parts = line.split()
                if len(parts) >= 2:
                    target = parts[1]
                    try:
                        t_path, t_name = resolve_db_path(target)
                        if os.path.exists(t_path):
                            state.active_db_name = t_name
                            state.active_db_path = t_path
                            completer = SQLiteCompleter(state.active_db_path)
                            readline.set_completer(completer.complete)
                            print(f"Switched to database: {CLR_BOLD}{CLR_GREEN}{state.active_db_name}{CLR_RESET}\n")
                        else:
                            print(f"{CLR_RED}Error: Database file does not exist: {t_path}{CLR_RESET}\n")
                    except Exception as e:
                        print(f"{CLR_RED}Error resolving database: {e}{CLR_RESET}\n")
            elif line.lower().startswith("export "):
                parts = line.split()
                if len(parts) < 3:
                    print(f"{CLR_RED}Usage: export <format> <filename>  (e.g., export json output.json){CLR_RESET}\n")
                else:
                    export_last_results(parts[1], parts[2])
            else:
                # Raw SQL execution
                if state.active_db_path:
                    # Automatically append terminating semicolon if missing
                    sql = line if line.endswith(";") else line + ";"
                    execute_sql(state.active_db_path, sql)
                else:
                    print(f"{CLR_RED}Error: No active database selected. Choose one with 'db <name>'.{CLR_RESET}\n")
                    
        except KeyboardInterrupt:
            # Clear input line on Ctrl-C
            print("\n(Use Ctrl-D or 'exit' to terminate)")
            continue
        except EOFError:
            # Handle Ctrl-D
            print("\nExiting interactive session.")
            break
            
    # Save history before exit
    try:
        readline.write_history_file(state.history_file)
    except Exception:
        pass

def show_help_menu():
    """Prints a beautiful summary of REPL actions."""
    print(f"\n{CLR_BOLD}{CLR_CYAN}=== SQLite Agent — Command Guidance ==={CLR_RESET}")
    print(f"  {CLR_BOLD}db <name>{CLR_RESET}         : Switch active database (e.g. 'db finance', 'db scout')")
    print(f"  {CLR_BOLD}tables{CLR_RESET}            : List tables and row counts inside the active database")
    print(f"  {CLR_BOLD}schema <table>{CLR_RESET}    : Describe schema and primary keys of a specific table")
    print(f"  {CLR_BOLD}export <fmt> <file>{CLR_RESET}: Export results of last query (formats: json, csv, markdown)")
    print(f"  {CLR_BOLD}<sql_query>{CLR_RESET}       : Run arbitrary SQL directly (e.g. 'SELECT * FROM jobs LIMIT 3;')")
    print(f"  {CLR_BOLD}exit / quit{CLR_RESET}       : Exit the interactive REPL")
    print(f"  {CLR_BOLD}help{CLR_RESET}              : Print this help catalog")
    print()

def main():
    parser = argparse.ArgumentParser(description="SQLite Agent: premium multi-database query engine.")
    parser.add_argument("database", nargs="?", help="Database shorthand profile (scout, finance, research, ledger, etc.) or absolute file path.")
    parser.add_argument("-q", "--query", help="Direct SQL query to execute. Skips REPL mode, prints output, and exits.")
    parser.add_argument("-s", "--schema", action="store_true", help="Inspect schemas of the specified database instead of querying.")
    parser.add_argument("-t", "--table", help="Inspect a specific table's schema columns (requires --schema).")
    parser.add_argument("-d", "--discover", action="store_true", help="Perform global autodiscovery scan of all 9+ project databases.")
    
    args = parser.parse_args()
    
    if args.discover:
        discover_databases()
        sys.exit(0)
        
    if args.query:
        if not args.database:
            print(CLR_RED + "Error: A database name/path is required to run direct queries." + CLR_RESET)
            sys.exit(1)
        path, _ = resolve_db_path(args.database)
        try:
            execute_sql(path, args.query)
        except Exception as e:
            print(f"{CLR_RED}Execution Failed: {e}{CLR_RESET}")
            sys.exit(1)
        sys.exit(0)
        
    if args.schema:
        if not args.database:
            print(CLR_RED + "Error: A database name/path is required to inspect schemas." + CLR_RESET)
            sys.exit(1)
        path, _ = resolve_db_path(args.database)
        inspect_schema(path, args.table)
        sys.exit(0)
        
    # Start interactive REPL
    discover_databases()
    start_repl(args.database)

if __name__ == "__main__":
    main()
