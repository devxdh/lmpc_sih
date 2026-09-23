"""
@file schemas.py
@description Pydantic models and data schemas for Legal Metrology Packaged Commodities (LMPC).
Defines strict statutory validation schemas for measurements, declarations, and inspection dossiers.
Supports automatic bidirectional camelCase (for Next.js/TypeScript frontend) and snake_case (for Python).
"""

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

ComplianceStatus = Literal["PASS", "FAIL", "WARNING"]
OverallInspectionStatus = Literal["COMPLIANT", "NON_COMPLIANT", "INCOMPLETE_DECLARATION"]
RuleSeverity = Literal["CRITICAL", "MAJOR", "MINOR"]


def _camel_to_snake(data: Any) -> Any:
    if isinstance(data, dict):
        new_dict = {}
        for k, v in data.items():
            clean_k = (
                k.replace("USP", "Usp")
                .replace("MRP", "Mrp")
                .replace("PDP", "Pdp")
                .replace("GTIN", "Gtin")
            )
            snake_k = re.sub(r"(?<!^)(?=[A-Z])", "_", clean_k).lower()
            new_dict[snake_k] = _camel_to_snake(v)
        return new_dict
    elif isinstance(data, list):
        return [_camel_to_snake(i) for i in data]
    return data


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True, extra="ignore"
    )


class PhysicalCalibrationMetrics(CamelModel):
    """
    Physical optical scale and font height metrics calibrated using standard GS1 EAN-13 fiducial.
    Nominal GS1 barcode width is 37.29 mm.
    """

    barcode_width_px: float = Field(
        default=380.0, description="Width of detected barcode in pixels"
    )
    barcode_height_px: float = Field(
        default=260.0, description="Height of detected barcode in pixels"
    )
    mm_per_pixel: float = Field(
        default=0.098, description="Calculated optical scale factor in mm/pixel"
    )
    pdp_area_cm2: float = Field(
        default=100.0, description="Principal Display Panel area in square centimeters"
    )
    measured_numeral_height_mm: float = Field(
        default=2.5, description="Measured font height of numerals in mm"
    )
    measured_numeral_width_mm: float = Field(
        default=1.2, description="Measured font width of numerals in mm"
    )
    mandated_min_height_mm: float = Field(
        default=2.0, description="Mandatory minimum numeral height per Rule 7 Table-I"
    )
    is_font_height_compliant: bool = Field(
        default=True, description="Whether font height satisfies Rule 7 Table-I"
    )
    width_to_height_ratio: float = Field(
        default=0.48, description="Width-to-height ratio of characters (must be >= 0.33)"
    )

    @model_validator(mode="before")
    @classmethod
    def convert_camel_case(cls, data: Any) -> Any:
        return _camel_to_snake(data)


class ExtractedPackageDeclarations(CamelModel):
    """
    Statutory mandatory declarations extracted from the packaging label under Rule 6.
    """

    mrp: float | None = Field(None, description="Maximum Retail Price in INR (Rule 6(1)(e))")
    mrp_conflict: bool | None = Field(False, description="In case of different MRP in front declaration and back declarations.")
    mrp_raw_text: str | None = None
    has_inclusive_of_taxes: bool = Field(
        False, description="Presence of 'inclusive of all taxes' clause"
    )
    net_quantity_value: float | None = Field(None, description="Net quantity value (e.g. 100)")
    net_quantity_unit: str | None = Field(None, description="Net quantity unit (e.g. 'ml', 'g')")
    net_quantity_raw_text: str | None = None
    is_standard_unit_symbol: bool = Field(
        False, description="Whether unit symbol strictly complies with Rule 12 SI standards"
    )
    declared_usp: float | None = Field(
        None, description="Unit Sale Price declared on packaging (Rule 6(11))"
    )
    declared_usp_unit: str | None = Field(
        None, description="Declared USP unit (e.g. 'per ml', 'per g')"
    )
    calculated_usp: float | None = Field(
        None, description="Theoretical calculated USP = MRP / Net Quantity"
    )
    usp_discrepancy_percent: float | None = Field(
        None, description="Percentage discrepancy between declared and calculated USP"
    )
    manufacturer_name: str | None = Field(
        None, description="Manufacturer, packer, or marketer name (Rule 6(1)(a))"
    )
    manufacturer_address: str | None = Field(
        None, description="Complete registered physical address"
    )
    country_of_origin: str | None = Field(
        None, description="Country of Origin (Rule 6(1)(b) & 2026 Amendment)"
    )
    manufacturing_date: str | None = Field(
        None,
        description="Month & year of manufacture / packing or embossed crimp notice (Rule 6(1)(d))",
    )
    expiry_date: str | None = Field(None, description="Best before or expiry period")
    consumer_care_phone: str | None = Field(
        None, description="Customer care helpline / toll-free number (Rule 6(1)(f))"
    )
    consumer_care_email: str | None = Field(
        None, description="Customer care grievance email address"
    )
    barcode: str | None = Field(None, description="13-digit GS1 EAN/UPC barcode number")
    is_dual_price_or_sticker_detected: bool = Field(
        False, description="Flag for sticker alteration / dual pricing under Section 36"
    )

    @model_validator(mode="before")
    @classmethod
    def convert_camel_case(cls, data: Any) -> Any:
        return _camel_to_snake(data)


