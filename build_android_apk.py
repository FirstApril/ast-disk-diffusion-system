#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
สคริปต์สร้างไฟล์ติดตั้งแอปพลิเคชัน Android (.apk) แบบทำงานในโทรศัพท์ 100% (100% On-Device ML — ไม่ต้องต่อ API)
รองรับระบบปฏิบัติการ CachyOS / Arch Linux (รวมถึง Ubuntu / macOS / Windows)
สำหรับระบบวิเคราะห์ความไวต่อยาปฏิชีวนะ (AST Disk Diffusion System — CLSI M100 / EUCAST)

สถาปัตยกรรม Machine Learning ที่รันในโทรศัพท์โดยตรง (ไม่ต้องพึ่งพาเซิร์ฟเวอร์หรืออินเทอร์เน็ต):
1. จุดที่ 1 (การตรวจจับแผ่นยาบนเครื่อง):
   - ค้นหาโมเดล `YOLO26n` ที่เทรนแล้ว (`runs/detect/runs_disc/train_yolo26n/weights/best.pt` หรือ `train_yolo26s`)
   - แปลงเป็นไฟล์ `assets/models/yolo26n_disc.onnx` ด้วย PyTorch (`torch.onnx.export`) โดยตรง
     (ไม่ติดปัญหา PEP 668 Externally-Managed Environment บน CachyOS / Arch Linux)
   - รันโมเดล `YOLO26n` ในโทรศัพท์ผ่านเอนจิน `com.microsoft.onnxruntime:onnxruntime-android:1.18.0`
2. จุดที่ 2 (การวัดขนาดวงยับยั้งเชื้อบนเครื่อง):
   - รันอัลกอริทึม `Continuous Warp Polar Transform` 360 องศา พร้อมการตรวจจับขอบจานเพาะเชื้ออัตโนมัติ
3. จุดที่ 3 (การอ่านรหัสยาบนเครื่อง):
   - ผสาน `Underline Bar & Two-Row Bimodal Orientation Alignment` + `3-Variant Circular Preprocessing
     (2D Integral-Image CLAHE, Contrast Stretch, 25x25 Adaptive Gaussian Threshold)` +
     `On-Device Connected-Component Glyph & Topological Recognizer` + `On-Device ML Kit` + `Hungarian Assignment`
4. ระบบเลือกตำแหน่งบันทึกไฟล์ส่งออก (Native Android Storage Access Framework `ACTION_CREATE_DOCUMENT` + `MediaStore`):
   - เปิดหน้าต่างระบบ Android ให้เลือกโฟลเดอร์ที่จะบันทึกไฟล์ (`.csv`, `.xls`, `.json`, `.md`) หรือบันทึกลงโฟลเดอร์ `Downloads` / `Documents` ได้ทันที
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
FLUTTER_DIR = PROJECT_ROOT / "ast_flutter_app"
OUTPUT_APK_PATH = PROJECT_ROOT / "AST_Disk_Diffusion_System.apk"

LOCAL_SDK_BASE = Path.home() / ".local" / "share" / "ast_mobile_sdk"
LOCAL_FLUTTER_DIR = LOCAL_SDK_BASE / "flutter"
LOCAL_ANDROID_SDK_DIR = LOCAL_SDK_BASE / "android-sdk"

CMDLINE_TOOLS_LINUX_URL = (
    "https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip"
)

UPGRADED_PUBSPEC_YAML = """name: ast_flutter_app
description: Antimicrobial Susceptibility Testing (AST) 100% On-Device ML System (CLSI M100 / EUCAST)
publish_to: 'none'
version: 2.3.0+5

environment:
  sdk: '>=3.2.0 <4.0.0'

dependencies:
  flutter:
    sdk: flutter

  image: ^4.1.7
  image_picker: ^1.0.7
  google_mlkit_text_recognition: ^0.13.0
  path_provider: ^2.1.3
  http: ^1.2.1

dev_dependencies:
  flutter_test:
    sdk: flutter
  flutter_lints: ^3.0.0

flutter:
  uses-material-design: true
  assets:
    - assets/models/
"""

PROGUARD_RULES_CONTENT = """# Keep rules & dontwarn for On-Device ML Kit & ONNX Runtime (YOLO26n)
-dontwarn com.google.mlkit.vision.text.chinese.**
-dontwarn com.google.mlkit.vision.text.devanagari.**
-dontwarn com.google.mlkit.vision.text.japanese.**
-dontwarn com.google.mlkit.vision.text.korean.**
-keep class com.google.mlkit.** { *; }
-keep class com.google_mlkit_text_recognition.** { *; }
-keep class com.google_mlkit_commons.** { *; }
-keep class ai.onnxruntime.** { *; }
-dontwarn ai.onnxruntime.**
"""

