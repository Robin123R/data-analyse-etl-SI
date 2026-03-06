"""
analyse.py — Step 5 : Descriptive statistics and visualisation from MongoDB

Produces a stats report and 4 PNG graphs in analyse/output/ :

  graph1_calendar_composition.png  — calendar composition (Working/Weekend/Holiday)
  graph2_top_products.png          — top 10 most ordered products
  graph3_top_clients.png           — top 10 clients by order count
  graph4_avg_orders_by_day_type.png — average orders per day type
  stats_report.txt                  — descriptive statistics

Usage:
  python etl/analyse.py
"""

import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # non-interactive backend, must be set before pyplot import
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR   = PROJECT_ROOT / "analyse" / "output"

MONGO_URI = "mongodb://localhost:27017/"
DB_NAME   = "etl_db"


# ─── MongoDB connection ────────────────────────────────────────────────────────

def connect_mongo(retries: int = 10, delay: float = 4.0):
    from pymongo import MongoClient
    from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError

    for attempt in range(1, retries + 1):
        try:
            client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=3000)
            client.admin.command("ping")
            print(f"  Connected to MongoDB (attempt {attempt}/{retries})")
            return client
        except (ConnectionFailure, ServerSelectionTimeoutError):
            if attempt < retries:
                print(f"  MongoDB not ready (attempt {attempt}/{retries}), retrying in {delay}s...")
                time.sleep(delay)
            else:
                print(f"  ERROR: Cannot connect to MongoDB after {retries} attempts.")
                sys.exit(1)


# ─── Descriptive statistics ────────────────────────────────────────────────────