class StatutoryRuleEvaluation(CamelModel):
    """
    Legal Metrology statutory evaluation result for an individual statutory provision.
    """

    id: str
    title: str
    statutory_reference: str = Field(default="", description="Statutory Act or Rule reference")
    status: ComplianceStatus
    explanation: str
    observed_value: str = Field(default="", description="Observed declaration on package")
    mandated_requirement: str = Field(default="", description="Statutory mandate requirement")
    severity: RuleSeverity = Field(default="MAJOR")
    penalty_clause: str | None = None

    @model_validator(mode="before")
    @classmethod
    def convert_camel_case(cls, data: Any) -> Any:
        return _camel_to_snake(data)


class GS1ProductRecord(CamelModel):
    """
    Official manufacturer packaging record from the GS1 India DataKart Master Registry.
    """

    gtin: str
    brand_name: str
    product_name: str
    company_name: str
    category: str
    registered_net_qty: str
    registered_mrp: float
    is_lmpc_registered: bool = True

    @model_validator(mode="before")
    @classmethod
    def convert_camel_case(cls, data: Any) -> Any:
        return _camel_to_snake(data)


class InspectionDossier(CamelModel):
    """
    Complete statutory inspection report and legal dossier stored in PostgreSQL for enforcement and court filings.
    """

    audit_id: str
    timestamp: str
    inspector_id: str
    inspection_location: str
    image_url: str | None = None
    overall_status: OverallInspectionStatus
    critical_violations_count: int
    evaluations: list[StatutoryRuleEvaluation]
    calibration: PhysicalCalibrationMetrics | None = None
    declarations: ExtractedPackageDeclarations
    gs1_record: GS1ProductRecord | None = None
    legal_notice_draft: str | None = None

    @model_validator(mode="before")
    @classmethod
    def convert_camel_case(cls, data: Any) -> Any:
        return _camel_to_snake(data)


class AuditRequestPayload(CamelModel):
    sample_id: str | None = None
    raw_text: str | None = None
    barcode: str | None = None
    image_url: str | None = None
    custom_declarations: ExtractedPackageDeclarations | None = None
    custom_calibration: dict | None = None
    inspector_id: str = "INS-LMPC-DL-402"
    inspection_location: str = "Retail Inspection, Connaught Place, New Delhi"

    @model_validator(mode="before")
    @classmethod
    def convert_camel_case(cls, data: Any) -> Any:
        return _camel_to_snake(data)


UserRole = Literal["CONSUMER", "OFFICER", "ADMIN"]


class UserRegisterRequest(CamelModel):
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=6, description="Password (minimum 6 characters)")
    full_name: str = Field(..., description="Full name of consumer or officer")
    role: UserRole = Field(default="CONSUMER", description="User statutory role")
    organization: str | None = Field(default=None, description="Department, NGO, or business")
    badge_number: str | None = Field(default=None, description="Official LMPC Inspector badge ID")


class UserLoginRequest(CamelModel):
    email: str = Field(..., description="User email address")
    password: str = Field(..., description="Password")


class UserResponse(CamelModel):
    id: str
    email: str
    full_name: str
    role: UserRole
    organization: str | None = None
    badge_number: str | None = None
    created_at: str | None = None


class TokenResponse(CamelModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = 43200  # 12-hour inspection shift in seconds
    user: UserResponse