MAIN_ACTIVITY_KT_TEMPLATE = """package __PACKAGE_NAME__

import android.app.Activity
import android.content.ContentValues
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import java.io.File
import java.io.FileOutputStream
import java.nio.FloatBuffer
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sqrt

class MainActivity : FlutterActivity() {
    private val CHANNEL = "org.clinical.ast/yolo26n"
    private val REQ_CREATE_DOCUMENT = 9401
    private var cachedSession: OrtSession? = null
    private var cachedModelPath: String? = null
    private var pendingSaveResult: MethodChannel.Result? = null
    private var pendingSaveBytes: ByteArray? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, CHANNEL).setMethodCallHandler { call, result ->
            when (call.method) {
                "detectDiscsYolo" -> {
                    val modelPath = call.argument<String>("modelPath")
                    val imageBytes = call.argument<ByteArray>("imageBytes")
                    val confThreshold = call.argument<Double>("confThreshold")?.toFloat() ?: 0.22f
                    if (modelPath == null || imageBytes == null) {
                        result.error("INVALID_ARGS", "Missing modelPath or imageBytes", null)
                        return@setMethodCallHandler
                    }
                    Thread {
                        try {
                            val detections = runYoloOnnx(modelPath, imageBytes, confThreshold)
                            runOnUiThread {
                                result.success(detections)
                            }
                        } catch (e: Exception) {
                            runOnUiThread {
                                result.error("ORT_ERROR", e.message ?: "ONNX inference error", null)
                            }
                        }
                    }.start()
                }
                "saveFileWithPicker" -> {
                    val fileName = call.argument<String>("fileName") ?: "ast_export.csv"
                    val mimeType = call.argument<String>("mimeType") ?: "text/csv"
                    val fileBytes = call.argument<ByteArray>("fileBytes")
                    if (fileBytes == null) {
                        result.error("INVALID_ARGS", "Missing fileBytes", null)
                        return@setMethodCallHandler
                    }
                    pendingSaveResult = result
                    pendingSaveBytes = fileBytes
                    try {
                        val intent = Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                            addCategory(Intent.CATEGORY_OPENABLE)
                            type = mimeType
                            putExtra(Intent.EXTRA_TITLE, fileName)
                        }
                        startActivityForResult(intent, REQ_CREATE_DOCUMENT)
                    } catch (e: Exception) {
                        pendingSaveResult = null
                        pendingSaveBytes = null
                        result.error("PICKER_ERROR", e.message ?: "Cannot open file picker", null)
                    }
                }
                "saveFileToPublicFolder" -> {
                    val folderMode = call.argument<String>("folderMode") ?: "downloads"
                    val customDirPath = call.argument<String>("customDirPath") ?: ""
                    val fileName = call.argument<String>("fileName") ?: "ast_export.csv"
                    val mimeType = call.argument<String>("mimeType") ?: "text/csv"
                    val fileBytes = call.argument<ByteArray>("fileBytes")
                    if (fileBytes == null) {
                        result.error("INVALID_ARGS", "Missing fileBytes", null)
                        return@setMethodCallHandler
                    }
                    try {
                        val savedPath = saveBytesToFolder(folderMode, customDirPath, fileName, mimeType, fileBytes)
                        result.success(savedPath)
                    } catch (e: Exception) {
                        result.error("SAVE_ERROR", e.message ?: "Cannot save file", null)
                    }
                }
                else -> result.notImplemented()
            }
        }
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == REQ_CREATE_DOCUMENT) {
            val res = pendingSaveResult
            val bytes = pendingSaveBytes
            pendingSaveResult = null
            pendingSaveBytes = null
            if (res == null) return
            if (resultCode == Activity.RESULT_OK && data?.data != null && bytes != null) {
                try {
                    val uri = data.data!!
                    contentResolver.openOutputStream(uri)?.use { out ->
                        out.write(bytes)
                        out.flush()
                    }
                    res.success(uri.path ?: uri.toString())
                } catch (e: Exception) {
                    res.error("WRITE_ERROR", e.message ?: "Cannot write to chosen URI", null)
                }
            } else {
                res.success("CANCELED")
            }
        }
    }

    private fun saveBytesToFolder(
        folderMode: String,
        customDirPath: String,
        fileName: String,
        mimeType: String,
        fileBytes: ByteArray
    ): String {
        if (folderMode == "custom" && customDirPath.isNotBlank()) {
            val dir = File(customDirPath.trim())
            if (!dir.exists()) dir.mkdirs()
            val outFile = File(dir, fileName)
            FileOutputStream(outFile).use { it.write(fileBytes) }
            return outFile.absolutePath
        }

        val relDir = if (folderMode == "documents") {
            Environment.DIRECTORY_DOCUMENTS
        } else {
            Environment.DIRECTORY_DOWNLOADS
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val values = ContentValues().apply {
                put(MediaStore.MediaColumns.DISPLAY_NAME, fileName)
                put(MediaStore.MediaColumns.MIME_TYPE, mimeType)
                put(MediaStore.MediaColumns.RELATIVE_PATH, relDir)
            }
            val collectionUri = if (folderMode == "documents") {
                MediaStore.Files.getContentUri("external")
            } else {
                MediaStore.Downloads.EXTERNAL_CONTENT_URI
            }
            val itemUri = contentResolver.insert(collectionUri, values)
            if (itemUri != null) {
                contentResolver.openOutputStream(itemUri)?.use { out ->
                    out.write(fileBytes)
                    out.flush()
                }
                return "/storage/emulated/0/$relDir/$fileName"
            }
        }

        val pubDir = Environment.getExternalStoragePublicDirectory(relDir)
        if (!pubDir.exists()) pubDir.mkdirs()
        val outFile = File(pubDir, fileName)
        FileOutputStream(outFile).use { it.write(fileBytes) }
        return outFile.absolutePath
    }

    @Synchronized
    private fun getOrCreateSession(modelPath: String): OrtSession {
        if (cachedSession != null && cachedModelPath == modelPath) {
            return cachedSession!!
        }
        try {
            cachedSession?.close()
        } catch (_: Exception) {}
        val env = OrtEnvironment.getEnvironment()
        val opts = OrtSession.SessionOptions()
        opts.setIntraOpNumThreads(4)
        opts.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT)
        cachedSession = env.createSession(modelPath, opts)
        cachedModelPath = modelPath
        return cachedSession!!
    }

    private fun computeIoU(a: FloatArray, b: FloatArray): Float {
        val ax1 = a[0] - a[2] * 0.5f
        val ay1 = a[1] - a[3] * 0.5f
        val ax2 = a[0] + a[2] * 0.5f
        val ay2 = a[1] + a[3] * 0.5f

        val bx1 = b[0] - b[2] * 0.5f
        val by1 = b[1] - b[3] * 0.5f
        val bx2 = b[0] + b[2] * 0.5f
        val by2 = b[1] + b[3] * 0.5f

        val ix1 = max(ax1, bx1)
        val iy1 = max(ay1, by1)
        val ix2 = min(ax2, bx2)
        val iy2 = min(ay2, by2)

        val iw = max(0.0f, ix2 - ix1)
        val ih = max(0.0f, iy2 - iy1)
        val inter = iw * ih
        val areaA = max(1.0f, a[2] * a[3])
        val areaB = max(1.0f, b[2] * b[3])
        return inter / (areaA + areaB - inter)
    }

    private fun runYoloOnnx(
        modelPath: String,
        imageBytes: ByteArray,
        confThreshold: Float
    ): List<Map<String, Double>> {
        val bitmap = BitmapFactory.decodeByteArray(imageBytes, 0, imageBytes.size)
            ?: throw IllegalArgumentException("Cannot decode plate image bytes")

        val origW = bitmap.width.toFloat()
        val origH = bitmap.height.toFloat()
        val inputSize = 640
        val scale = min(inputSize.toFloat() / origW, inputSize.toFloat() / origH)
        val newW = (origW * scale).roundToInt()
        val newH = (origH * scale).roundToInt()
        val padX = (inputSize - newW) / 2.0f
        val padY = (inputSize - newH) / 2.0f

        val letterboxed = Bitmap.createBitmap(inputSize, inputSize, Bitmap.Config.ARGB_8888)
        val canvas = Canvas(letterboxed)
        canvas.drawColor(Color.rgb(114, 114, 114))
        val paint = Paint(Paint.FILTER_BITMAP_FLAG)
        val dstRect = RectF(padX, padY, padX + newW, padY + newH)
        canvas.drawBitmap(bitmap, null, dstRect, paint)

        val pixels = IntArray(inputSize * inputSize)
        letterboxed.getPixels(pixels, 0, inputSize, 0, 0, inputSize, inputSize)
        val area = inputSize * inputSize
        val floatValues = FloatArray(3 * area)
        for (i in 0 until area) {
            val c = pixels[i]
            floatValues[i] = ((c shr 16) and 0xFF) / 255.0f
            floatValues[area + i] = ((c shr 8) and 0xFF) / 255.0f
            floatValues[2 * area + i] = (c and 0xFF) / 255.0f
        }

        val env = OrtEnvironment.getEnvironment()
        val session = getOrCreateSession(modelPath)
        val inputName = session.inputNames.iterator().next()
        val inShape = longArrayOf(1, 3, inputSize.toLong(), inputSize.toLong())
        val inputTensor = OnnxTensor.createTensor(env, FloatBuffer.wrap(floatValues), inShape)

        val rawBoxes = mutableListOf<FloatArray>()

        inputTensor.use { tensor ->
            session.run(mapOf(inputName to tensor)).use { results ->
                val outValue = results[0] as OnnxTensor
                val outShape = outValue.info.shape
                val fb = outValue.floatBuffer
                val arr = FloatArray(fb.remaining())
                fb.get(arr)

                if (outShape.size == 3) {
                    val d1 = outShape[1].toInt()
                    val d2 = outShape[2].toInt()
                    if (d2 == 6 && d1 <= 1000) {
                        for (i in 0 until d1) {
                            val base = i * 6
                            val conf = arr[base + 4]
                            if (conf >= confThreshold) {
                                var v0 = arr[base + 0]
                                var v1 = arr[base + 1]
                                var v2 = arr[base + 2]
                                var v3 = arr[base + 3]
                                if (v2 <= 1.5f && v3 <= 1.5f && v0 <= 1.5f) {
                                    v0 *= inputSize
                                    v1 *= inputSize
                                    v2 *= inputSize
                                    v3 *= inputSize
                                }
                                val isXyxy = (v2 > v0) && (v3 > v1) &&
                                    (abs((v2 - v0) - (v3 - v1)) <= max(v2 - v0, v3 - v1) * 0.55f)
                                val bcx: Float
                                val bcy: Float
                                val bw: Float
                                val bh: Float
                                if (isXyxy) {
                                    bw = max(4.0f, v2 - v0)
                                    bh = max(4.0f, v3 - v1)
                                    bcx = (v0 + v2) * 0.5f
                                    bcy = (v1 + v3) * 0.5f
                                } else {
                                    bcx = v0
                                    bcy = v1
                                    bw = max(4.0f, v2)
                                    bh = max(4.0f, v3)
                                }
                                rawBoxes.add(floatArrayOf(bcx, bcy, bw, bh, conf))
                            }
                        }
                    } else if (d1 in 5..100 && d2 >= 1000) {
                        for (i in 0 until d2) {
                            var maxConf = 0.0f
                            for (c in 4 until d1) {
                                val s = arr[c * d2 + i]
                                if (s > maxConf) maxConf = s
                            }
                            if (maxConf >= confThreshold) {
                                var bcx = arr[0 * d2 + i]
                                var bcy = arr[1 * d2 + i]
                                var bw = arr[2 * d2 + i]
                                var bh = arr[3 * d2 + i]
                                if (bw <= 1.5f && bh <= 1.5f && bcx <= 1.5f) {
                                    bcx *= inputSize
                                    bcy *= inputSize
                                    bw *= inputSize
                                    bh *= inputSize
                                }
                                rawBoxes.add(floatArrayOf(bcx, bcy, bw, bh, maxConf))
                            }
                        }
                    } else if (d2 in 5..100 && d1 >= 1000) {
                        for (i in 0 until d1) {
                            val base = i * d2
                            var maxConf = 0.0f
                            for (c in 4 until d2) {
                                val s = arr[base + c]
                                if (s > maxConf) maxConf = s
                            }
                            if (maxConf >= confThreshold) {
                                var bcx = arr[base + 0]
                                var bcy = arr[base + 1]
                                var bw = arr[base + 2]
                                var bh = arr[base + 3]
                                if (bw <= 1.5f && bh <= 1.5f && bcx <= 1.5f) {
                                    bcx *= inputSize
                                    bcy *= inputSize
                                    bw *= inputSize
                                    bh *= inputSize
                                }
                                rawBoxes.add(floatArrayOf(bcx, bcy, bw, bh, maxConf))
                            }
                        }
                    }
                }
            }
        }

        rawBoxes.sortByDescending { it[4] }
        val kept = mutableListOf<FloatArray>()
        for (cand in rawBoxes) {
            var suppressed = false
            for (ex in kept) {
                val dx = cand[0] - ex[0]
                val dy = cand[1] - ex[1]
                val centerDist = sqrt(dx * dx + dy * dy)
                val minAllowedDist = min(cand[2], ex[2]) * 0.72f
                if (centerDist < minAllowedDist || computeIoU(cand, ex) > 0.45f) {
                    suppressed = true
                    break
                }
            }
            if (!suppressed) {
                kept.add(cand)
                if (kept.size >= 20) break
            }
        }

        val outputList = mutableListOf<Map<String, Double>>()
        for (b in kept) {
            val cxOrig = ((b[0] - padX) / scale).coerceIn(0.0f, origW - 1.0f)
            val cyOrig = ((b[1] - padY) / scale).coerceIn(0.0f, origH - 1.0f)
            val rxOrig = ((b[2] * 0.5f) / scale).coerceAtLeast(8.0f)
            val ryOrig = ((b[3] * 0.5f) / scale).coerceAtLeast(8.0f)
            val rOrig = ((rxOrig + ryOrig) * 0.5f).coerceAtLeast(8.0f)
            outputList.add(
                mapOf(
                    "cx" to cxOrig.toDouble(),
                    "cy" to cyOrig.toDouble(),
                    "r" to rOrig.toDouble(),
                    "rx" to rxOrig.toDouble(),
                    "ry" to ryOrig.toDouble(),
                    "conf" to b[4].toDouble()
                )
            )
        }
        return outputList
    }
}
"""


