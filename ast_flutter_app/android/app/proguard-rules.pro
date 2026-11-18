# Keep rules & dontwarn for On-Device ML Kit & ONNX Runtime (YOLO26n)
-dontwarn com.google.mlkit.vision.text.chinese.**
-dontwarn com.google.mlkit.vision.text.devanagari.**
-dontwarn com.google.mlkit.vision.text.japanese.**
-dontwarn com.google.mlkit.vision.text.korean.**
-keep class com.google.mlkit.** { *; }
-keep class com.google_mlkit_text_recognition.** { *; }
-keep class com.google_mlkit_commons.** { *; }
-keep class ai.onnxruntime.** { *; }
-dontwarn ai.onnxruntime.**
