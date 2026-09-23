"""
@file routes_ocr.py
@description PaddleOCR PP-OCR text inference endpoints.
Accepts image uploads via JSON body (Base64 data URL) or multipart/form-data,
runs CPU PaddleOCR inference, and returns extracted text, bounding metrics, and declarations.
"""

import base64
import io
import json
import time
from collections.abc import Iterable
from typing import Any

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from paddleocr import PaddleOCR
from PIL import Image

from app.engine.calibration import calibrate_optical_metrics
from app.engine.ocr_parser import (
    extract_bounding_boxes_and_font_height,
    extract_declarations_from_text,
)
from app.schemas import ExtractedPackageDeclarations

router = APIRouter(prefix="/api/ocr", tags=["OCR Engine"])

# PaddleOCR 3.x with PaddlePaddle CPU inference.
# Models are downloaded on first use and then cached by PaddleOCR.
ocr_engine = PaddleOCR(
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
    engine="paddle",
)


def _to_python(value: Any) -> Any:
    """Convert numpy/Paddle values to normal Python containers when possible."""
    if hasattr(value, "tolist"):
        return value.tolist()
    return value


def _extract_paddle_result(result: Any) -> list[list[Any]]:
    """
    Normalize PaddleOCR 3.x output to the internal format expected by the parser:

        [
            [bbox_polygon, text, confidence],
            ...
        ]

    PaddleOCR 3.x prediction results expose rec_texts, rec_scores and
    rec_polys/dt_polys on each result object. This adapter isolates the rest of
    Niyamit from PaddleOCR's result-object API.
    """
    normalized: list[list[Any]] = []

    if isinstance(result, (list, tuple)):
        pages = list(result)
    elif hasattr(result, "json") or isinstance(result, dict):
        pages = [result]
    elif isinstance(result, Iterable) and not isinstance(result, (str, bytes)):
        pages = list(result)
    else:
        pages = [result]

    for page_result in pages:
        if page_result is None:
            continue

        payload = getattr(page_result, "json", None)
        if callable(payload):
            payload = payload()
        elif payload is not None:
            payload = payload
        elif isinstance(page_result, dict):
            payload = page_result
        else:
            payload = {}

        if isinstance(payload, str):
            payload = json.loads(payload)

        if not isinstance(payload, dict):
            continue

        data = payload.get("res", payload)
        if not isinstance(data, dict):
            continue

        texts = _to_python(data.get("rec_texts", [])) or []
        scores = _to_python(data.get("rec_scores", [])) or []
        boxes = _to_python(
            data.get("rec_polys", data.get("dt_polys", []))
        ) or []

        for index, text in enumerate(texts):
            if text is None:
                continue

            bbox = boxes[index] if index < len(boxes) else []
            score = scores[index] if index < len(scores) else 0.0

            normalized.append([
                bbox,
                str(text),
                float(score),
            ])

    return normalized


def process_cv_image(
    img: Image.Image,
    barcode: str | None = None,
) -> dict[str, Any]:
    """Run PaddleOCR and convert its result into Niyamit's internal OCR format."""
    img_rgb = img.convert("RGB")
    np_img = np.asarray(img_rgb)
    width, _height = img.size

    start_time = time.perf_counter()
    result = ocr_engine.predict(np_img)
    inference_time = time.perf_counter() - start_time

    ocr_results = _extract_paddle_result(result)
    lines = [item[1] for item in ocr_results]
    raw_text = "\n".join(lines)

    b_width, b_height, avg_numeral_h, avg_numeral_w = (
        extract_bounding_boxes_and_font_height(ocr_results)
    )

    declarations = extract_declarations_from_text(
        raw_text,
        detected_barcode=barcode,
    )

    calibration = calibrate_optical_metrics(
        barcode_width_px=b_width,
        barcode_height_px=b_height,
        numeral_box_height_px=avg_numeral_h,
        numeral_box_width_px=avg_numeral_w,
        image_width_px=width,
    )

    return {
        "rawText": raw_text,
        "raw_text": raw_text,
        "lineCount": len(lines),
        "detectedNumeralHeightPx": (
            round(avg_numeral_h, 1) if avg_numeral_h else 24.0
        ),
        "declarations": declarations.model_dump(by_alias=True),
        "calibration": calibration.model_dump(by_alias=True),
        "inferenceTimeSeconds": round(inference_time, 3),
        "ocrResults": ocr_results,
    }


