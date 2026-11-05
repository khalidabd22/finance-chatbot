import pandas as pd

from bots.base import BaseBot
from core.context import find_column


def finance_summary(df: pd.DataFrame, name: str) -> str:
    amount_col = find_column(df, "amount", "value", "price", "total", "debit", "credit")
    if not amount_col:
        return ""
    amounts = pd.to_numeric(df[amount_col].astype(str).str.replace(r"[^\d.\-]", "", regex=True), errors="coerce")
    if amounts.notna().sum() == 0:
        return ""
    data = df.assign(_amount=amounts).dropna(subset=["_amount"])
    out = [f"[{name}] using column '{amount_col}': rows={len(data)}, total={data['_amount'].sum():,.2f}, "
           f"average={data['_amount'].mean():,.2f}, max={data['_amount'].max():,.2f}, min={data['_amount'].min():,.2f}"]

    type_col = find_column(df, "type", "transaction_type", "dr_cr")
    if type_col:
        by_type = data.groupby(data[type_col].astype(str).str.lower())["_amount"].sum().round(2)
        out.append("Total by type:\n" + by_type.to_string())
        income = by_type[[i for i in by_type.index if "income" in i or "credit" in i]].sum()
        expense = by_type[[i for i in by_type.index if "expense" in i or "debit" in i]].sum()
        if income or expense:
            out.append(f"Income={income:,.2f}, Expense={expense:,.2f}, Net savings={income - expense:,.2f}")

    cat_col = find_column(df, "category", "head", "description")
    if cat_col:
        by_cat = data.groupby(cat_col)["_amount"].sum().sort_values(ascending=False).head(15).round(2)
        out.append("Top categories by amount:\n" + by_cat.to_string())

    date_col = find_column(df, "date", "txn_date", "transaction_date")
    if date_col:
        dates = pd.to_datetime(data[date_col], errors="coerce", dayfirst=False)
        if dates.notna().any():
            monthly = data.assign(_m=dates.dt.to_period("M").astype(str)).groupby("_m")["_amount"].sum().round(2)
            out.append("Monthly totals:\n" + monthly.to_string())
    return "\n".join(out)


class FinanceBot(BaseBot):
    key = "finance"
    name = "Finance Assistant"
    icon = "💰"
    description = "Expenses, budgets, savings analysis - bank statement / transactions CSV upload karein."
    sample_files = ["sample_data/transactions.csv"]
    placeholder = "e.g. Is mahine sabse zyada kharcha kis category me hua?"
    disclaimer = "Yeh general financial information hai, professional financial advice nahi. Bade decision se pehle certified advisor se baat karein."

    system_prompt = (
        "You are a careful personal-finance and accounting assistant.\n"
        "- Use VERIFIED FACTS for totals - they are computed exactly by Python, do not recompute them differently.\n"
        "- Explain spending patterns, budgeting (e.g. 50/30/20 rule), savings, EMI and basic tax concepts clearly.\n"
        "- Show calculations step by step when you do math. Use the currency present in the data (default INR, ₹).\n"
        "- Do not recommend specific stocks or guarantee returns."
    )

    def extra_context(self, query, datasets):
        parts = []
        for ds in datasets:
            if ds.df is not None:
                summary = finance_summary(ds.df, ds.name)
                if summary:
                    parts.append(summary)
        return "\n\n".join(parts)
