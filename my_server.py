import os
import json
import requests
from typing import Annotated, Optional
from datetime import datetime
import pytz
import pandas as pd
from fastmcp import FastMCP
from utils import get_db
from transaction_manager import TransactionManager

mcp = FastMCP("Hevy MCP Server")

NYC = pytz.timezone("America/New_York")

txn_mgr = TransactionManager()


def _row_to_dict(row) -> dict:
    # used only while returning existing data to user
    return {
        "id": row[0],
        "meal_type": row[1],
        "calories": row[2],
        "protein_g": row[3],
        "carbs_g": row[4],
        "fat_g": row[5],
        "logged_at": datetime.fromisoformat(row[6]).astimezone(NYC).isoformat(),
        "desc": row[7],
    }


@mcp.tool
def get_workouts(
    page: Annotated[int, "Page number, starting from 1"],
    page_size: Annotated[int, "Number of workouts per page (max 10)"],
) -> str:
    """Get a paginated list of workouts from Hevy, ordered newest to oldest."""
    url = "https://api.hevyapp.com/v1/workouts"
    params = {"page": page, "pageSize": page_size}
    headers = {"accept": "application/json", "api-key": os.environ.get("HEVY", "")}
    response = requests.get(url, headers=headers, params=params)
    return response.text


@mcp.tool
def body_measurements(
    page: Annotated[int, "Page number, starting from 1"],
    page_size: Annotated[int, "Number of workouts per page (max 10)"],
) -> str:
    """Get a paginated list of body measurements (weight, body fat, etc.) from Hevy."""
    url = "https://api.hevyapp.com/v1/body_measurements"
    params = {"page": page, "pageSize": page_size}
    headers = {"accept": "application/json", "api-key": os.environ.get("HEVY", "")}
    response = requests.get(url, headers=headers, params=params)
    return response.text


@mcp.tool
def get_workout_count() -> str:
    """Get the total number of workouts logged in Hevy."""
    url = "https://api.hevyapp.com/v1/workouts/count"
    headers = {"accept": "application/json", "api-key": os.environ.get("HEVY", "")}
    response = requests.get(url, headers=headers)
    return response.text


@mcp.tool
def log_meal(
    meal_type: Annotated[str, "One of: breakfast, lunch, dinner, snack"],
    logged_at: Annotated[
        str,
        "ISO 8601 timestamp INCLUDING a UTC offset (e.g. '2026-08-03T08:30:00-04:00'), "
        "representing the moment the meal was actually eaten in the user's local time. "
        "Always determine and pass this explicitly — never omit it. Never pass a naive "
        "timestamp with no offset — it makes the stored instant ambiguous and breaks "
        "date-based queries.",
    ],
    calories: Annotated[Optional[float], "Calories"] = None,
    protein_g: Annotated[Optional[float], "Protein in grams"] = None,
    carbs_g: Annotated[Optional[float], "Carbs in grams"] = None,
    fat_g: Annotated[Optional[float], "Fat in grams"] = None,
    desc: Annotated[Optional[str], "Description of the meal"] = None,
) -> str:
    """Log a meal to the database."""
    conn = get_db()
    conn.execute(
        "INSERT INTO meals (meal_type, calories, protein_g, carbs_g, fat_g, logged_at, desc) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (meal_type, calories, protein_g, carbs_g, fat_g, logged_at, desc or ""),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM meals WHERE logged_at = ? AND meal_type = ? ORDER BY rowid DESC LIMIT 1",
        (logged_at, meal_type),
    ).fetchone()
    return json.dumps(_row_to_dict(row))


