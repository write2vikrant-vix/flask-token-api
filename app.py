import sqlite3
import math
from datetime import datetime
from flask import Flask, jsonify, request, g, render_template_string

app = Flask(__name__)
DATABASE = "tokens.db"

MAX_TRANSFER = 25.0
MIN_BALANCE  = 10.0

# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(error):
    db = g.pop("db", None)
    if db is not None:
        db.close()

def init_db():
    db = sqlite3.connect(DATABASE)
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            name    TEXT PRIMARY KEY,
            balance REAL NOT NULL DEFAULT 100.0
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS transfers (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            from_user  TEXT NOT NULL,
            to_user    TEXT NOT NULL,
            amount     REAL NOT NULL,
            timestamp  TEXT NOT NULL
        )
    """)
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO users (name, balance) VALUES (?, 100.0)",
            [("vix",), ("pc",), ("tino",)]
        )
    db.commit()
    db.close()

init_db()

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def lookup_user(db, name):
    return db.execute(
        "SELECT name, balance FROM users WHERE name = ?", (name.lower(),)
    ).fetchone()

def round2(val):
    """Round to 2 decimal places."""
    return round(val, 2)

# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.route("/users")
def list_users():
    db = get_db()
    rows = db.execute("SELECT name, balance FROM users ORDER BY name").fetchall()
    return jsonify([{"user": r["name"], "balance": round2(r["balance"])} for r in rows]), 200

@app.route("/balance/<user>")
def balance(user):
    db = get_db()
    row = lookup_user(db, user)
    if row is None:
        return jsonify({"error": f"User '{user}' not found"}), 404
    return jsonify({"user": row["name"], "balance": round2(row["balance"])}), 200

@app.route("/history")
def history():
    db = get_db()
    rows = db.execute(
        "SELECT * FROM transfers ORDER BY id DESC LIMIT 50"
    ).fetchall()
    return jsonify([{
        "id": r["id"],
        "from": r["from_user"],
        "to": r["to_user"],
        "amount": round2(r["amount"]),
        "timestamp": r["timestamp"]
    } for r in rows]), 200

@app.route("/transfer")
def transfer():
    db = get_db()
    from_name = request.args.get("from")
    to_name   = request.args.get("to")

    # Validate users
    from_row = lookup_user(db, from_name) if from_name else None
    if from_row is None:
        return jsonify({"error": f"User '{from_name or ''}' not found"}), 404

    to_row = lookup_user(db, to_name) if to_name else None
    if to_row is None:
        return jsonify({"error": f"User '{to_name or ''}' not found"}), 404

    if from_row["name"] == to_row["name"]:
        return jsonify({"error": "Cannot transfer tokens to yourself"}), 400

    # Validate amount
    amount_str = request.args.get("amount")
    if amount_str is None:
        return jsonify({"error": "Missing required parameter: amount"}), 400

    try:
        amount = round2(float(amount_str))
        if amount <= 0:
            raise ValueError
        # Max 2 decimal places check
        if amount != round(float(amount_str), 2):
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "amount must be a positive number with up to 2 decimal places"}), 400

    # Rule 1: max 25 tokens per transfer
    if amount > MAX_TRANSFER:
        return jsonify({"error": f"Cannot transfer more than {MAX_TRANSFER} tokens in one transaction"}), 400

    # Rule 2: sender must keep at least 10 tokens
    if round2(from_row["balance"] - amount) < MIN_BALANCE:
        return jsonify({
            "error": f"{from_row['name']} must keep at least {MIN_BALANCE} tokens. "
                     f"Current balance: {round2(from_row['balance'])}, max transferable: {round2(from_row['balance'] - MIN_BALANCE)}"
        }), 400

    # Perform transfer
    db.execute("UPDATE users SET balance = ROUND(balance - ?, 2) WHERE name = ?", (amount, from_row["name"]))
    db.execute("UPDATE users SET balance = ROUND(balance + ?, 2) WHERE name = ?", (amount, to_row["name"]))

    # Record the transfer
    db.execute(
        "INSERT INTO transfers (from_user, to_user, amount, timestamp) VALUES (?, ?, ?, ?)",
        (from_row["name"], to_row["name"], amount, datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"))
    )
    db.commit()

    from_updated = lookup_user(db, from_row["name"])
    to_updated   = lookup_user(db, to_row["name"])

    return jsonify({
        "from":    {"user": from_updated["name"], "balance": round2(from_updated["balance"])},
        "to":      {"user": to_updated["name"],   "balance": round2(to_updated["balance"])},
        "amount":  amount,
        "message": "Transfer successful"
    }), 200

# ---------------------------------------------------------------------------
# Web UI
# ---------------------------------------------------------------------------

WEB_UI = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Token Exchange</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: system-ui, sans-serif; background: #f0f2f5; color: #1a1a2e; }
    header { background: #4f46e5; color: white; padding: 16px 24px; }
    header h1 { font-size: 1.4rem; }
    .container { max-width: 800px; margin: 24px auto; padding: 0 16px; }
    .card { background: white; border-radius: 12px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
    h2 { font-size: 1rem; font-weight: 600; margin-bottom: 14px; color: #4f46e5; }
    .balances { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
    .balance-item { background: #f5f3ff; border-radius: 8px; padding: 14px; text-align: center; }
    .balance-item .name { font-weight: 700; font-size: 1.1rem; text-transform: uppercase; }
    .balance-item .tokens { font-size: 1.5rem; font-weight: 800; color: #4f46e5; margin-top: 4px; }
    .balance-item .label { font-size: 0.75rem; color: #888; }
    .rules { background: #fef9c3; border: 1px solid #fde047; border-radius: 8px; padding: 12px 16px; margin-bottom: 20px; font-size: 0.85rem; }
    .rules ul { padding-left: 18px; margin-top: 6px; }
    .rules li { margin-bottom: 4px; }
    .form-row { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
    .form-group { flex: 1; min-width: 140px; }
    label { display: block; font-size: 0.8rem; font-weight: 600; margin-bottom: 4px; color: #555; }
    select, input { width: 100%; padding: 10px 12px; border: 1px solid #ddd; border-radius: 8px; font-size: 0.95rem; }
    button { background: #4f46e5; color: white; border: none; padding: 12px 24px; border-radius: 8px; font-size: 0.95rem; font-weight: 600; cursor: pointer; width: 100%; }
    button:hover { background: #4338ca; }
    .msg { margin-top: 12px; padding: 10px 14px; border-radius: 8px; font-size: 0.9rem; display: none; }
    .msg.success { background: #dcfce7; color: #166534; border: 1px solid #86efac; }
    .msg.error   { background: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; }
    table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
    th { text-align: left; padding: 8px 10px; background: #f5f3ff; color: #4f46e5; font-weight: 600; }
    td { padding: 8px 10px; border-bottom: 1px solid #f0f0f0; }
    tr:last-child td { border-bottom: none; }
    .badge { display: inline-block; padding: 2px 8px; border-radius: 99px; font-size: 0.75rem; font-weight: 700; background: #e0e7ff; color: #4f46e5; }
    .refresh-btn { background: none; border: 1px solid #4f46e5; color: #4f46e5; padding: 6px 14px; border-radius: 6px; font-size: 0.8rem; cursor: pointer; width: auto; margin-bottom: 12px; }
  </style>
</head>
<body>
<header><h1>Token Exchange</h1></header>
<div class="container">

  <div class="rules">
    <strong>Rules:</strong>
    <ul>
      <li>Max <strong>25 tokens</strong> per transfer</li>
      <li>Each user must keep at least <strong>10 tokens</strong></li>
      <li>Decimals allowed up to <strong>2 decimal places</strong> (e.g. 10.50)</li>
      <li>All transfers are recorded in history</li>
    </ul>
  </div>

  <div class="card">
    <h2>Balances</h2>
    <div class="balances" id="balances">Loading...</div>
  </div>

  <div class="card">
    <h2>Transfer Tokens</h2>
    <div class="form-row">
      <div class="form-group">
        <label>From</label>
        <select id="from"></select>
      </div>
      <div class="form-group">
        <label>To</label>
        <select id="to"></select>
      </div>
      <div class="form-group">
        <label>Amount (max 25)</label>
        <input type="number" id="amount" placeholder="e.g. 10.50" step="0.01" min="0.01" max="25">
      </div>
    </div>
    <button onclick="doTransfer()">Send Tokens</button>
    <div class="msg" id="msg"></div>
  </div>

  <div class="card">
    <h2>Transfer History</h2>
    <button class="refresh-btn" onclick="loadHistory()">Refresh</button>
    <table>
      <thead><tr><th>#</th><th>From</th><th>To</th><th>Amount</th><th>Time</th></tr></thead>
      <tbody id="history-body"><tr><td colspan="5">Loading...</td></tr></tbody>
    </table>
  </div>

</div>
<script>
  const BASE = '';

  async function loadBalances() {
    const res = await fetch(BASE + '/users');
    const users = await res.json();
    const el = document.getElementById('balances');
    el.innerHTML = users.map(u => `
      <div class="balance-item">
        <div class="name">${u.user}</div>
        <div class="tokens">${u.balance}</div>
        <div class="label">tokens</div>
      </div>
    `).join('');
    // populate dropdowns
    ['from','to'].forEach(id => {
      const sel = document.getElementById(id);
      const cur = sel.value;
      sel.innerHTML = users.map(u => `<option value="${u.user}">${u.user.toUpperCase()}</option>`).join('');
      if (cur) sel.value = cur;
    });
  }

  async function loadHistory() {
    const res = await fetch(BASE + '/history');
    const rows = await res.json();
    const tbody = document.getElementById('history-body');
    if (rows.length === 0) {
      tbody.innerHTML = '<tr><td colspan="5" style="color:#888">No transfers yet</td></tr>';
      return;
    }
    tbody.innerHTML = rows.map(r => `
      <tr>
        <td>${r.id}</td>
        <td><span class="badge">${r.from}</span></td>
        <td><span class="badge">${r.to}</span></td>
        <td><strong>${r.amount}</strong></td>
        <td style="color:#888;font-size:0.8rem">${r.timestamp}</td>
      </tr>
    `).join('');
  }

  async function doTransfer() {
    const from   = document.getElementById('from').value;
    const to     = document.getElementById('to').value;
    const amount = document.getElementById('amount').value;
    const msg    = document.getElementById('msg');

    msg.style.display = 'none';
    const res = await fetch(`${BASE}/transfer?from=${from}&to=${to}&amount=${amount}`);
    const data = await res.json();

    if (res.ok) {
      msg.className = 'msg success';
      msg.textContent = `Transferred ${amount} tokens from ${from.toUpperCase()} to ${to.toUpperCase()}. New balances: ${from.toUpperCase()} = ${data.from.balance}, ${to.toUpperCase()} = ${data.to.balance}`;
      document.getElementById('amount').value = '';
      await loadBalances();
      await loadHistory();
    } else {
      msg.className = 'msg error';
      msg.textContent = data.error || 'Transfer failed';
    }
    msg.style.display = 'block';
  }

  // Initial load
  loadBalances();
  loadHistory();
</script>
</body>
</html>
"""

@app.route("/")
def web_ui():
    return render_template_string(WEB_UI)

if __name__ == "__main__":
    app.run(debug=True)