def find_source_file(filename: str) -> Path:
    candidates = [
        PROJECT_ROOT / filename,
        FLUTTER_DIR / "lib" / filename,
        FLUTTER_DIR / filename,
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError(
        f"ไม่พบไฟล์ {filename} ในโฟลเดอร์ {PROJECT_ROOT} กรุณาวางไฟล์ {filename} ไว้ในโฟลเดอร์เดียวกันกับสคริปต์นี้"
    )


def ensure_upgraded_pubspec() -> Path:
    pubspec_path = PROJECT_ROOT / "pubspec.yaml"
    pubspec_path.write_text(UPGRADED_PUBSPEC_YAML, encoding="utf-8")
    print(f"[OK] อัปเดต {pubspec_path.name} ให้ฝังโมเดล YOLO26n (assets/models/) ลงในโทรศัพท์เรียบร้อยแล้ว")
    return pubspec_path


def run_cmd(cmd: list[str], cwd: Path, input_text: str | None = None) -> None:
    print(f"\n[COMMAND] {' '.join(cmd)}")
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        input=input_text,
        text=True if input_text is not None else False,
        check=False,
        env=os.environ.copy(),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"คำสั่งทำงานไม่สำเร็จ (Exit code: {proc.returncode}): {' '.join(cmd)}")


