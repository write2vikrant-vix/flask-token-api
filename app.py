import sqlite3
import os
from flask import Flask, jsonify, request, g

app = Flask(__name__)

DATABASE = "tokens.db"


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    """Open a database connection for the current request context."""
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(error):
    """Close the database connection at the end of each request."""
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    """Create the users table and seed it if it does not exist yet."""
    db = sqlite3.connect(DATABASE)
    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            name    TEXT PRIMARY KEY,
            balance INTEGER NOT NULL DEFAULT 100
        )
    """)
    if db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO users (name, balance) VALUES (?, 100)",
            [("vix",), ("pc",), ("tino",)]
        )
    db.commit()
    db.close()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def lookup_user(db, name):
    """Return the row for a user (case-insensitive) or None if not found."""
    return db.execute(
        "SELECT name, balance FROM users WHERE name = ?", (name.lower(),)
    ).fetchone()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/balance/<user>")
def balance(user):
    db = get_db()
    row = lookup_user(db, user)
    if row is None:
        return jsonify({"error": f"User '{user}' not found"}), 404
    return jsonify({"user": row["name"], "balance": row["balance"]}), 200


@app.route("/transfer")
def transfer():
    db = get_db()
    from_name = request.args.get("from")
    to_name   = request.args.get("to")

    from_row = lookup_user(db, from_name) if from_name else None
    if from_row is None:
        return jsonify({"error": f"User '{from_name or ''}' not found"}), 404

    to_row = lookup_user(db, to_name) if to_name else None
    if to_row is None:
        return jsonify({"error": f"User '{to_name or ''}' not found"}), 404

    if from_row["name"] == to_row["name"]:
        return jsonify({"error": "Cannot transfer tokens to yourself"}), 400

    amount_str = request.args.get("amount")
    if amount_str is None:
        return jsonify({"error": "Missing required parameter: amount"}), 400

    try:
        if "." in amount_str:
            raise ValueError
        amount = int(amount_str)
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "amount must be a positive integer"}), 400

    if from_row["balance"] < amount:
        return jsonify({
            "error": (
                f"Insufficient tokens: {from_row['name']} has "
                f"{from_row['balance']} but tried to send {amount}"
            )
        }), 400

    db.execute("UPDATE users SET balance = balance - ? WHERE name = ?", (amount, from_row["name"]))
    db.execute("UPDATE users SET balance = balance + ? WHERE name = ?", (amount, to_row["name"]))
    db.commit()

    from_updated = lookup_user(db, from_row["name"])
    to_updated   = lookup_user(db, to_row["name"])

    return jsonify({
        "from": {"user": from_updated["name"], "balance": from_updated["balance"]},
        "to":   {"user": to_updated["name"],   "balance": to_updated["balance"]},
    }), 200


@app.route("/users")
def list_users():
    """Return all users and their balances."""
    db = get_db()
    rows = db.execute("SELECT name, balance FROM users ORDER BY name").fetchall()
    return jsonify([{"user": r["name"], "balance": r["balance"]} for r in rows]), 200


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
init_db()
if __name__ == "__main__":
    init_db()
    app.run(debug=True)
