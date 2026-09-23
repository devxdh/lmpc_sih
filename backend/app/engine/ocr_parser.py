"""
@file ocr_parser.py
@description Statutory lexical and semantic parser for Legal Metrology Packaged Commodities (LMPC).
Extracts mandatory Rule 6 declarations from PaddleOCR text output with bounding boxes.
Special handling for embossed crimp seals, inverted Unit Sale Price, dual-pricing stickers,
and Rule 12 SI symbols.
"""

import re
from typing import Any

from app.schemas import ExtractedPackageDeclarations

# Standard SI Unit symbols strictly mandated under Rule 12 of LMPC Rules 2011
VALID_SI_UNITS = {"g", "kg", "ml", "mL", "l", "L", "m", "cm", "mm", "N", "U", "unit", "units"}
NON_STANDARD_UNIT_PATTERNS = [
    (r"\b(gms?|gm|GMS?|Gm)\b", "g"),
    (r"\b(kgs?|KGS?|Kg)\b", "kg"),
    (r"\b(ltrs?|ltr|LTRS?|Ltr)\b", "L"),
    (r"\b(mls?|MLS?|Mls?)\b", "ml"),
    (r"\b(pcs?|pieces?)\b", "U"),
]


def extract_declarations_from_text(
    raw_text: str, detected_barcode: str | None = None
) -> ExtractedPackageDeclarations:
    """Parses full raw OCR text from a packaged commodity label."""
    lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
    full_text = "\n".join(lines)

    barcode = detected_barcode
    if not barcode:
        barcode_match = re.search(r"\b(890\d{10}|\d{13}|\d{12}|\d{8})\b", full_text)
        if barcode_match:
            barcode = barcode_match.group(1)

    mrp: float | None = None
    mrp_raw_text: str | None = None
    has_inclusive_of_taxes = False

    tax_clause_regex = (
        r"(?:incl(?:usive)?\.?\s*of\s*all\s*taxes|incl\.?\s*taxes|inclusive\s*of\s*taxes|incl\b)"
    )
    if re.search(tax_clause_regex, full_text, re.IGNORECASE):
        has_inclusive_of_taxes = True

    mrp_patterns = [
        r"(?:M\.?R\.?P\.?|MRP|Max(?:imum)?\s*Retail\s*Price)[\s:₹Rs\.]*([0-9]+(?:[\.,][0-9]{2})?)",
        r"(?:₹|Rs\.?)\s*([0-9]+(?:[\.,][0-9]{2})?)",
        r"\b([0-9]+[\.,][0-9]{2})\s*(?:\(?(?:incl|inclusive))",
    ]
    for pattern in mrp_patterns:
        match = re.search(pattern, full_text, re.IGNORECASE)
        if match:
            val_str = match.group(1).replace(",", ".")
            try:
                candidate_mrp = float(val_str)
                if candidate_mrp > 1.0 and candidate_mrp not in (2024.0, 2025.0, 2026.0):
                    mrp = candidate_mrp
                    mrp_raw_text = match.group(0).strip()
                    break
            except ValueError:
                continue

    if mrp is None:
        for idx, line in enumerate(lines):
            if re.search(r"(?:M\.?R\.?P\.?|MRP)", line, re.IGNORECASE):
                for j in range(idx, min(idx + 4, len(lines))):
                    num_match = re.search(r"(?:₹|Rs\.?|R)?\s*([0-9]+[\.,][0-9]{2})", lines[j])
                    if num_match:
                        try:
                            candidate_mrp = float(num_match.group(1).replace(",", "."))
                            if candidate_mrp > 1.0 and candidate_mrp not in (2024.0, 2025.0, 2026.0):
                                mrp = candidate_mrp
                                mrp_raw_text = f"MRP ₹ {candidate_mrp:.2f}"
                                break
                        except ValueError:
                            continue
                if mrp is not None:
                    break

    net_quantity_value: float | None = None
    net_quantity_unit: str | None = None
    net_quantity_raw_text: str | None = None
    is_standard_unit_symbol = False

    net_qty_patterns = [
        r"(?:Net\s*(?:Quantity|Qty|Weight|Wt|Volume|Vol)[\s\.:/]*)\s*([0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z]+)",
        r"\b([0-9]+(?:\.[0-9]+)?)\s*(ml|mL|g|kg|l|L|cm|m|N|U|gms|gm|kgs|ltr|pcs)\b",
    ]
    for pattern in net_qty_patterns:
        matches = re.finditer(pattern, full_text, re.IGNORECASE)
        for match in matches:
            val_str = match.group(1)
            unit_str = match.group(2).strip()
            try:
                candidate_qty = float(val_str)
                if candidate_qty > 0 and candidate_qty != mrp and candidate_qty not in (2024, 2025, 2026):
                    net_quantity_value = candidate_qty
                    net_quantity_unit = unit_str.lower()
                    net_quantity_raw_text = match.group(0).strip()
                    is_standard_unit_symbol = unit_str in VALID_SI_UNITS
                    break
            except ValueError:
                continue
        if net_quantity_value is not None:
            break

    declared_usp: float | None = None
    declared_usp_unit: str | None = None
    calculated_usp: float | None = None
    usp_discrepancy_percent: float | None = None

    usp_patterns = [
        r"(?:USP|Unit\s*Sale\s*Price)[\s:₹Rs\.]*([0-9]+(?:\.[0-9]+)?)\s*(?:per|\/)\s*([a-zA-Z]+)",
        r"(?:USP|Unit\s*Sale\s*Price)\s*(?:per|\/)\s*([a-zA-Z]+)[\s:₹Rs\.]*([0-9]+(?:\.[0-9]+)?)",
        r"(?:₹|Rs\.?)\s*([0-9]+(?:\.[0-9]+)?)\s*(?:per|\/)\s*(g|ml|kg|l|cm|m|piece|unit)",
    ]
    for pattern in usp_patterns:
        match = re.search(pattern, full_text, re.IGNORECASE)
        if match:
            g1, g2 = match.group(1), match.group(2)
            try:
                if re.match(r"^[0-9]+(?:\.[0-9]+)?$", g1):
                    declared_usp = float(g1)
                    declared_usp_unit = f"per {g2.lower()}"
                else:
                    declared_usp = float(g2)
                    declared_usp_unit = f"per {g1.lower()}"
                break
            except ValueError:
                continue

    if mrp is not None and net_quantity_value is not None and net_quantity_value > 0:
        calculated_usp = round(mrp / net_quantity_value, 2)
        if declared_usp is not None and declared_usp > 0:
            diff = abs(declared_usp - calculated_usp)
            usp_discrepancy_percent = round((diff / calculated_usp) * 100.0, 2)

    manufacturing_date: str | None = None
    crimp_notice_regex = r"(?:(?:see|refer|check)\s+(?:on\s+)?(?:the\s+)?crimp|see\s+crimp|stamped\s+on\s+crimp|on\s+crimp|see\s+bottom|on\s+seal|embossed)"
    crimp_match = re.search(crimp_notice_regex, full_text, re.IGNORECASE)
    if crimp_match:
        manufacturing_date = "Embossed on crimp / seal (Rule 6(1)(d) statutory proviso)"
    else:
        mfg_date_patterns = [
            r"(?:Mfg|Manufactured|Packed|Mfg\s*Date|Date\s*of\s*Mfg|PKD)[\s\.:]*([0-9]{1,2}[\/\-\.][0-9]{2,4}|[A-Za-z]{3,9}\s*['\-]?[0-9]{2,4})",
            r"\b(0[1-9]|1[0-2])[\/\-\.](20[2-3][0-9]|[2-3][0-9])\b",
        ]
        for pattern in mfg_date_patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                manufacturing_date = match.group(1).strip()
                break

    expiry_date: str | None = None
    shelf_life_patterns = [
        r"(?:Use\s*before|Best\s*before|Expiry|Exp\s*Date|Exp)[\s\.:]*([0-9]+\s*months?[^\n\.]*|[0-9]{1,2}[\/\-\.][0-9]{2,4}|[A-Za-z]{3,9}\s*[0-9]{2,4})",
        r"(?:Use\s*before\s*[0-9]+\s*months\s*from\s*(?:date\s*of\s*)?(?:mfg|manufacturing))",
    ]
    for pattern in shelf_life_patterns:
        match = re.search(pattern, full_text, re.IGNORECASE)
        if match:
            expiry_date = match.group(0).strip()
            break

    manufacturer_name: str | None = None
    manufacturer_address: str | None = None
    mfg_patterns = [
        r"(?:Manufactured\s*by|Mfg\s*by|Marketed\s*by|Packed\s*by|Made\s*by)[\s\.:]*([^\n,]+(?:Limited|Ltd|Pvt|Private|Inc|LLP|Industries|Laboratories|Pharma|Health|Care|Herbals)?)",
        r"\b([A-Z][A-Za-z0-9\s&]+(?:Limited|Ltd|Pvt|Private|LLP|Corporation))\b",
    ]
    for pattern in mfg_patterns:
        match = re.search(pattern, full_text)
        if match:
            candidate_mfg = match.group(1).strip()
            if len(candidate_mfg) > 3 and not re.search(r"(?:MRP|Net|Qty|USP|Date)", candidate_mfg, re.IGNORECASE):
                manufacturer_name = candidate_mfg
                break

    address_match = re.search(
        r"([A-Za-z0-9\s,\-\/]+(?:State|District|Road|Plot|Village|Tehsil|Phase|Industrial Area|Sector)?[A-Za-z0-9\s,\-]+\b[1-8][0-9]{5}\b)",
        full_text,
    )
    if address_match:
        manufacturer_address = address_match.group(1).strip()
    elif manufacturer_name:
        for i, line in enumerate(lines):
            if manufacturer_name in line and i + 1 < len(lines):
                manufacturer_address = lines[i + 1].strip()
                break

    country_of_origin: str | None = None
    origin_patterns = [
        r"(?:Country\s*of\s*Origin|Made\s*in|Product\s*of|Origin)[\s\.:]*([A-Za-z]+)",
        r"\b(Made\s*in\s*India|Product\s*of\s*India)\b",
    ]
    for pattern in origin_patterns:
        match = re.search(pattern, full_text, re.IGNORECASE)
        if match:
            country_of_origin = match.group(1).strip() if match.lastindex else match.group(0).strip()
            break

    INDIAN_STATES_REGEX = r"\b(Maharashtra|Himachal\s*Pradesh|Karnataka|Gujarat|Tamil\s*Nadu|Delhi|Uttar\s*Pradesh|Haryana|Punjab|Rajasthan|Madhya\s*Pradesh|Kerala|West\s*Bengal|Telangana|Andhra\s*Pradesh|Uttarakhand|Goa|Assam|Bihar|Jharkhand|Odisha)\b"
    if not country_of_origin:
        if (
            re.search(r"\bIndia\b", full_text, re.IGNORECASE)
            or re.search(INDIAN_STATES_REGEX, full_text, re.IGNORECASE)
            or re.search(r"\b[1-8][0-9]{5}\b", full_text)
        ):
            country_of_origin = "India"

    consumer_care_phone: str | None = None
    consumer_care_email: str | None = None

    phone_match = re.search(
        r"\b(1800[\-\s]?[0-9]{3,4}[\-\s]?[0-9]{3,5}|(?:\+?91[\-\s]?)?[6-9][0-9]{9})\b", full_text
    )
    if phone_match:
        consumer_care_phone = phone_match.group(1).strip()

    email_match = re.search(r"\b([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)\b", full_text)
    if email_match:
        consumer_care_email = email_match.group(1).strip()

    is_dual_price_or_sticker = False
    mrp_matches = re.findall(
        r"(?:MRP|M\.R\.P\.|₹|Rs\.)[\s:]*([0-9]+(?:\.[0-9]{2})?)", full_text, re.IGNORECASE
    )
    if len(set(mrp_matches)) > 1:
        is_dual_price_or_sticker = True
    if re.search(r"(?:overprinted|sticker|revised\s*mrp|dual\s*price)", full_text, re.IGNORECASE):
        is_dual_price_or_sticker = True

    return ExtractedPackageDeclarations(
        mrp=mrp,
        mrp_raw_text=mrp_raw_text,
        mrp_conflict=False,
        has_inclusive_of_taxes=has_inclusive_of_taxes,
        net_quantity_value=net_quantity_value,
        net_quantity_unit=net_quantity_unit,
        net_quantity_raw_text=net_quantity_raw_text,
        is_standard_unit_symbol=is_standard_unit_symbol,
        declared_usp=declared_usp,
        declared_usp_unit=declared_usp_unit,
        calculated_usp=calculated_usp,
        usp_discrepancy_percent=usp_discrepancy_percent,
        manufacturer_name=manufacturer_name,
        manufacturer_address=manufacturer_address,
        country_of_origin=country_of_origin,
        manufacturing_date=manufacturing_date,
        expiry_date=expiry_date,
        consumer_care_phone=consumer_care_phone,
        consumer_care_email=consumer_care_email,
        barcode=barcode,
        is_dual_price_or_sticker_detected=is_dual_price_or_sticker,
    )