def find_trained_yolo_weights() -> Path | None:
    explicit_candidates = [
        PROJECT_ROOT / "runs" / "detect" / "runs_disc" / "train_yolo26n" / "weights" / "best.pt",
        PROJECT_ROOT / "weights" / "yolo26n_best.pt",
        PROJECT_ROOT / "runs" / "detect" / "runs_disc" / "train_yolo26s" / "weights" / "best.pt",
        PROJECT_ROOT / "weights" / "best.pt",
        PROJECT_ROOT / "weights" / "yolo26s_best.pt",
        PROJECT_ROOT / "best.pt",
    ]
    for cand in explicit_candidates:
        if cand.is_file():
            return cand

    runs_dir = PROJECT_ROOT / "runs"
    if runs_dir.is_dir():
        all_best = sorted(runs_dir.glob("**/weights/best.pt"))
        for p in all_best:
            if "26n" in str(p).lower():
                return p
        if all_best:
            return all_best[0]

    fallback_pt = [
        PROJECT_ROOT / "weights" / "yolo26n.pt",
        PROJECT_ROOT / "yolo26n.pt",
        PROJECT_ROOT / "weights" / "yolo26s.pt",
        PROJECT_ROOT / "yolo26s.pt",
    ]
    for cand in fallback_pt:
        if cand.is_file():
            return cand

    return None


def find_python_with_ultralytics() -> str | None:
    candidates = [
        sys.executable,
        str(PROJECT_ROOT / ".venv" / "bin" / "python"),
        str(PROJECT_ROOT / "venv" / "bin" / "python"),
        str(PROJECT_ROOT.parent / ".venv" / "bin" / "python"),
        str(Path.home() / ".venv" / "bin" / "python"),
        "/usr/bin/python3",
    ]
    for conda_base in (
        Path.home() / "miniconda3" / "envs",
        Path.home() / "anaconda3" / "envs",
        Path.home() / "miniforge3" / "envs",
        Path.home() / ".conda" / "envs",
    ):
        if conda_base.is_dir():
            for env_py in sorted(conda_base.glob("*/bin/python")):
                candidates.append(str(env_py))

    seen = set()
    for py_bin in candidates:
        if not py_bin or py_bin in seen or not Path(py_bin).is_file():
            continue
        seen.add(py_bin)
        chk = subprocess.run(
            [py_bin, "-c", "import torch, ultralytics; print('OK')"],
            capture_output=True,
            text=True,
            check=False,
        )
        if chk.returncode == 0 and "OK" in chk.stdout:
            return py_bin
    return None