def compute_orders_stats(coll) -> dict:
    """Compute stats on the orders collection using server-side aggregation."""

    # ── OrderAmount global stats ──
    amount_pipeline = [
        {"$match": {"OrderAmount": {"$ne": "unknown"}}},
        {"$project": {"amount": {"$toDouble": "$OrderAmount"}}},
        {"$group": {
            "_id":    None,
            "count":  {"$sum": 1},
            "mean":   {"$avg": "$amount"},
            "stddev": {"$stdDevPop": "$amount"},
            "min":    {"$min": "$amount"},
            "max":    {"$max": "$amount"},
            "sum":    {"$sum": "$amount"},
        }},
    ]
    amount_res = list(coll.aggregate(amount_pipeline))

    # ── Percentiles (MongoDB 7.0+ $percentile operator) ──
    pct_pipeline = [
        {"$match": {"OrderAmount": {"$ne": "unknown"}}},
        {"$project": {"amount": {"$toDouble": "$OrderAmount"}}},
        {"$group": {
            "_id":    None,
            "q1":     {"$percentile": {"input": "$amount", "p": [0.25], "method": "approximate"}},
            "median": {"$percentile": {"input": "$amount", "p": [0.50], "method": "approximate"}},
            "q3":     {"$percentile": {"input": "$amount", "p": [0.75], "method": "approximate"}},
        }},
    ]
    try:
        pct_res = list(coll.aggregate(pct_pipeline))
    except Exception:
        pct_res = []

    # ── CustomerSatisfaction distribution ──
    sat_pipeline = [
        {"$match": {"CustomerSatisfaction": {"$ne": "unknown"}}},
        {"$project": {"sat": {"$toInt": "$CustomerSatisfaction"}}},
        {"$group": {"_id": "$sat", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    sat_res = list(coll.aggregate(sat_pipeline))

    # ── Top 10 suppliers by order count ──
    sup_pipeline = [
        {"$match": {"SupplierName": {"$ne": "unknown"}}},
        {"$group": {
            "_id":          "$SupplierName",
            "order_count":  {"$sum": 1},
            "total_amount": {"$sum": {"$toDouble": "$OrderAmount"}},
        }},
        {"$sort": {"order_count": -1}},
        {"$limit": 10},
    ]
    sup_res = list(coll.aggregate(sup_pipeline))

    # ── Data quality: "unknown" counts ──
    unk_pipeline = [
        {"$group": {
            "_id":                   None,
            "total":                 {"$sum": 1},
            "unknown_orderid":       {"$sum": {"$cond": [{"$eq": ["$OrderID",       "unknown"]}, 1, 0]}},
            "unknown_orderdate":     {"$sum": {"$cond": [{"$eq": ["$OrderDate",     "unknown"]}, 1, 0]}},
            "unknown_clientstreet":  {"$sum": {"$cond": [{"$eq": ["$ClientStreet",  "unknown"]}, 1, 0]}},
            "unknown_suppliername":  {"$sum": {"$cond": [{"$eq": ["$SupplierName",  "unknown"]}, 1, 0]}},
        }},
    ]
    unk_res = list(coll.aggregate(unk_pipeline))

    return {
        "amount":       amount_res[0] if amount_res else {},
        "percentiles":  pct_res[0]    if pct_res    else {},
        "satisfaction": sat_res,
        "top_suppliers": sup_res,
        "unknown":      unk_res[0]    if unk_res    else {},
    }


def compute_calendar_stats(coll) -> dict:
    """Compute stats on the calendar collection."""

    global_pipeline = [
        {"$group": {
            "_id":                None,
            "total":              {"$sum": 1},
            "weekends":           {"$sum": {"$cond": ["$isWeekend",   1, 0]}},
            "holidays":           {"$sum": {"$cond": ["$isUSHoliday", 1, 0]}},
            "holiday_on_weekend": {"$sum": {"$cond": [
                {"$and": ["$isWeekend", "$isUSHoliday"]}, 1, 0
            ]}},
        }},
    ]
    global_res = list(coll.aggregate(global_pipeline))

    month_pipeline = [
        {"$match": {"isUSHoliday": True}},
        {"$project": {"month": {"$substr": ["$date", 0, 7]}}},
        {"$group": {"_id": "$month", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    month_res = list(coll.aggregate(month_pipeline))

    return {
        "global":             global_res[0] if global_res else {},
        "holidays_by_month":  month_res,
    }


# ─── Stats report ─────────────────────────────────────────────────────────────

def write_stats_report(orders_stats: dict, calendar_stats: dict, report_path: Path):
    lines = []

    def p(line=""):
        lines.append(line)
        print(line)

    sep = "=" * 65

    p(sep)
    p("  DESCRIPTIVE STATISTICS REPORT — etl_db (MongoDB)")
    p(sep)

    # ── orders ──
    a   = orders_stats.get("amount", {})
    pct = orders_stats.get("percentiles", {})
    unk = orders_stats.get("unknown", {})
    total = unk.get("total", 0)

    p()
    p("── COLLECTION: orders  (moodle dataset) " + "─" * 26)
    p()
    p("  OrderAmount ($)")
    p(f"    Records : {a.get('count',  0):>12,}")
    p(f"    Mean    : {a.get('mean',   0):>12.2f}")
    p(f"    Std Dev : {a.get('stddev', 0):>12.2f}")
    p(f"    Min     : {a.get('min',    0):>12.2f}")
    if pct.get("q1"):
        p(f"    Q1      : {pct['q1'][0]:>12.2f}")
        p(f"    Median  : {pct['median'][0]:>12.2f}")
        p(f"    Q3      : {pct['q3'][0]:>12.2f}")
    p(f"    Max     : {a.get('max',    0):>12.2f}")

    p()
    p("  CustomerSatisfaction distribution")
    sat_total = sum(r["count"] for r in orders_stats.get("satisfaction", []))
    for row in orders_stats.get("satisfaction", []):
        pct_val = row["count"] / sat_total * 100 if sat_total else 0
        bar = "█" * max(1, int(pct_val / 2))
        p(f"    Score {row['_id']} : {row['count']:>8,}  ({pct_val:5.1f}%)  {bar}")

    p()
    p("  Top 10 Suppliers by order count")
    for i, row in enumerate(orders_stats.get("top_suppliers", []), 1):
        name = row["_id"][:38]
        p(f"    {i:2}. {name:<40} {row['order_count']:>6,} orders   ${row['total_amount']:>12,.0f}")

    p()
    p("  Data quality — 'unknown' values")
    for label, key in [
        ("OrderID",      "unknown_orderid"),
        ("OrderDate",    "unknown_orderdate"),
        ("ClientStreet", "unknown_clientstreet"),
        ("SupplierName", "unknown_suppliername"),
    ]:
        n = unk.get(key, 0)
        pct_val = n / total * 100 if total else 0
        p(f"    {label:<20} : {n:>8,}  ({pct_val:.2f}%)")

    # ── calendar ──
    g         = calendar_stats.get("global", {})
    total_d   = g.get("total", 0)
    weekends  = g.get("weekends", 0)
    holidays  = g.get("holidays", 0)
    hol_wknd  = g.get("holiday_on_weekend", 0)
    hol_wkday = holidays - hol_wknd
    working   = total_d - weekends - hol_wkday

    p()
    p("── COLLECTION: calendar  (external dataset) " + "─" * 22)
    p()
    p(f"  Period          : 2022–2023 ({total_d} days)")
    p(f"  Working days    : {working:>4}  ({working / total_d * 100:.1f}%)")
    p(f"  Weekends        : {weekends:>4}  ({weekends / total_d * 100:.1f}%)")
    p(f"  US Holidays     : {holidays:>4}  ({holidays / total_d * 100:.1f}%)")
    p(f"    → on a weekday: {hol_wkday:>4}")
    p(f"    → on a weekend: {hol_wknd:>4}")
    p()
    p("  US Public Holidays by month")
    for row in calendar_stats.get("holidays_by_month", []):
        p(f"    {row['_id']} : {row['count']} holiday(s)")

    p()
    p(sep)

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  Stats report saved: {report_path.relative_to(PROJECT_ROOT)}")


# ─── Graph styling ─────────────────────────────────────────────────────────────

def setup_style():
    sns.set_theme(style="whitegrid", palette="muted")
    plt.rcParams.update({
        "figure.dpi":    150,
        "font.family":   "sans-serif",
        "axes.titlepad": 12,
    })


# ─── Graph 1 — Calendar composition ──────────────────────────────────────────

def graph1_calendar_composition(calendar_stats: dict, output_dir: Path) -> Path:
    """
    Vertical bar chart: Working Days / Weekends / US Holidays totals for 2022–2023.
    Reuses the global_res already computed by compute_calendar_stats().
    """
    g         = calendar_stats.get("global", {})
    total_d   = g.get("total", 0)
    weekends  = g.get("weekends", 0)
    holidays  = g.get("holidays", 0)
    hol_wknd  = g.get("holiday_on_weekend", 0)
    hol_wkday = holidays - hol_wknd
    working   = total_d - weekends - hol_wkday

    labels = ["Working Days", "Weekends", "US Holidays"]
    values = [working, weekends, hol_wkday]
    colors = ["#4CAF50", "#2196F3", "#FF5722"]

    fig, ax = plt.subplots(figsize=(8, 6))
    bars = ax.bar(labels, values, color=colors, edgecolor="white", width=0.5)

    ax.set_title(
        "Calendar Composition — 2022–2023\n(external dataset)",
        fontsize=13, fontweight="bold",
    )
    ax.set_ylabel("Number of Days", fontsize=11)
    sns.despine()

    for bar, val in zip(bars, values):
        pct = val / total_d * 100 if total_d else 0
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height() + 2,
            f"{val}\n({pct:.1f}%)", ha="center", va="bottom", fontsize=10,
        )

    plt.tight_layout()
    path = output_dir / "graph1_calendar_composition.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {path.relative_to(PROJECT_ROOT)}")
    return path


# ─── Graph 2 — Top 10 products ────────────────────────────────────────────────

def graph2_top_products(coll, output_dir: Path) -> Path:
    """
    Horizontal bar chart: top 10 most ordered products by order count.
    Source: orders collection.
    """
    pipeline = [
        {"$match": {"ProductName": {"$ne": "unknown"}}},
        {"$group": {"_id": "$ProductName", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    docs = list(coll.aggregate(pipeline))
    df   = pd.DataFrame(docs).rename(columns={"_id": "product", "count": "count"})
    # Sort ascending so the highest bar appears at the top
    df   = df.sort_values("count", ascending=True)

    fig, ax = plt.subplots(figsize=(11, 7))

    # Color gradient: lightest bar for lowest, darkest for highest
    norm = plt.Normalize(df["count"].min(), df["count"].max())
    colors = plt.cm.Blues(0.35 + norm(df["count"]) * 0.55)

    bars = ax.barh(df["product"], df["count"], color=colors, edgecolor="white", linewidth=0.5)

    # Zoom in on the actual data range to reveal differences
    x_min = df["count"].min() * 0.97
    x_max = df["count"].max() * 1.035
    ax.set_xlim(x_min, x_max)

    ax.set_title(
        "Top 10 Most Ordered Products\n(moodle dataset)",
        fontsize=13, fontweight="bold",
    )
    ax.set_xlabel("Number of Orders", fontsize=11)
    sns.despine(left=True)

    for bar, val in zip(bars, df["count"]):
        ax.text(
            bar.get_width() + (x_max - x_min) * 0.004,
            bar.get_y() + bar.get_height() / 2,
            f"{val:,}", va="center", fontsize=9,
        )

    # Broken axis indicator (diagonal tick marks on left spine)
    ax.annotate("* L'axe X ne commence pas à 0", xy=(0, -0.09),
                xycoords="axes fraction", fontsize=8,
                color="gray", style="italic")

    plt.tight_layout()
    path = output_dir / "graph2_top_products.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {path.relative_to(PROJECT_ROOT)}")
    return path


# ─── Graph 3 — Top 10 clients ─────────────────────────────────────────────────

def graph3_top_clients(coll, output_dir: Path) -> Path:
    """
    Horizontal bar chart: top 10 clients by order count.
    Source: orders collection.
    """
    pipeline = [
        {"$match": {"ClientName": {"$ne": "unknown"}}},
        {"$group": {"_id": "$ClientName", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    docs = list(coll.aggregate(pipeline))
    df   = pd.DataFrame(docs).rename(columns={"_id": "client", "count": "count"})
    df   = df.sort_values("count", ascending=True)

    fig, ax = plt.subplots(figsize=(10, 7))
    bars = ax.barh(df["client"], df["count"], color="#FF5722", edgecolor="white")

    ax.set_title(
        "Top 10 Clients by Number of Orders\n(moodle dataset)",
        fontsize=13, fontweight="bold",
    )
    ax.set_xlabel("Number of Orders", fontsize=11)
    sns.despine(left=True)

    for bar, val in zip(bars, df["count"]):
        ax.text(
            bar.get_width() + df["count"].max() * 0.005, bar.get_y() + bar.get_height() / 2,
            f"{val:,}", va="center", fontsize=9,
        )

    plt.tight_layout()
    path = output_dir / "graph3_top_clients.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {path.relative_to(PROJECT_ROOT)}")
    return path


# ─── Graph 4 — Average orders by day type ────────────────────────────────────

def graph4_avg_orders_by_day_type(orders_coll, calendar_coll, output_dir: Path) -> Path:
    """
    Vertical bar chart: average number of orders per day, grouped by day type
    (Working Day / Weekend / US Holiday).
    Orders are aggregated by date server-side; then joined in Python with the
    calendar lookup to compute the mean count per type.
    """
    # ── Build calendar lookup: date_str -> day_type ──
    cal_docs = list(calendar_coll.find({}, {"_id": 0, "date": 1, "isWeekend": 1, "isUSHoliday": 1}))
    cal_df   = pd.DataFrame(cal_docs)

    def get_day_type(row):
        if row["isUSHoliday"]:
            return "US Holiday"
        elif row["isWeekend"]:
            return "Weekend"
        return "Working Day"

    cal_df["day_type"] = cal_df.apply(get_day_type, axis=1)
    cal_lookup = dict(zip(cal_df["date"], cal_df["day_type"]))

    # ── Aggregate orders by date (server-side) ──
    print("  Aggregating orders by date for graph 4...")
    agg_pipeline = [
        {"$match": {"OrderDate": {"$ne": "unknown"}}},
        {"$project": {"date": {"$substr": ["$OrderDate", 0, 10]}}},
        {"$group": {"_id": "$date", "count": {"$sum": 1}}},
    ]
    orders_by_date = list(orders_coll.aggregate(agg_pipeline, allowDiskUse=True))
    df = pd.DataFrame(orders_by_date).rename(columns={"_id": "date"})

    # ── Join with calendar ──
    df["day_type"] = df["date"].map(cal_lookup)
    df = df.dropna(subset=["day_type"])

    avg_by_type = (
        df.groupby("day_type")["count"]
        .mean()
        .reindex(["Working Day", "Weekend", "US Holiday"])
    )

    labels = avg_by_type.index.tolist()
    values = avg_by_type.values.tolist()
    colors = ["#4CAF50", "#2196F3", "#FF5722"]

    fig, ax = plt.subplots(figsize=(8, 6))
    bars = ax.bar(labels, values, color=colors, edgecolor="white", width=0.5)

    ax.set_title(
        "Average Number of Orders per Day by Day Type\n"
        "Moodle Orders × External Calendar (2022–2023)",
        fontsize=13, fontweight="bold",
    )
    ax.set_ylabel("Avg. Orders / Day", fontsize=11)
    sns.despine()

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height() + max(values) * 0.01,
            f"{val:.1f}", ha="center", va="bottom", fontsize=11, fontweight="bold",
        )

    plt.tight_layout()
    path = output_dir / "graph4_avg_orders_by_day_type.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {path.relative_to(PROJECT_ROOT)}")
    return path


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    setup_style()

    print("[Connecting to MongoDB]")
    client = connect_mongo()
    db     = client[DB_NAME]
    orders_coll   = db["orders"]
    calendar_coll = db["calendar"]

    print("\n[Computing descriptive statistics]")
    orders_stats   = compute_orders_stats(orders_coll)
    calendar_stats = compute_calendar_stats(calendar_coll)

    report_path = OUTPUT_DIR / "stats_report.txt"
    print()
    write_stats_report(orders_stats, calendar_stats, report_path)

    print("\n[Generating graphs]")
    graph1_calendar_composition(calendar_stats, OUTPUT_DIR)
    graph2_top_products(orders_coll, OUTPUT_DIR)
    graph3_top_clients(orders_coll, OUTPUT_DIR)
    graph4_avg_orders_by_day_type(orders_coll, calendar_coll, OUTPUT_DIR)

    client.close()

    print(f"\n  Output directory : analyse/output/")
    print(f"  Files produced   :")
    print(f"    stats_report.txt")
    print(f"    graph1_calendar_composition.png")
    print(f"    graph2_top_products.png")
    print(f"    graph3_top_clients.png")
    print(f"    graph4_avg_orders_by_day_type.png")


if __name__ == "__main__":
    main()