@mcp.tool
def update_meal(
    meal_id: Annotated[str, "ID of the meal to update"],
    meal_type: Annotated[
        Optional[str], "One of: breakfast, lunch, dinner, snack"
    ] = None,
    calories: Annotated[Optional[float], "Calories"] = None,
    protein_g: Annotated[Optional[float], "Protein in grams"] = None,
    carbs_g: Annotated[Optional[float], "Carbs in grams"] = None,
    fat_g: Annotated[Optional[float], "Fat in grams"] = None,
    logged_at: Annotated[
        Optional[str],
        "ISO 8601 timestamp INCLUDING a UTC offset (e.g. '2026-08-03T08:30:00-04:00'), "
        "representing the moment the meal was actually eaten in the user's local time. "
        "Never pass a naive timestamp with no offset — it makes the stored instant "
        "ambiguous and breaks date-based queries.",
    ] = None,
    desc: Annotated[Optional[str], "Description of the meal"] = None,
) -> str:
    """Update fields of an existing meal by ID."""
    fields = {
        "meal_type": meal_type,
        "calories": calories,
        "protein_g": protein_g,
        "carbs_g": carbs_g,
        "fat_g": fat_g,
        "logged_at": logged_at,
        "desc": desc,
    }
    updates = {k: v for k, v in fields.items() if v is not None}
    if not updates:
        return "No fields provided to update."
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [meal_id]
    conn = get_db()
    conn.execute(f"UPDATE meals SET {set_clause} WHERE id = ?", tuple(values))
    conn.commit()
    row = conn.execute("SELECT * FROM meals WHERE id = ?", (meal_id,)).fetchone()
    if row is None:
        return f"No meal found with id {meal_id}"
    return json.dumps(_row_to_dict(row))


@mcp.tool
def delete_meal(
    meal_id: Annotated[str, "ID of the meal to delete"],
) -> str:
    """Delete a meal by ID."""
    conn = get_db()
    row = conn.execute("SELECT id FROM meals WHERE id = ?", (meal_id,)).fetchone()
    if row is None:
        return f"No meal found with id {meal_id}"
    conn.execute("DELETE FROM meals WHERE id = ?", (meal_id,))
    conn.commit()
    return f"Deleted meal {meal_id}"


@mcp.tool
def get_meals_by_date(
    date: Annotated[str, "Date in YYYY-MM-DD format (NYC timezone)"],
) -> str:
    """Get all meals logged on a specific NYC calendar date."""
    conn = get_db(sync=True)
    rows = conn.execute(
        "SELECT * FROM meals WHERE substr(logged_at, 1, 10) = ? ORDER BY logged_at",
        (date,),
    ).fetchall()
    return json.dumps([_row_to_dict(r) for r in rows])


@mcp.tool
def list_templates() -> str:
    """Get all meals logged on a specific NYC calendar date."""
    conn = get_db(sync=True)
    rows = pd.read_sql("select id, name, notes from meal_templates", con=conn).to_json(
        orient="records"
    )
    return rows


@mcp.tool
def get_meals_by_date_range(
    start_date: Annotated[str, "Start date YYYY-MM-DD (inclusive, NYC timezone)"],
    end_date: Annotated[str, "End date YYYY-MM-DD (inclusive, NYC timezone)"],
) -> str:
    """Get all meals in a date range, filtered by NYC timezone."""
    conn = get_db(sync=True)
    rows = conn.execute(
        "SELECT * FROM meals WHERE substr(logged_at, 1, 10) BETWEEN ? AND ? ORDER BY logged_at",
        (start_date, end_date),
    ).fetchall()
    return json.dumps([_row_to_dict(r) for r in rows])


@mcp.tool
def get_meals_today() -> str:
    """Get all meals logged today (NYC timezone)."""
    today = datetime.now(NYC).strftime("%Y-%m-%d")
    return get_meals_by_date(today)