def export_yolo26n_to_onnx_asset(flutter_dir: Path) -> None:
    models_dir = flutter_dir / "assets" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    keep_file = models_dir / ".keep"
    if not keep_file.is_file():
        keep_file.write_text("AST On-Device Models Directory\n", encoding="utf-8")

    target_onnx = models_dir / "yolo26n_disc.onnx"
    cached_onnx = PROJECT_ROOT / "weights" / "yolo26n_disc.onnx"

    for existing_onnx in (
        PROJECT_ROOT / "yolo26n_disc.onnx",
        cached_onnx,
        PROJECT_ROOT / "runs" / "detect" / "runs_disc" / "train_yolo26n" / "weights" / "best.onnx",
        PROJECT_ROOT / "runs" / "detect" / "runs_disc" / "train_yolo26s" / "weights" / "best.onnx",
    ):
        if existing_onnx.is_file() and existing_onnx.stat().st_size > 100_000:
            shutil.copy2(existing_onnx, target_onnx)
            size_mb = target_onnx.stat().st_size / (1024 * 1024)
            print(f"[OK] พบไฟล์โมเดล ONNX พร้อมใช้งาน: {existing_onnx.name} ({size_mb:.2f} MB) -> ฝังลงแอปเรียบร้อยแล้ว")
            return

    pt_path = find_trained_yolo_weights()
    if pt_path is None:
        print("[INFO] ไม่พบไฟล์ .pt ในโปรเจกต์ จะใช้ระบบตรวจจับจานเพาะเชื้อ 2D Center-Surround บนเครื่องแทน")
        return

    py_bin = find_python_with_ultralytics()
    if py_bin is None:
        print(f"[INFO] พบไฟล์ {pt_path.name} แต่ไม่พบไลบรารี ultralytics สำหรับแปลงเป็น ONNX")
        return

    print(f"\n[AUTO-EXPORT] กำลังแปลงโมเดล {pt_path.relative_to(PROJECT_ROOT)} เป็น ONNX สำหรับรันในโทรศัพท์...")

    chk_onnx = subprocess.run([py_bin, "-c", "import onnx"], capture_output=True, check=False)
    if chk_onnx.returncode != 0:
        print("[AUTO-EXPORT] กำลังติดตั้งแพ็กเกจ onnx สำหรับส่งออกโมเดล YOLO26n...")
        subprocess.run([py_bin, "-m", "pip", "install", "--quiet", "onnx"], check=False)
        chk_onnx2 = subprocess.run([py_bin, "-c", "import onnx"], capture_output=True, check=False)
        if chk_onnx2.returncode != 0:
            subprocess.run(
                [py_bin, "-m", "pip", "install", "--quiet", "--user", "--break-system-packages", "onnx"],
                check=False,
            )

    export_code = f"""
import os
import shutil
from copy import deepcopy
from pathlib import Path
import torch
from ultralytics import YOLO

os.environ["ULTRALYTICS_AUTOINSTALL"] = "0"
pt_file = Path({repr(str(pt_path))})
out_onnx = Path({repr(str(target_onnx))})

yolo = YOLO(str(pt_file))
net = deepcopy(yolo.model).to("cpu").float().eval()
for p in net.parameters():
    p.requires_grad = False
if hasattr(net, "fuse"):
    net = net.fuse()
for m in net.modules():
    if m.__class__.__name__ in ("Detect", "v10Detect", "OBB", "Segment", "Pose"):
        m.dynamic = False
        m.export = True
        m.format = "onnx"

dummy = torch.zeros(1, 3, 640, 640, dtype=torch.float32)
_ = net(dummy)
torch.onnx.export(
    net,
    dummy,
    str(out_onnx),
    verbose=False,
    opset_version=12,
    do_constant_folding=True,
    input_names=["images"],
    output_names=["output0"],
)
print("EXPORT_SUCCESS:", out_onnx)
"""
    res = subprocess.run([py_bin, "-c", export_code], cwd=str(PROJECT_ROOT), check=False)
    if res.returncode == 0 and target_onnx.is_file() and target_onnx.stat().st_size > 100_000:
        try:
            cached_onnx.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target_onnx, cached_onnx)
        except Exception:
            pass
        size_mb = target_onnx.stat().st_size / (1024 * 1024)
        print(f"[OK] แปลงและฝังโมเดล YOLO ({pt_path.parent.parent.name}) ลงใน assets/models/yolo26n_disc.onnx สำเร็จ ({size_mb:.2f} MB)")
    else:
        print("[WARN] ไม่สามารถแปลงโมเดล .pt เป็น .onnx ได้ ระบบจะใช้ตัวตรวจจับสำรองบนเครื่องโดยอัตโนมัติ")


