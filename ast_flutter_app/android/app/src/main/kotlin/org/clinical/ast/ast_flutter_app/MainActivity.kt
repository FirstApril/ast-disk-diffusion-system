package org.clinical.ast.ast_flutter_app

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