@mcp.tool
def get_nutrition_summary(
    start_date: Annotated[str, "Start date YYYY-MM-DD (inclusive, NYC timezone)"],
    end_date: Annotated[str, "End date YYYY-MM-DD (inclusive, NYC timezone)"],
) -> str:
    """Get daily nutrition totals and averages over a date range (NYC timezone)."""
    conn = get_db(sync=True)
    rows = conn.execute(
        """
        SELECT substr(logged_at, 1, 10) AS day,
               COALESCE(SUM(calories), 0) AS calories,
               COALESCE(SUM(protein_g), 0) AS protein_g,
               COALESCE(SUM(carbs_g), 0) AS carbs_g,
               COALESCE(SUM(fat_g), 0) AS fat_g,
               COUNT(*) AS meal_count
        FROM meals
        WHERE substr(logged_at, 1, 10) BETWEEN ? AND ?
        GROUP BY day
        ORDER BY day
        """,
        (start_date, end_date),
    ).fetchall()

    by_date = {
        r[0]: {
            "calories": r[1],
            "protein_g": r[2],
            "carbs_g": r[3],
            "fat_g": r[4],
            "meal_count": r[5],
        }
        for r in rows
    }

    day_count = len(by_date)
    totals = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    for d in by_date.values():
        for k in totals:
            totals[k] += d[k]

    averages = {
        k: round(v / day_count, 1) if day_count else 0 for k, v in totals.items()
    }
    return json.dumps(
        {
            "by_date": by_date,
            "day_count": day_count,
            "totals": {k: round(v, 1) for k, v in totals.items()},
            "daily_averages": averages,
        }
    )


def _template_row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "name": row[1],
        "calories": row[2],
        "protein_g": row[3],
        "carbs_g": row[4],
        "fat_g": row[5],
        "notes": row[6],
    }


@mcp.tool
def create_meal_template(
    name: Annotated[str, "Name of the meal template"],
    calories: Annotated[Optional[float], "Calories"] = None,
    protein_g: Annotated[Optional[float], "Protein in grams"] = None,
    carbs_g: Annotated[Optional[float], "Carbs in grams"] = None,
    fat_g: Annotated[Optional[float], "Fat in grams"] = None,
    notes: Annotated[Optional[str], "Notes about the template"] = None,
) -> str:
    """Create a new meal template."""
    conn = get_db()
    conn.execute(
        "INSERT INTO meal_templates (name, calories, protein_g, carbs_g, fat_g, notes) VALUES (?, ?, ?, ?, ?, ?)",
        (name, calories, protein_g, carbs_g, fat_g, notes or ""),
    )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM meal_templates WHERE name = ? ORDER BY rowid DESC LIMIT 1",
        (name,),
    ).fetchone()
    return json.dumps(_template_row_to_dict(row))


@mcp.tool
def update_meal_template(
    template_id: Annotated[str, "ID of the template to update"],
    name: Annotated[Optional[str], "Name of the meal template"] = None,
    calories: Annotated[Optional[float], "Calories"] = None,
    protein_g: Annotated[Optional[float], "Protein in grams"] = None,
    carbs_g: Annotated[Optional[float], "Carbs in grams"] = None,
    fat_g: Annotated[Optional[float], "Fat in grams"] = None,
    notes: Annotated[Optional[str], "Notes about the template"] = None,
) -> str:
    """Update fields of an existing meal template by ID."""
    fields = {
        "name": name,
        "calories": calories,
        "protein_g": protein_g,
        "carbs_g": carbs_g,
        "fat_g": fat_g,
        "notes": notes,
    }
    updates = {k: v for k, v in fields.items() if v is not None}
    if not updates:
        return "No fields provided to update."
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [template_id]
    conn = get_db()
    conn.execute(f"UPDATE meal_templates SET {set_clause} WHERE id = ?", tuple(values))
    conn.commit()
    row = conn.execute(
        "SELECT * FROM meal_templates WHERE id = ?", (template_id,)
    ).fetchone()
    if row is None:
        return f"No meal template found with id {template_id}"
    return json.dumps(_template_row_to_dict(row))


