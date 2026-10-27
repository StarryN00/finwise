"""Bake the OCR variants used by local_pdf_ocr into read-only task images."""
from rapidocr import RapidOCR, ModelType, OCRVersion, LangRec

for language in (LangRec.CH, LangRec.EN):
    RapidOCR(params={
        'Det.ocr_version': OCRVersion.PPOCRV4, 'Det.model_type': ModelType.MOBILE,
        'Rec.ocr_version': OCRVersion.PPOCRV4, 'Rec.model_type': ModelType.MOBILE,
        'Rec.lang_type': language,
        'EngineConfig.onnxruntime.intra_op_num_threads': 2,
        'EngineConfig.onnxruntime.inter_op_num_threads': 2,
        'Global.log_level': 'warning',
    })
print('Chinese and numeric OCR models are ready')