@router.post("")
async def run_ocr(
    request: Request,
    file: UploadFile | None = File(None),
    image_base64: str | None = Form(None),
    barcode: str | None = Form(None),
):
    """
    Packaging OCR inference endpoint.

    Accepts:
    1. JSON: {"imageBase64": "data:image/jpeg;base64,...", "barcode": "..."}
    2. JSON multi-shot: {"images": ["data:image/...;base64,...", ...]}
    3. Multipart: file or form data (image_base64, barcode)
    """
    try:
        clean_barcode = barcode
        img_bytes: bytes | None = None
        content_type = request.headers.get("content-type", "")

        if "application/json" in content_type:
            body = await request.json()
            if not isinstance(body, dict):
                raise HTTPException(status_code=400, detail="JSON body must be an object")

            images_list = body.get("images") or []
            raw_b64 = body.get("imageBase64") or body.get("image_base64")
            clean_barcode = body.get("barcode", clean_barcode)

            if images_list and isinstance(images_list, list) and len(images_list) > 1:
                from app.engine.ocr_parser import merge_declarations

                combined_texts: list[str] = []
                declarations_list: list[ExtractedPackageDeclarations] = []
                total_lines = 0
                max_numeral_h = 24.0

                for img_item in images_list:
                    if not isinstance(img_item, str):
                        raise HTTPException(
                            status_code=400,
                            detail="Each item in 'images' must be a base64 string",
                        )

                    if "," in img_item:
                        img_item = img_item.split(",", 1)[1]

                    item_bytes = base64.b64decode(img_item, validate=True)
                    sub_img = Image.open(io.BytesIO(item_bytes))
                    sub_res = process_cv_image(sub_img, barcode=clean_barcode)

                    combined_texts.append(sub_res["rawText"])
                    total_lines += sub_res["lineCount"]
                    max_numeral_h = max(
                        max_numeral_h,
                        sub_res.get("detectedNumeralHeightPx", 24.0),
                    )
                    declarations_list.append(
                        ExtractedPackageDeclarations(**sub_res["declarations"])
                    )

                merged_decl = merge_declarations(declarations_list)
                combined_raw = "\n---\n".join(combined_texts)

                return {
                    "rawText": combined_raw,
                    "raw_text": combined_raw,
                    "lineCount": total_lines,
                    "detectedNumeralHeightPx": max_numeral_h,
                    "declarations": merged_decl.model_dump(by_alias=True),
                    "calibration": calibrate_optical_metrics().model_dump(by_alias=True),
                    "isMultiShot": True,
                    "shotCount": len(images_list),
                }

            if not raw_b64 and images_list:
                raw_b64 = images_list[0]

            if not raw_b64:
                raise HTTPException(
                    status_code=400,
                    detail="Missing 'imageBase64' or 'images' in JSON payload",
                )

            if "," in raw_b64:
                raw_b64 = raw_b64.split(",", 1)[1]

            img_bytes = base64.b64decode(raw_b64, validate=True)

        elif file:
            img_bytes = await file.read()

        elif image_base64:
            clean_b64 = image_base64
            if "," in clean_b64:
                clean_b64 = clean_b64.split(",", 1)[1]
            img_bytes = base64.b64decode(clean_b64, validate=True)

        else:
            raise HTTPException(
                status_code=400,
                detail="No image file or imageBase64 data provided",
            )

        if not img_bytes:
            raise HTTPException(status_code=400, detail="Image data is empty")

        img = Image.open(io.BytesIO(img_bytes))
        img.load()
        return process_cv_image(img, barcode=clean_barcode)

    except HTTPException:
        raise
    except (ValueError, UnicodeDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"Invalid image/base64 data: {e!s}") from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"OCR inference failed: {e!s}") from e