def configure_cachyos_linux_java() -> None:
    if platform.system() != "Linux":
        return

    jvm_candidates = [
        Path("/usr/lib/jvm/java-17-openjdk"),
        Path("/usr/lib/jvm/java-21-openjdk"),
        Path("/usr/lib/jvm/default"),
    ]
    for jvm in jvm_candidates:
        if (jvm / "bin" / "java").is_file() and (jvm / "bin" / "javac").is_file():
            os.environ["JAVA_HOME"] = str(jvm)
            os.environ["PATH"] = f"{jvm / 'bin'}:{os.environ.get('PATH', '')}"
            print(f"[OK] ตั้งค่า JAVA_HOME สำหรับ CachyOS/Linux ที่: {jvm}")
            return

    if not shutil.which("javac"):
        print("\n[แจ้งเตือน] ไม่พบ Java Development Kit (JDK) บนเครื่อง CachyOS")
        print("กรุณารันคำสั่งต่อไปนี้ใน Terminal เพื่อติดตั้ง JDK 17 และเครื่องมือพื้นฐานก่อน:")
        print("    sudo pacman -S --needed jdk17-openjdk git unzip curl xz glu")
        sys.exit(1)


def ensure_flutter_sdk() -> str:
    local_candidates = [
        LOCAL_FLUTTER_DIR / "bin" / "flutter",
        Path.home() / "flutter" / "bin" / "flutter",
        Path.home() / "develop" / "flutter" / "bin" / "flutter",
    ]
    for cand in local_candidates:
        if cand.is_file() and os.access(cand, os.X_OK):
            os.environ["PATH"] = f"{cand.parent}:{os.environ.get('PATH', '')}"
            return str(cand)

    for cmd in ("flutter", "flutter.bat"):
        resolved = shutil.which(cmd)
        if resolved:
            resolved_path = Path(resolved).resolve()
            if "/opt/flutter" in str(resolved_path) and not os.access(resolved_path.parent, os.W_OK):
                print("[INFO] พบ /opt/flutter แต่จำกัดสิทธิ์การเขียนของระบบ จะใช้ Flutter ในโฟลเดอร์ผู้ใช้แทน")
                break
            return resolved

    if platform.system() == "Linux":
        if not shutil.which("git"):
            raise RuntimeError(
                "ไม่พบคำสั่ง git กรุณารัน: sudo pacman -S --needed jdk17-openjdk git unzip curl xz glu"
            )
        print("\n[AUTO-SETUP] กำลังดาวน์โหลด Flutter SDK (Stable) สำหรับ CachyOS ลงใน ~/.local/share/...")
        LOCAL_SDK_BASE.mkdir(parents=True, exist_ok=True)
        if LOCAL_FLUTTER_DIR.exists():
            shutil.rmtree(LOCAL_FLUTTER_DIR)
        run_cmd(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "-b",
                "stable",
                "https://github.com/flutter/flutter.git",
                str(LOCAL_FLUTTER_DIR),
            ],
            cwd=LOCAL_SDK_BASE,
        )
        flutter_bin = LOCAL_FLUTTER_DIR / "bin" / "flutter"
        os.environ["PATH"] = f"{flutter_bin.parent}:{os.environ.get('PATH', '')}"
        run_cmd([str(flutter_bin), "--version"], cwd=PROJECT_ROOT)
        return str(flutter_bin)

    raise RuntimeError("ไม่พบ Flutter SDK กรุณาติดตั้ง Flutter SDK ก่อนรันสคริปต์")


def ensure_android_sdk_linux(flutter_bin: str) -> None:
    if platform.system() != "Linux":
        return

    existing_sdk_candidates = [
        Path(os.environ["ANDROID_HOME"]) if os.environ.get("ANDROID_HOME") else None,
        Path(os.environ["ANDROID_SDK_ROOT"]) if os.environ.get("ANDROID_SDK_ROOT") else None,
        LOCAL_ANDROID_SDK_DIR,
        Path.home() / "Android" / "Sdk",
        Path("/opt/android-sdk"),
    ]

    sdk_root: Path | None = None
    for cand in existing_sdk_candidates:
        if cand and (cand / "platforms").is_dir() and os.access(cand, os.W_OK):
            sdk_root = cand
            break

    if sdk_root is None:
        sdk_root = LOCAL_ANDROID_SDK_DIR
        cmdline_latest_bin = sdk_root / "cmdline-tools" / "latest" / "bin" / "sdkmanager"

        if not cmdline_latest_bin.is_file():
            print("\n[AUTO-SETUP] กำลังดาวน์โหลด Android Command-line Tools สำหรับ Linux (~140 MB)...")
            sdk_root.mkdir(parents=True, exist_ok=True)
            zip_path = LOCAL_SDK_BASE / "cmdline-tools-linux.zip"
            urllib.request.urlretrieve(CMDLINE_TOOLS_LINUX_URL, str(zip_path))

            extract_tmp = LOCAL_SDK_BASE / "cmdline_extract_tmp"
            if extract_tmp.exists():
                shutil.rmtree(extract_tmp)
            extract_tmp.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_tmp)

            latest_dir = sdk_root / "cmdline-tools" / "latest"
            if latest_dir.exists():
                shutil.rmtree(latest_dir)
            latest_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(extract_tmp / "cmdline-tools"), str(latest_dir))
            shutil.rmtree(extract_tmp, ignore_errors=True)
            zip_path.unlink(missing_ok=True)

            for f in (latest_dir / "bin").iterdir():
                f.chmod(0o755)

        sdkmanager_bin = str(cmdline_latest_bin)
        os.environ["ANDROID_HOME"] = str(sdk_root)
        os.environ["ANDROID_SDK_ROOT"] = str(sdk_root)

        print("\n[AUTO-SETUP] กำลังตอบรับใบอนุญาต Android SDK และติดตั้งแพ็กเกจสำหรับสร้างไฟล์ .apk...")
        yes_inputs = "y\n" * 40
        run_cmd([sdkmanager_bin, f"--sdk_root={sdk_root}", "--licenses"], cwd=sdk_root, input_text=yes_inputs)
        run_cmd(
            [
                sdkmanager_bin,
                f"--sdk_root={sdk_root}",
                "platform-tools",
                "platforms;android-34",
                "build-tools;34.0.0",
            ],
            cwd=sdk_root,
            input_text=yes_inputs,
        )

    os.environ["ANDROID_HOME"] = str(sdk_root)
    os.environ["ANDROID_SDK_ROOT"] = str(sdk_root)
    os.environ["PATH"] = (
        f"{sdk_root / 'cmdline-tools' / 'latest' / 'bin'}:"
        f"{sdk_root / 'platform-tools'}:"
        f"{os.environ.get('PATH', '')}"
    )
    run_cmd([flutter_bin, "config", "--android-sdk", str(sdk_root)], cwd=PROJECT_ROOT)
    print(f"[OK] ตั้งค่า ANDROID_HOME ที่: {sdk_root}")