def extract_bounding_boxes_and_font_height(
    ocr_results: list[Any],
) -> tuple[float | None, float | None, float | None, float | None]:
    """Compute numeral box metrics from normalized PaddleOCR polygons."""
    numeral_heights: list[float] = []
    numeral_widths: list[float] = []
    barcode_width = None
    barcode_height = None

    if not ocr_results:
        return None, None, None, None

    for item in ocr_results:
        if not item or len(item) < 2:
            continue

        box = item[0]
        text = str(item[1])

        try:
            if len(box) < 4:
                continue
            h = abs(float(box[2][1]) - float(box[0][1]))
            w = abs(float(box[1][0]) - float(box[0][0]))
        except (IndexError, TypeError, ValueError):
            continue

        if re.search(r"\d", text):
            clean_text = re.sub(r"\s+", "", text)
            char_count = max(len(clean_text), 1)
            char_w = w / char_count
            numeral_heights.append(h)
            numeral_widths.append(char_w)

    avg_h = sum(numeral_heights) / len(numeral_heights) if numeral_heights else None
    avg_w = sum(numeral_widths) / len(numeral_widths) if numeral_widths else None

    return barcode_width, barcode_height, avg_h, avg_w


def merge_declarations(
    declarations_list: list[ExtractedPackageDeclarations],
) -> ExtractedPackageDeclarations:
    """Merge declarations extracted across multiple package photo angles."""
    if not declarations_list:
        return ExtractedPackageDeclarations()

    merged = declarations_list[0].model_copy(deep=True)

    for d in declarations_list[1:]:
        if not merged.barcode and d.barcode:
            merged.barcode = d.barcode

        if merged.mrp is None and d.mrp is not None:
            merged.mrp = d.mrp
            merged.mrp_raw_text = d.mrp_raw_text
        elif (
            merged.mrp is not None
            and d.mrp is not None
            and merged.mrp != d.mrp
        ):
            merged.mrp_conflict = True

        if d.mrp_conflict:
            merged.mrp_conflict = True

        if not merged.has_inclusive_of_taxes and d.has_inclusive_of_taxes:
            merged.has_inclusive_of_taxes = True

        if merged.net_quantity_value is None and d.net_quantity_value is not None:
            merged.net_quantity_value = d.net_quantity_value
            merged.net_quantity_unit = d.net_quantity_unit
            merged.net_quantity_raw_text = d.net_quantity_raw_text
            merged.is_standard_unit_symbol = d.is_standard_unit_symbol

        if merged.declared_usp is None and d.declared_usp is not None:
            merged.declared_usp = d.declared_usp
            merged.declared_usp_unit = d.declared_usp_unit

        if not merged.manufacturer_name and d.manufacturer_name:
            merged.manufacturer_name = d.manufacturer_name
        if not merged.manufacturer_address and d.manufacturer_address:
            merged.manufacturer_address = d.manufacturer_address
        if not merged.country_of_origin and d.country_of_origin:
            merged.country_of_origin = d.country_of_origin
        if not merged.manufacturing_date and d.manufacturing_date:
            merged.manufacturing_date = d.manufacturing_date
        if not merged.expiry_date and d.expiry_date:
            merged.expiry_date = d.expiry_date
        if not merged.consumer_care_phone and d.consumer_care_phone:
            merged.consumer_care_phone = d.consumer_care_phone
        if not merged.consumer_care_email and d.consumer_care_email:
            merged.consumer_care_email = d.consumer_care_email
        if d.is_dual_price_or_sticker_detected:
            merged.is_dual_price_or_sticker_detected = True

    if (
        merged.mrp is not None
        and merged.net_quantity_value is not None
        and merged.net_quantity_value > 0
    ):
        merged.calculated_usp = round(merged.mrp / merged.net_quantity_value, 2)
        if merged.declared_usp is not None and merged.declared_usp > 0:
            diff = abs(merged.declared_usp - merged.calculated_usp)
            merged.usp_discrepancy_percent = round(
                (diff / merged.calculated_usp) * 100.0,
                2,
            )

    return merged
