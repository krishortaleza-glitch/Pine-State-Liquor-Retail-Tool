import streamlit as st
import pandas as pd
from io import BytesIO

# ==========================================================
# Page Configuration
# ==========================================================

st.set_page_config(
    page_title="Pinestate Liquor Retail Tool",
    layout="wide"
)

st.title("Pinestate Liquor Retail Tool")

st.markdown("""
Generate Standard and Promo retail files from:

- Vendor Store Cost File
- Master Price List

Supported Retailers:
- Circle K
- EG America
""")

st.divider()

# ==========================================================
# Retailer Selection
# ==========================================================

retailer = st.selectbox(
    "Retailer",
    [
        "Circle K",
        "EG America"
    ]
)

# ==========================================================
# File Uploads
# ==========================================================

vendor_file = st.file_uploader(
    "Vendor Store Cost File",
    type=["csv", "xlsx"]
)

master_file = st.file_uploader(
    "Master Price List",
    type=["xlsx"]
)

# ==========================================================
# Helper Functions
# ==========================================================

def read_vendor(uploaded_file):
    """Read Vendor Store Cost File."""

    if uploaded_file.name.lower().endswith(".csv"):
        return pd.read_csv(
            uploaded_file,
            dtype=str,
            low_memory=False
        )

    return pd.read_excel(
        uploaded_file,
        dtype=str
    )


def read_master(uploaded_file):
    """Read Master Price List."""

    return pd.read_excel(
        uploaded_file,
        dtype=str
    )


def clean_uid(series):
    """
    Normalize UPC / UID values.

    Examples
    --------
    0006270
    06270
    6270
    6270.0

    becomes

    6270
    """

    return (
        series
        .fillna("")
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.strip()
        .str.upper()
        .str.lstrip("0")
        .replace("", pd.NA)
    )


def validate_columns(df, required_columns, file_name):

    missing = [
        col
        for col in required_columns
        if col not in df.columns
    ]

    if missing:

        st.error(
            f"""
**{file_name}** is missing the following required columns:

- """ + "\n- ".join(missing)
        )

        st.stop()


# ==========================================================
# Required Columns
# ==========================================================

VENDOR_COLUMNS = [
    "StoreID",
    "retailProductUID",
    "retailProductName",
    "group",
    "vendorProductUID"
]

MASTER_COLUMNS = [
    "Retail Price",
    "Sales Price"
]

# Retailer-specific matching column

if retailer == "Circle K":
    MASTER_COLUMNS.append("Item .")
else:
    MASTER_COLUMNS.append("UPC")

# ==========================================================
# Main
# ==========================================================