def patch_android_manifest(manifest_path: Path) -> None:
    if not manifest_path.is_file():
        return

    content = manifest_path.read_text(encoding="utf-8")

    required_permissions = [
        '<uses-permission android:name="android.permission.INTERNET" />',
        '<uses-permission android:name="android.permission.CAMERA" />',
        '<uses-permission android:name="android.permission.READ_EXTERNAL_STORAGE" android:maxSdkVersion="32" />',
        '<uses-permission android:name="android.permission.WRITE_EXTERNAL_STORAGE" android:maxSdkVersion="29" />',
        '<uses-permission android:name="android.permission.READ_MEDIA_IMAGES" />',
    ]

    missing_perms = [
        perm for perm in required_permissions
        if perm.split('"')[1] not in content
    ]

    if missing_perms:
        perm_block = "\n    " + "\n    ".join(missing_perms) + "\n"
        content = re.sub(
            r"(<manifest[^>]*>)",
            r"\1" + perm_block,
            content,
            count=1,
        )

    if 'android:usesCleartextTraffic="true"' not in content:
        content = re.sub(
            r"(<application\b)",
            r'\1 android:usesCleartextTraffic="true"',
            content,
            count=1,
        )

    if "com.google.mlkit.vision.DEPENDENCIES" not in content:
        mlkit_meta = (
            '\n        <meta-data\n'
            '            android:name="com.google.mlkit.vision.DEPENDENCIES"\n'
            '            android:value="ocr" />\n    '
        )
        content = re.sub(
            r"(</application>)",
            mlkit_meta + r"\1",
            content,
            count=1,
        )

    content = re.sub(
        r'android:label="[^"]*"',
        'android:label="AST Disk Diffusion"',
        content,
        count=1,
    )

    manifest_path.write_text(content, encoding="utf-8")
    print(f"[OK] อัปเดตสิทธิ์กล้อง, การบันทึกไฟล์ และโมเดล OCR บนเครื่องใน {manifest_path.relative_to(PROJECT_ROOT)} เรียบร้อยแล้ว")


def patch_android_main_activity_for_yolo_onnx(android_dir: Path) -> None:
    src_main = android_dir / "app" / "src" / "main"
    kt_files = list(src_main.rglob("MainActivity.kt"))
    if kt_files:
        kt_path = kt_files[0]
        cur = kt_path.read_text(encoding="utf-8")
        m = re.search(r"^\s*package\s+([a-zA-Z0-9_.]+)", cur, flags=re.MULTILINE)
        pkg_name = m.group(1) if m else "org.clinical.ast.ast_flutter_app"
    else:
        pkg_name = "org.clinical.ast.ast_flutter_app"
        kt_path = src_main / "kotlin" / "org" / "clinical" / "ast" / "ast_flutter_app" / "MainActivity.kt"
        kt_path.parent.mkdir(parents=True, exist_ok=True)

    kt_code = MAIN_ACTIVITY_KT_TEMPLATE.replace("__PACKAGE_NAME__", pkg_name)
    kt_path.write_text(kt_code, encoding="utf-8")
    print(f"[OK] ติดตั้งเอ็นจิน YOLO26n ONNX Runtime และระบบเลือกโฟลเดอร์บันทึกไฟล์ใน {kt_path.relative_to(PROJECT_ROOT)} เรียบร้อยแล้ว")


def patch_android_gradle_and_proguard(android_dir: Path) -> None:
    app_dir = android_dir / "app"
    app_dir.mkdir(parents=True, exist_ok=True)

    proguard_file = app_dir / "proguard-rules.pro"
    proguard_file.write_text(PROGUARD_RULES_CONTENT, encoding="utf-8")
    print(f"[OK] สร้างไฟล์กฎ ProGuard/R8 ที่: {proguard_file.relative_to(PROJECT_ROOT)}")

    groovy_gradle = app_dir / "build.gradle"
    kts_gradle = app_dir / "build.gradle.kts"

    if groovy_gradle.is_file():
        txt = groovy_gradle.read_text(encoding="utf-8")
        txt = re.sub(r"minSdkVersion\s+flutter\.minSdkVersion", "minSdkVersion 21", txt)
        txt = re.sub(r"minSdk\s*=\s*flutter\.minSdkVersion", "minSdk = 21", txt)
        txt = re.sub(r"minSdk\s+flutter\.minSdkVersion", "minSdk 21", txt)

        if "proguard-rules.pro" not in txt:
            txt = re.sub(
                r"(buildTypes\s*\{\s*release\s*\{)",
                r"\1\n            minifyEnabled false\n            shrinkResources false\n            proguardFiles getDefaultProguardFile('proguard-android-optimize.txt'), 'proguard-rules.pro'",
                txt,
                count=1,
            )
        if "com.microsoft.onnxruntime:onnxruntime-android" not in txt:
            txt += '\n\ndependencies {\n    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.18.0")\n}\n'
        groovy_gradle.write_text(txt, encoding="utf-8")
        print("[OK] ตั้งค่า minSdk = 21, ONNX Runtime และกฎ R8/ProGuard ใน android/app/build.gradle เรียบร้อยแล้ว")

    if kts_gradle.is_file():
        txt = kts_gradle.read_text(encoding="utf-8")
        txt = re.sub(r"minSdk\s*=\s*flutter\.minSdkVersion", "minSdk = 21", txt)

        if "proguard-rules.pro" not in txt:
            txt = re.sub(
                r"(buildTypes\s*\{\s*release\s*\{)",
                r'\1\n            isMinifyEnabled = false\n            isShrinkResources = false\n            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")',
                txt,
                count=1,
            )
        if "com.microsoft.onnxruntime:onnxruntime-android" not in txt:
            txt += '\n\ndependencies {\n    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.18.0")\n}\n'
        kts_gradle.write_text(txt, encoding="utf-8")
        print("[OK] ตั้งค่า minSdk = 21, ONNX Runtime และกฎ R8/ProGuard ใน android/app/build.gradle.kts เรียบร้อยแล้ว")