@mcp.tool
def delete_meal_template(
    template_id: Annotated[str, "ID of the template to delete"],
) -> str:
    """Delete a meal template by ID."""
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM meal_templates WHERE id = ?", (template_id,)
    ).fetchone()
    if row is None:
        return f"No meal template found with id {template_id}"
    conn.execute("DELETE FROM meal_templates WHERE id = ?", (template_id,))
    conn.commit()
    return f"Deleted meal template {template_id}"


@mcp.tool
def log_meal_from_template(
    template_id: Annotated[str, "ID of the meal template to log"],
    meal_type: Annotated[str, "One of: breakfast, lunch, dinner, snack"],
    logged_at: Annotated[
        str,
        "ISO 8601 timestamp INCLUDING a UTC offset (e.g. '2026-08-03T08:30:00-04:00'), "
        "representing the moment the meal was actually eaten in the user's local time. "
        "Always determine and pass this explicitly — never omit it. Never pass a naive "
        "timestamp with no offset — it makes the stored instant ambiguous and breaks "
        "date-based queries.",
    ],
) -> str:
    """Log a meal using macros from a saved template."""
    conn = get_db(sync=True)
    row = conn.execute(
        "SELECT * FROM meal_templates WHERE id = ?", (template_id,)
    ).fetchone()
    if row is None:
        return f"No meal template found with id {template_id}"
    t = _template_row_to_dict(row)
    conn.execute(
        "INSERT INTO meals (meal_type, calories, protein_g, carbs_g, fat_g, logged_at, desc) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            meal_type,
            t["calories"],
            t["protein_g"],
            t["carbs_g"],
            t["fat_g"],
            logged_at,
            t["name"],
        ),
    )
    conn.commit()
    meal_row = conn.execute(
        "SELECT * FROM meals WHERE logged_at = ? AND meal_type = ? ORDER BY rowid DESC LIMIT 1",
        (logged_at, meal_type),
    ).fetchone()
    return json.dumps(_row_to_dict(meal_row))


def _txn_row_to_dict(row) -> dict:
    return {
        "transaction_id": row[0],
        "authorized_date": row[1],
        "amount": row[2],
        "merchant_name": row[3],
        "category": row[4],
    }


@mcp.tool
def sync_transactions() -> str:
    """Sync transactions from Plaid into the local database, following the
    saved cursor. Returns counts of added, modified, and removed transactions."""
    return json.dumps(txn_mgr.sync())


@mcp.tool
def get_transactions_by_date(
    date: Annotated[str, "Date in YYYY-MM-DD format"],
) -> str:
    """Get all stored transactions authorized on a specific date."""
    rows = txn_mgr.get_transactions_by_date(date)
    return json.dumps([_txn_row_to_dict(r) for r in rows])


@mcp.tool
def get_transactions_by_date_range(
    start_date: Annotated[str, "Start date YYYY-MM-DD (inclusive)"],
    end_date: Annotated[str, "End date YYYY-MM-DD (inclusive)"],
) -> str:
    """Get all stored transactions authorized within a date range."""
    rows = txn_mgr.get_transactions_by_date_range(start_date, end_date)
    return json.dumps([_txn_row_to_dict(r) for r in rows])


@mcp.tool
def get_transactions_by_merchant(
    merchant_name: Annotated[str, "Exact merchant name to match"],
) -> str:
    """Get all stored transactions for a given merchant."""
    rows = txn_mgr.get_transactions_by_merchant(merchant_name)
    return json.dumps([_txn_row_to_dict(r) for r in rows])


@mcp.tool
def get_transactions_by_category(
    category: Annotated[str, "Exact category string to match"],
) -> str:
    """Get all stored transactions matching a category."""
    rows = txn_mgr.get_transactions_by_category(category)
    return json.dumps([_txn_row_to_dict(r) for r in rows])


@mcp.tool
def get_recurring_transactions() -> str:
    """Get recurring transaction streams directly from Plaid (not the local DB)."""
    return json.dumps(txn_mgr.get_recurring_transactions())


if __name__ == "__main__":
    mcp.run(transport="http", port=8000)