if vendor_file and master_file:

    progress = st.progress(
        0,
        text="Reading files..."
    )

    vendor = read_vendor(vendor_file)

    progress.progress(
        20,
        text="Reading Master Price List..."
    )

    master = read_master(master_file)

    progress.progress(
        40,
        text="Validating files..."
    )

    validate_columns(
        vendor,
        VENDOR_COLUMNS,
        "Vendor Store Cost File"
    )

    validate_columns(
        master,
        MASTER_COLUMNS,
        "Master Price List"
    )

    progress.progress(
        50,
        text="Preparing data..."
    )

    # ======================================================
    # PART 2 STARTS HERE
    # ======================================================

    # ======================================================
    # PART 2 - Data Preparation
    # ======================================================

    progress.progress(
        60,
        text="Cleaning data..."
    )

    # -----------------------------
    # Normalize Vendor IDs
    # -----------------------------

    vendor["vendorProductUID"] = clean_uid(vendor["vendorProductUID"])
    vendor["retailProductUID"] = clean_uid(vendor["retailProductUID"])

    # -----------------------------
    # Retailer-specific Lookup Key
    # -----------------------------

    if retailer == "Circle K":

        master["LookupKey"] = clean_uid(
            master["Item ."]
        )

    else:

        master["LookupKey"] = clean_uid(
            master["UPC"]
        )

    # Remove blanks

    master = master[
        master["LookupKey"].notna()
    ].copy()

    # -----------------------------
    # Retail Prices
    # -----------------------------

    master["Retail Price"] = pd.to_numeric(
        master["Retail Price"],
        errors="coerce"
    )

    master["Sales Price"] = pd.to_numeric(
        master["Sales Price"],
        errors="coerce"
    )

    # Promo 0 = blank

    master["Sales Price"] = (
        master["Sales Price"]
        .mask(master["Sales Price"].fillna(0) == 0)
    )

    # -----------------------------
    # Remove duplicate lookup keys
    # -----------------------------

    master = master.drop_duplicates(
        subset="LookupKey",
        keep="first"
    )

    # -----------------------------
    # Pack Type
    # -----------------------------

    vendor["Pack Type"] = (
        vendor["group"]
        .fillna("")
        .astype(str)
        .str.lower()
        .apply(
            lambda x: "Each"
            if "single" in x
            else "Pack"
        )
    )

    progress.progress(
        70,
        text="Preparing matching engine..."
    )

    # ======================================================
    # PART 3 STARTS HERE
    # Matching Engine
    # ======================================================

    # ======================================================
    # PART 3 - Matching Engine
    # ======================================================

    progress.progress(
        80,
        text=f"Matching {retailer} products..."
    )

    # Create output columns
    vendor["Retail"] = pd.NA
    vendor["PromoRetail"] = pd.NA

    # --------------------------------------------------
    # CIRCLE K
    # Exact dictionary lookup
    # --------------------------------------------------

    if retailer == "Circle K":

        retail_lookup = dict(
            zip(
                master["LookupKey"],
                master["Retail Price"]
            )
        )

        promo_lookup = dict(
            zip(
                master["LookupKey"],
                master["Sales Price"]
            )
        )

        vendor["Retail"] = (
            vendor["vendorProductUID"]
            .map(retail_lookup)
        )

        vendor["PromoRetail"] = (
            vendor["vendorProductUID"]
            .map(promo_lookup)
        )

    # --------------------------------------------------
    # EG AMERICA
    # Exact -> Contains
    # --------------------------------------------------

    else:

        total = len(vendor)

        for i, row in enumerate(vendor.itertuples(), start=1):

            vendor_upc = row.vendorProductUID

            if pd.isna(vendor_upc):
                continue

            vendor_upc = str(vendor_upc)

            # -------------------------
            # 1. Exact Match
            # -------------------------

            exact = master[
                master["LookupKey"] == vendor_upc
            ]

            if len(exact) == 1:

                vendor.at[row.Index, "Retail"] = exact.iloc[0]["Retail Price"]
                vendor.at[row.Index, "PromoRetail"] = exact.iloc[0]["Sales Price"]

                continue

            # -------------------------
            # 2. Contains Match
            # -------------------------

            contains = master[
                master["LookupKey"].str.contains(
                    vendor_upc,
                    regex=False,
                    na=False
                )
            ]

            # Only accept ONE unique match

            if len(contains) == 1:

                vendor.at[row.Index, "Retail"] = contains.iloc[0]["Retail Price"]
                vendor.at[row.Index, "PromoRetail"] = contains.iloc[0]["Sales Price"]

            # Multiple matches are ignored intentionally

            if i % 500 == 0:

                progress.progress(
                    min(95, 80 + int((i / total) * 15)),
                    text=f"Matching EG America... {i:,}/{total:,}"
                )

    # ======================================================
    # PART 4 STARTS HERE
    # Build Output Files
    # ======================================================
    # ======================================================
    # PART 4 - Build Output Files
    # ======================================================

    progress.progress(
        96,
        text="Building output files..."
    )

    # --------------------------------------------------
    # Standard Output
    # --------------------------------------------------

    standard = pd.DataFrame({

        "StoreID": vendor["StoreID"],

        "RetailUID": vendor["retailProductUID"],

        "Retail": vendor["Retail"],

        "Pack Type": vendor["Pack Type"],

        "retailProductName": vendor["retailProductName"],

        "group": vendor["group"]

    })

    # Remove rows without retail

    standard_missing = standard[
        standard["Retail"].isna()
    ].copy()

    standard = standard[
        standard["Retail"].notna()
    ].copy()

    # --------------------------------------------------
    # Promo Output
    # --------------------------------------------------

    promo = pd.DataFrame({

        "StoreID": vendor["StoreID"],

        "RetailUID": vendor["retailProductUID"],

        "Retail": vendor["PromoRetail"],

        "Pack Type": vendor["Pack Type"],

        "retailProductName": vendor["retailProductName"],

        "group": vendor["group"]

    })

    # Remove blank promo prices

    promo_missing = promo[
        promo["Retail"].isna()
    ].copy()

    promo = promo[
        promo["Retail"].notna()
    ].copy()

    # --------------------------------------------------
    # Missing Retails
    # --------------------------------------------------

    missing_retails = vendor.loc[
        vendor["Retail"].isna(),
        [
            "StoreID",
            "vendorProductUID",
            "retailProductUID",
            "retailProductName",
            "group"
        ]
    ].copy()

    missing_retails.rename(
        columns={
            "vendorProductUID": "VendorProductUID",
            "retailProductUID": "RetailUID",
            "retailProductName": "Product Name",
            "group": "Group"
        },
        inplace=True
    )

    # Sort for easier review

    missing_retails = missing_retails.sort_values(
        by=[
            "StoreID",
            "Product Name"
        ]
    )

    progress.progress(
        99,
        text="Preparing Excel workbook..."
    )

    # ======================================================
    # PART 5 STARTS HERE
    # Export Workbook
    # ======================================================
    # ======================================================
    # PART 5 - Export Workbook
    # ======================================================

    output = BytesIO()

    with pd.ExcelWriter(output, engine="openpyxl") as writer:

        standard.to_excel(
            writer,
            sheet_name="Standard Retail",
            index=False
        )

        promo.to_excel(
            writer,
            sheet_name="Promo Retail",
            index=False
        )

        missing_retails.to_excel(
            writer,
            sheet_name="Missing Retails",
            index=False
        )

    output.seek(0)

    progress.progress(
        100,
        text="Complete!"
    )

    st.success("Retail files generated successfully!")

    st.divider()
  
    # ======================================================
    # Download
    # ======================================================

    st.download_button(
        label="📥 Download Retail Workbook",
        data=output.getvalue(),
        file_name=f"{retailer}_Retail_Output.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