def main() -> int:
    print("=" * 78)
    print("AST Disk Diffusion System — สร้างไฟล์ .apk รุ่นรัน ML บนโทรศัพท์ 100% (ไม่ต้องต่อ API)")
    print("=" * 78)

    configure_cachyos_linux_java()
    flutter_bin = ensure_flutter_sdk()
    print(f"[OK] ใช้ Flutter SDK จาก: {flutter_bin}")

    ensure_android_sdk_linux(flutter_bin)

    main_dart_src = find_source_file("main.dart")
    pubspec_src = ensure_upgraded_pubspec()

    android_dir = FLUTTER_DIR / "android"
    if not android_dir.is_dir():
        print("\n[STEP 1/5] กำลังสร้างโครงสร้างโปรเจกต์ Flutter สำหรับ Android...")
        FLUTTER_DIR.mkdir(parents=True, exist_ok=True)
        run_cmd(
            [
                flutter_bin,
                "create",
                "--platforms=android,web",
                "--org",
                "org.clinical.ast",
                "--project-name",
                "ast_flutter_app",
                ".",
            ],
            cwd=FLUTTER_DIR,
        )
    else:
        print("\n[STEP 1/5] พบโครงสร้างโปรเจกต์ Android เดิมใน ast_flutter_app/android แล้ว")

    print("\n[STEP 2/5] กำลังเตรียมโมเดล YOLO26n ONNX สำหรับฝังลงในโทรศัพท์...")
    export_yolo26n_to_onnx_asset(FLUTTER_DIR)

    print("\n[STEP 3/5] กำลังคัดลอกไฟล์ main.dart และ pubspec.yaml เข้าสู่โปรเจกต์...")
    lib_dir = FLUTTER_DIR / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)

    target_main = lib_dir / "main.dart"
    target_pubspec = FLUTTER_DIR / "pubspec.yaml"

    if main_dart_src.resolve() != target_main.resolve():
        shutil.copy2(main_dart_src, target_main)
    if pubspec_src.resolve() != target_pubspec.resolve():
        shutil.copy2(pubspec_src, target_pubspec)

    default_test = FLUTTER_DIR / "test" / "widget_test.dart"
    if default_test.is_file():
        default_test.unlink()

    print("\n[STEP 4/5] กำลังตั้งค่า AndroidManifest.xml, MainActivity.kt (ONNX Runtime + File Picker) และ ProGuard/R8...")
    manifest_file = FLUTTER_DIR / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
    patch_android_manifest(manifest_file)
    patch_android_main_activity_for_yolo_onnx(android_dir)
    patch_android_gradle_and_proguard(android_dir)

    print("\n[STEP 5/5] กำลังติดตั้งไลบรารีและคอมไพล์ไฟล์ Android APK (Release Mode)...")
    run_cmd([flutter_bin, "pub", "get"], cwd=FLUTTER_DIR)
    run_cmd([flutter_bin, "build", "apk", "--release"], cwd=FLUTTER_DIR)

    built_apk = FLUTTER_DIR / "build" / "app" / "outputs" / "flutter-apk" / "app-release.apk"
    if built_apk.is_file():
        shutil.copy2(built_apk, OUTPUT_APK_PATH)
        size_mb = OUTPUT_APK_PATH.stat().st_size / (1024 * 1024)
        print("\n" + "=" * 78)
        print("[สำเร็จ] สร้างไฟล์ติดตั้ง Android (.apk) รุ่นรัน ML ในโทรศัพท์ 100% เสร็จสมบูรณ์")
        print(f"ตำแหน่งไฟล์ .apk: {OUTPUT_APK_PATH} (ขนาด {size_mb:.2f} MB)")
        print("ขั้นตอนการติดตั้งลงโทรศัพท์ Android:")
        print("  1. ส่งไฟล์ AST_Disk_Diffusion_System.apk เข้าโทรศัพท์ (ผ่านสาย USB, KDE Connect, LocalSend หรือ Google Drive)")
        print("  2. แตะที่ไฟล์บนโทรศัพท์แล้วกด 'ติดตั้ง (Install)'")
        print("  3. เปิดแอปใช้งานได้ทันที — โมเดล YOLO26n ONNX + Custom AST-OCR + Warp-Polar รันในโทรศัพท์ 100% พร้อมหน้าต่างเลือกโฟลเดอร์บันทึกไฟล์ส่งออก")
        print("=" * 78)
        return 0

    print("\n[ข้อผิดพลาด] ไม่พบไฟล์ app-release.apk หลังการคอมไพล์")
    return 1


if __name__ == "__main__":
    sys.exit(main())