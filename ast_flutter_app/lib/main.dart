import 'dart:async';
import 'dart:convert';
import 'dart:io' show Directory, File;
import 'dart:math' as math;
import 'dart:typed_data';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_mlkit_text_recognition/google_mlkit_text_recognition.dart';
import 'package:http/http.dart' as http;
import 'package:image/image.dart' as img;
import 'package:image_picker/image_picker.dart';
import 'package:path_provider/path_provider.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const AstFlutterApp());
}

// ============================================================================
// 1. ฐานข้อมูลเกณฑ์มาตรฐาน CLSI M100 / EUCAST + รหัสแผ่นยา Oxoid / Mast / BD
// ============================================================================
class DrugBreakpoint {
  final String code;
  final String fullName;
  final double sMinMm;
  final double rMaxMm;

  const DrugBreakpoint({
    required this.code,
    required this.fullName,
    required this.sMinMm,
    required this.rMaxMm,
  });

  String interpret(double diameterMm) {
    if (diameterMm >= sMinMm) return 'S';
    if (diameterMm <= rMaxMm) return 'R';
    return 'I';
  }
}

final Map<String, DrugBreakpoint> kClsiEucastDb = {
  'AMC30': const DrugBreakpoint(code: 'AMC30', fullName: 'Amoxicillin-Clavulanate 30 µg', sMinMm: 18.0, rMaxMm: 13.0),
  'AMC20/10': const DrugBreakpoint(code: 'AMC20/10', fullName: 'Amoxicillin-Clavulanate 20/10 µg (AMC 30)', sMinMm: 18.0, rMaxMm: 13.0),
  'AMP10': const DrugBreakpoint(code: 'AMP10', fullName: 'Ampicillin 10 µg', sMinMm: 17.0, rMaxMm: 13.0),
  'AM10': const DrugBreakpoint(code: 'AM10', fullName: 'Ampicillin 10 µg (EUCAST)', sMinMm: 14.0, rMaxMm: 14.0),
  'AUG30': const DrugBreakpoint(code: 'AUG30', fullName: 'Amoxicillin-Clavulanate 30 µg (AUG30)', sMinMm: 18.0, rMaxMm: 13.0),
  'CAZ30': const DrugBreakpoint(code: 'CAZ30', fullName: 'Ceftazidime 30 µg', sMinMm: 21.0, rMaxMm: 17.0),
  'CAZ10': const DrugBreakpoint(code: 'CAZ10', fullName: 'Ceftazidime 10 µg (EUCAST)', sMinMm: 22.0, rMaxMm: 19.0),
  'SXT25': const DrugBreakpoint(code: 'SXT25', fullName: 'Trimethoprim-Sulfamethoxazole 25 µg', sMinMm: 16.0, rMaxMm: 10.0),
  'TS25': const DrugBreakpoint(code: 'TS25', fullName: 'Trimethoprim-Sulfamethoxazole 25 µg (TS25)', sMinMm: 16.0, rMaxMm: 10.0),
  'TE30': const DrugBreakpoint(code: 'TE30', fullName: 'Tetracycline 30 µg', sMinMm: 19.0, rMaxMm: 14.0),
  'CIP5': const DrugBreakpoint(code: 'CIP5', fullName: 'Ciprofloxacin 5 µg', sMinMm: 25.0, rMaxMm: 22.0),
  'LEV5': const DrugBreakpoint(code: 'LEV5', fullName: 'Levofloxacin 5 µg', sMinMm: 23.0, rMaxMm: 19.0),
  'NOR10': const DrugBreakpoint(code: 'NOR10', fullName: 'Norfloxacin 10 µg', sMinMm: 17.0, rMaxMm: 12.0),
  'PEF5': const DrugBreakpoint(code: 'PEF5', fullName: 'Pefloxacin 5 µg', sMinMm: 24.0, rMaxMm: 24.0),
  'CN10': const DrugBreakpoint(code: 'CN10', fullName: 'Gentamicin 10 µg', sMinMm: 17.0, rMaxMm: 14.0),
  'AK30': const DrugBreakpoint(code: 'AK30', fullName: 'Amikacin 30 µg', sMinMm: 17.0, rMaxMm: 14.0),
  'TOB10': const DrugBreakpoint(code: 'TOB10', fullName: 'Tobramycin 10 µg', sMinMm: 17.0, rMaxMm: 14.0),
  'S10': const DrugBreakpoint(code: 'S10', fullName: 'Streptomycin 10 µg', sMinMm: 15.0, rMaxMm: 11.0),
  'FOX30': const DrugBreakpoint(code: 'FOX30', fullName: 'Cefoxitin 30 µg', sMinMm: 18.0, rMaxMm: 14.0),
  'CRO30': const DrugBreakpoint(code: 'CRO30', fullName: 'Ceftriaxone 30 µg', sMinMm: 25.0, rMaxMm: 22.0),
  'CTX5': const DrugBreakpoint(code: 'CTX5', fullName: 'Cefotaxime 5 µg', sMinMm: 20.0, rMaxMm: 17.0),
  'CTX30': const DrugBreakpoint(code: 'CTX30', fullName: 'Cefotaxime 30 µg', sMinMm: 26.0, rMaxMm: 22.0),
  'CPD10': const DrugBreakpoint(code: 'CPD10', fullName: 'Cefpodoxime 10 µg', sMinMm: 21.0, rMaxMm: 21.0),
  'FEP30': const DrugBreakpoint(code: 'FEP30', fullName: 'Cefepime 30 µg', sMinMm: 27.0, rMaxMm: 24.0),
  'ATM30': const DrugBreakpoint(code: 'ATM30', fullName: 'Aztreonam 30 µg', sMinMm: 21.0, rMaxMm: 17.0),
  'AZT30': const DrugBreakpoint(code: 'AZT30', fullName: 'Aztreonam 30 µg (AZT30)', sMinMm: 21.0, rMaxMm: 17.0),
  'TZP36': const DrugBreakpoint(code: 'TZP36', fullName: 'Piperacillin-Tazobactam 36 µg', sMinMm: 20.0, rMaxMm: 17.0),
  'TPZ36': const DrugBreakpoint(code: 'TPZ36', fullName: 'Piperacillin-Tazobactam 36 µg', sMinMm: 20.0, rMaxMm: 17.0),
  'TZP110': const DrugBreakpoint(code: 'TZP110', fullName: 'Piperacillin-Tazobactam 110 µg', sMinMm: 21.0, rMaxMm: 17.0),
  'TAZ110': const DrugBreakpoint(code: 'TAZ110', fullName: 'Piperacillin-Tazobactam 110 µg (TAZ110)', sMinMm: 21.0, rMaxMm: 17.0),
  'AMS20': const DrugBreakpoint(code: 'AMS20', fullName: 'Ampicillin-Sulbactam 10/10 µg (AMS 20)', sMinMm: 15.0, rMaxMm: 11.0),
  'AMS10/10': const DrugBreakpoint(code: 'AMS10/10', fullName: 'Ampicillin-Sulbactam 10/10 µg (AMS 10/10)', sMinMm: 15.0, rMaxMm: 11.0),
  'SAM20': const DrugBreakpoint(code: 'SAM20', fullName: 'Ampicillin-Sulbactam 20 µg (SAM 20)', sMinMm: 15.0, rMaxMm: 11.0),
  'SCF105': const DrugBreakpoint(code: 'SCF105', fullName: 'Cefoperazone-Sulbactam 105 µg (SCF 75/30)', sMinMm: 21.0, rMaxMm: 15.0),
  'CFM5': const DrugBreakpoint(code: 'CFM5', fullName: 'Cefixime 5 µg', sMinMm: 19.0, rMaxMm: 15.0),
  'CXM30': const DrugBreakpoint(code: 'CXM30', fullName: 'Cefuroxime 30 µg', sMinMm: 18.0, rMaxMm: 14.0),
  'CZO30': const DrugBreakpoint(code: 'CZO30', fullName: 'Cefazolin 30 µg', sMinMm: 23.0, rMaxMm: 19.0),
  'DO30': const DrugBreakpoint(code: 'DO30', fullName: 'Doxycycline 30 µg', sMinMm: 14.0, rMaxMm: 10.0),
  'F300': const DrugBreakpoint(code: 'F300', fullName: 'Nitrofurantoin 300 µg', sMinMm: 17.0, rMaxMm: 14.0),
  'FOS200': const DrugBreakpoint(code: 'FOS200', fullName: 'Fosfomycin 200 µg', sMinMm: 16.0, rMaxMm: 12.0),
  'LZD30': const DrugBreakpoint(code: 'LZD30', fullName: 'Linezolid 30 µg', sMinMm: 21.0, rMaxMm: 20.0),
  'NET30': const DrugBreakpoint(code: 'NET30', fullName: 'Netilmicin 30 µg', sMinMm: 15.0, rMaxMm: 12.0),
  'OFX5': const DrugBreakpoint(code: 'OFX5', fullName: 'Ofloxacin 5 µg', sMinMm: 16.0, rMaxMm: 12.0),
  'OX1': const DrugBreakpoint(code: 'OX1', fullName: 'Oxacillin 1 µg', sMinMm: 13.0, rMaxMm: 10.0),
  'PIP100': const DrugBreakpoint(code: 'PIP100', fullName: 'Piperacillin 100 µg', sMinMm: 21.0, rMaxMm: 17.0),
  'PRL100': const DrugBreakpoint(code: 'PRL100', fullName: 'Piperacillin 100 µg (PRL100)', sMinMm: 21.0, rMaxMm: 17.0),
  'TGC15': const DrugBreakpoint(code: 'TGC15', fullName: 'Tigecycline 15 µg', sMinMm: 19.0, rMaxMm: 14.0),
  'TMP5': const DrugBreakpoint(code: 'TMP5', fullName: 'Trimethoprim 5 µg', sMinMm: 16.0, rMaxMm: 10.0),
  'ETP10': const DrugBreakpoint(code: 'ETP10', fullName: 'Ertapenem 10 µg', sMinMm: 25.0, rMaxMm: 22.0),
  'IPM10': const DrugBreakpoint(code: 'IPM10', fullName: 'Imipenem 10 µg (IPM10)', sMinMm: 23.0, rMaxMm: 19.0),
  'IMI10': const DrugBreakpoint(code: 'IMI10', fullName: 'Imipenem 10 µg (IMI10)', sMinMm: 23.0, rMaxMm: 19.0),
  'MEM10': const DrugBreakpoint(code: 'MEM10', fullName: 'Meropenem 10 µg', sMinMm: 22.0, rMaxMm: 16.0),
  'VA30': const DrugBreakpoint(code: 'VA30', fullName: 'Vancomycin 30 µg', sMinMm: 17.0, rMaxMm: 14.0),
  'VA5': const DrugBreakpoint(code: 'VA5', fullName: 'Vancomycin 5 µg', sMinMm: 15.0, rMaxMm: 12.0),
  'E15': const DrugBreakpoint(code: 'E15', fullName: 'Erythromycin 15 µg', sMinMm: 23.0, rMaxMm: 13.0),
  'CD2': const DrugBreakpoint(code: 'CD2', fullName: 'Clindamycin 2 µg', sMinMm: 21.0, rMaxMm: 14.0),
  'C30': const DrugBreakpoint(code: 'C30', fullName: 'Chloramphenicol 30 µg', sMinMm: 18.0, rMaxMm: 12.0),
  'RD5': const DrugBreakpoint(code: 'RD5', fullName: 'Rifampin 5 µg', sMinMm: 20.0, rMaxMm: 16.0),
  'P10': const DrugBreakpoint(code: 'P10', fullName: 'Penicillin G 10 U', sMinMm: 15.0, rMaxMm: 14.0),
  'TC75': const DrugBreakpoint(code: 'TC75', fullName: 'Ticarcillin 75 µg', sMinMm: 20.0, rMaxMm: 14.0),
  'UNKNOWN': const DrugBreakpoint(code: 'UNKNOWN', fullName: 'รอการระบุรหัสยา (เลือกจากรายการหรือหมุนภาพเพื่ออ่านซ้ำ)', sMinMm: 19.0, rMaxMm: 14.0),
};

const Map<String, String> kDrugPrefixAliases = {
  'AMC': 'AMC30',
  'AUG': 'AUG30',
  'AMO': 'AMC30',
  'AMX': 'AMC30',
  'AIVIC': 'AMC30',
  'AMP': 'AMP10',
  'AM': 'AM10',
  'CAZ': 'CAZ30',
  'SXT': 'SXT25',
  'TS': 'TS25',
  'TS25': 'TS25',
  'COT': 'SXT25',
  'TE': 'TE30',
  'TET': 'TE30',
  'CIP': 'CIP5',
  'LEV': 'LEV5',
  'LVX': 'LEV5',
  'NOR': 'NOR10',
  'PEF': 'PEF5',
  'CN': 'CN10',
  'GEN': 'CN10',
  'GM': 'CN10',
  'AK': 'AK30',
  'AN': 'AK30',
  'TOB': 'TOB10',
  'NN': 'TOB10',
  'S': 'S10',
  'STR': 'S10',
  'FOX': 'FOX30',
  'CRO': 'CRO30',
  'CTX': 'CTX30',
  'CPD': 'CPD10',
  'CPO': 'CPD10',
  'FEP': 'FEP30',
  'CPM': 'FEP30',
  'ATM': 'ATM30',
  'AZT': 'AZT30',
  'AZT30': 'AZT30',
  'AMC2010': 'AMC20/10',
  'AMC20/10': 'AMC20/10',
  'AMS10/10': 'AMS10/10',
  'TZP': 'TZP36',
  'TPZ': 'TPZ36',
  'TAZ': 'TAZ110',
  'TAZ110': 'TAZ110',
  'AMS': 'AMS20',
  'AMS10': 'AMS20',
  'AMS20': 'AMS20',
  'AMS1010': 'AMS20',
  'SAM': 'SAM20',
  'SCF': 'SCF105',
  'CFM': 'CFM5',
  'CXM': 'CXM30',
  'CZO': 'CZO30',
  'KZ': 'CZO30',
  'DO': 'DO30',
  'DOX': 'DO30',
  'F': 'F300',
  'NIT': 'F300',
  'FOS': 'FOS200',
  'FF': 'FOS200',
  'LZD': 'LZD30',
  'NET': 'NET30',
  'OFX': 'OFX5',
  'OX': 'OX1',
  'PIP': 'PIP100',
  'PRL': 'PRL100',
  'TGC': 'TGC15',
  'TMP': 'TMP5',
  'W': 'TMP5',
  'ETP': 'ETP10',
  'IPM': 'IPM10',
  'IMI': 'IMI10',
  'IMI10': 'IMI10',
  'IM10': 'IMI10',
  'MEM': 'MEM10',
  'MRP': 'MEM10',
  'VA': 'VA30',
  'VAN': 'VA30',
  'E': 'E15',
  'ERY': 'E15',
  'CD': 'CD2',
  'DA': 'CD2',
  'CLI': 'CD2',
  'C': 'C30',
  'CHL': 'C30',
  'RD': 'RD5',
  'RA': 'RD5',
  'RIF': 'RD5',
  'P': 'P10',
  'TC': 'TC75',
};

// ============================================================================
// 2. โครงสร้างข้อมูลแผ่นยา (DiscRecord) พร้อมตารางความเชื่อมั่น OCR รายตัวยา
// ============================================================================
class OcrCandidateScore {
  final String code;
  final double confidence;

  const OcrCandidateScore({required this.code, required this.confidence});

  Map<String, dynamic> toJson() => {
        'code': code,
        'confidence': confidence,
      };

  factory OcrCandidateScore.fromJson(Map<String, dynamic> json) {
    return OcrCandidateScore(
      code: (json['code'] ?? '').toString(),
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0.0,
    );
  }
}

class DiscRecord {
  int discOrder;
  double cx;
  double cy;
  double rDiscPx;
  double rxDiscPx;
  double ryDiscPx;
  double rZonePx;
  double diameterMm;
  String drugCode;
  String rawOcrText;
  String? customDrugFullName;
  double? customSMinMm;
  double? customRMaxMm;
  String plateZone;
  double confidence;
  bool needsReview;
  bool isManualEntry;
  double userRotDeg;
  List<OcrCandidateScore> ocrCandidates;

  DiscRecord({
    required this.discOrder,
    required this.cx,
    required this.cy,
    required this.rDiscPx,
    double? rxDiscPx,
    double? ryDiscPx,
    required this.rZonePx,
    required this.diameterMm,
    required this.drugCode,
    required this.plateZone,
    this.rawOcrText = '',
    this.customDrugFullName,
    this.customSMinMm,
    this.customRMaxMm,
    this.confidence = 0.96,
    this.needsReview = false,
    this.isManualEntry = false,
    this.userRotDeg = 0.0,
    this.ocrCandidates = const <OcrCandidateScore>[],
  })  : rxDiscPx = rxDiscPx ?? rDiscPx,
        ryDiscPx = ryDiscPx ?? rDiscPx;

  DrugBreakpoint get breakpoint {
    final String clean = drugCode.trim().toUpperCase();
    if (kClsiEucastDb.containsKey(clean)) {
      final base = kClsiEucastDb[clean]!;
      return DrugBreakpoint(
        code: clean,
        fullName: customDrugFullName ?? base.fullName,
        sMinMm: customSMinMm ?? base.sMinMm,
        rMaxMm: customRMaxMm ?? base.rMaxMm,
      );
    }
    return DrugBreakpoint(
      code: clean.isEmpty ? 'UNKNOWN' : clean,
      fullName: customDrugFullName ?? 'ยานอกฐานข้อมูล (อ่านได้: $clean — เลือกชื่อยาที่เป็นไปได้ด้านล่าง)',
      sMinMm: customSMinMm ?? 19.0,
      rMaxMm: customRMaxMm ?? 14.0,
    );
  }

  String get sirStatus => breakpoint.interpret(diameterMm);

  DiscRecord copy() => DiscRecord(
        discOrder: discOrder,
        cx: cx,
        cy: cy,
        rDiscPx: rDiscPx,
        rxDiscPx: rxDiscPx,
        ryDiscPx: ryDiscPx,
        rZonePx: rZonePx,
        diameterMm: diameterMm,
        drugCode: drugCode,
        rawOcrText: rawOcrText,
        plateZone: plateZone,
        customDrugFullName: customDrugFullName,
        customSMinMm: customSMinMm,
        customRMaxMm: customRMaxMm,
        confidence: confidence,
        needsReview: needsReview,
        isManualEntry: isManualEntry,
        userRotDeg: userRotDeg,
        ocrCandidates: List<OcrCandidateScore>.from(ocrCandidates),
      );

  Map<String, dynamic> toJson() => {
        'disc_order': discOrder,
        'plate_zone': plateZone,
        'drug_code': drugCode,
        'raw_ocr_text': rawOcrText,
        'drug_full_name': breakpoint.fullName,
        'cx_px': double.parse(cx.toStringAsFixed(1)),
        'cy_px': double.parse(cy.toStringAsFixed(1)),
        'r_disc_px': double.parse(rDiscPx.toStringAsFixed(1)),
        'r_zone_px': double.parse(rZonePx.toStringAsFixed(1)),
        'diameter_mm': double.parse(diameterMm.toStringAsFixed(2)),
        'sir_status': sirStatus,
        'clsi_s_min_mm': breakpoint.sMinMm,
        'clsi_r_max_mm': breakpoint.rMaxMm,
      };

  Map<String, dynamic> toStorageJson() => {
        'discOrder': discOrder,
        'cx': cx,
        'cy': cy,
        'rDiscPx': rDiscPx,
        'rxDiscPx': rxDiscPx,
        'ryDiscPx': ryDiscPx,
        'rZonePx': rZonePx,
        'diameterMm': diameterMm,
        'drugCode': drugCode,
        'rawOcrText': rawOcrText,
        'customDrugFullName': customDrugFullName,
        'customSMinMm': customSMinMm,
        'customRMaxMm': customRMaxMm,
        'plateZone': plateZone,
        'confidence': confidence,
        'needsReview': needsReview,
        'isManualEntry': isManualEntry,
        'userRotDeg': userRotDeg,
        'ocrCandidates': ocrCandidates.map((c) => c.toJson()).toList(),
      };

  factory DiscRecord.fromStorageJson(Map<String, dynamic> json) {
    final double rDisc = (json['rDiscPx'] as num?)?.toDouble() ?? 21.0;
    final List<OcrCandidateScore> cands = <OcrCandidateScore>[];
    if (json['ocrCandidates'] is List) {
      for (final item in (json['ocrCandidates'] as List)) {
        if (item is Map<String, dynamic>) {
          cands.add(OcrCandidateScore.fromJson(item));
        } else if (item is Map) {
          cands.add(OcrCandidateScore.fromJson(Map<String, dynamic>.from(item)));
        }
      }
    }
    return DiscRecord(
      discOrder: (json['discOrder'] as num?)?.toInt() ?? 1,
      cx: (json['cx'] as num?)?.toDouble() ?? 0.0,
      cy: (json['cy'] as num?)?.toDouble() ?? 0.0,
      rDiscPx: rDisc,
      rxDiscPx: (json['rxDiscPx'] as num?)?.toDouble() ?? rDisc,
      ryDiscPx: (json['ryDiscPx'] as num?)?.toDouble() ?? rDisc,
      rZonePx: (json['rZonePx'] as num?)?.toDouble() ?? rDisc,
      diameterMm: (json['diameterMm'] as num?)?.toDouble() ?? 6.0,
      drugCode: (json['drugCode'] ?? 'UNKNOWN').toString(),
      rawOcrText: (json['rawOcrText'] ?? '').toString(),
      customDrugFullName: json['customDrugFullName']?.toString(),
      customSMinMm: (json['customSMinMm'] as num?)?.toDouble(),
      customRMaxMm: (json['customRMaxMm'] as num?)?.toDouble(),
      plateZone: (json['plateZone'] ?? 'Outer').toString(),
      confidence: (json['confidence'] as num?)?.toDouble() ?? 0.9,
      needsReview: json['needsReview'] == true,
      isManualEntry: json['isManualEntry'] == true,
      userRotDeg: (json['userRotDeg'] as num?)?.toDouble() ?? 0.0,
      ocrCandidates: cands,
    );
  }
}

class PendingUploadTask {
  final String tempId;
  final String title;
  final Uint8List? previewBytes;

  const PendingUploadTask({
    required this.tempId,
    required this.title,
    this.previewBytes,
  });
}

class AlbumPlateEntry {
  final String id;
  final String title;
  final DateTime createdAt;
  final Uint8List? imageBytes;
  final img.Image decodedImage;
  final double medianDiscRadiusPx;
  final List<DiscRecord> discs;

  AlbumPlateEntry({
    required this.id,
    required this.title,
    required this.createdAt,
    required this.imageBytes,
    required this.decodedImage,
    required this.medianDiscRadiusPx,
    required this.discs,
  });
}

// ============================================================================
// 3. Full SOTA Vision Engine:
//    - On-Device YOLO26n ONNX Runtime Detector (MethodChannel 'org.clinical.ast/yolo26n')
//    - Auto Petri Dish Circle Localization + 8-Sector Radial Symmetry Fallback
//    - Continuous Warp Polar Transform 1:1 จาก src/measurements.py
//    - Custom Point-3 AST-OCR Pipeline (Underline Bar & Two-Row Projection Alignment +
//      2D Integral-Image CLAHE & Adaptive Gaussian Threshold + Clinical Fingerprint +
//      Plate-Level Hungarian Assignment จาก src/classifiers.py & src/api_server.py)
// ============================================================================
class AstSotaVisionEngine {
  static const MethodChannel _yoloChannel = MethodChannel('org.clinical.ast/yolo26n');
  static String? _cachedOnnxModelPath;
  static bool _checkedOnnxAsset = false;
  static TextRecognizer? _mlkitRecognizer;
  static String lastUsedDetectorName = 'YOLO26n (On-Device)';

  static TextRecognizer? _getOrCreateRecognizer() {
    if (kIsWeb) return null;
    _mlkitRecognizer ??= TextRecognizer(script: TextRecognitionScript.latin);
    return _mlkitRecognizer;
  }

  static void disposeRecognizer() {
    _mlkitRecognizer?.close();
    _mlkitRecognizer = null;
  }

  /// เตรียมไฟล์โมเดล `assets/models/yolo26n_disc.onnx` ลงในโฟลเดอร์ชั่วคราวของเครื่องเพื่อส่งให้ ONNX Runtime
  static Future<String?> _prepareYoloOnnxModelFileAsync() async {
    if (kIsWeb) return null;
    if (_cachedOnnxModelPath != null) {
      try {
        if (await File(_cachedOnnxModelPath!).exists()) {
          return _cachedOnnxModelPath;
        }
      } catch (_) {}
    }
    if (_checkedOnnxAsset && _cachedOnnxModelPath == null) {
      return null;
    }
    _checkedOnnxAsset = true;
    try {
      final ByteData data = await rootBundle.load('assets/models/yolo26n_disc.onnx');
      if (data.lengthInBytes < 50000) return null;
      final Directory tmpDir = await getTemporaryDirectory();
      final File outFile = File('${tmpDir.path}/yolo26n_disc.onnx');
      await outFile.writeAsBytes(
        data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes),
        flush: true,
      );
      _cachedOnnxModelPath = outFile.path;
      return _cachedOnnxModelPath;
    } catch (_) {
      return null;
    }
  }

  /// รันโมเดล YOLO26n ONNX บนเครื่อง Android ผ่าน MethodChannel ('org.clinical.ast/yolo26n')
  /// ส่งภาพที่ผ่านการปรับแกน EXIF (bakeOrientation) แล้วเสมอ เพื่อให้พิกัดตรงกับภาพที่แสดงผล 100%
  /// และรองรับภาพถ่ายมุมเอียง (Elliptical Perspective: rx, ry)
  static Future<List<({double cx, double cy, double r, double rx, double ry})>?> detectDiscsWithYolo26nOnnxAsync(
    img.Image plateImage,
    Uint8List? rawImageBytes,
  ) async {
    if (kIsWeb) return null;
    final String? modelPath = await _prepareYoloOnnxModelFileAsync();
    if (modelPath == null) return null;

    try {
      // เข้ารหัสจาก plateImage ที่ผ่านการ bakeOrientation แล้วเสมอ เพื่อป้องกันปัญหา EXIF หมุนภาพ 90/270 องศาใน BitmapFactory
      final Uint8List bytesToUse = Uint8List.fromList(img.encodeJpg(plateImage, quality: 94));
      final dynamic rawResult = await _yoloChannel.invokeMethod('detectDiscsYolo', <String, dynamic>{
        'modelPath': modelPath,
        'imageBytes': bytesToUse,
        'confThreshold': 0.22,
      });
      if (rawResult is! List || rawResult.isEmpty) return null;

      final List<({double cx, double cy, double r, double rx, double ry})> refinedList =
          <({double cx, double cy, double r, double rx, double ry})>[];
      for (final item in rawResult) {
        if (item is Map) {
          final double cx = (item['cx'] as num?)?.toDouble() ?? 0.0;
          final double cy = (item['cy'] as num?)?.toDouble() ?? 0.0;
          final double r = (item['r'] as num?)?.toDouble() ?? 24.0;
          final double rx = (item['rx'] as num?)?.toDouble() ?? r;
          final double ry = (item['ry'] as num?)?.toDouble() ?? r;
          if (cx > 4 && cy > 4) {
            final refined = _refineDiscCenterAndRadius(
              plateImage,
              cx,
              cy,
              r,
              initRx: rx,
              initRy: ry,
              fromYolo: true,
            );
            refinedList.add(refined);
          }
        }
      }
      if (refinedList.isEmpty) return null;

      // รองรับขนาดเม็ดยาที่แตกต่างกันตามระยะใกล้-ไกลเมื่อถ่ายภาพมุมเอียง (ไม่บีบให้เท่ากันทุกเม็ด)
      if (refinedList.length >= 3) {
        final List<double> sortedR = refinedList.map((e) => e.r).toList()..sort();
        final double medR = sortedR[sortedR.length ~/ 2];
        for (int i = 0; i < refinedList.length; i++) {
          final cur = refinedList[i];
          final double clampedR = cur.r.clamp(medR * 0.65, medR * 1.42);
          final double scaleAdj = clampedR / math.max(1.0, cur.r);
          refinedList[i] = (
            cx: cur.cx,
            cy: cur.cy,
            r: clampedR,
            rx: (cur.rx * scaleAdj).clamp(medR * 0.58, medR * 1.50),
            ry: (cur.ry * scaleAdj).clamp(medR * 0.58, medR * 1.50),
          );
        }
      }
      lastUsedDetectorName = 'YOLO26n (ONNX บนเครื่อง)';
      return refinedList;
    } catch (_) {
      return null;
    }
  }

  // --------------------------------------------------------------------------
  // 3.1 การจับคู่รหัสยาด้วย Clinical Fingerprint + Alias + Hungarian (พอร์ตจาก src/classifiers.py)
  // --------------------------------------------------------------------------
  static String _snapConfusedDoseDigits(String digits) {
    if (digits.isEmpty) return digits;
    switch (digits) {
      case '19':
      case '18':
      case '16':
      case '14':
      case '12':
      case '11':
      case '0':
        return '10';
      case '26':
      case '28':
      case '23':
      case '29':
        return '25';
      case '38':
      case '39':
      case '32':
      case '80':
        return '30';
      case '119':
      case '118':
      case '100':
      case '116':
        return '110';
      default:
        return digits;
    }
  }

  /// พอร์ตฟังก์ชัน `resolve_fingerprint_match` จาก `src/classifiers.py`
  /// เพื่อดึงเอกลักษณ์เฉพาะของรหัสยาแม้ตัวอักษรบางตัวเลือนหรืออ่านติดกัน
  static String? resolveFingerprintMatch(String rawText) {
    final String c = rawText.toUpperCase().replaceAll(RegExp(r'[^A-Z0-9]'), '');
    if (c.isEmpty) return null;

    if (c.contains('AMS') || c.contains('AM5') || (c.contains('AM') && c.contains('1010'))) {
      return c.contains('1010') ? 'AMS10/10' : 'AMS20';
    }
    if ((c.contains('AMC') || c.contains('AIVIC')) && c.contains('2010')) {
      return 'AMC20/10';
    }
    if (c.contains('AZT')) {
      return 'AZT30';
    }
    if (c.contains('SAM')) {
      return 'SAM20';
    }
    if (c.contains('TAZ') || c.contains('IAZ') || c.contains('110') || c.contains('119')) {
      return 'TAZ110';
    }
    if (c.contains('IMI') || c.contains('IM1') || c.contains('INI') || c.contains('IWI') ||
        (c.contains('IM') && !c.contains('AM') && (c.contains('10') || c.contains('19') || c.contains('18')))) {
      return 'IMI10';
    }
    if (c.contains('IPM')) {
      return 'IPM10';
    }
    if ((c.contains('TS') || c.contains('T5') || c.contains('7S') || c.contains('IS')) &&
        (c.contains('25') || c.contains('26') || c.contains('28') || c.length <= 4)) {
      if (!c.contains('CTX') && !c.contains('FOX')) {
        return 'TS25';
      }
    }
    if (c.contains('SXT') || (c.contains('X') && !c.contains('FOX') && !c.contains('CTX') && c.contains('25'))) {
      return 'SXT25';
    }
    if (c.contains('CAZ') || (c.contains('Z') && !c.contains('TPZ') && !c.contains('TZP') && !c.contains('TAZ'))) {
      return c.contains('10') ? 'CAZ10' : 'CAZ30';
    }
    if (c.contains('TPZ') || c.contains('TZP') || c.contains('36')) {
      return 'TZP36';
    }
    if (c.contains('FOX') || (c.contains('OX') && c.contains('30'))) {
      return 'FOX30';
    }
    if (c.contains('FEP') || (c.contains('EP') && c.contains('30'))) {
      return 'FEP30';
    }
    if (c.contains('MEM') || (c.contains('EM') && (c.contains('10') || c.contains('19')))) {
      return 'MEM10';
    }
    if (c.contains('CPD') || c.contains('CPO') || (c.contains('PD') && c.contains('10'))) {
      return 'CPD10';
    }
    if (c.contains('CRO') || (c.contains('RO') && c.contains('30'))) {
      return 'CRO30';
    }
    if (c.contains('TOB') || (c.contains('OB') && c.contains('10'))) {
      return 'TOB10';
    }
    if (c.contains('ETP')) {
      return 'ETP10';
    }
    if (c.contains('PEF') || (c.contains('EF') && c.contains('5'))) {
      return 'PEF5';
    }
    if (c.contains('CIP') || (c.contains('IP') && c.contains('5'))) {
      return 'CIP5';
    }
    if (c.contains('LEV')) {
      return 'LEV5';
    }
    if (c.contains('AK') && (c.contains('30') || c.length <= 4)) {
      return 'AK30';
    }
    if (c.contains('CN') && (c.contains('10') || c.contains('19') || c.length <= 4)) {
      return 'CN10';
    }
    if (c.contains('AMC') || c.contains('AIVIC') || (c.contains('MC') && c.contains('30'))) {
      return 'AMC30';
    }
    if (c.contains('AMP') || (c.contains('MP') && (c.contains('10') || c.contains('19')))) {
      return 'AMP10';
    }
    if (c.contains('TE') && (c.contains('30') || c.contains('38'))) {
      return 'TE30';
    }
    return null;
  }

  static List<String> normalizeOcrTokenVariants(String rawText) {
    final String clean = rawText.toUpperCase().replaceAll(RegExp(r'[^A-Z0-9]'), '');
    if (clean.isEmpty) return const <String>[];

    final List<String> variants = <String>[clean];
    final String? fp = resolveFingerprintMatch(clean);
    if (fp != null && !variants.contains(fp)) {
      variants.insert(0, fp);
    }

    const Map<String, String> letterMap = {
      '0': 'O',
      '1': 'I',
      '5': 'S',
      '8': 'B',
      '2': 'Z',
      '7': 'T',
      '4': 'A',
    };
    const Map<String, String> digitMap = {
      'O': '0',
      'Q': '0',
      'D': '0',
      'I': '1',
      'L': '1',
      'S': '5',
      'B': '8',
      'Z': '2',
      'G': '6',
    };

    String translateChars(String s, Map<String, String> m) {
      final StringBuffer sb = StringBuffer();
      for (int i = 0; i < s.length; i++) {
        final String ch = s[i];
        sb.write(m[ch] ?? ch);
      }
      return sb.toString();
    }

    if (RegExp(r'^\d+$').hasMatch(clean)) {
      final String snapped = _snapConfusedDoseDigits(clean);
      if (!variants.contains(snapped)) variants.add(snapped);
    }

    final int maxSplit = math.min(5, clean.length + 1);
    for (int splitPos = 1; splitPos < maxSplit; splitPos++) {
      final String head = translateChars(clean.substring(0, splitPos), letterMap);
      final String tail = translateChars(clean.substring(splitPos), digitMap);
      final bool headIsAlpha = RegExp(r'^[A-Z]+$').hasMatch(head);
      final bool tailIsDigit = tail.isEmpty || RegExp(r'^[0-9]+$').hasMatch(tail);
      if (headIsAlpha && tailIsDigit) {
        final String cand = '$head$tail';
        if (!variants.contains(cand)) variants.add(cand);
        final String snappedTail = _snapConfusedDoseDigits(tail);
        if (snappedTail != tail) {
          final String snappedCand = '$head$snappedTail';
          if (!variants.contains(snappedCand)) variants.add(snappedCand);
        }
        final String? fpCand = resolveFingerprintMatch('$head$snappedTail');
        if (fpCand != null && !variants.contains(fpCand)) {
          variants.insert(0, fpCand);
        }
      }
      if (headIsAlpha && !variants.contains(head)) {
        variants.add(head);
      }
    }

    final RegExp revMatch = RegExp(r'^(\d{1,3})([A-Z]{1,4})$');
    final Match? mRev = revMatch.firstMatch(clean);
    if (mRev != null) {
      final String dPart = _snapConfusedDoseDigits(mRev.group(1)!);
      final String aPart = mRev.group(2)!;
      final String reordered = '$aPart$dPart';
      if (!variants.contains(reordered)) variants.add(reordered);
      final String? fpRev = resolveFingerprintMatch(reordered);
      if (fpRev != null && !variants.contains(fpRev)) {
        variants.insert(0, fpRev);
      }
    }

    return variants;
  }

  static ({String prefix, String digits}) _splitAlphaNumCode(String code) {
    final String clean = code.toUpperCase().replaceAll(RegExp(r'[^A-Z0-9]'), '');
    final RegExp m = RegExp(r'^([A-Z]+)(\d*)$');
    final Match? match = m.firstMatch(clean);
    if (match != null) {
      return (prefix: match.group(1) ?? '', digits: match.group(2) ?? '');
    }
    return (
      prefix: clean.replaceAll(RegExp(r'[^A-Z]'), ''),
      digits: clean.replaceAll(RegExp(r'[^0-9]'), ''),
    );
  }

  static double _prefixSimilarity(String a, String b) {
    if (a.isEmpty || b.isEmpty) return 0.0;
    if (a == b) return 1.0;
    if (a.contains(b) || b.contains(a)) {
      return (2.0 * math.min(a.length, b.length)) / (a.length + b.length);
    }
    int i = 0;
    int inOrder = 0;
    for (int idx = 0; idx < a.length; idx++) {
      final int pos = b.indexOf(a[idx], i);
      if (pos != -1) {
        inOrder++;
        i = pos + 1;
      }
    }
    final Set<String> setA = a.split('').toSet();
    final Set<String> setB = b.split('').toSet();
    final int commonSet = setA.intersection(setB).length;
    final double bestMatch = math.max(inOrder.toDouble(), commonSet * 0.85);
    return math.min(0.95, (2.0 * bestMatch) / (a.length + b.length));
  }

  static bool isTe30BrownDisc(img.Image plateImage, double cx, double cy, double rDiscPx) {
    final int rInner = math.max(4, (rDiscPx * 0.58).round());
    final List<double> rVals = <double>[];
    final List<double> gVals = <double>[];
    final List<double> bVals = <double>[];

    for (int dy = -rInner; dy <= rInner; dy += 2) {
      for (int dx = -rInner; dx <= rInner; dx += 2) {
        if (dx * dx + dy * dy > rInner * rInner) continue;
        final int px = (cx + dx).round().clamp(0, plateImage.width - 1);
        final int py = (cy + dy).round().clamp(0, plateImage.height - 1);
        final p = plateImage.getPixel(px, py);
        rVals.add(p.r.toDouble());
        gVals.add(p.g.toDouble());
        bVals.add(p.b.toDouble());
      }
    }
    if (rVals.isEmpty) return false;
    rVals.sort();
    gVals.sort();
    bVals.sort();
    final double medR = rVals[rVals.length ~/ 2];
    final double medG = gVals[gVals.length ~/ 2];
    final double medB = bVals[bVals.length ~/ 2];
    return (medR - medG) >= 22.0 && (medR - medB) >= 40.0;
  }

  static List<OcrCandidateScore> rankAllDrugsFromOcr({
    required List<String> rawTexts,
    bool isBrownTe30 = false,
  }) {
    final List<String> allCodes =
        kClsiEucastDb.keys.where((k) => k != 'UNKNOWN' && k != 'DISC').toList();
    final Map<String, double> scores = {for (final c in allCodes) c: 0.01};

    final List<String> normalizedTokens = <String>[];
    for (final raw in rawTexts) {
      final String? fpDirect = resolveFingerprintMatch(raw);
      if (fpDirect != null && scores.containsKey(fpDirect)) {
        scores[fpDirect] = math.max(scores[fpDirect]!, 0.96);
      }
      for (final v in normalizeOcrTokenVariants(raw)) {
        if (v.isNotEmpty && !normalizedTokens.contains(v)) {
          normalizedTokens.add(v);
        }
      }
    }

    if (isBrownTe30 && scores.containsKey('TE30')) {
      scores['TE30'] = math.max(scores['TE30']!, 0.94);
    }

    for (final code in allCodes) {
      final kSplit = _splitAlphaNumCode(code);
      final String kPrefix = kSplit.prefix;
      final String kNum = kSplit.digits;
      double bestForCode = scores[code] ?? 0.01;

      for (final tok in normalizedTokens) {
        final tSplit = _splitAlphaNumCode(tok);
        final String tPrefix = tSplit.prefix;
        final String tNum = _snapConfusedDoseDigits(tSplit.digits);

        if (tok == code || (tPrefix == kPrefix && tNum == kNum && kPrefix.isNotEmpty)) {
          bestForCode = math.max(bestForCode, 0.98);
          continue;
        }

        final String? mappedAlias = kDrugPrefixAliases[tPrefix] ?? kDrugPrefixAliases[tok];
        if (mappedAlias == code) {
          if (tNum == kNum && kNum.isNotEmpty) {
            bestForCode = math.max(bestForCode, 0.96);
          } else if (tNum.isEmpty) {
            bestForCode = math.max(bestForCode, tPrefix.length >= 2 ? 0.88 : 0.45);
          } else {
            bestForCode = math.max(bestForCode, 0.76);
          }
          continue;
        }

        double pSim = (tPrefix.isNotEmpty && kPrefix.isNotEmpty)
            ? _prefixSimilarity(tPrefix, kPrefix)
            : 0.0;
        if (mappedAlias != null) {
          final aliasSplit = _splitAlphaNumCode(mappedAlias);
          pSim = math.max(pSim, _prefixSimilarity(aliasSplit.prefix, kPrefix) * 0.95);
        }

        final bool doseExact = tNum.isNotEmpty && kNum.isNotEmpty && tNum == kNum;
        final bool dosePartial = tNum.isNotEmpty &&
            kNum.isNotEmpty &&
            !doseExact &&
            (tNum.contains(kNum) || kNum.contains(tNum));

        double candScore = 0.01;
        if (pSim >= 0.99) {
          if (doseExact) {
            candScore = 0.97;
          } else if (tNum.isEmpty) {
            candScore = kPrefix.length >= 2 ? 0.86 : 0.45;
          } else if (dosePartial) {
            candScore = 0.91;
          } else {
            candScore = 0.68;
          }
        } else if (pSim >= 0.55) {
          if (doseExact) {
            candScore = math.min(0.89, 0.52 * pSim + 0.36);
          } else if (dosePartial) {
            candScore = 0.48 * pSim + 0.18;
          } else if (tNum.isEmpty) {
            candScore = 0.45 * pSim;
          } else {
            candScore = 0.35 * pSim;
          }
        } else if (pSim > 0.0) {
          if (doseExact) {
            candScore = 0.32 * pSim + 0.24;
          } else if (dosePartial) {
            candScore = 0.25 * pSim + 0.10;
          } else {
            candScore = 0.18 * pSim;
          }
        } else {
          if (doseExact) {
            candScore = (kNum == '110' || kNum == '25' || kNum == '36' || kNum == '75') ? 0.62 : 0.32;
          } else if (dosePartial) {
            candScore = 0.14;
          } else {
            candScore = 0.01;
          }
        }

        bestForCode = math.max(bestForCode, candScore);
      }

      scores[code] = double.parse(math.min(0.99, bestForCode).toStringAsFixed(3));
    }

    const List<String> commonPriority = <String>[
      'AMC30', 'AMS20', 'AMP10', 'CAZ30', 'CIP5', 'CN10', 'CRO30',
      'CTX30', 'FEP30', 'FOX30', 'IMI10', 'MEM10', 'SXT25', 'TS25',
      'TAZ110', 'TE30', 'TZP36', 'AK30',
    ];
    for (int i = 0; i < commonPriority.length; i++) {
      final String c = commonPriority[i];
      if (scores.containsKey(c) && (scores[c] ?? 0.0) <= 0.02) {
        scores[c] = double.parse((0.15 - i * 0.005).clamp(0.05, 0.15).toStringAsFixed(3));
      }
    }

    final List<OcrCandidateScore> ranked = allCodes
        .map((c) => OcrCandidateScore(code: c, confidence: scores[c] ?? 0.02))
        .toList()
      ..sort((a, b) {
        final int cmp = b.confidence.compareTo(a.confidence);
        return cmp != 0 ? cmp : a.code.compareTo(b.code);
      });
    return ranked;
  }

  static List<OcrCandidateScore> rankCandidatesForDisc(DiscRecord disc) {
    final List<String> seedTexts = <String>[
      if (disc.rawOcrText.trim().isNotEmpty) disc.rawOcrText.trim(),
      if (disc.drugCode.trim().isNotEmpty &&
          disc.drugCode != 'UNKNOWN' &&
          disc.drugCode != 'DISC')
        disc.drugCode.trim(),
    ];
    final List<OcrCandidateScore> baseList = disc.ocrCandidates.isNotEmpty
        ? List<OcrCandidateScore>.from(
            disc.ocrCandidates.where((c) => kClsiEucastDb.containsKey(c.code) && c.code != 'UNKNOWN'),
          )
        : rankAllDrugsFromOcr(rawTexts: seedTexts);

    final String current = disc.drugCode.trim().toUpperCase();
    if (current != 'UNKNOWN' && current != 'DISC' && kClsiEucastDb.containsKey(current)) {
      final int idx = baseList.indexWhere((c) => c.code == current);
      if (idx >= 0 && disc.isManualEntry) {
        baseList[idx] = OcrCandidateScore(code: current, confidence: 1.0);
      } else if (idx < 0) {
        baseList.insert(0, OcrCandidateScore(code: current, confidence: disc.confidence));
      }
    }
    baseList.sort((a, b) {
      final int cmp = b.confidence.compareTo(a.confidence);
      return cmp != 0 ? cmp : a.code.compareTo(b.code);
    });
    return baseList;
  }

  // --------------------------------------------------------------------------
  // 3.2 การหมุนตั้งตรงอัตโนมัติด้วย Underline Bar + Two-Row Horizontal Projection
  //     (แก้ปัญหาเม็ดยาเอียง 35°/45°/135° หรือไม่มีขีดเส้นใต้ เช่น TS 25, TAZ 110, IMI 10)
  // --------------------------------------------------------------------------
  static double estimateUnderlineUprightAngle(
    img.Image plateImage,
    double cx,
    double cy,
    double rDiscPx,
  ) {
    final List<double> lumas = <double>[];
    final double rLim = math.max(6.0, rDiscPx * 0.85);
    for (double dy = -rLim; dy <= rLim; dy += 2.0) {
      for (double dx = -rLim; dx <= rLim; dx += 2.0) {
        if (dx * dx + dy * dy > rLim * rLim) continue;
        final int px = (cx + dx).round().clamp(0, plateImage.width - 1);
        final int py = (cy + dy).round().clamp(0, plateImage.height - 1);
        final p = plateImage.getPixel(px, py);
        lumas.add(0.299 * p.r + 0.587 * p.g + 0.114 * p.b);
      }
    }
    if (lumas.isEmpty) return 0.0;
    lumas.sort();
    final double paperMed = lumas[(lumas.length * 0.72).floor().clamp(0, lumas.length - 1)];

    double bestAxisDeg = 0.0;
    double bestBimodalScore = -1e9;
    bool topWiderAtBest = true;
    bool barAtBottomAtBest = false;

    // ใช้มุม -deg เพื่อให้ตรงกับทิศทางการหมุนของ renderCleanDiscForOcr และ Transform.rotate 100%
    for (int deg = 0; deg < 180; deg += 5) {
      final double rad = -deg * math.pi / 180.0;
      final double cosA = math.cos(rad);
      final double sinA = math.sin(rad);

      double upperEnergy = 0.0;
      double lowerEnergy = 0.0;
      double centerValley = 0.0;
      double topMaxSpan = 0.0;
      double botMaxSpan = 0.0;
      double botBarScore = 0.0;
      double topBarScore = 0.0;

      for (int b = -14; b <= 14; b++) {
        final double ny = b * 0.05;
        double rowInk = 0.0;
        double minNx = 1.0, maxNx = -1.0;
        int inkHits = 0;
        for (int s = -12; s <= 12; s++) {
          final double nx = s * 0.06;
          if (nx * nx + ny * ny > 0.80 * 0.80) continue;
          final double sx = cx + (nx * cosA - ny * sinA) * rDiscPx;
          final double sy = cy + (nx * sinA + ny * cosA) * rDiscPx;
          final int ix = sx.round().clamp(0, plateImage.width - 1);
          final int iy = sy.round().clamp(0, plateImage.height - 1);
          final p = plateImage.getPixel(ix, iy);
          final double luma = 0.299 * p.r + 0.587 * p.g + 0.114 * p.b;
          final double ink = math.max(0.0, paperMed - 14.0 - luma);
          if (ink > 0) {
            rowInk += ink;
            inkHits++;
            if (nx < minNx) minNx = nx;
            if (nx > maxNx) maxNx = nx;
          }
        }
        final double span = inkHits >= 2 ? (maxNx - minNx) : 0.0;
        if (ny >= -0.60 && ny <= -0.10) {
          upperEnergy += rowInk;
          if (span > topMaxSpan) topMaxSpan = span;
          if (ny <= -0.42 && inkHits >= 6 && span >= 0.42) topBarScore += rowInk;
        } else if (ny >= 0.10 && ny <= 0.60) {
          lowerEnergy += rowInk;
          if (span > botMaxSpan) botMaxSpan = span;
          if (ny >= 0.42 && inkHits >= 6 && span >= 0.42) botBarScore += rowInk;
        } else if (ny.abs() < 0.10) {
          centerValley += rowInk;
        }
      }

      final double bimodal =
          ((upperEnergy * lowerEnergy) * 0.001 + (upperEnergy + lowerEnergy)) /
          (1.0 + 2.4 * centerValley);
      if (bimodal > bestBimodalScore) {
        bestBimodalScore = bimodal;
        bestAxisDeg = deg.toDouble();
        topWiderAtBest = (upperEnergy * (topMaxSpan + 0.2)) >= (lowerEnergy * (botMaxSpan + 0.2));
        barAtBottomAtBest = botBarScore > topBarScore * 1.25;
      }
    }

    if (barAtBottomAtBest) {
      return bestAxisDeg;
    }
    return topWiderAtBest ? bestAxisDeg : ((bestAxisDeg + 180.0) % 360.0);
  }

  /// ปรับระดับแนวนอนละเอียด (±14° ทีละ 2°) รอบมุมตั้งตรงที่ชนะ เพื่อให้บรรทัดตัวอักษรบนและตัวเลขล่างขนานกับแนวนอนเป๊ะ
  static double refineDiscHorizontalLevelAngle(
    img.Image plateImage,
    double cx,
    double cy,
    double rDiscPx,
    double coarseUprightDeg,
  ) {
    final List<double> lumas = <double>[];
    final double rLim = math.max(6.0, rDiscPx * 0.82);
    for (double dy = -rLim; dy <= rLim; dy += 2.0) {
      for (double dx = -rLim; dx <= rLim; dx += 2.0) {
        if (dx * dx + dy * dy > rLim * rLim) continue;
        final int px = (cx + dx).round().clamp(0, plateImage.width - 1);
        final int py = (cy + dy).round().clamp(0, plateImage.height - 1);
        final p = plateImage.getPixel(px, py);
        lumas.add(0.299 * p.r + 0.587 * p.g + 0.114 * p.b);
      }
    }
    if (lumas.isEmpty) return coarseUprightDeg;
    lumas.sort();
    final double paperMed = lumas[(lumas.length * 0.72).floor().clamp(0, lumas.length - 1)];

    double bestDeg = coarseUprightDeg;
    double bestScore = -1e9;
    for (double delta = -14.0; delta <= 14.0; delta += 2.0) {
      final double candDeg = (coarseUprightDeg + delta + 360.0) % 360.0;
      final double rad = -candDeg * math.pi / 180.0;
      final double cosA = math.cos(rad);
      final double sinA = math.sin(rad);

      double upperE = 0.0;
      double lowerE = 0.0;
      double valleyE = 0.0;
      double rowVarSum = 0.0;

      for (int b = -14; b <= 14; b++) {
        final double ny = b * 0.045;
        double rowInk = 0.0;
        for (int s = -12; s <= 12; s++) {
          final double nx = s * 0.055;
          if (nx * nx + ny * ny > 0.78 * 0.78) continue;
          final int ix = (cx + (nx * cosA - ny * sinA) * rDiscPx).round().clamp(0, plateImage.width - 1);
          final int iy = (cy + (nx * sinA + ny * cosA) * rDiscPx).round().clamp(0, plateImage.height - 1);
          final p = plateImage.getPixel(ix, iy);
          final double luma = 0.299 * p.r + 0.587 * p.g + 0.114 * p.b;
          final double ink = math.max(0.0, paperMed - 14.0 - luma);
          rowInk += ink;
        }
        rowVarSum += rowInk * rowInk;
        if (ny >= -0.58 && ny <= -0.10) {
          upperE += rowInk;
        } else if (ny >= 0.10 && ny <= 0.58) {
          lowerE += rowInk;
        } else if (ny.abs() < 0.10) {
          valleyE += rowInk;
        }
      }
      // ลงโทษเล็กน้อยถ้าห่างจากมุมเดิมมาก เพื่อป้องกันการแกว่ง
      final double score =
          ((upperE * lowerE) * 0.001 + rowVarSum * 0.0005) / (1.0 + 2.8 * valleyE) -
          delta.abs() * 0.02;
      if (score > bestScore) {
        bestScore = score;
        bestDeg = candDeg;
      }
    }
    return bestDeg;
  }

  /// จัดเรียงข้อความที่อ่านได้ภายในเม็ดยาให้ "อ่านตัวบน (ตัวอักษรย่อชื่อยา) ก่อนตัวล่าง (ตัวเลขความแรงยา)" เสมอ
  /// และคำนวณมุมชดเชยเวกเตอร์ (angleCorrectionDeg = atan2(vx, vy)) จากจุดกึ่งกลางแถวตัวอักษรไปยังจุดกึ่งกลางแถวตัวเลข
  /// เพื่อหมุนเม็ดยาให้แถวตัวอักษรอยู่ด้านบน (12 นาฬิกา) และแถวตัวเลขอยู่ด้านล่าง (6 นาฬิกา) ตั้งตรงเป๊ะ
  /// แยกโทเคนที่มีทั้งตัวอักษรและตัวเลขติดกันในก้อนเดียว (เช่น "30FEP" หรือ "FEP30") ให้ตัวอักษรขึ้นก่อนตัวเลขเสมอ
  static String reorderSingleTokenTopFirst(String dispTok) {
    final RegExp revSingle = RegExp(r'^(\d+(?:/\d+)?)([A-Z]{1,4})$');
    final Match? mRev = revSingle.firstMatch(dispTok);
    if (mRev != null) {
      return '${mRev.group(2)!} ${mRev.group(1)!}';
    }
    final RegExp fwdSingle = RegExp(r'^([A-Z]{1,4})(\d+(?:/\d+)?)$');
    final Match? mFwd = fwdSingle.firstMatch(dispTok);
    if (mFwd != null) {
      return '${mFwd.group(1)!} ${mFwd.group(2)!}';
    }
    return dispTok;
  }

  static ({
    String display,
    String clean,
    bool isUprightTwoRow,
    bool isUpsideDownTwoRow,
    bool hasTwoRowVector,
    double angleCorrectionDeg,
  }) _assembleCellTopRowFirst(
    List<({double y, double x, String display, String clean})> rawItems,
    double cellLeftX,
    double cellTopY,
    double cellSize,
  ) {
    if (rawItems.isEmpty) {
      return (
        display: '',
        clean: '',
        isUprightTwoRow: false,
        isUpsideDownTwoRow: false,
        hasTwoRowVector: false,
        angleCorrectionDeg: 0.0,
      );
    }

    // แยกกลุ่มโทเคนที่เป็นตัวอักษรชื่อยา (Alpha) และตัวเลขความแรงยา (Digit/Slash)
    final List<({double y, double x, String display, String clean})> alphaItems = [];
    final List<({double y, double x, String display, String clean})> digitItems = [];

    for (final item in rawItems) {
      final bool hasAlpha = RegExp(r'[A-Z]').hasMatch(item.clean);
      final bool isPureDigitSlash =
          RegExp(r'^[0-9/]+$').hasMatch(item.display) && !hasAlpha;
      if (isPureDigitSlash) {
        digitItems.add(item);
      } else if (hasAlpha) {
        alphaItems.add(item);
      }
    }

    // กรณีพบทั้งก้อนตัวอักษร (เช่น FEP, TAZ, AMC, AMS, AZT) และก้อนตัวเลข (เช่น 30, 110, 20/10, 10/10)
    if (alphaItems.isNotEmpty && digitItems.isNotEmpty) {
      double alphaCx = 0.0, alphaCy = 0.0;
      for (final a in alphaItems) {
        alphaCx += a.x;
        alphaCy += a.y;
      }
      alphaCx /= alphaItems.length;
      alphaCy /= alphaItems.length;

      double digitCx = 0.0, digitCy = 0.0;
      for (final d in digitItems) {
        digitCx += d.x;
        digitCy += d.y;
      }
      digitCx /= digitItems.length;
      digitCy /= digitItems.length;

      // เวกเตอร์จากแถวตัวอักษร (ต้องอยู่ด้านบน 12 นาฬิกา) ไปยังแถวตัวเลข (ต้องอยู่ด้านล่าง 6 นาฬิกา)
      final double vx = digitCx - alphaCx;
      final double vy = digitCy - alphaCy;
      final double distRows = math.sqrt(vx * vx + vy * vy);
      // มุมที่ต้องหมุนตามเข็มนาฬิกาเพื่อให้เวกเตอร์ (vx, vy) ชี้ลงด้านล่างตรงๆ (vx_new = 0, vy_new > 0)
      final double corrDeg = distRows >= 6.0 ? (math.atan2(vx, vy) * 180.0 / math.pi) : 0.0;
      final bool isUpright = corrDeg.abs() <= 38.0 && vy >= 10.0;
      final bool isUpsideDown = corrDeg.abs() >= 135.0 && vy <= -10.0;

      // เรียงตัวอักษรและตัวเลขจากซ้ายไปขวาในแกนที่หมุนตั้งตรงแล้ว
      final double rad = corrDeg * math.pi / 180.0;
      final double cosA = math.cos(rad);
      final double sinA = math.sin(rad);
      double projX(({double y, double x, String display, String clean}) e) =>
          e.x * cosA - e.y * sinA;

      alphaItems.sort((a, b) => projX(a).compareTo(projX(b)));
      digitItems.sort((a, b) => projX(a).compareTo(projX(b)));

      // อ่านแถวบน (ตัวอักษรชื่อยา) ก่อนแถวล่าง (ตัวเลขความแรงยา) เสมอ!
      final String topDisp = alphaItems
          .map((e) => reorderSingleTokenTopFirst(e.display).replaceAll(' ', ''))
          .join();
      final String botDisp = digitItems.map((e) => e.display).join();
      final String topClean = alphaItems.map((e) => e.clean).join();
      final String botClean = digitItems.map((e) => e.clean).join();

      return (
        display: '$topDisp $botDisp',
        clean: '$topClean$botClean',
        isUprightTwoRow: isUpright,
        isUpsideDownTwoRow: isUpsideDown,
        hasTwoRowVector: distRows >= 6.0,
        angleCorrectionDeg: corrDeg,
      );
    }

    // กรณีมีเพียง 1 โทเคนในช่องนั้น
    if (rawItems.length == 1) {
      final String d0 = rawItems.first.display;
      final String c0 = rawItems.first.clean;
      final bool startsWithDigitThenAlpha = RegExp(r'^\d+(?:/\d+)?[A-Z]{1,4}$').hasMatch(d0);
      final String fixedDisp = reorderSingleTokenTopFirst(d0);
      final String fixedClean = fixedDisp.replaceAll(RegExp(r'[^A-Z0-9]'), '');
      final double localX = rawItems.first.x - cellLeftX - (cellSize * 0.5);
      final double localY = rawItems.first.y - cellTopY - (cellSize * 0.5);
      final bool isAlphaOnly = RegExp(r'^[A-Z]{1,4}$').hasMatch(c0);
      final bool isDigitOnly = RegExp(r'^[0-9/]+$').hasMatch(d0);

      if (startsWithDigitThenAlpha) {
        return (
          display: fixedDisp,
          clean: fixedClean,
          isUprightTwoRow: false,
          isUpsideDownTwoRow: true,
          hasTwoRowVector: true,
          angleCorrectionDeg: 180.0,
        );
      }
      if (isAlphaOnly) {
        // ตัวอักษรชื่อยาควรอยู่ครึ่งบนของเม็ดยา (localY < 0)
        final bool inUpperHalf = localY <= 0.0;
        final double corr =
            (localX.abs() + localY.abs() >= 6.0) ? (math.atan2(-localX, -localY) * 180.0 / math.pi) : 0.0;
        return (
          display: fixedDisp,
          clean: fixedClean,
          isUprightTwoRow: inUpperHalf && corr.abs() <= 45.0,
          isUpsideDownTwoRow: !inUpperHalf && corr.abs() >= 135.0,
          hasTwoRowVector: false,
          angleCorrectionDeg: inUpperHalf ? corr.clamp(-20.0, 20.0) : 180.0,
        );
      }
      if (isDigitOnly) {
        // ตัวเลขความแรงยาควรอยู่ครึ่งล่างของเม็ดยา (localY >= 0)
        final bool inLowerHalf = localY >= 0.0;
        return (
          display: fixedDisp,
          clean: fixedClean,
          isUprightTwoRow: inLowerHalf,
          isUpsideDownTwoRow: !inLowerHalf,
          hasTwoRowVector: false,
          angleCorrectionDeg: inLowerHalf ? 0.0 : 180.0,
        );
      }
      return (
        display: fixedDisp,
        clean: fixedClean,
        isUprightTwoRow: localY <= 4.0,
        isUpsideDownTwoRow: false,
        hasTwoRowVector: false,
        angleCorrectionDeg: 0.0,
      );
    }

    // กรณีมีหลายโทเคนชนิดเดียวกัน: เรียงจากบนลงล่าง แล้วซ้ายไปขวา
    final List<({double y, double x, String display, String clean})> sorted =
        List.from(rawItems)
          ..sort((a, b) {
            if ((a.y - b.y).abs() >= 12.0) return a.y.compareTo(b.y);
            return a.x.compareTo(b.x);
          });
    final String joinedDisp =
        sorted.map((e) => reorderSingleTokenTopFirst(e.display)).join(' ');
    final String joinedClean =
        joinedDisp.replaceAll(RegExp(r'[^A-Z0-9]'), '');
    return (
      display: joinedDisp,
      clean: joinedClean,
      isUprightTwoRow: false,
      isUpsideDownTwoRow: false,
      hasTwoRowVector: false,
      angleCorrectionDeg: 0.0,
    );
  }

  /// พอร์ตฟังก์ชัน `_prepare_circular_disc_variants_for_ocr` จาก `src/api_server.py`:
  /// - เก็บเนื้อกระดาษด้านในถึง `0.93 * rDiscPx` เพื่อรักษาตัวอักษรแถวบนสุด (`IMI`, `TAZ`, `TS`, `FEP`)
  /// - ถมพื้นที่นอกวงกลมแผ่นยาด้วยสีเนื้อกระดาษ/สีขาว และเว้นขอบขาวรอบด้าน (White Margin Padding)
  /// - รองรับ 3 โหมด:
  ///   mode 0 = Local Contrast Normalized (CLAHE 2D Integral Image)
  ///   mode 1 = Percentile P8-P88 Contrast Stretch บนพื้นขาว 255
  ///   mode 2 = Local Adaptive Gaussian Threshold (หน้าต่าง 25x25 พิกเซล ตัดหมึกดำคมชัดบนพื้นขาว 255)
  static img.Image renderCleanDiscForOcr({
    required img.Image plateImage,
    required double cx,
    required double cy,
    required double rDiscPx,
    double? rxDiscPx,
    double? ryDiscPx,
    required double rotDeg,
    int cellSize = 220,
    int discRadiusInCell = 80,
    int mode = 0,
  }) {
    final double effRx = rxDiscPx ?? rDiscPx;
    final double effRy = ryDiscPx ?? rDiscPx;
    final img.Image out = img.Image(width: cellSize, height: cellSize);
    final double half = cellSize / 2.0;
    final double rad = -rotDeg * math.pi / 180.0;
    final double cosA = math.cos(rad);
    final double sinA = math.sin(rad);

    final List<double> innerLumas = <double>[];
    final double rSample = math.max(6.0, rDiscPx * 0.82);
    for (double dy = -rSample; dy <= rSample; dy += 2.0) {
      for (double dx = -rSample; dx <= rSample; dx += 2.0) {
        if (dx * dx + dy * dy > rSample * rSample) continue;
        final int px = (cx + dx).round().clamp(0, plateImage.width - 1);
        final int py = (cy + dy).round().clamp(0, plateImage.height - 1);
        final p = plateImage.getPixel(px, py);
        innerLumas.add(0.299 * p.r + 0.587 * p.g + 0.114 * p.b);
      }
    }
    innerLumas.sort();
    final double p8 = innerLumas.isNotEmpty
        ? innerLumas[(innerLumas.length * 0.08).floor().clamp(0, innerLumas.length - 1)]
        : 45.0;
    final double p75 = innerLumas.isNotEmpty
        ? innerLumas[(innerLumas.length * 0.75).floor().clamp(0, innerLumas.length - 1)]
        : 225.0;
    final double p88 = innerLumas.isNotEmpty
        ? innerLumas[(innerLumas.length * 0.88).floor().clamp(0, innerLumas.length - 1)]
        : 238.0;
    final int paperBg = mode == 0 ? p75.round().clamp(195, 248) : 255;
    final double denom = math.max(22.0, p88 - p8);

    final Float32List stretchedGrid = Float32List(cellSize * cellSize);
    final Float32List rawGrid = Float32List(cellSize * cellSize);

    for (int y = 0; y < cellSize; y++) {
      for (int x = 0; x < cellSize; x++) {
        final double dxCell = x - half;
        final double dyCell = y - half;
        final double distCell = math.sqrt(dxCell * dxCell + dyCell * dyCell);
        if (distCell > discRadiusInCell) {
          rawGrid[y * cellSize + x] = paperBg.toDouble();
          stretchedGrid[y * cellSize + x] = 255.0;
          continue;
        }

        final double normX = dxCell / discRadiusInCell;
        final double normY = dyCell / discRadiusInCell;
        // ดึงภาพเม็ดยาที่ถ่ายมุมเอียง (วงรี effRx x effRy) ให้กลับมาตั้งฉากเป็นวงกลมสมมาตรก่อนหมุนอ่าน OCR
        final double uRot = normX * cosA - normY * sinA;
        final double vRot = normX * sinA + normY * cosA;
        final double rx = uRot * (effRx * 0.93);
        final double ry = vRot * (effRy * 0.93);

        final int sx = (cx + rx).round().clamp(0, plateImage.width - 1);
        final int sy = (cy + ry).round().clamp(0, plateImage.height - 1);
        final p = plateImage.getPixel(sx, sy);
        final double rawLuma = 0.299 * p.r + 0.587 * p.g + 0.114 * p.b;
        final double strVal = ((rawLuma - p8) * (255.0 / denom)).clamp(0.0, 255.0);

        if (distCell > discRadiusInCell * 0.90) {
          final double blend =
              ((distCell - discRadiusInCell * 0.90) / (discRadiusInCell * 0.10)).clamp(0.0, 1.0);
          rawGrid[y * cellSize + x] = rawLuma * (1.0 - blend) + paperBg * blend;
          stretchedGrid[y * cellSize + x] = strVal * (1.0 - blend) + 255.0 * blend;
        } else {
          rawGrid[y * cellSize + x] = rawLuma;
          stretchedGrid[y * cellSize + x] = strVal;
        }
      }
    }

    if (mode == 0 || mode == 2) {
      final Float64List sat = Float64List((cellSize + 1) * (cellSize + 1));
      final Float32List src = mode == 0 ? rawGrid : stretchedGrid;
      for (int y = 0; y < cellSize; y++) {
        double rSum = 0.0;
        for (int x = 0; x < cellSize; x++) {
          rSum += src[y * cellSize + x];
          sat[(y + 1) * (cellSize + 1) + (x + 1)] = sat[y * (cellSize + 1) + (x + 1)] + rSum;
        }
      }

      double localMean(int x, int y, int halfWin) {
        final int x1 = (x - halfWin).clamp(0, cellSize);
        final int y1 = (y - halfWin).clamp(0, cellSize);
        final int x2 = (x + halfWin + 1).clamp(0, cellSize);
        final int y2 = (y + halfWin + 1).clamp(0, cellSize);
        final int area = math.max(1, (x2 - x1) * (y2 - y1));
        final double sum = sat[y2 * (cellSize + 1) + x2] -
            sat[y1 * (cellSize + 1) + x2] -
            sat[y2 * (cellSize + 1) + x1] +
            sat[y1 * (cellSize + 1) + x1];
        return sum / area;
      }

      for (int y = 0; y < cellSize; y++) {
        for (int x = 0; x < cellSize; x++) {
          final double dxCell = x - half;
          final double dyCell = y - half;
          final double distCell = math.sqrt(dxCell * dxCell + dyCell * dyCell);
          if (distCell > discRadiusInCell * 0.94) {
            out.setPixelRgb(x, y, paperBg, paperBg, paperBg);
            continue;
          }
          if (mode == 0) {
            final double mean19 = localMean(x, y, 10);
            final double cur = rawGrid[y * cellSize + x];
            final int enhanced = ((cur - mean19) * 1.85 + paperBg - 12.0).round().clamp(0, 255);
            out.setPixelRgb(x, y, enhanced, enhanced, enhanced);
          } else {
            final double mean25 = localMean(x, y, 12);
            final double cur = stretchedGrid[y * cellSize + x];
            final int binVal = (distCell <= discRadiusInCell * 0.88 && cur < mean25 - 10.0) ? 0 : 255;
            out.setPixelRgb(x, y, binVal, binVal, binVal);
          }
        }
      }
      return out;
    }

    for (int y = 0; y < cellSize; y++) {
      for (int x = 0; x < cellSize; x++) {
        final int v = stretchedGrid[y * cellSize + x].round().clamp(0, 255);
        out.setPixelRgb(x, y, v, v, v);
      }
    }
    return out;
  }

  /// ตัวจำแนกโครงสร้างตัวอักษรและตัวเลขระดับพิกเซลบนเครื่อง (On-Device Connected-Component Glyph & Topological Matcher)
  /// ทำงานร่วมกับภาพ Adaptive Binary (Mode 2) ที่จัดแนวตั้งตรงแล้ว เพื่ออ่านรหัสยา 2 แถว (เช่น IMI 10, TAZ 110, TS 25, AMC 30, SXT 25)
  /// โดยไม่อาศัย API ภายนอก และแก้ปัญหาตัวอักษรเส้นบาง ('I', '1', 'T') ที่ OCR ทั่วไปมักข้าม
  static List<String> recognizeDiscByConnectedGlyphs({
    required img.Image plateImage,
    required double cx,
    required double cy,
    required double rDiscPx,
    required double baseAngleDeg,
  }) {
    // ไม่ยัดรหัสยาเดาสุ่มจากจำนวนก้อนหมึก (เช่น TS25, TE30, CN10) เพื่อไม่ให้ทับตัวอักษรจริงที่ OCR อ่านได้จากแผ่นยา
    return const <String>[];
  }

  /// แก้ปัญหาความซ้ำซ้อนของรหัสยาบนจานเพาะเชื้อเดียวกัน (Plate-Level Hungarian Disambiguation)
  static void _resolvePlateLevelHungarian(List<DiscRecord> discs) {
    if (discs.length <= 1) return;

    // หากมีเม็ดยา 2 เม็ดได้รหัสยาตัวเดียวกัน ให้เม็ดที่มีความเชื่อมั่นสูงกว่าได้รหัสนั้นไป
    // และให้เม็ดที่ความเชื่อมั่นต่ำกว่าขยับไปใช้รหัสยาอันดับถัดไปหากมีคะแนนใกล้เคียง
    final Set<String> claimed = <String>{};
    final List<int> orderByConf = List<int>.generate(discs.length, (i) => i)
      ..sort((a, b) => discs[b].confidence.compareTo(discs[a].confidence));

    for (final idx in orderByConf) {
      final d = discs[idx];
      if (d.drugCode == 'UNKNOWN' || !kClsiEucastDb.containsKey(d.drugCode) || d.ocrCandidates.isEmpty) {
        continue;
      }
      if (!claimed.contains(d.drugCode)) {
        claimed.add(d.drugCode);
      } else {
        bool reassigned = false;
        for (final cand in d.ocrCandidates) {
          if (!claimed.contains(cand.code) && cand.confidence >= 0.78) {
            d.drugCode = cand.code;
            d.confidence = cand.confidence;
            d.needsReview = false;
            claimed.add(cand.code);
            reassigned = true;
            break;
          }
        }
        if (!reassigned) {
          final String rawCompact = d.rawOcrText.replaceAll(' ', '').trim();
          d.drugCode = rawCompact.isNotEmpty ? rawCompact : d.drugCode;
          d.needsReview = true;
        }
      }
    }
  }

  /// รันไปป์ไลน์ Custom AST-OCR (Underline/Two-Row Alignment + 3-Variant Circular Preprocessing +
  /// 12-Angle Multi-Variant Sprite Sheet + Hungarian Plate Disambiguation)
  static Future<void> recognizeAllDiscsOnPlateWithMlKit({
    required img.Image plateImage,
    required List<DiscRecord> discs,
  }) async {
    if (discs.isEmpty) return;
    final TextRecognizer? recognizer = _getOrCreateRecognizer();
    if (recognizer == null) return;

    const int cellSize = 216;
    const int cellStride = 256; // เว้นระยะห่าง 40px ระหว่างช่องเพื่อป้องกันไม่ให้ ML Kit อ่านข้ามช่องปนกัน
    // กวาดทั้งมุมตั้งตรงจาก Underline/Two-Row (Mode 1, 2, 0) และกวาดรอบทิศทางทุกๆ 30 องศา (0°..330°)
    // เพื่อให้ไม่ว่าเม็ดยาจะวางเอียงมุมไหนบนจาน ก็มีช่องที่ตั้งตรงภายในระยะ ±15° เสมอ
    const List<({double relDeg, int mode, bool isAbsolute})> colSpecs =
        <({double relDeg, int mode, bool isAbsolute})>[
      (relDeg: 0.0, mode: 1, isAbsolute: false),
      (relDeg: 180.0, mode: 1, isAbsolute: false),
      (relDeg: 0.0, mode: 2, isAbsolute: false),
      (relDeg: 180.0, mode: 2, isAbsolute: false),
      (relDeg: -15.0, mode: 1, isAbsolute: false),
      (relDeg: 15.0, mode: 1, isAbsolute: false),
      (relDeg: 0.0, mode: 0, isAbsolute: false),
      (relDeg: 180.0, mode: 0, isAbsolute: false),
      (relDeg: 0.0, mode: 1, isAbsolute: true),
      (relDeg: 30.0, mode: 1, isAbsolute: true),
      (relDeg: 60.0, mode: 1, isAbsolute: true),
      (relDeg: 90.0, mode: 1, isAbsolute: true),
      (relDeg: 120.0, mode: 1, isAbsolute: true),
      (relDeg: 150.0, mode: 1, isAbsolute: true),
      (relDeg: 180.0, mode: 1, isAbsolute: true),
      (relDeg: 210.0, mode: 1, isAbsolute: true),
      (relDeg: 240.0, mode: 1, isAbsolute: true),
      (relDeg: 270.0, mode: 1, isAbsolute: true),
      (relDeg: 300.0, mode: 1, isAbsolute: true),
      (relDeg: 330.0, mode: 1, isAbsolute: true),
    ];
    final int numCols = colSpecs.length;
    final int sheetW = numCols * cellStride;
    final int sheetH = discs.length * cellStride;

    final img.Image spriteSheet = img.Image(width: sheetW, height: sheetH);
    for (int y = 0; y < sheetH; y++) {
      for (int x = 0; x < sheetW; x++) {
        spriteSheet.setPixelRgb(x, y, 255, 255, 255);
      }
    }

    final List<double> baseAngles = <double>[];
    for (int r = 0; r < discs.length; r++) {
      final d = discs[r];
      final double autoDeg = estimateUnderlineUprightAngle(plateImage, d.cx, d.cy, d.rDiscPx);
      baseAngles.add(autoDeg);

      for (int c = 0; c < numCols; c++) {
        final double totalDeg = colSpecs[c].isAbsolute
            ? colSpecs[c].relDeg
            : ((autoDeg + colSpecs[c].relDeg + 360.0) % 360.0);
        final img.Image cellImg = renderCleanDiscForOcr(
          plateImage: plateImage,
          cx: d.cx,
          cy: d.cy,
          rDiscPx: d.rDiscPx,
          rxDiscPx: d.rxDiscPx,
          ryDiscPx: d.ryDiscPx,
          rotDeg: totalDeg,
          cellSize: cellSize,
          discRadiusInCell: 80,
          mode: colSpecs[c].mode,
        );
        img.compositeImage(spriteSheet, cellImg, dstX: c * cellStride, dstY: r * cellStride);
      }
    }

    try {
      final Directory tmpDir = await getTemporaryDirectory();
      final File sheetFile =
          File('${tmpDir.path}/ast_plate_ocr_${DateTime.now().microsecondsSinceEpoch}.png');
      await sheetFile.writeAsBytes(img.encodePng(spriteSheet), flush: true);

      final InputImage inputImg = InputImage.fromFilePath(sheetFile.path);
      final RecognizedText recText = await recognizer.processImage(inputImg);

      try {
        if (await sheetFile.exists()) {
          await sheetFile.delete();
        }
      } catch (_) {}

      final Map<int, Map<int, List<({double y, double x, String display, String clean})>>> cellTokens = {};

      // สกัดระดับ Element (คำย่อย) แทนการรวบทั้ง Line เพื่อไม่ให้คำจากคนละช่องติดกันเป็น "30 FEP"
      for (final block in recText.blocks) {
        for (final line in block.lines) {
          for (final el in line.elements) {
            final rect = el.boundingBox;
            final double cxBox = rect.center.dx;
            final double cyBox = rect.center.dy;
            final int row = (cyBox ~/ cellStride).clamp(0, discs.length - 1);
            final int col = (cxBox ~/ cellStride).clamp(0, numCols - 1);
            final double localX = cxBox - (col * cellStride);
            final double localY = cyBox - (row * cellStride);
            if (localX < 4 || localX > cellSize - 4 || localY < 4 || localY > cellSize - 4) {
              continue;
            }
            final double dxC = localX - (cellSize * 0.5);
            final double dyC = localY - (cellSize * 0.5);
            if (dxC * dxC + dyC * dyC > 94.0 * 94.0) continue;

            final String disp = el.text
                .toUpperCase()
                .replaceAll(RegExp(r'[^A-Z0-9/]'), '')
                .replaceAll(RegExp(r'^/+|/+$'), '');
            final String cleaned = el.text.toUpperCase().replaceAll(RegExp(r'[^A-Z0-9]'), '');
            if (cleaned.isNotEmpty) {
              cellTokens
                  .putIfAbsent(row, () => {})
                  .putIfAbsent(col, () => [])
                  .add((y: cyBox, x: cxBox, display: disp.isNotEmpty ? disp : cleaned, clean: cleaned));
            }
          }
        }
      }

      for (int r = 0; r < discs.length; r++) {
        final d = discs[r];
        final bool isBrown = isTe30BrownDisc(plateImage, d.cx, d.cy, d.rDiscPx);
        final List<String> rawCandidates = <String>[];
        double winningRotDeg = baseAngles[r];
        double winningSlopeDeg = 0.0;
        double bestCellConf = -1.0;
        String bestRawDisplay = '';

        final Map<int, List<({double y, double x, String display, String clean})>> byCol =
            cellTokens[r] ?? {};
        for (final entry in byCol.entries) {
          final int colIdx = entry.key;
          final double cellLeftX = (colIdx * cellStride).toDouble();
          final double cellTopY = (r * cellStride).toDouble();
          final assembled = _assembleCellTopRowFirst(
            entry.value,
            cellLeftX,
            cellTopY,
            cellSize.toDouble(),
          );
          final String joinedClean = assembled.clean;
          final String joinedDisplay = assembled.display;
          if (joinedClean.isNotEmpty) {
            rawCandidates.add(joinedClean);
            for (final e in entry.value) {
              if (e.clean != joinedClean) rawCandidates.add(e.clean);
            }

            final List<OcrCandidateScore> colRank = rankAllDrugsFromOcr(
              rawTexts: <String>[joinedClean],
              isBrownTe30: isBrown,
            );
            final double topConf = colRank.isNotEmpty ? colRank.first.confidence : 0.0;
            final bool hasAlphaAndNum =
                RegExp(r'[A-Z]').hasMatch(joinedClean) && RegExp(r'[0-9]').hasMatch(joinedClean);

            // ให้คะแนนพิเศษสูงมากสำหรับมุมที่ตัวอักษรอยู่แถวบนและตัวเลขอยู่แถวล่าง (Upright Two-Row)
            // และตัดคะแนนช่องที่กลับหัว 180° (ตัวเลขอยู่แถวบน ตัวอักษรอยู่แถวล่าง)
            double orientBonus = 0.0;
            if (assembled.isUprightTwoRow) {
              orientBonus = 0.42;
            } else if (assembled.isUpsideDownTwoRow) {
              orientBonus = -0.25;
            } else if (hasAlphaAndNum) {
              orientBonus = 0.10;
            }

            final double cellQuality = topConf + orientBonus;
            final double rawColDeg = colSpecs[colIdx].isAbsolute
                ? colSpecs[colIdx].relDeg
                : ((baseAngles[r] + colSpecs[colIdx].relDeg + 360.0) % 360.0);

            if (cellQuality > bestCellConf) {
              bestCellConf = cellQuality;
              // หมุนชดเชยด้วยมุมเวกเตอร์ (angleCorrectionDeg = atan2(vx, vy)) จากแถวตัวอักษรบนไปยังแถวตัวเลขล่าง
              // เพื่อให้ตัวอักษรอยู่ด้านบน (12 นาฬิกา) และตัวเลขอยู่ด้านล่าง (6 นาฬิกา) ตั้งตรงเสมอ
              winningRotDeg = (rawColDeg + assembled.angleCorrectionDeg + 360.0) % 360.0;
              winningSlopeDeg = assembled.hasTwoRowVector ? 1.0 : 0.0;
              bestRawDisplay = joinedDisplay;
            }
          }
        }

        // ปรับระดับแนวนอนละเอียดเพื่อให้ตัวอักษรแถวบนและตัวเลขแถวล่างขนานกับแนวนอนตรงเป๊ะ
        final double leveledRotDeg = winningSlopeDeg > 0.5
            ? refineDiscHorizontalLevelAngle(
                plateImage,
                d.cx,
                d.cy,
                d.rDiscPx,
                winningRotDeg,
              )
            : winningRotDeg;

        final List<OcrCandidateScore> ranked = rankAllDrugsFromOcr(
          rawTexts: <String>[
            if (bestRawDisplay.isNotEmpty) bestRawDisplay.replaceAll(' ', ''),
            ...rawCandidates,
          ],
          isBrownTe30: isBrown,
        );
        d.ocrCandidates = ranked;
        final String compactRaw = bestRawDisplay.replaceAll(' ', '');
        d.rawOcrText = bestRawDisplay.isNotEmpty
            ? bestRawDisplay
            : (rawCandidates.isNotEmpty ? rawCandidates.first : '');
        // คงมุมภาพซูมเริ่มต้นไว้ที่ 0.0 องศาตรงตามภาพจานจริง (ไม่หมุนภาพซูมเองอัตโนมัติ)
        d.userRotDeg = 0.0;

        if (compactRaw.isNotEmpty && kClsiEucastDb.containsKey(compactRaw) && compactRaw != 'UNKNOWN') {
          d.drugCode = compactRaw;
          d.confidence = math.max(0.98, ranked.isNotEmpty ? ranked.first.confidence : 0.98);
          d.needsReview = false;
        } else if (ranked.isNotEmpty && ranked.first.confidence >= 0.84) {
          d.drugCode = ranked.first.code;
          d.confidence = ranked.first.confidence;
          d.needsReview = false;
        } else if (compactRaw.isNotEmpty) {
          d.drugCode = compactRaw;
          d.confidence = ranked.isNotEmpty ? ranked.first.confidence : 0.0;
          d.needsReview = true;
        } else {
          d.drugCode = 'UNKNOWN';
          d.confidence = 0.0;
          d.needsReview = true;
        }
      }

      _resolvePlateLevelHungarian(discs);
    } catch (_) {
      for (final d in discs) {
        final bool isBrown = isTe30BrownDisc(plateImage, d.cx, d.cy, d.rDiscPx);
        final List<OcrCandidateScore> ranked =
            rankAllDrugsFromOcr(rawTexts: const <String>[], isBrownTe30: isBrown);
        d.ocrCandidates = ranked;
        if (isBrown) {
          d.drugCode = 'TE30';
          d.confidence = 0.94;
          d.needsReview = false;
        }
      }
    }
  }

  /// อ่านรหัสยาซ้ำสำหรับแผ่นยาที่ผู้ใช้หมุนปรับมุมเอง (Manual Upright Re-OCR)
  /// อ่านแถวบนก่อนแถวล่างเสมอ และหากตรวจพบว่าภาพกลับหัวจะหมุนตั้งตรงให้อัตโนมัติ
  static Future<({String drugCode, double confidence, String rawText, List<OcrCandidateScore> candidates})>
      reReadRotatedDiscOcrAsync({
    required img.Image plateImage,
    required DiscRecord disc,
    String? serverBaseUrl,
  }) async {
    if (serverBaseUrl != null && serverBaseUrl.trim().isNotEmpty) {
      try {
        final Uint8List cropPng = extractZoomedDiscCropPng(
          plateImage: plateImage,
          disc: disc,
          boostContrast: false,
          applyUserRotation: true,
        );
        final Uri uri =
            Uri.parse('${serverBaseUrl.trim().replaceAll(RegExp(r'/$'), '')}/api/ocr_disc');
        final resp = await http
            .post(
              uri,
              headers: {'Content-Type': 'application/json'},
              body: jsonEncode({
                'image_base64': base64Encode(cropPng),
                'panel_preset': 'auto',
              }),
            )
            .timeout(const Duration(seconds: 6));

        if (resp.statusCode == 200) {
          final Map<String, dynamic> data = jsonDecode(utf8.decode(resp.bodyBytes));
          final String code = (data['drug_code']?.toString() ?? 'UNKNOWN').toUpperCase();
          final double conf = (data['ocr_confidence'] as num?)?.toDouble() ?? 0.0;
          final String rawTxt = data['raw_ocr_text']?.toString() ?? '';
          final List<OcrCandidateScore> cands = <OcrCandidateScore>[];
          if (data['ocr_candidates'] is List) {
            for (final item in (data['ocr_candidates'] as List)) {
              if (item is Map) {
                cands.add(
                  OcrCandidateScore(
                    code: item['code']?.toString() ?? 'UNKNOWN',
                    confidence: (item['confidence'] as num?)?.toDouble() ?? 0.01,
                  ),
                );
              }
            }
          }
          final String effectiveCode =
              (code != 'UNKNOWN' && conf >= 0.80) ? code : (rawTxt.isNotEmpty ? rawTxt : code);
          return (
            drugCode: effectiveCode,
            confidence: conf,
            rawText: rawTxt,
            candidates: cands.isNotEmpty
                ? cands
                : rankAllDrugsFromOcr(rawTexts: <String>[rawTxt, code]),
          );
        }
      } catch (_) {}
    }

    final bool isBrown = isTe30BrownDisc(plateImage, disc.cx, disc.cy, disc.rDiscPx);
    final TextRecognizer? recognizer = _getOrCreateRecognizer();
    final List<String> collectedRaw = <String>[];
    String bestSlotDisplay = '';
    double bestSlotScore = -1.0;

    if (recognizer != null) {
      try {
        const int cellSize = 232;
        const int cellStride = 272;
        // อ่านเฉพาะมุมที่ผู้ใช้หมุนไว้ (disc.userRotDeg) และชดเชยละเอียด ±5 องศาเท่านั้น
        // ห้ามกลับด้าน 90°/180°/270° และห้ามเปลี่ยนค่า disc.userRotDeg ของผู้ใช้โดยเด็ดขาด
        final List<({double deg, int mode})> specs = <({double deg, int mode})>[
          (deg: disc.userRotDeg, mode: 1),
          (deg: disc.userRotDeg, mode: 2),
          (deg: disc.userRotDeg, mode: 0),
          (deg: (disc.userRotDeg - 5.0 + 360.0) % 360.0, mode: 1),
          (deg: (disc.userRotDeg + 5.0 + 360.0) % 360.0, mode: 1),
          (deg: (disc.userRotDeg - 5.0 + 360.0) % 360.0, mode: 2),
          (deg: (disc.userRotDeg + 5.0 + 360.0) % 360.0, mode: 2),
        ];

        final img.Image strip = img.Image(width: cellStride * specs.length, height: cellSize);
        for (int y = 0; y < strip.height; y++) {
          for (int x = 0; x < strip.width; x++) {
            strip.setPixelRgb(x, y, 255, 255, 255);
          }
        }

        for (int i = 0; i < specs.length; i++) {
          final cell = renderCleanDiscForOcr(
            plateImage: plateImage,
            cx: disc.cx,
            cy: disc.cy,
            rDiscPx: disc.rDiscPx,
            rxDiscPx: disc.rxDiscPx,
            ryDiscPx: disc.ryDiscPx,
            rotDeg: specs[i].deg,
            cellSize: cellSize,
            discRadiusInCell: 86,
            mode: specs[i].mode,
          );
          img.compositeImage(strip, cell, dstX: i * cellStride, dstY: 0);
        }

        final Directory tmpDir = await getTemporaryDirectory();
        final File stripFile =
            File('${tmpDir.path}/ast_reocr_${DateTime.now().microsecondsSinceEpoch}.png');
        await stripFile.writeAsBytes(img.encodePng(strip), flush: true);

        final RecognizedText recText =
            await recognizer.processImage(InputImage.fromFilePath(stripFile.path));

        try {
          if (await stripFile.exists()) {
            await stripFile.delete();
          }
        } catch (_) {}

        final Map<int, List<({double y, double x, String display, String clean})>> bySlot = {};
        for (final block in recText.blocks) {
          for (final line in block.lines) {
            for (final el in line.elements) {
              final double cxBox = el.boundingBox.center.dx;
              final double cyBox = el.boundingBox.center.dy;
              final int slot = (cxBox ~/ cellStride).clamp(0, specs.length - 1);
              final double localX = cxBox - (slot * cellStride);
              if (localX < 4 || localX > cellSize - 4) continue;
              final double dxC = localX - (cellSize * 0.5);
              final double dyC = cyBox - (cellSize * 0.5);
              if (dxC * dxC + dyC * dyC > 98.0 * 98.0) continue;

              final String disp = el.text
                  .toUpperCase()
                  .replaceAll(RegExp(r'[^A-Z0-9/]'), '')
                  .replaceAll(RegExp(r'^/+|/+$'), '');
              final String clean = el.text.toUpperCase().replaceAll(RegExp(r'[^A-Z0-9]'), '');
              if (clean.isNotEmpty) {
                bySlot.putIfAbsent(slot, () => []).add((
                  y: cyBox,
                  x: cxBox,
                  display: disp.isNotEmpty ? disp : clean,
                  clean: clean,
                ));
              }
            }
          }
        }

        for (int s = 0; s < specs.length; s++) {
          final items = bySlot[s];
          if (items != null && items.isNotEmpty) {
            // เรียงลำดับจากบรรทัดบนสุดลงมาบรรทัดล่างสุด (y น้อยไปมาก) ตามมุมที่ผู้ใช้หมุนไว้โดยตรง
            final List<({double y, double x, String display, String clean})> topToBottom =
                List.from(items)
                  ..sort((a, b) {
                    if ((a.y - b.y).abs() >= 12.0) return a.y.compareTo(b.y);
                    return a.x.compareTo(b.x);
                  });
            final String joinedDisp = topToBottom
                .map((e) => reorderSingleTokenTopFirst(e.display))
                .join(' ');
            final String joinedClean =
                joinedDisp.replaceAll(RegExp(r'[^A-Z0-9]'), '');
            if (joinedClean.isEmpty) continue;
            collectedRaw.add(joinedClean);

            final slotRank = rankAllDrugsFromOcr(
              rawTexts: <String>[joinedClean],
              isBrownTe30: isBrown,
            );
            final double sConf = slotRank.isNotEmpty ? slotRank.first.confidence : 0.0;
            final bool hasAlphaAndNum =
                RegExp(r'[A-Z]').hasMatch(joinedClean) && RegExp(r'[0-9]').hasMatch(joinedClean);
            final double exactAngleBonus = s <= 2 ? 0.12 : 0.0;
            final double alphaFirstBonus =
                RegExp(r'^[A-Z]').hasMatch(joinedClean) ? 0.25 : -0.15;
            final double totalScore =
                sConf + exactAngleBonus + alphaFirstBonus + (hasAlphaAndNum ? 0.15 : 0.0);
            if (totalScore > bestSlotScore) {
              bestSlotScore = totalScore;
              bestSlotDisplay = joinedDisp;
            }
          }
        }
      } catch (_) {}
    }
    final List<OcrCandidateScore> ranked = rankAllDrugsFromOcr(
      rawTexts: <String>[
        if (bestSlotDisplay.isNotEmpty) bestSlotDisplay.replaceAll(' ', ''),
        ...collectedRaw,
      ],
      isBrownTe30: isBrown,
    );
    final String bestRaw = bestSlotDisplay.isNotEmpty
        ? bestSlotDisplay
        : (collectedRaw.isNotEmpty ? collectedRaw.first : '');
    final String compactRaw = bestRaw.replaceAll(' ', '');

    if (compactRaw.isNotEmpty && kClsiEucastDb.containsKey(compactRaw) && compactRaw != 'UNKNOWN') {
      return (
        drugCode: compactRaw,
        confidence: math.max(0.98, ranked.isNotEmpty ? ranked.first.confidence : 0.98),
        rawText: bestRaw,
        candidates: ranked,
      );
    }
    if (ranked.isNotEmpty && ranked.first.confidence >= 0.84) {
      return (
        drugCode: ranked.first.code,
        confidence: ranked.first.confidence,
        rawText: bestRaw,
        candidates: ranked,
      );
    }
    if (compactRaw.isNotEmpty) {
      return (
        drugCode: compactRaw,
        confidence: ranked.isNotEmpty ? ranked.first.confidence : 0.0,
        rawText: bestRaw,
        candidates: ranked,
      );
    }
    return (
      drugCode: 'UNKNOWN',
      confidence: 0.0,
      rawText: bestRaw,
      candidates: ranked,
    );
  }

  static Uint8List extractZoomedDiscCropPng({
    required img.Image plateImage,
    required DiscRecord disc,
    bool boostContrast = false,
    bool applyUserRotation = false,
  }) {
    final double baseR = math.max(8.0, disc.rDiscPx);
    final double scaleX = (disc.rxDiscPx / baseR).clamp(0.68, 1.42);
    final double scaleY = (disc.ryDiscPx / baseR).clamp(0.68, 1.42);
    final int cropRadius = (baseR * 1.18).round().clamp(14, 180);
    final int size = cropRadius * 2;
    final img.Image out = img.Image(width: size, height: size);
    final double rotRad = applyUserRotation ? (-disc.userRotDeg * math.pi / 180.0) : 0.0;
    final double cosA = math.cos(rotRad);
    final double sinA = math.sin(rotRad);

    for (int y = 0; y < size; y++) {
      for (int x = 0; x < size; x++) {
        final double dx = x - cropRadius.toDouble();
        final double dy = y - cropRadius.toDouble();
        if (dx * dx + dy * dy > cropRadius * cropRadius) {
          out.setPixelRgba(x, y, 9, 13, 22, 255);
          continue;
        }
        final double u = applyUserRotation ? (dx * cosA - dy * sinA) : dx;
        final double v = applyUserRotation ? (dx * sinA + dy * cosA) : dy;
        // ชดเชยสัดส่วนมุมเอียง (scaleX, scaleY) เพื่อให้ภาพซูมเม็ดยาตั้งฉากและเต็มวงกลมเส้นประพอดี
        final int sx = (disc.cx + u * scaleX).round().clamp(0, plateImage.width - 1);
        final int sy = (disc.cy + v * scaleY).round().clamp(0, plateImage.height - 1);
        final p = plateImage.getPixel(sx, sy);
        int r = p.r.toInt();
        int g = p.g.toInt();
        int b = p.b.toInt();

        if (boostContrast) {
          final int gray = (0.299 * r + 0.587 * g + 0.114 * b).round();
          final int stretched = ((gray - 128) * 2.15 + 118).round().clamp(0, 255);
          r = stretched;
          g = stretched;
          b = stretched;
        }
        out.setPixelRgba(x, y, r, g, b, 255);
      }
    }
    return Uint8List.fromList(img.encodePng(out));
  }

  // --------------------------------------------------------------------------
  // 3.3 ตัวตรวจจับตำแหน่งวงกลมจานเพาะเชื้อจริง (Auto Petri Dish Circle Locator)
  // --------------------------------------------------------------------------
  static ({double cx, double cy, double r, bool isCircularPlate}) detectPetriDishCircle(
    img.Image plateImage,
  ) {
    final int origW = plateImage.width;
    final int origH = plateImage.height;
    const int coarseMax = 180;
    final double scale = math.min(1.0, coarseMax / math.max(origW, origH));
    final int w = math.max(60, (origW * scale).round());
    final int h = math.max(60, (origH * scale).round());
    final img.Image small = scale < 0.99
        ? img.copyResize(plateImage, width: w, height: h, interpolation: img.Interpolation.linear)
        : plateImage;

    final Float32List luma = Float32List(w * h);
    for (int y = 0; y < h; y++) {
      for (int x = 0; x < w; x++) {
        final p = small.getPixel(x, y);
        luma[y * w + x] = 0.299 * p.r + 0.587 * p.g + 0.114 * p.b;
      }
    }

    final int minDim = math.min(w, h);
    double bestCx = w / 2.0;
    double bestCy = h / 2.0;
    double bestR = minDim * 0.45;
    double bestScore = -1e9;

    final List<double> cosT = <double>[];
    final List<double> sinT = <double>[];
    for (int deg = 0; deg < 360; deg += 10) {
      final double rad = deg * math.pi / 180.0;
      cosT.add(math.cos(rad));
      sinT.add(math.sin(rad));
    }

    for (double rCand = minDim * 0.36; rCand <= minDim * 0.49; rCand += minDim * 0.025) {
      for (double cyCand = h * 0.34; cyCand <= h * 0.66; cyCand += h * 0.04) {
        for (double cxCand = w * 0.26; cxCand <= w * 0.74; cxCand += w * 0.04) {
          if (cxCand - rCand < -4 ||
              cxCand + rCand > w + 4 ||
              cyCand - rCand < -4 ||
              cyCand + rCand > h + 4) {
            continue;
          }

          double rimEdgeSum = 0.0;
          int validAngles = 0;
          for (int k = 0; k < cosT.length; k++) {
            final int ixIn = (cxCand + (rCand * 0.86) * cosT[k]).round().clamp(0, w - 1);
            final int iyIn = (cyCand + (rCand * 0.86) * sinT[k]).round().clamp(0, h - 1);
            final int ixRim = (cxCand + (rCand * 0.99) * cosT[k]).round().clamp(0, w - 1);
            final int iyRim = (cyCand + (rCand * 0.99) * sinT[k]).round().clamp(0, h - 1);
            final int ixOut = (cxCand + (rCand * 1.12) * cosT[k]).round().clamp(0, w - 1);
            final int iyOut = (cyCand + (rCand * 1.12) * sinT[k]).round().clamp(0, h - 1);

            final double vIn = luma[iyIn * w + ixIn];
            final double vRim = luma[iyRim * w + ixRim];
            final double vOut = luma[iyOut * w + ixOut];

            final double contrastOut = (vIn - vOut).abs() + (vRim - vOut);
            rimEdgeSum += contrastOut;
            validAngles++;
          }

          if (validAngles > 0) {
            final double score = rimEdgeSum / validAngles;
            if (score > bestScore) {
              bestScore = score;
              bestCx = cxCand;
              bestCy = cyCand;
              bestR = rCand;
            }
          }
        }
      }
    }

    return (
      cx: bestCx / scale,
      cy: bestCy / scale,
      r: bestR / scale,
      isCircularPlate: bestScore >= 12.0,
    );
  }

  // --------------------------------------------------------------------------
  // 3.4 Continuous Warp Polar Transform ฉบับเต็ม
  // --------------------------------------------------------------------------
  static double _percentileSorted(List<double> sortedVals, double q) {
    if (sortedVals.isEmpty) return 0.0;
    final double pos = (sortedVals.length - 1) * q.clamp(0.0, 1.0);
    final int base = pos.floor();
    final double rest = pos - base;
    if (base + 1 < sortedVals.length) {
      return sortedVals[base] + rest * (sortedVals[base + 1] - sortedVals[base]);
    }
    return sortedVals[base];
  }

  static bool isWhiteboxPlate(img.Image plateImage) {
    final int w = plateImage.width;
    final int h = plateImage.height;
    final int pad = math.max(8, math.min(36, math.min(w, h) ~/ 20));

    final List<double> corners = <double>[];
    for (int y = 0; y < pad; y += 2) {
      for (int x = 0; x < pad; x += 2) {
        final p1 = plateImage.getPixel(x, y);
        final p2 = plateImage.getPixel(w - 1 - x, y);
        final p3 = plateImage.getPixel(x, h - 1 - y);
        final p4 = plateImage.getPixel(w - 1 - x, h - 1 - y);
        corners.add(0.299 * p1.r + 0.587 * p1.g + 0.114 * p1.b);
        corners.add(0.299 * p2.r + 0.587 * p2.g + 0.114 * p2.b);
        corners.add(0.299 * p3.r + 0.587 * p3.g + 0.114 * p3.b);
        corners.add(0.299 * p4.r + 0.587 * p4.g + 0.114 * p4.b);
      }
    }
    corners.sort();
    final double cornerMed = _percentileSorted(corners, 0.50);

    final List<double> centerAgar = <double>[];
    final int y1 = (h * 0.28).round();
    final int y2 = (h * 0.72).round();
    final int x1 = (w * 0.25).round();
    final int x2 = (w * 0.68).round();
    final int step = math.max(2, math.min(w, h) ~/ 120);
    for (int y = y1; y < y2; y += step) {
      for (int x = x1; x < x2; x += step) {
        final p = plateImage.getPixel(x, y);
        centerAgar.add(0.299 * p.r + 0.587 * p.g + 0.114 * p.b);
      }
    }
    centerAgar.sort();
    final double agarMed = centerAgar.isNotEmpty ? _percentileSorted(centerAgar, 0.50) : cornerMed;
    return (cornerMed > 180.0) || (cornerMed > agarMed + 4.0 && cornerMed > 38.0);
  }

  static ({
    Float32List map,
    bool whitebox,
    double lawnRef,
    double plateCx,
    double plateCy,
    double plateR,
  }) buildPreprocessedZoneMap({
    required img.Image plateImage,
    required List<({double cx, double cy, double r})> allDiscs,
    ({double cx, double cy, double r, bool isCircularPlate})? petriCircle,
  }) {
    final int w = plateImage.width;
    final int h = plateImage.height;
    final dish = petriCircle ?? detectPetriDishCircle(plateImage);
    final bool wb = isWhiteboxPlate(plateImage);
    final Float32List rawMap = Float32List(w * h);

    for (int y = 0; y < h; y++) {
      final int rowOff = y * w;
      for (int x = 0; x < w; x++) {
        final p = plateImage.getPixel(x, y);
        final double r = p.r.toDouble();
        final double g = p.g.toDouble();
        final double b = p.b.toDouble();
        final double gray = 0.299 * r + 0.587 * g + 0.114 * b;
        double val;
        if (wb) {
          val = 0.45 * gray + 0.55 * b + 0.35 * (b - r);
        } else {
          val = gray;
        }
        rawMap[rowOff + x] = val.clamp(0.0, 255.0);
      }
    }

    final List<double> centerSample = <double>[];
    final int step = math.max(2, math.min(w, h) ~/ 120);
    final double rSampleLimitSq = math.pow(dish.r * 0.65, 2).toDouble();
    for (int y = (dish.cy - dish.r * 0.65).round().clamp(0, h - 1);
        y < (dish.cy + dish.r * 0.65).round().clamp(0, h - 1);
        y += step) {
      for (int x = (dish.cx - dish.r * 0.65).round().clamp(0, w - 1);
          x < (dish.cx + dish.r * 0.65).round().clamp(0, w - 1);
          x += step) {
        final double dx = x - dish.cx;
        final double dy = y - dish.cy;
        if (dx * dx + dy * dy <= rSampleLimitSq) {
          centerSample.add(rawMap[y * w + x]);
        }
      }
    }
    centerSample.sort();
    final double agarMed = centerSample.isNotEmpty ? _percentileSorted(centerSample, 0.50) : 128.0;
    final double targetMed = wb ? 205.0 : 138.0;
    if (agarMed < targetMed * 0.88) {
      final double gain = math.min(3.8, targetMed / math.max(agarMed, 18.0));
      for (int i = 0; i < rawMap.length; i++) {
        rawMap[i] = (rawMap[i] * gain).clamp(0.0, 255.0);
      }
    }

    final List<double> agarVals = <double>[];
    final int nTotal = allDiscs.isNotEmpty ? allDiscs.length : 1;
    final double rAgarLimitSq = math.pow(dish.r * 0.82, 2).toDouble();
    for (int y = (h * 0.08).round(); y < (h * 0.92).round(); y += step) {
      for (int x = (w * 0.08).round(); x < (w * 0.92).round(); x += step) {
        if (nTotal < 12) {
          final double dxP = x - dish.cx;
          final double dyP = y - dish.cy;
          if (dxP * dxP + dyP * dyP > rAgarLimitSq) continue;
        }
        bool insideAnyDisc = false;
        for (final d in allDiscs) {
          final double dx = x - d.cx;
          final double dy = y - d.cy;
          if (dx * dx + dy * dy <= (d.r * 2.2) * (d.r * 2.2)) {
            insideAnyDisc = true;
            break;
          }
        }
        if (!insideAnyDisc) {
          agarVals.add(rawMap[y * w + x]);
        }
      }
    }
    agarVals.sort();
    final double lawnRef = agarVals.length > 20
        ? _percentileSorted(agarVals, wb ? 0.35 : 0.72)
        : agarMed;

    return (
      map: rawMap,
      whitebox: wb,
      lawnRef: lawnRef,
      plateCx: dish.cx,
      plateCy: dish.cy,
      plateR: dish.r,
    );
  }

  static bool _isPointInAgar(
    double x,
    double y,
    int w,
    int h,
    int totalDiscs,
    double plateCx,
    double plateCy,
    double plateR,
  ) {
    if (x < 6 || x >= w - 6 || y < 6 || y >= h - 6) return false;
    if (totalDiscs >= 12) {
      final double mx = w * 0.055;
      final double my = h * 0.055;
      return x >= mx && x < w - mx && y >= my && y < h - my;
    }
    final double rLimit = plateR * 0.90;
    final double dx = x - plateCx;
    final double dy = y - plateCy;
    return (dx * dx + dy * dy) <= rLimit * rLimit;
  }

  static List<double> _gaussianSmooth1D(List<double> signal, double sigma) {
    if (signal.length < 3) return List<double>.from(signal);
    final int radius = math.max(1, (sigma * 3.0).ceil());
    final List<double> kernel = <double>[];
    double kSum = 0.0;
    for (int k = -radius; k <= radius; k++) {
      final double w = math.exp(-(k * k) / (2.0 * sigma * sigma));
      kernel.add(w);
      kSum += w;
    }
    for (int i = 0; i < kernel.length; i++) {
      kernel[i] /= kSum;
    }

    final int n = signal.length;
    final List<double> out = List<double>.filled(n, 0.0);
    for (int i = 0; i < n; i++) {
      double acc = 0.0;
      for (int k = -radius; k <= radius; k++) {
        final int idx = (i + k).clamp(0, n - 1);
        acc += signal[idx] * kernel[k + radius];
      }
      out[i] = acc;
    }
    return out;
  }

  static DiscRecord measureSingleDiscWarpPolar({
    required img.Image plateImage,
    required double cx,
    required double cy,
    required double rDiscPx,
    double? rxDiscPx,
    double? ryDiscPx,
    required double medianDiscRadiusPx,
    required int discOrder,
    required String drugCode,
    required String plateZone,
    bool needsReview = false,
    List<({double cx, double cy, double r})>? allDiscs,
    ({
      Float32List map,
      bool whitebox,
      double lawnRef,
      double plateCx,
      double plateCy,
      double plateR,
    })? precomputedZoneMap,
  }) {
    final int w = plateImage.width;
    final int h = plateImage.height;
    final double effRx = rxDiscPx ?? rDiscPx;
    final double effRy = ryDiscPx ?? rDiscPx;
    final double ellipScaleX = (effRx / math.max(8.0, rDiscPx)).clamp(0.70, 1.40);
    final double ellipScaleY = (effRy / math.max(8.0, rDiscPx)).clamp(0.70, 1.40);
    final List<({double cx, double cy, double r})> discList =
        allDiscs ?? <({double cx, double cy, double r})>[(cx: cx, cy: cy, r: rDiscPx)];
    final int nTotal = discList.length;

    final zoneBundle =
        precomputedZoneMap ?? buildPreprocessedZoneMap(plateImage: plateImage, allDiscs: discList);
    final Float32List zoneMap = zoneBundle.map;
    final bool whiteboxMode = zoneBundle.whitebox;
    final double lawnRef = zoneBundle.lawnRef;
    final double plateCx = zoneBundle.plateCx;
    final double plateCy = zoneBundle.plateCy;
    final double plateR = zoneBundle.plateR;

    final double scaleMmPerPx = 6.0 / (2.0 * math.max(rDiscPx, 8.0));
    final int haloMarginPx = math.max(5, (rDiscPx * 0.38).round());
    final int minRPx = rDiscPx.round() + haloMarginPx;
    final int maxRPx = math.max(minRPx + 12, (17.5 / scaleMmPerPx).round());
    final int numRadii = maxRPx - minRPx;
    const int numAngles = 360;

    if (numRadii < 8) {
      return DiscRecord(
        discOrder: discOrder,
        cx: cx,
        cy: cy,
        rDiscPx: rDiscPx,
        rxDiscPx: effRx,
        ryDiscPx: effRy,
        rZonePx: rDiscPx,
        diameterMm: 6.0,
        drugCode: drugCode,
        plateZone: plateZone,
        needsReview: needsReview,
      );
    }

    final double maxInteractPx = 34.0 / scaleMmPerPx;
    final double checkWallRPx = 14.5 / scaleMmPerPx;
    final List<double> clearanceScore = List<double>.filled(numAngles, 180.0);
    final List<bool> wallSafe = List<bool>.filled(numAngles, true);

    for (int a = 0; a < numAngles; a++) {
      final double rad = (a * math.pi) / 180.0;
      final double endX = cx + checkWallRPx * math.cos(rad);
      final double endY = cy + checkWallRPx * math.sin(rad);
      wallSafe[a] = _isPointInAgar(endX, endY, w, h, nTotal, plateCx, plateCy, plateR);
    }

    for (final other in discList) {
      final double dx = other.cx - cx;
      final double dy = other.cy - cy;
      final double distPx = math.sqrt(dx * dx + dy * dy);
      if (distPx > 2.5 && distPx < maxInteractPx) {
        final double angToNeighbor = (math.atan2(dy, dx) * 180.0 / math.pi + 360.0) % 360.0;
        final double proxWeight =
            ((24.0 / scaleMmPerPx) / math.max(distPx, 1.0)).clamp(0.85, 1.35);
        for (int a = 0; a < numAngles; a++) {
          final double diff = ((a.toDouble() - angToNeighbor + 180.0) % 360.0 - 180.0).abs();
          final double eff = diff / proxWeight;
          if (eff < clearanceScore[a]) clearanceScore[a] = eff;
        }
      }
    }

    final List<bool> validMask = List<bool>.generate(
      numAngles,
      (a) => clearanceScore[a] >= 28.0 && wallSafe[a],
    );
    final int validCount = validMask.where((v) => v).length;
    if (validCount < 72) {
      final List<double> combined = List<double>.generate(
        numAngles,
        (a) => clearanceScore[a] * (wallSafe[a] ? 1.0 : 0.25),
      );
      final List<double> sortedComb = List<double>.from(combined)..sort();
      final double cutoff = _percentileSorted(sortedComb, 0.70);
      for (int a = 0; a < numAngles; a++) {
        validMask[a] = combined[a] >= cutoff;
      }
    }

    final List<List<double>> polarMatrix = List<List<double>>.generate(
      numAngles,
      (_) => List<double>.filled(numRadii, lawnRef),
    );
    final List<List<bool>> inAgarMatrix = List<List<bool>>.generate(
      numAngles,
      (_) => List<bool>.filled(numRadii, false),
    );

    for (int a = 0; a < numAngles; a++) {
      final double rad = (a * math.pi) / 180.0;
      final double cosA = math.cos(rad);
      final double sinA = math.sin(rad);
      for (int rIdx = 0; rIdx < numRadii; rIdx++) {
        final double rPx = (minRPx + rIdx).toDouble();
        // สุ่มพิกเซลตามสัดส่วนวงรีของระนาบจานเพาะเชื้อที่เอียง (ellipScaleX, ellipScaleY)
        final double sx = cx + rPx * ellipScaleX * cosA;
        final double sy = cy + rPx * ellipScaleY * sinA;
        final bool inAgar = _isPointInAgar(sx, sy, w, h, nTotal, plateCx, plateCy, plateR);
        inAgarMatrix[a][rIdx] = inAgar;
        if (!inAgar) {
          polarMatrix[a][rIdx] = lawnRef;
          continue;
        }

        bool insideNeighborDisc = false;
        for (final other in discList) {
          if ((other.cx - cx).abs() <= 2.5 && (other.cy - cy).abs() <= 2.5) continue;
          final double odx = sx - other.cx;
          final double ody = sy - other.cy;
          if (odx * odx + ody * ody <= (other.r * 1.4) * (other.r * 1.4)) {
            insideNeighborDisc = true;
            break;
          }
        }
        if (insideNeighborDisc) {
          polarMatrix[a][rIdx] = lawnRef;
        } else {
          final int ix = sx.round().clamp(0, w - 1);
          final int iy = sy.round().clamp(0, h - 1);
          polarMatrix[a][rIdx] = zoneMap[iy * w + ix];
        }
      }
    }

    final double qStat = whiteboxMode ? 0.60 : 0.50;
    final List<double> consensusProfile = <double>[];
    for (int rIdx = 0; rIdx < numRadii; rIdx++) {
      final List<double> vals = <double>[];
      for (int a = 0; a < numAngles; a++) {
        if (validMask[a] && inAgarMatrix[a][rIdx]) {
          vals.add(polarMatrix[a][rIdx]);
        }
      }
      if (vals.length < 12) {
        vals.clear();
        for (int a = 0; a < numAngles; a++) {
          if (inAgarMatrix[a][rIdx]) vals.add(polarMatrix[a][rIdx]);
        }
      }
      if (vals.length >= 8) {
        vals.sort();
        consensusProfile.add(_percentileSorted(vals, qStat));
      } else {
        consensusProfile.add(consensusProfile.isNotEmpty ? consensusProfile.last : lawnRef);
      }
    }

    final List<double> smooth = _gaussianSmooth1D(consensusProfile, 2.2);
    double guideRadiusPx = rDiscPx;

    if (whiteboxMode) {
      final int peakSearchEnd = math.min(numRadii, math.max(4, (3.8 / scaleMmPerPx).round()));
      int peakIdx = 0;
      double peakVal = smooth[0];
      for (int i = 1; i < peakSearchEnd; i++) {
        if (smooth[i] > peakVal) {
          peakVal = smooth[i];
          peakIdx = i;
        }
      }
      double outerMin = peakVal;
      for (int i = peakIdx; i < numRadii; i++) {
        if (smooth[i] < outerMin) outerMin = smooth[i];
      }
      final double dropSpan = peakVal - outerMin;
      if (peakVal >= lawnRef + 4.5 && dropSpan >= 8.5 && (numRadii - peakIdx) >= 4) {
        final List<double> subProf = smooth.sublist(peakIdx);
        final int subLen = subProf.length;
        final List<double> negGrad = List<double>.filled(subLen, 0.0);
        for (int i = 0; i < subLen; i++) {
          final double prev = subProf[math.max(0, i - 1)];
          final double next = subProf[math.min(subLen - 1, i + 1)];
          negGrad[i] = -(next - prev) * 0.5;
        }
        final double midVal = peakVal - 0.48 * dropSpan;
        int crossIdx = -1;
        for (int i = 0; i < subLen; i++) {
          if (subProf[i] <= midVal) {
            crossIdx = i;
            break;
          }
        }
        int bestI = 0;
        if (crossIdx >= 0) {
          final int w0 = math.max(0, crossIdx - 8);
          final int w1 = math.min(subLen, crossIdx + 9);
          bestI = w0;
          for (int i = w0; i < w1; i++) {
            if (negGrad[i] > negGrad[bestI]) bestI = i;
          }
        } else {
          for (int i = 1; i < subLen; i++) {
            if (negGrad[i] > negGrad[bestI]) bestI = i;
          }
        }
        guideRadiusPx = (minRPx + peakIdx + bestI).toDouble();
      }
    } else {
      final int innerWindow = math.max(3, math.min(8, numRadii ~/ 5));
      final List<double> innerSlice = smooth.sublist(0, innerWindow)..sort();
      final double innerLevel = _percentileSorted(innerSlice, 0.50);
      final List<double> sortedAll = List<double>.from(smooth)..sort();
      final double outerHigh = _percentileSorted(sortedAll, 0.85);
      final double riseSpan = outerHigh - innerLevel;

      final List<double> grad = List<double>.filled(numRadii, 0.0);
      double maxGrad = 0.0;
      for (int i = 0; i < numRadii; i++) {
        final double prev = smooth[math.max(0, i - 1)];
        final double next = smooth[math.min(numRadii - 1, i + 1)];
        grad[i] = (next - prev) * 0.5;
        if (grad[i] > maxGrad) maxGrad = grad[i];
      }

      if (riseSpan >= 9.5 && innerLevel <= lawnRef - 6.0 && maxGrad >= 0.85) {
        final double midVal = innerLevel + 0.48 * riseSpan;
        int crossIdx = -1;
        for (int i = 0; i < numRadii; i++) {
          if (smooth[i] >= midVal) {
            crossIdx = i;
            break;
          }
        }
        int localIdx = 0;
        if (crossIdx >= 0) {
          final int w0 = math.max(0, crossIdx - 8);
          final int w1 = math.min(numRadii, crossIdx + 9);
          localIdx = w0;
          for (int i = w0; i < w1; i++) {
            if (grad[i] > grad[localIdx]) localIdx = i;
          }
        } else {
          for (int i = 1; i < numRadii; i++) {
            if (grad[i] > grad[localIdx]) localIdx = i;
          }
        }
        guideRadiusPx = (minRPx + localIdx).toDouble();
      }
    }

    double robustRadiusPx = rDiscPx;
    if (guideRadiusPx > rDiscPx + 1.0) {
      final int corridorHalfPx = math.max(5, (2.0 / scaleMmPerPx).round());
      final int guideRelIdx = (guideRadiusPx - minRPx).round();
      final int cStart = math.max(1, guideRelIdx - corridorHalfPx);
      final int cEnd = math.min(numRadii - 1, guideRelIdx + corridorHalfPx + 1);

      final List<double> validRadii = <double>[];
      for (int a = 0; a < numAngles; a++) {
        if (!validMask[a]) continue;
        double bestG = -1e9;
        int bestIdx = guideRelIdx.clamp(0, numRadii - 1);
        for (int rIdx = cStart; rIdx < cEnd; rIdx++) {
          final double vNext = (polarMatrix[(a - 1 + numAngles) % numAngles][rIdx + 1] +
                  polarMatrix[a][rIdx + 1] +
                  polarMatrix[(a + 1) % numAngles][rIdx + 1]) /
              3.0;
          final double vPrev = (polarMatrix[(a - 1 + numAngles) % numAngles][rIdx - 1] +
                  polarMatrix[a][rIdx - 1] +
                  polarMatrix[(a + 1) % numAngles][rIdx - 1]) /
              3.0;
          final double g = whiteboxMode ? -(vNext - vPrev) * 0.5 : (vNext - vPrev) * 0.5;
          if (g > bestG) {
            bestG = g;
            bestIdx = rIdx;
          }
        }
        if (bestG >= 0.75) {
          validRadii.add((minRPx + bestIdx).toDouble());
        } else {
          validRadii.add(guideRadiusPx);
        }
      }

      if (validRadii.isNotEmpty) {
        validRadii.sort();
        final double q25 = _percentileSorted(validRadii, 0.25);
        final double q75 = _percentileSorted(validRadii, 0.75);
        final double iqr = q75 - q25;
        final double lo = q25 - 1.2 * iqr;
        final double hi = q75 + 1.2 * iqr;
        final List<double> inliers = validRadii.where((v) => v >= lo && v <= hi).toList();
        robustRadiusPx = _percentileSorted(inliers.isNotEmpty ? inliers : validRadii, 0.50);
      } else {
        robustRadiusPx = guideRadiusPx;
      }
    }

    final double rawDiameterMm = (2.0 * robustRadiusPx * scaleMmPerPx).clamp(6.0, 42.0);
    final double roundedMm = (rawDiameterMm * 2.0).round() / 2.0;
    final double finalZonePx = roundedMm <= 6.0 ? rDiscPx : (roundedMm / 2.0) / scaleMmPerPx;

    return DiscRecord(
      discOrder: discOrder,
      cx: cx,
      cy: cy,
      rDiscPx: rDiscPx,
      rxDiscPx: effRx,
      ryDiscPx: effRy,
      rZonePx: finalZonePx,
      diameterMm: roundedMm,
      drugCode: drugCode,
      plateZone: plateZone,
      needsReview: needsReview,
    );
  }

  static void assignAutomaticSpatialOrder(
    List<DiscRecord> discs,
    double imgWidth,
    double imgHeight,
  ) {
    if (discs.isEmpty) return;

    final double rowTol = math.max(38.0, imgHeight * 0.09);
    final List<DiscRecord> byY = List<DiscRecord>.from(discs)
      ..sort((a, b) => a.cy.compareTo(b.cy));

    final List<List<DiscRecord>> rows = <List<DiscRecord>>[];
    for (final d in byY) {
      bool placed = false;
      for (final row in rows) {
        final double meanY = row.map((e) => e.cy).reduce((a, b) => a + b) / row.length;
        if ((d.cy - meanY).abs() <= rowTol) {
          row.add(d);
          placed = true;
          break;
        }
      }
      if (!placed) rows.add(<DiscRecord>[d]);
    }

    double minX = discs.first.cx, maxX = discs.first.cx;
    double minY = discs.first.cy, maxY = discs.first.cy;
    for (final d in discs) {
      if (d.cx < minX) minX = d.cx;
      if (d.cx > maxX) maxX = d.cx;
      if (d.cy < minY) minY = d.cy;
      if (d.cy > maxY) maxY = d.cy;
    }
    final double spanX = math.max(80.0, maxX - minX);
    final double spanY = math.max(80.0, maxY - minY);

    final List<DiscRecord> ordered = <DiscRecord>[];
    for (int rIdx = 0; rIdx < rows.length; rIdx++) {
      final row = rows[rIdx]..sort((a, b) => a.cx.compareTo(b.cx));
      for (int cIdx = 0; cIdx < row.length; cIdx++) {
        final d = row[cIdx];
        d.discOrder = ordered.length + 1;
        if (discs.length >= 12) {
          d.plateZone = 'R${rIdx + 1}-C${cIdx + 1}';
        } else {
          final double rx = (d.cx - minX) / spanX;
          final double ry = (d.cy - minY) / spanY;
          if (rx >= 0.33 && rx <= 0.67 && ry >= 0.33 && ry <= 0.67) {
            d.plateZone = 'Center';
          } else {
            final String v = ry < 0.34 ? 'Top' : (ry > 0.66 ? 'Bottom' : 'Mid');
            final String h = rx < 0.34 ? 'Left' : (rx > 0.66 ? 'Right' : 'Center');
            d.plateZone = (v == 'Mid' && h == 'Center') ? 'Center' : '$v-$h';
          }
        }
        ordered.add(d);
      }
    }

    discs
      ..clear()
      ..addAll(ordered);
  }

  /// ปรับจุดศูนย์กลางและรัศมีแกน X/Y ของแผ่นยาด้วยสมมาตรคอร์ดตรงข้าม 16 คู่ทิศทาง (Opposite-Ray Elliptical Rim Symmetry)
  /// - สแกนเฉพาะขอบนอกของกระดาษ (0.56*r .. 1.38*r) จึงไม่ถูกตัวอักษรพิมพ์สีดำตรงกลางเม็ดยา ('FEP 30', 'TAZ 110') ดึงจุดศูนย์กลางเบี้ยว
  /// - รองรับภาพที่ไม่ได้ถ่ายตั้งฉากกับจานเพาะเชื้อ (เม็ดยาปรากฏเป็นวงรี rx != ry และมีขนาดต่างกันตามระยะใกล้-ไกล)
  static ({double cx, double cy, double r, double rx, double ry}) _refineDiscCenterAndRadius(
    img.Image plateImage,
    double initCx,
    double initCy,
    double estR, {
    double? initRx,
    double? initRy,
    bool fromYolo = false,
  }) {
    final int imgW = plateImage.width;
    final int imgH = plateImage.height;
    double cx = initCx.clamp(8.0, imgW - 8.0);
    double cy = initCy.clamp(8.0, imgH - 8.0);
    double rx = (initRx ?? estR).clamp(8.0, 120.0);
    double ry = (initRy ?? estR).clamp(8.0, 120.0);

    double discFeatAt(int px, int py) {
      final p = plateImage.getPixel(px.clamp(0, imgW - 1), py.clamp(0, imgH - 1));
      final double r = p.r.toDouble();
      final double g = p.g.toDouble();
      final double b = p.b.toDouble();
      final double luma = 0.299 * r + 0.587 * g + 0.114 * b;
      final double brownBoost =
          (r - g >= 18.0 && r - b >= 34.0 && r >= 75.0) ? ((r - b) * 1.40) : 0.0;
      return (luma + brownBoost).clamp(0.0, 280.0);
    }

    for (int iter = 0; iter < 2; iter++) {
      final double meanR = 0.5 * (rx + ry);
      final int innerLim = math.max(5, (meanR * 0.72).round());
      final List<double> innerVals = <double>[];
      for (int dy = -innerLim; dy <= innerLim; dy += 2) {
        for (int dx = -innerLim; dx <= innerLim; dx += 2) {
          if (dx * dx + dy * dy > innerLim * innerLim) continue;
          innerVals.add(discFeatAt((cx + dx).round(), (cy + dy).round()));
        }
      }
      if (innerVals.isEmpty) break;
      innerVals.sort();
      // ใช้ P78 ของเนื้อกระดาษด้านในเพื่อข้ามหมึกพิมพ์สีดำบนแผ่นยา
      final double paperRef = _percentileSorted(innerVals, 0.78);

      final List<double> outerVals = <double>[];
      for (int deg = 0; deg < 360; deg += 15) {
        final double rad = deg * math.pi / 180.0;
        final double cosA = math.cos(rad);
        final double sinA = math.sin(rad);
        final int ox = (cx + (rx * 1.32) * cosA).round();
        final int oy = (cy + (ry * 1.32) * sinA).round();
        outerVals.add(discFeatAt(ox, oy));
      }
      outerVals.sort();
      final double outerRef = _percentileSorted(outerVals, 0.45);
      final double contrastSpan = paperRef - outerRef;
      if (contrastSpan < 7.5) break;

      final double midThr = outerRef + 0.48 * contrastSpan;
      const int numRays = 32; // 16 คู่ทิศทางตรงข้าม (ทุกๆ 11.25 องศา)
      final List<double> edgeR = List<double>.filled(numRays, -1.0);

      for (int k = 0; k < numRays; k++) {
        final double rad = (k * 2.0 * math.pi) / numRays;
        final double cosA = math.cos(rad);
        final double sinA = math.sin(rad);
        final double rExpected = (rx * ry) /
            math.max(4.0, math.sqrt((ry * cosA) * (ry * cosA) + (rx * sinA) * (rx * sinA)));

        // เริ่มสแกนจาก 0.58 * rExpected ออกไปด้านนอก เพื่อไม่ให้ไปจับโดนตัวอักษรพิมพ์ด้านในเม็ดยา
        final int rStart = math.max(5, (rExpected * 0.58).round());
        final int rEnd = math.min(115, (rExpected * 1.36).round());
        if (rEnd <= rStart + 2) continue;

        double bestScore = -1e9;
        double bestEdge = rExpected;
        for (int rStep = rStart; rStep <= rEnd; rStep++) {
          final double fIn = discFeatAt(
            (cx + (rStep - 2) * cosA).round(),
            (cy + (rStep - 2) * sinA).round(),
          );
          final double fMid = discFeatAt(
            (cx + rStep * cosA).round(),
            (cy + rStep * sinA).round(),
          );
          final double fOut = discFeatAt(
            (cx + (rStep + 2) * cosA).round(),
            (cy + (rStep + 2) * sinA).round(),
          );
          if (fIn < outerRef + 0.30 * contrastSpan) continue;
          final double drop = fIn - fOut;
          final double distPenalty = (rStep - rExpected).abs() * (fromYolo ? 0.55 : 0.25);
          final double thrBonus = (contrastSpan - (fMid - midThr).abs()).clamp(0.0, contrastSpan) * 0.25;
          final double score = drop + thrBonus - distPenalty;
          if (drop >= 5.0 && score > bestScore) {
            bestScore = score;
            bestEdge = rStep.toDouble();
          }
        }
        if (bestScore > -1e8) {
          edgeR[k] = bestEdge;
        }
      }

      double sumDx = 0.0, sumWx = 0.0;
      double sumDy = 0.0, sumWy = 0.0;
      final List<double> horizRadii = <double>[];
      final List<double> vertRadii = <double>[];
      final List<double> allPairRadii = <double>[];

      for (int k = 0; k < 16; k++) {
        final double rPos = edgeR[k];
        final double rNeg = edgeR[k + 16];
        if (rPos <= 0.0 || rNeg <= 0.0) continue;

        final double rad = (k * 2.0 * math.pi) / numRays;
        final double cosA = math.cos(rad);
        final double sinA = math.sin(rad);
        final double delta = 0.5 * (rPos - rNeg);
        final double pairR = 0.5 * (rPos + rNeg);

        if (delta.abs() <= meanR * 0.42) {
          final double w2x = cosA * cosA;
          final double w2y = sinA * sinA;
          sumDx += delta * cosA;
          sumWx += w2x;
          sumDy += delta * sinA;
          sumWy += w2y;
        }
        allPairRadii.add(pairR);
        if (cosA.abs() >= 0.70) horizRadii.add(pairR);
        if (sinA.abs() >= 0.70) vertRadii.add(pairR);
      }

      if (sumWx >= 1.5 && sumWy >= 1.5) {
        final double maxShift = estR * (fromYolo ? 0.28 : 0.42);
        final double dxShift = (sumDx / sumWx).clamp(-maxShift, maxShift);
        final double dyShift = (sumDy / sumWy).clamp(-maxShift, maxShift);
        cx = (initCx + ((cx + dxShift) - initCx).clamp(-maxShift, maxShift)).clamp(8.0, imgW - 8.0);
        cy = (initCy + ((cy + dyShift) - initCy).clamp(-maxShift, maxShift)).clamp(8.0, imgH - 8.0);
      }

      if (allPairRadii.length >= 6) {
        allPairRadii.sort();
        horizRadii.sort();
        vertRadii.sort();
        final double medPairR = _percentileSorted(allPairRadii, 0.50);
        final double measuredRx =
            horizRadii.isNotEmpty ? _percentileSorted(horizRadii, 0.50) : medPairR;
        final double measuredRy =
            vertRadii.isNotEmpty ? _percentileSorted(vertRadii, 0.50) : medPairR;

        if (fromYolo) {
          // ผสานขนาดกรอบจาก YOLO26n เข้ากับขอบจริงของกระดาษเพื่อความแม่นยำสูงสุดบนภาพถ่ายมุมเอียง
          rx = (0.45 * (initRx ?? estR) + 0.55 * measuredRx).clamp(estR * 0.70, estR * 1.35);
          ry = (0.45 * (initRy ?? estR) + 0.55 * measuredRy).clamp(estR * 0.70, estR * 1.35);
        } else {
          rx = measuredRx.clamp(estR * 0.68, estR * 1.38);
          ry = measuredRy.clamp(estR * 0.68, estR * 1.38);
        }
      }
    }

    final double finalR = 0.5 * (rx + ry);
    return (cx: cx, cy: cy, r: finalR, rx: rx, ry: ry);
  }

  static List<({double cx, double cy, double r, double rx, double ry})> detectDiscsCenterSurround(
    img.Image plateImage, {
    ({double cx, double cy, double r, bool isCircularPlate})? petriCircle,
  }) {
    final int origW = plateImage.width;
    final int origH = plateImage.height;
    final dish = petriCircle ?? detectPetriDishCircle(plateImage);

    const int workMax = 560;
    final double scaleDown = math.min(1.0, workMax / math.max(origW, origH));
    final int w = math.max(120, (origW * scaleDown).round());
    final int h = math.max(120, (origH * scaleDown).round());
    final img.Image workImg = scaleDown < 0.99
        ? img.copyResize(plateImage, width: w, height: h, interpolation: img.Interpolation.linear)
        : plateImage;

    final double dishCxWork = dish.cx * scaleDown;
    final double dishCyWork = dish.cy * scaleDown;
    final double dishRWork = dish.r * scaleDown;

    final Float64List sat = Float64List((w + 1) * (h + 1));
    final Float32List rawFeat = Float32List(w * h);

    for (int y = 0; y < h; y++) {
      double rowSum = 0.0;
      for (int x = 0; x < w; x++) {
        final p = workImg.getPixel(x, y);
        final double r = p.r.toDouble();
        final double g = p.g.toDouble();
        final double b = p.b.toDouble();
        final double luma = 0.299 * r + 0.587 * g + 0.114 * b;
        final double brownBoost =
            (r - g >= 18.0 && r - b >= 34.0 && r >= 75.0) ? ((r - b) * 1.45) : 0.0;
        final double feat = (luma + brownBoost).clamp(0.0, 280.0);
        rawFeat[y * w + x] = feat;
        rowSum += feat;
        sat[(y + 1) * (w + 1) + (x + 1)] = sat[y * (w + 1) + (x + 1)] + rowSum;
      }
    }

    double boxSum(int x1, int y1, int x2, int y2) {
      final int cx1 = x1.clamp(0, w);
      final int cy1 = y1.clamp(0, h);
      final int cx2 = x2.clamp(0, w);
      final int cy2 = y2.clamp(0, h);
      if (cx2 <= cx1 || cy2 <= cy1) return 0.0;
      return sat[cy2 * (w + 1) + cx2] -
          sat[cy1 * (w + 1) + cx2] -
          sat[cy2 * (w + 1) + cx1] +
          sat[cy1 * (w + 1) + cx1];
    }

    final int rIn = math.max(5, (dishRWork * 0.062).round());
    final int rOut = math.max(rIn + 4, (dishRWork * 0.115).round());
    final int margin = math.max(rOut + 2, (math.min(w, h) * 0.05).round());

    final List<_CandidatePeak> peaks = <_CandidatePeak>[];
    for (int y = margin; y < h - margin; y += 2) {
      for (int x = margin; x < w - margin; x += 2) {
        final double centerVal = rawFeat[y * w + x];
        if (centerVal < 78.0) continue;

        final int inArea = (2 * rIn + 1) * (2 * rIn + 1);
        final int outArea = (2 * rOut + 1) * (2 * rOut + 1) - inArea;
        final double inSum = boxSum(x - rIn, y - rIn, x + rIn + 1, y + rIn + 1);
        final double totalOutSum = boxSum(x - rOut, y - rOut, x + rOut + 1, y + rOut + 1);
        final double ringSum = totalOutSum - inSum;

        final double inMean = inSum / inArea;
        final double ringMean = ringSum / math.max(1, outArea);
        final double contrast = inMean - ringMean;

        if (inMean >= 92.0 && contrast >= 12.5) {
          int brightSectors = 0;
          final double rCheck = rIn * 0.65;
          for (int k = 0; k < 8; k++) {
            final double ang = k * math.pi / 4.0;
            final int sx = (x + rCheck * math.cos(ang)).round().clamp(0, w - 1);
            final int sy = (y + rCheck * math.sin(ang)).round().clamp(0, h - 1);
            final double sVal = rawFeat[sy * w + sx];
            if (sVal >= ringMean + 8.0 && (sVal - inMean).abs() <= 55.0) {
              brightSectors++;
            }
          }
          if (brightSectors >= 7) {
            peaks.add(_CandidatePeak(x.toDouble(), y.toDouble(), contrast));
          }
        }
      }
    }

    peaks.sort((a, b) => b.score.compareTo(a.score));

    List<_CandidatePeak> selectPeaks({
      required double minDist,
      required int maxCount,
      required bool restrictToDishCircle,
    }) {
      final List<_CandidatePeak> chosen = <_CandidatePeak>[];
      final double maxRadialFromDishCenter = dishRWork * 0.855;
      for (final p in peaks) {
        if (restrictToDishCircle) {
          final double dxD = p.x - dishCxWork;
          final double dyD = p.y - dishCyWork;
          if (math.sqrt(dxD * dxD + dyD * dyD) > maxRadialFromDishCenter) continue;
        }
        bool tooClose = false;
        for (final c in chosen) {
          final double d = math.sqrt((p.x - c.x) * (p.x - c.x) + (p.y - c.y) * (p.y - c.y));
          if (d < minDist) {
            tooClose = true;
            break;
          }
        }
        if (!tooClose) {
          chosen.add(p);
          if (chosen.length >= maxCount) break;
        }
      }
      return chosen;
    }

    final int minDim = math.min(w, h);
    final List<_CandidatePeak> dense16 = selectPeaks(
      minDist: minDim * 0.130,
      maxCount: 16,
      restrictToDishCircle: false,
    );
    final List<_CandidatePeak> circularDiscs = selectPeaks(
      minDist: dishRWork * 0.26,
      maxCount: 10,
      restrictToDishCircle: true,
    );

    final bool is16Grid = dense16.length >= 12 &&
        (origW - origH).abs() <= origW * 0.12 &&
        dense16[math.min(11, dense16.length - 1)].score >= 20.0;

    List<_CandidatePeak> finalPeaks;
    if (is16Grid) {
      finalPeaks = dense16;
    } else if (circularDiscs.isNotEmpty) {
      final double topScore = circularDiscs.first.score;
      final double minKeepScore = math.max(13.0, topScore * 0.36);
      finalPeaks = circularDiscs.where((p) => p.score >= minKeepScore).toList();
    } else {
      finalPeaks = dense16.take(7).toList();
    }

    final double baseEstROrig = is16Grid
        ? (math.min(origW, origH) * 0.0305)
        : (dish.r * 0.068).clamp(14.0, math.min(origW, origH) * 0.055);

    final List<({double cx, double cy, double r, double rx, double ry})> result =
        <({double cx, double cy, double r, double rx, double ry})>[];
    for (final pk in finalPeaks) {
      final double cxOrig = pk.x / scaleDown;
      final double cyOrig = pk.y / scaleDown;
      final refined = _refineDiscCenterAndRadius(plateImage, cxOrig, cyOrig, baseEstROrig);
      result.add(refined);
    }

    if (result.length >= 3) {
      final List<double> sortedR = result.map((e) => e.r).toList()..sort();
      final double medR = sortedR[sortedR.length ~/ 2];
      for (int i = 0; i < result.length; i++) {
        final cur = result[i];
        final double clampedR = cur.r.clamp(medR * 0.65, medR * 1.42);
        final double scaleAdj = clampedR / math.max(1.0, cur.r);
        result[i] = (
          cx: cur.cx,
          cy: cur.cy,
          r: clampedR,
          rx: (cur.rx * scaleAdj).clamp(medR * 0.58, medR * 1.50),
          ry: (cur.ry * scaleAdj).clamp(medR * 0.58, medR * 1.50),
        );
      }
    }

    if (result.isEmpty) {
      final double fallbackR = baseEstROrig.clamp(14.0, 48.0);
      result.add((
        cx: dish.cx,
        cy: dish.cy,
        r: fallbackR,
        rx: fallbackR,
        ry: fallbackR,
      ));
    }
    lastUsedDetectorName = '2D Center-Surround + Petri Locator';
    return result;
  }

  /// ไปป์ไลน์วิเคราะห์จานเพาะเชื้อครบวงจร:
  /// 1. โหมดเซิร์ฟเวอร์ (หากระบุ URL) -> YOLOv26s/n + EasyOCR
  /// 2. โหมดบนเครื่อง (Offline) -> รัน YOLO26n (ONNX Runtime) เป็นอันดับแรก (ตกกลับเป็น Petri Circle + 2D Center-Surround หากไม่มีไฟล์ ONNX)
  /// 3. วัดขนาดวงยับยั้งเชื้อด้วย Continuous Warp Polar Transform
  /// 4. อ่านรหัสยาด้วย Custom Point-3 AST-OCR Pipeline (Underline/Two-Row Alignment + 3-Variant Preprocessing + Hungarian)
  static Future<List<DiscRecord>> detectAndMeasurePlateAsync(
    img.Image plateImage, {
    Uint8List? rawImageBytes,
    String filename = 'plate.png',
    String? serverBaseUrl,
  }) async {
    if (serverBaseUrl != null && serverBaseUrl.trim().isNotEmpty && rawImageBytes != null) {
      try {
        final Uri uri =
            Uri.parse('${serverBaseUrl.trim().replaceAll(RegExp(r'/$'), '')}/api/analyze');
        final resp = await http
            .post(
              uri,
              headers: {'Content-Type': 'application/json'},
              body: jsonEncode({
                'filename': filename,
                'image_base64': base64Encode(rawImageBytes),
                'panel_preset': 'auto',
              }),
            )
            .timeout(const Duration(seconds: 12));

        if (resp.statusCode == 200) {
          final Map<String, dynamic> payload = jsonDecode(utf8.decode(resp.bodyBytes));
          if (payload['status'] == 'ok' && payload['discs'] is List) {
            final List<DiscRecord> serverDiscs = <DiscRecord>[];
            for (final item in (payload['discs'] as List)) {
              if (item is Map) {
                final List<OcrCandidateScore> cands = <OcrCandidateScore>[];
                if (item['ocr_candidates'] is List) {
                  for (final c in (item['ocr_candidates'] as List)) {
                    if (c is Map) {
                      cands.add(
                        OcrCandidateScore(
                          code: c['code']?.toString() ?? 'UNKNOWN',
                          confidence: (c['confidence'] as num?)?.toDouble() ?? 0.01,
                        ),
                      );
                    }
                  }
                }
                final String code = (item['drug_code']?.toString() ?? 'UNKNOWN').toUpperCase();
                final double ocrConf = (item['ocr_confidence'] as num?)?.toDouble() ??
                    ((item['confidence'] as num?)?.toDouble() ?? 0.95);
                serverDiscs.add(
                  DiscRecord(
                    discOrder:
                        (item['disc_order'] as num?)?.toInt() ?? (serverDiscs.length + 1),
                    cx: (item['center_x'] as num?)?.toDouble() ?? 0.0,
                    cy: (item['center_y'] as num?)?.toDouble() ?? 0.0,
                    rDiscPx: (item['r_disc_px'] as num?)?.toDouble() ?? 28.0,
                    rZonePx: (item['r_zone_px'] as num?)?.toDouble() ?? 28.0,
                    diameterMm: (item['diameter_mm'] as num?)?.toDouble() ?? 6.0,
                    drugCode: code,
                    rawOcrText: item['raw_ocr_text']?.toString() ?? '',
                    plateZone: item['plate_zone']?.toString() ?? 'Center',
                    confidence: ocrConf,
                    needsReview: item['needs_review'] == true || code == 'UNKNOWN',
                    ocrCandidates: cands,
                  ),
                );
              }
            }
            if (serverDiscs.isNotEmpty) {
              lastUsedDetectorName = 'Server YOLO + EasyOCR';
              return serverDiscs;
            }
          }
        }
      } catch (_) {}
    }

    final petriCircle = detectPetriDishCircle(plateImage);
    // ลองรันโมเดล YOLO26n ONNX บนเครื่องก่อนเป็นอันดับแรก
    List<({double cx, double cy, double r, double rx, double ry})>? detectedCoords =
        await detectDiscsWithYolo26nOnnxAsync(plateImage, rawImageBytes);
    if (detectedCoords == null || detectedCoords.isEmpty) {
      detectedCoords = detectDiscsCenterSurround(plateImage, petriCircle: petriCircle);
    }

    final List<double> sortedRadii = detectedCoords.map((d) => d.r).toList()..sort();
    final double medianR =
        sortedRadii.isNotEmpty ? sortedRadii[sortedRadii.length ~/ 2] : 24.0;

    final List<DiscRecord> initial = <DiscRecord>[];
    for (int i = 0; i < detectedCoords.length; i++) {
      final d = detectedCoords[i];
      initial.add(
        DiscRecord(
          discOrder: i + 1,
          cx: d.cx,
          cy: d.cy,
          rDiscPx: d.r,
          rxDiscPx: d.rx,
          ryDiscPx: d.ry,
          rZonePx: d.r,
          diameterMm: 6.0,
          drugCode: 'UNKNOWN',
          plateZone: 'Pos #${i + 1}',
        ),
      );
    }

    assignAutomaticSpatialOrder(
      initial,
      plateImage.width.toDouble(),
      plateImage.height.toDouble(),
    );

    final List<({double cx, double cy, double r})> orderedCoords =
        initial.map((d) => (cx: d.cx, cy: d.cy, r: d.rDiscPx)).toList();
    final zoneBundle = buildPreprocessedZoneMap(
      plateImage: plateImage,
      allDiscs: orderedCoords,
      petriCircle: petriCircle,
    );

    final List<DiscRecord> measured = <DiscRecord>[];
    for (int i = 0; i < initial.length; i++) {
      final d = initial[i];
      measured.add(
        measureSingleDiscWarpPolar(
          plateImage: plateImage,
          cx: d.cx,
          cy: d.cy,
          rDiscPx: d.rDiscPx,
          rxDiscPx: d.rxDiscPx,
          ryDiscPx: d.ryDiscPx,
          medianDiscRadiusPx: medianR,
          discOrder: d.discOrder,
          drugCode: 'UNKNOWN',
          plateZone: d.plateZone,
          allDiscs: orderedCoords,
          precomputedZoneMap: zoneBundle,
        ),
      );
    }

    await recognizeAllDiscsOnPlateWithMlKit(
      plateImage: plateImage,
      discs: measured,
    );

    return measured;
  }

  static ({img.Image image, Uint8List pngBytes, List<DiscRecord> discs, double medianDiscRadiusPx})
      generateDemoPlate() {
    const int size = 640;
    final img.Image canvas = img.Image(width: size, height: size);
    const double cxPlate = size / 2.0;
    const double cyPlate = size / 2.0;
    const double rPlate = 285.0;
    const double rDisc = 21.0;

    final List<({double x, double y, double zoneMm, String code})> specs = [
      (x: 225.0, y: 190.0, zoneMm: 22.8, code: 'AMC30'),
      (x: 415.0, y: 190.0, zoneMm: 25.4, code: 'CAZ30'),
      (x: 320.0, y: 320.0, zoneMm: 6.0, code: 'SXT25'),
      (x: 215.0, y: 445.0, zoneMm: 16.5, code: 'TE30'),
      (x: 425.0, y: 445.0, zoneMm: 28.6, code: 'CIP5'),
    ];

    for (int y = 0; y < size; y++) {
      for (int x = 0; x < size; x++) {
        final double dxP = x - cxPlate;
        final double dyP = y - cyPlate;
        final double distPlate = math.sqrt(dxP * dxP + dyP * dyP);

        if (distPlate > rPlate + 6) {
          canvas.setPixelRgb(x, y, 15, 23, 42);
          continue;
        }
        if (distPlate > rPlate) {
          canvas.setPixelRgb(x, y, 148, 163, 184);
          continue;
        }

        double luma = 165.0 + (((x * 31 + y * 17) % 13) - 6).toDouble();

        for (final s in specs) {
          final double d = math.sqrt((x - s.x) * (x - s.x) + (y - s.y) * (y - s.y));
          final double rZonePx = (s.zoneMm / 6.0) * rDisc;
          if (d <= rDisc) {
            luma = 248.0;
            if ((y - s.y) >= 5 && (y - s.y) <= 8 && (x - s.x).abs() <= 10) {
              luma = 45.0;
            }
            break;
          } else if (s.zoneMm > 6.5 && d <= rZonePx) {
            final double edgeMix = ((d - (rZonePx - 4.0)) / 4.0).clamp(0.0, 1.0);
            luma = 74.0 * (1.0 - edgeMix) + luma * edgeMix;
          }
        }

        final int c = luma.round().clamp(0, 255);
        canvas.setPixelRgb(x, y, (c * 0.92).round(), (c * 0.96).round(), (c * 0.84).round());
      }
    }

    final List<DiscRecord> raw = <DiscRecord>[];
    for (int i = 0; i < specs.length; i++) {
      raw.add(
        DiscRecord(
          discOrder: i + 1,
          cx: specs[i].x,
          cy: specs[i].y,
          rDiscPx: rDisc,
          rZonePx: rDisc,
          diameterMm: 6.0,
          drugCode: specs[i].code,
          plateZone: 'Pos #${i + 1}',
        ),
      );
    }

    assignAutomaticSpatialOrder(raw, size.toDouble(), size.toDouble());
    final allCoords = raw.map((d) => (cx: d.cx, cy: d.cy, r: d.rDiscPx)).toList();
    final zoneBundle = buildPreprocessedZoneMap(
      plateImage: canvas,
      allDiscs: allCoords,
      petriCircle: (cx: cxPlate, cy: cyPlate, r: rPlate, isCircularPlate: true),
    );

    final List<DiscRecord> measured = <DiscRecord>[];
    for (final d in raw) {
      final m = measureSingleDiscWarpPolar(
        plateImage: canvas,
        cx: d.cx,
        cy: d.cy,
        rDiscPx: d.rDiscPx,
        medianDiscRadiusPx: rDisc,
        discOrder: d.discOrder,
        drugCode: d.drugCode,
        plateZone: d.plateZone,
        allDiscs: allCoords,
        precomputedZoneMap: zoneBundle,
      );
      m.ocrCandidates = rankAllDrugsFromOcr(rawTexts: <String>[d.drugCode]);
      measured.add(m);
    }

    return (
      image: canvas,
      pngBytes: Uint8List.fromList(img.encodePng(canvas)),
      discs: measured,
      medianDiscRadiusPx: rDisc,
    );
  }
}

class _CandidatePeak {
  final double x;
  final double y;
  final double score;
  const _CandidatePeak(this.x, this.y, this.score);
}

// ============================================================================
// 4. Shimmer Skeleton Loading Widget
// ============================================================================
class _SkeletonShimmerBox extends StatefulWidget {
  final double width;
  final double height;
  final double borderRadius;

  const _SkeletonShimmerBox({
    this.width = double.infinity,
    required this.height,
    this.borderRadius = 8.0,
  });

  @override
  State<_SkeletonShimmerBox> createState() => _SkeletonShimmerBoxState();
}

class _SkeletonShimmerBoxState extends State<_SkeletonShimmerBox>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1250),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, _) {
        final double t = _controller.value;
        return Container(
          width: widget.width,
          height: widget.height,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(widget.borderRadius),
            gradient: LinearGradient(
              begin: Alignment(-1.0 + 2.0 * t, -0.3),
              end: Alignment(1.0 + 2.0 * t, 0.3),
              colors: const [
                Color(0xFF1F2630),
                Color(0xFF2B3543),
                Color(0xFF1F2630),
              ],
            ),
          ),
        );
      },
    );
  }
}

// ============================================================================
// 5. Main Flutter Application (Eye-Care Clinical Slate & Sage — Dark & Light Mode)
// ============================================================================
// ออกแบบตามหลักการลดความล้าของสายตา (Low-Glare & Low-Halation Ergonomics):
// - หลีกเลี่ยงพื้นหลังดำสนิท (#000) และขาวจัด (#FFF) ใช้โทนเทาอมฟ้าอุ่น (#161B22 / #F3F5F8)
// - ใช้สีเขียวอมฟ้าตุ่น (Muted Sage Teal #3B827B / #72B3A8) และสีสถานะพาสเทลตุ่นที่ความอิ่มตัวพอเหมาะ
class AstDashboardTheme {
  final bool isDark;
  const AstDashboardTheme({this.isDark = true});

  Color get bg => isDark ? const Color(0xFF161B22) : const Color(0xFFF3F5F8);
  Color get card => isDark ? const Color(0xFF1F2630) : const Color(0xFFFBFCFD);
  Color get cardElevated => isDark ? const Color(0xFF262F3B) : const Color(0xFFEAF0F6);
  Color get border => isDark ? const Color(0xFF303B49) : const Color(0xFFD8E1EB);
  Color get text => isDark ? const Color(0xFFDBE2EB) : const Color(0xFF1E293B);
  Color get muted => isDark ? const Color(0xFF8B98A9) : const Color(0xFF64748B);
  Color get primary => isDark ? const Color(0xFF3B827B) : const Color(0xFF2D7A73);
  Color get secondary => isDark ? const Color(0xFF263342) : const Color(0xFFDDE9F2);
  Color get selectedNavBg => isDark ? const Color(0xFF253538) : const Color(0xFFE0EFEA);
  Color get accent => isDark ? const Color(0xFF72B3A8) : const Color(0xFF2D7A73);
  Color get accentVivid => isDark ? const Color(0xFF84C2B7) : const Color(0xFF2D7A73);
  Color get warning => isDark ? const Color(0xFFD9A754) : const Color(0xFFB87D1E);
  Color get danger => isDark ? const Color(0xFFD96C6C) : const Color(0xFFC44949);
}

class AstFlutterApp extends StatefulWidget {
  const AstFlutterApp({super.key});

  @override
  State<AstFlutterApp> createState() => _AstFlutterAppState();
}

class _AstFlutterAppState extends State<AstFlutterApp> {
  bool _isDarkMode = true;

  void _toggleThemeMode() {
    setState(() => _isDarkMode = !_isDarkMode);
  }

  @override
  Widget build(BuildContext context) {
    final t = AstDashboardTheme(isDark: _isDarkMode);
    return MaterialApp(
      title: 'ระบบวิเคราะห์ความไวต่อยาปฏิชีวนะ (AST Disk Diffusion System)',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        fontFamily: 'Inter',
        fontFamilyFallback: const ['Noto Sans Thai', 'Sarabun', 'Roboto', 'sans-serif'],
        brightness: _isDarkMode ? Brightness.dark : Brightness.light,
        scaffoldBackgroundColor: t.bg,
        colorScheme: ColorScheme(
          brightness: _isDarkMode ? Brightness.dark : Brightness.light,
          primary: t.primary,
          onPrimary: const Color(0xFFF1F5F9),
          secondary: t.accent,
          onSecondary: _isDarkMode ? const Color(0xFF161B22) : const Color(0xFF1E293B),
          tertiary: t.secondary,
          onTertiary: t.text,
          error: t.danger,
          onError: Colors.white,
          surface: t.card,
          onSurface: t.text,
        ),
        dividerColor: t.border,
        cardTheme: CardThemeData(
          color: t.card,
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(14),
            side: BorderSide(color: t.border, width: 1.0),
          ),
        ),
        sliderTheme: SliderThemeData(
          activeTrackColor: t.accent,
          thumbColor: t.accent,
          overlayColor: t.accent.withOpacity(0.18),
          inactiveTrackColor: t.border,
        ),
      ),
      home: AstHomePage(
        isDarkMode: _isDarkMode,
        onToggleTheme: _toggleThemeMode,
      ),
    );
  }
}

class AstHomePage extends StatefulWidget {
  final bool isDarkMode;
  final VoidCallback? onToggleTheme;

  const AstHomePage({
    super.key,
    this.isDarkMode = true,
    this.onToggleTheme,
  });

  @override
  State<AstHomePage> createState() => _AstHomePageState();
}

class _AstHomePageState extends State<AstHomePage> {
  final GlobalKey<ScaffoldState> _scaffoldKey = GlobalKey<ScaffoldState>();
  final ImagePicker _picker = ImagePicker();

  AstDashboardTheme get _t => AstDashboardTheme(isDark: widget.isDarkMode);

  final List<AlbumPlateEntry> _album = <AlbumPlateEntry>[];
  final List<PendingUploadTask> _pendingTasks = <PendingUploadTask>[];
  final Set<String> _checkedAlbumIds = <String>{};

  String? _activeAlbumId;
  Uint8List? _displayImageBytes;
  img.Image? _decodedImage;
  double _medianDiscRadiusPx = 21.0;
  List<DiscRecord> _discs = <DiscRecord>[];
  int? _selectedIndex;
  Uint8List? _selectedDiscCropBytes;

  bool _showAlbumSlideBar = false;
  bool _fillPlateFrame = false;
  bool _editCircleMode = true;
  bool _addDiscTapMode = false;
  bool _isDraggingCenter = false;
  bool _isActivelyAdjustingZone = false;
  bool _soloSelectedZoneMode = false;

  bool _isSkeletonLoading = false;
  String _loadingStatusText = 'กำลังประมวลผลจานเพาะเชื้อ...';
  int _totalQueuedCount = 0;
  int _completedQueuedCount = 0;

  bool _zoomContrastBoost = false;
  bool _isReOcrBusy = false;
  String _reOcrStatus = '';

  bool _usePcServerMode = false;
  String _pcServerUrl = 'http://192.168.1.100:8000';

  String _exportScope = 'current';
  String _exportFormat = 'csv';

  Timer? _saveDebounceTimer;
  bool _isSavingAlbum = false;
  bool _hasPendingSave = false;
  final Set<String> _savedImageIdsOnDisk = <String>{};

  @override
  void initState() {
    super.initState();
    _initAlbumFromStorageOrDemo();
  }

  @override
  void dispose() {
    _saveDebounceTimer?.cancel();
    AstSotaVisionEngine.disposeRecognizer();
    super.dispose();
  }

  String _safeFileId(String id) =>
      id.replaceAll(RegExp(r'[^a-zA-Z0-9_-]'), '_');

  Future<Directory?> _getAlbumStorageDir() async {
    if (kIsWeb) return null;
    try {
      final Directory appDocDir = await getApplicationDocumentsDirectory();
      final Directory dir = Directory('${appDocDir.path}/ast_album_storage');
      if (!await dir.exists()) {
        await dir.create(recursive: true);
      }
      return dir;
    } catch (_) {
      return null;
    }
  }

  Future<void> _initAlbumFromStorageOrDemo() async {
    if (kIsWeb) {
      setState(() => _loadInitialDemoPlate());
      return;
    }
    try {
      final Directory? dir = await _getAlbumStorageDir();
      if (dir != null) {
        final File indexFile = File('${dir.path}/album_index.json');
        if (await indexFile.exists()) {
          final String rawJson = await indexFile.readAsString();
          final dynamic decodedJson = jsonDecode(rawJson);
          if (decodedJson is Map) {
            final Map<String, dynamic> meta =
                Map<String, dynamic>.from(decodedJson);
            final List<dynamic> platesList =
                (meta['plates'] as List?) ?? const <dynamic>[];
            final List<AlbumPlateEntry> restored = <AlbumPlateEntry>[];

            for (final dynamic item in platesList) {
              if (item is! Map) continue;
              final Map<String, dynamic> pMap = Map<String, dynamic>.from(item);
              final String id = (pMap['id'] ?? '').toString();
              if (id.isEmpty) continue;
              final String imgFileName =
                  (pMap['imageFile'] ?? 'img_${_safeFileId(id)}.bin').toString();
              final File imgFile = File('${dir.path}/$imgFileName');
              if (!await imgFile.exists()) continue;

              final Uint8List bytes = await imgFile.readAsBytes();
              final img.Image? decodedImg = img.decodeImage(bytes);
              if (decodedImg == null) continue;

              final List<DiscRecord> discs = <DiscRecord>[];
              if (pMap['discs'] is List) {
                for (final dynamic dItem in (pMap['discs'] as List)) {
                  if (dItem is Map) {
                    discs.add(
                      DiscRecord.fromStorageJson(
                        Map<String, dynamic>.from(dItem),
                      ),
                    );
                  }
                }
              }

              restored.add(
                AlbumPlateEntry(
                  id: id,
                  title: (pMap['title'] ?? 'Plate.png').toString(),
                  createdAt: DateTime.tryParse(
                        (pMap['createdAt'] ?? '').toString(),
                      ) ??
                      DateTime.now(),
                  imageBytes: bytes,
                  decodedImage: decodedImg,
                  medianDiscRadiusPx:
                      (pMap['medianDiscRadiusPx'] as num?)?.toDouble() ?? 21.0,
                  discs: discs,
                ),
              );
              _savedImageIdsOnDisk.add(id);
            }

            if (restored.isNotEmpty && mounted) {
              setState(() {
                _album
                  ..clear()
                  ..addAll(restored);
                _checkedAlbumIds.clear();
                if (meta['checkedIds'] is List) {
                  for (final dynamic cid in (meta['checkedIds'] as List)) {
                    final String s = cid.toString();
                    if (_album.any((e) => e.id == s)) {
                      _checkedAlbumIds.add(s);
                    }
                  }
                }
                if (_checkedAlbumIds.isEmpty) {
                  for (final e in _album) {
                    _checkedAlbumIds.add(e.id);
                  }
                }

                _usePcServerMode = meta['usePcServerMode'] == true;
                if (meta['pcServerUrl'] is String &&
                    (meta['pcServerUrl'] as String).trim().isNotEmpty) {
                  _pcServerUrl = (meta['pcServerUrl'] as String).trim();
                }
                _fillPlateFrame = meta['fillPlateFrame'] == true;
                _soloSelectedZoneMode = meta['soloSelectedZoneMode'] == true;

                final String? savedActiveId = meta['activeAlbumId']?.toString();
                final AlbumPlateEntry activeEntry = _album.firstWhere(
                  (e) => e.id == savedActiveId,
                  orElse: () => _album.first,
                );
                _activeAlbumId = activeEntry.id;
                _displayImageBytes = activeEntry.imageBytes;
                _decodedImage = activeEntry.decodedImage;
                _medianDiscRadiusPx = activeEntry.medianDiscRadiusPx;
                _discs = activeEntry.discs.map((d) => d.copy()).toList();
                _selectedIndex = _discs.isNotEmpty ? 0 : null;
                _refreshSelectedDiscZoomCrop();
              });
              return;
            }
          }
        }
      }
    } catch (_) {
      // Fallback to demo plate if storage reading fails
    }

    if (!mounted) return;
    setState(() {
      _loadInitialDemoPlate();
    });
    _scheduleSaveAlbumToDisk(immediate: true);
  }

  void _scheduleSaveAlbumToDisk({bool immediate = false}) {
    if (kIsWeb) return;
    _saveDebounceTimer?.cancel();
    if (immediate) {
      _persistAlbumToDisk();
    } else {
      _saveDebounceTimer = Timer(const Duration(milliseconds: 280), () {
        _persistAlbumToDisk();
      });
    }
  }

  Future<void> _persistAlbumToDisk() async {
    if (kIsWeb) return;
    if (_isSavingAlbum) {
      _hasPendingSave = true;
      return;
    }
    _isSavingAlbum = true;
    try {
      final Directory? dir = await _getAlbumStorageDir();
      if (dir == null) return;

      final List<AlbumPlateEntry> snapshot = List<AlbumPlateEntry>.from(_album);
      final Set<String> currentIds = snapshot.map((e) => e.id).toSet();

      // 1. Write any new plate image bytes to disk
      final List<Map<String, dynamic>> serializedPlates = <Map<String, dynamic>>[];
      for (final AlbumPlateEntry entry in snapshot) {
        final String imgFileName = 'img_${_safeFileId(entry.id)}.bin';
        final File imgFile = File('${dir.path}/$imgFileName');
        if (entry.imageBytes != null &&
            (!_savedImageIdsOnDisk.contains(entry.id) || !await imgFile.exists())) {
          await imgFile.writeAsBytes(entry.imageBytes!, flush: true);
          _savedImageIdsOnDisk.add(entry.id);
        }
        serializedPlates.add({
          'id': entry.id,
          'title': entry.title,
          'createdAt': entry.createdAt.toIso8601String(),
          'imageFile': imgFileName,
          'medianDiscRadiusPx': entry.medianDiscRadiusPx,
          'discs': entry.discs.map((d) => d.toStorageJson()).toList(),
        });
      }

      // 2. Clean up removed image files
      final List<String> removedIds = _savedImageIdsOnDisk
          .where((id) => !currentIds.contains(id))
          .toList();
      for (final String oldId in removedIds) {
        final File oldFile = File('${dir.path}/img_${_safeFileId(oldId)}.bin');
        if (await oldFile.exists()) {
          try {
            await oldFile.delete();
          } catch (_) {}
        }
        _savedImageIdsOnDisk.remove(oldId);
      }

      // 3. Write album_index.json atomically
      final Map<String, dynamic> indexPayload = {
        'version': 1,
        'updatedAt': DateTime.now().toIso8601String(),
        'activeAlbumId': _activeAlbumId,
        'checkedIds': _checkedAlbumIds.toList(),
        'usePcServerMode': _usePcServerMode,
        'pcServerUrl': _pcServerUrl,
        'fillPlateFrame': _fillPlateFrame,
        'soloSelectedZoneMode': _soloSelectedZoneMode,
        'plates': serializedPlates,
      };
      final File tempIndex = File('${dir.path}/album_index.json.tmp');
      final File finalIndex = File('${dir.path}/album_index.json');
      await tempIndex.writeAsString(jsonEncode(indexPayload), flush: true);
      await tempIndex.rename(finalIndex.path);
    } catch (_) {
      // Ignore disk write errors safely
    } finally {
      _isSavingAlbum = false;
      if (_hasPendingSave) {
        _hasPendingSave = false;
        _persistAlbumToDisk();
      }
    }
  }

  void _loadInitialDemoPlate() {
    final demo = AstSotaVisionEngine.generateDemoPlate();
    final entry = AlbumPlateEntry(
      id: 'demo_plate_1',
      title: 'Sample_Plate_CLSI.png',
      createdAt: DateTime.now(),
      imageBytes: demo.pngBytes,
      decodedImage: demo.image,
      medianDiscRadiusPx: demo.medianDiscRadiusPx,
      discs: demo.discs,
    );
    _album.add(entry);
    _checkedAlbumIds.add(entry.id);
    _activeAlbumId = entry.id;
    _displayImageBytes = entry.imageBytes;
    _decodedImage = entry.decodedImage;
    _medianDiscRadiusPx = entry.medianDiscRadiusPx;
    _discs = entry.discs.map((d) => d.copy()).toList();
    _selectedIndex = _discs.isNotEmpty ? 0 : null;
    _refreshSelectedDiscZoomCrop();
  }

  void _syncActiveAlbumState({bool persist = true}) {
    if (_activeAlbumId == null) return;
    final int idx = _album.indexWhere((e) => e.id == _activeAlbumId);
    if (idx < 0 || _decodedImage == null) return;
    _album[idx] = AlbumPlateEntry(
      id: _album[idx].id,
      title: _album[idx].title,
      createdAt: _album[idx].createdAt,
      imageBytes: _displayImageBytes,
      decodedImage: _decodedImage!,
      medianDiscRadiusPx: _medianDiscRadiusPx,
      discs: _discs.map((d) => d.copy()).toList(),
    );
    if (persist) {
      _scheduleSaveAlbumToDisk();
    }
  }

  Future<void> _switchAlbumItemWithSkeleton(AlbumPlateEntry item) async {
    if (_activeAlbumId == item.id && !_isSkeletonLoading) return;
    _syncActiveAlbumState();
    setState(() {
      _isSkeletonLoading = true;
      _loadingStatusText = 'กำลังสลับไปยัง ${item.title}...';
      _activeAlbumId = item.id;
    });
    await Future<void>.delayed(const Duration(milliseconds: 140));
    if (!mounted) return;
    setState(() {
      _displayImageBytes = item.imageBytes;
      _decodedImage = item.decodedImage;
      _medianDiscRadiusPx = item.medianDiscRadiusPx;
      _discs = item.discs.map((d) => d.copy()).toList();
      _selectedIndex = _discs.isNotEmpty ? 0 : null;
      _isSkeletonLoading = false;
      _reOcrStatus = '';
      _refreshSelectedDiscZoomCrop();
    });
    _scheduleSaveAlbumToDisk();
  }

  Future<void> _pickSinglePlateFallback(ImageSource source) async {
    try {
      final XFile? file = await _picker.pickImage(source: source, imageQuality: 96);
      if (file == null) return;
      await _processPickedFiles(<XFile>[file]);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('ไม่สามารถเลือกภาพได้: $e')),
      );
    }
  }

  Future<void> _pickAndAnalyzeMultiplePlates() async {
    try {
      final List<XFile> files = await _picker.pickMultiImage(imageQuality: 96);
      if (files.isEmpty) return;
      await _processPickedFiles(files);
    } catch (_) {
      await _pickSinglePlateFallback(ImageSource.gallery);
    }
  }

  Future<void> _processPickedFiles(List<XFile> files) async {
    if (files.isEmpty) return;
    _syncActiveAlbumState();

    final List<({XFile file, String tempId, Uint8List bytes})> loaded = [];
    for (int i = 0; i < files.length; i++) {
      final Uint8List bytes = await files[i].readAsBytes();
      final String tempId = 'pending_${DateTime.now().microsecondsSinceEpoch}_$i';
      loaded.add((file: files[i], tempId: tempId, bytes: bytes));
    }

    setState(() {
      _totalQueuedCount = loaded.length;
      _completedQueuedCount = 0;
      _isSkeletonLoading = true;
      _loadingStatusText =
          'กำลังตรวจจับแผ่นยาและวัดขนาดวงยับยั้ง (1/${loaded.length})...';
      for (final item in loaded) {
        _pendingTasks.add(
          PendingUploadTask(
            tempId: item.tempId,
            title: item.file.name,
            previewBytes: item.bytes,
          ),
        );
      }
    });

    for (int i = 0; i < loaded.length; i++) {
      final item = loaded[i];
      if (!mounted) return;
      setState(() {
        _loadingStatusText =
            'กำลังวิเคราะห์ ${item.file.name} (${i + 1}/${loaded.length})...';
      });
      await Future<void>.delayed(const Duration(milliseconds: 30));

      final img.Image? decoded = img.decodeImage(item.bytes);
      if (decoded == null) {
        setState(() {
          _pendingTasks.removeWhere((t) => t.tempId == item.tempId);
          _completedQueuedCount++;
        });
        continue;
      }

      final List<DiscRecord> measured =
          await AstSotaVisionEngine.detectAndMeasurePlateAsync(
        decoded,
        rawImageBytes: item.bytes,
        filename: item.file.name,
        serverBaseUrl: _usePcServerMode ? _pcServerUrl : null,
      );

      double medR = 21.0;
      if (measured.isNotEmpty) {
        final List<double> rs = measured.map((d) => d.rDiscPx).toList()..sort();
        medR = rs[rs.length ~/ 2];
      }

      final AlbumPlateEntry newEntry = AlbumPlateEntry(
        id: 'plate_${DateTime.now().microsecondsSinceEpoch}_$i',
        title: item.file.name,
        createdAt: DateTime.now(),
        imageBytes: item.bytes,
        decodedImage: decoded,
        medianDiscRadiusPx: medR,
        discs: measured,
      );

      if (!mounted) return;
      setState(() {
        _pendingTasks.removeWhere((t) => t.tempId == item.tempId);
        _completedQueuedCount++;
        _album.insert(0, newEntry);
        _checkedAlbumIds.add(newEntry.id);
        _activeAlbumId = newEntry.id;
        _displayImageBytes = newEntry.imageBytes;
        _decodedImage = newEntry.decodedImage;
        _medianDiscRadiusPx = newEntry.medianDiscRadiusPx;
        _discs = newEntry.discs.map((d) => d.copy()).toList();
        _selectedIndex = _discs.isNotEmpty ? 0 : null;
        _refreshSelectedDiscZoomCrop();
      });
      await _persistAlbumToDisk();
    }

    if (!mounted) return;
    setState(() {
      _isSkeletonLoading = false;
    });
    _scheduleSaveAlbumToDisk(immediate: true);
  }

  void _deleteAlbumEntry(String id) {
    setState(() {
      _album.removeWhere((e) => e.id == id);
      _checkedAlbumIds.remove(id);
      if (_activeAlbumId == id) {
        if (_album.isNotEmpty) {
          final first = _album.first;
          _activeAlbumId = first.id;
          _displayImageBytes = first.imageBytes;
          _decodedImage = first.decodedImage;
          _medianDiscRadiusPx = first.medianDiscRadiusPx;
          _discs = first.discs.map((d) => d.copy()).toList();
          _selectedIndex = _discs.isNotEmpty ? 0 : null;
          _refreshSelectedDiscZoomCrop();
        } else {
          _activeAlbumId = null;
          _displayImageBytes = null;
          _decodedImage = null;
          _discs = <DiscRecord>[];
          _selectedIndex = null;
          _selectedDiscCropBytes = null;
        }
      }
    });
    _scheduleSaveAlbumToDisk(immediate: true);
  }

  void _bulkDeleteSelectedEntries() {
    if (_checkedAlbumIds.isEmpty) return;
    final Set<String> toDelete = Set<String>.from(_checkedAlbumIds);
    for (final String id in toDelete) {
      _deleteAlbumEntry(id);
    }
  }

  void _clearEntireAlbum() {
    setState(() {
      _album.clear();
      _checkedAlbumIds.clear();
      _activeAlbumId = null;
      _displayImageBytes = null;
      _decodedImage = null;
      _discs = <DiscRecord>[];
      _selectedIndex = null;
      _selectedDiscCropBytes = null;
    });
    _scheduleSaveAlbumToDisk(immediate: true);
  }

  void _selectDiscIndex(int index) {
    if (index < 0 || index >= _discs.length) return;
    setState(() {
      _selectedIndex = index;
      _reOcrStatus = '';
      _refreshSelectedDiscZoomCrop();
    });
  }

  void _refreshSelectedDiscZoomCrop() {
    if (_decodedImage == null ||
        _selectedIndex == null ||
        _selectedIndex! < 0 ||
        _selectedIndex! >= _discs.length) {
      _selectedDiscCropBytes = null;
      return;
    }
    _selectedDiscCropBytes = AstSotaVisionEngine.extractZoomedDiscCropPng(
      plateImage: _decodedImage!,
      disc: _discs[_selectedIndex!],
      boostContrast: _zoomContrastBoost,
      applyUserRotation: false,
    );
  }

  void _rotateSelectedDiscZoom(double deltaDeg) {
    if (_selectedIndex == null || _selectedIndex! >= _discs.length) return;
    setState(() {
      final d = _discs[_selectedIndex!];
      d.userRotDeg = (d.userRotDeg + deltaDeg) % 360.0;
      if (d.userRotDeg < 0) d.userRotDeg += 360.0;
      _syncActiveAlbumState();
    });
  }

  Future<void> _reReadSelectedDiscOcr() async {
    if (_decodedImage == null ||
        _selectedIndex == null ||
        _selectedIndex! >= _discs.length ||
        _isReOcrBusy) {
      return;
    }
    final DiscRecord target = _discs[_selectedIndex!];
    setState(() {
      _isReOcrBusy = true;
      _reOcrStatus = 'กำลังอ่านรหัสยาซ้ำตามแนวตั้ง...';
    });
    try {
      final res = await AstSotaVisionEngine.reReadRotatedDiscOcrAsync(
        plateImage: _decodedImage!,
        disc: target,
        serverBaseUrl: _usePcServerMode ? _pcServerUrl : null,
      );
      if (!mounted) return;
      setState(() {
        target.drugCode = res.drugCode;
        target.confidence = res.confidence;
        target.rawOcrText = res.rawText;
        target.ocrCandidates = res.candidates;
        target.needsReview = res.drugCode == 'UNKNOWN' || res.confidence < 0.72;
        _reOcrStatus =
            'อ่านสำเร็จ: ${res.drugCode} (${(res.confidence * 100).toStringAsFixed(0)}%)';
        _syncActiveAlbumState();
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _reOcrStatus = 'อ่านซ้ำไม่สำเร็จ: $e';
      });
    } finally {
      if (mounted) {
        setState(() => _isReOcrBusy = false);
      }
    }
  }

  void _applyTypedDrugCode(
    int index,
    String rawCode, {
    bool isManual = true,
    double? ocrConfidence,
  }) {
    if (index < 0 || index >= _discs.length) return;
    final String cleaned = rawCode.trim().toUpperCase().replaceAll(' ', '');
    if (cleaned.isEmpty) return;
    final String resolved = kDrugPrefixAliases[cleaned] ?? cleaned;
    setState(() {
      final d = _discs[index];
      d.drugCode = resolved;
      d.isManualEntry = isManual;
      d.needsReview = !kClsiEucastDb.containsKey(resolved) || resolved == 'UNKNOWN';
      d.confidence = ocrConfidence ?? (isManual ? 1.0 : d.confidence);
      _reOcrStatus = 'กำหนดรหัสยาเป็น $resolved แล้ว';
      _syncActiveAlbumState();
    });
  }

  void _updateSelectedDiameter(double newDiameterMm) {
    if (_selectedIndex == null || _selectedIndex! >= _discs.length) return;
    setState(() {
      final d = _discs[_selectedIndex!];
      final double clamped = newDiameterMm.clamp(6.0, 46.0);
      d.diameterMm = clamped;
      d.rZonePx = d.rDiscPx * (clamped / 6.0);
      d.isManualEntry = true;
      _syncActiveAlbumState();
    });
  }

  void _handleCanvasTap(Offset localPos, Size renderSize) {
    if (_decodedImage == null) return;
    final double scaleX = _decodedImage!.width / renderSize.width;
    final double scaleY = _decodedImage!.height / renderSize.height;
    final double imgX = localPos.dx * scaleX;
    final double imgY = localPos.dy * scaleY;

    if (_addDiscTapMode) {
      setState(() {
        final double rDisc = _medianDiscRadiusPx.clamp(12.0, 64.0);
        final allCoords = _discs
            .map((e) => (cx: e.cx, cy: e.cy, r: e.rDiscPx))
            .toList()
          ..add((cx: imgX, cy: imgY, r: rDisc));
        final DiscRecord measured =
            AstSotaVisionEngine.measureSingleDiscWarpPolar(
          plateImage: _decodedImage!,
          cx: imgX,
          cy: imgY,
          rDiscPx: rDisc,
          medianDiscRadiusPx: rDisc,
          discOrder: _discs.length + 1,
          drugCode: 'AMC30',
          plateZone: 'Manual',
          allDiscs: allCoords,
        );
        measured.isManualEntry = true;
        _discs.add(measured);
        AstSotaVisionEngine.assignAutomaticSpatialOrder(
          _discs,
          _decodedImage!.width.toDouble(),
          _decodedImage!.height.toDouble(),
        );
        _selectedIndex = _discs.indexOf(measured);
        _addDiscTapMode = false;
        _refreshSelectedDiscZoomCrop();
        _syncActiveAlbumState();
      });
      return;
    }

    int? bestIdx;
    double bestDist = double.infinity;
    for (int i = 0; i < _discs.length; i++) {
      final d = _discs[i];
      final double dist = math.sqrt(
        math.pow(imgX - d.cx, 2) + math.pow(imgY - d.cy, 2),
      );
      if (dist <= math.max(d.rZonePx * 1.15, d.rDiscPx * 2.2) &&
          dist < bestDist) {
        bestDist = dist;
        bestIdx = i;
      }
    }
    if (bestIdx != null) {
      _selectDiscIndex(bestIdx);
    }
  }

  Future<void> _showServerConfigDialog() async {
    final TextEditingController urlCtrl =
        TextEditingController(text: _pcServerUrl);
    bool tempUseServer = _usePcServerMode;
    final t = _t;

    await showDialog<void>(
      context: context,
      builder: (ctx) {
        return StatefulBuilder(
          builder: (ctx, setDialogState) {
            return AlertDialog(
              backgroundColor: t.card,
              title: Text(
                'สถานะเอนจินประมวลผล (On-Device ML 100% / PC Server)',
                style: TextStyle(
                  fontSize: 15.5,
                  fontWeight: FontWeight.bold,
                  color: t.text,
                ),
              ),
              content: SizedBox(
                width: 440,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      [
                        '• จุดที่ 1 (ตรวจจับแผ่นยา): ${AstSotaVisionEngine.lastUsedDetectorName}',
                        '• จุดที่ 2 (วัดขนาดวงยับยั้งเชื้อ): Continuous Warp Polar Transform 360°',
                        '• จุดที่ 3 (อ่านรหัสยา): Custom AST-OCR + Hungarian Assignment',
                      ].join('\n'),
                      style: TextStyle(fontSize: 12, color: t.muted, height: 1.45),
                    ),
                    const SizedBox(height: 12),
                    SwitchListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text(
                        'เชื่อมต่อเซิร์ฟเวอร์ PC (FastAPI) ผ่าน Wi-Fi',
                        style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: t.text,
                        ),
                      ),
                      value: tempUseServer,
                      onChanged: (v) => setDialogState(() => tempUseServer = v),
                    ),
                    if (tempUseServer)
                      TextField(
                        controller: urlCtrl,
                        style: TextStyle(color: t.text, fontSize: 13),
                        decoration: InputDecoration(
                          labelText: 'URL เซิร์ฟเวอร์ (เช่น http://192.168.1.100:8000)',
                          labelStyle: TextStyle(color: t.muted),
                          border: const OutlineInputBorder(),
                        ),
                      ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(ctx).pop(),
                  child: Text('ยกเลิก', style: TextStyle(color: t.muted)),
                ),
                FilledButton(
                  onPressed: () {
                    setState(() {
                      _usePcServerMode = tempUseServer;
                      _pcServerUrl = urlCtrl.text.trim();
                    });
                    _scheduleSaveAlbumToDisk(immediate: true);
                    Navigator.of(ctx).pop();
                  },
                  child: const Text('บันทึก'),
                ),
              ],
            );
          },
        );
      },
    );
  }

  Future<void> _showCustomDrugEditDialog({int? targetDiscIndex}) async {
    final int? idx = targetDiscIndex ?? _selectedIndex;
    if (idx == null || idx < 0 || idx >= _discs.length) return;
    final DiscRecord disc = _discs[idx];
    final DrugBreakpoint bp = disc.breakpoint;
    final t = _t;

    final TextEditingController codeCtrl =
        TextEditingController(text: disc.drugCode);
    final TextEditingController nameCtrl =
        TextEditingController(text: bp.fullName);
    final TextEditingController sMinCtrl =
        TextEditingController(text: bp.sMinMm.toStringAsFixed(1));
    final TextEditingController rMaxCtrl =
        TextEditingController(text: bp.rMaxMm.toStringAsFixed(1));

    await showDialog<void>(
      context: context,
      builder: (ctx) {
        return AlertDialog(
          backgroundColor: t.card,
          title: Text(
            'กำหนดเกณฑ์ยา CLSI / EUCAST (#${disc.discOrder})',
            style: TextStyle(
              fontSize: 15.5,
              fontWeight: FontWeight.bold,
              color: t.text,
            ),
          ),
          content: SizedBox(
            width: 400,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextField(
                  controller: codeCtrl,
                  style: TextStyle(color: t.text),
                  decoration: InputDecoration(
                    labelText: 'รหัสยา (เช่น AMC30, CAZ30, IMI10)',
                    labelStyle: TextStyle(color: t.muted),
                  ),
                ),
                const SizedBox(height: 8),
                TextField(
                  controller: nameCtrl,
                  style: TextStyle(color: t.text),
                  decoration: InputDecoration(
                    labelText: 'ชื่อเต็มของยาปฏิชีวนะ',
                    labelStyle: TextStyle(color: t.muted),
                  ),
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(
                      child: TextField(
                        controller: sMinCtrl,
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                        style: TextStyle(color: t.text),
                        decoration: InputDecoration(
                          labelText: 'เกณฑ์ S ≥ (mm)',
                          labelStyle: TextStyle(color: t.muted),
                        ),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: TextField(
                        controller: rMaxCtrl,
                        keyboardType: const TextInputType.numberWithOptions(decimal: true),
                        style: TextStyle(color: t.text),
                        decoration: InputDecoration(
                          labelText: 'เกณฑ์ R ≤ (mm)',
                          labelStyle: TextStyle(color: t.muted),
                        ),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(ctx).pop(),
              child: Text('ยกเลิก', style: TextStyle(color: t.muted)),
            ),
            FilledButton(
              onPressed: () {
                setState(() {
                  final String c = codeCtrl.text.trim().toUpperCase();
                  if (c.isNotEmpty) disc.drugCode = c;
                  disc.customDrugFullName = nameCtrl.text.trim().isNotEmpty
                      ? nameCtrl.text.trim()
                      : null;
                  disc.customSMinMm = double.tryParse(sMinCtrl.text.trim());
                  disc.customRMaxMm = double.tryParse(rMaxCtrl.text.trim());
                  disc.isManualEntry = true;
                  disc.needsReview = false;
                  _syncActiveAlbumState();
                });
                Navigator.of(ctx).pop();
              },
              child: const Text('บันทึกเกณฑ์ยา'),
            ),
          ],
        );
      },
    );
  }

  List<AlbumPlateEntry> _getPlatesForExport() {
    _syncActiveAlbumState();
    if (_exportScope == 'all') {
      return List<AlbumPlateEntry>.from(_album);
    }
    if (_exportScope == 'checked') {
      final List<AlbumPlateEntry> checked =
          _album.where((e) => _checkedAlbumIds.contains(e.id)).toList();
      if (checked.isNotEmpty) return checked;
    }
    if (_activeAlbumId != null) {
      final List<AlbumPlateEntry> cur =
          _album.where((e) => e.id == _activeAlbumId).toList();
      if (cur.isNotEmpty) return cur;
    }
    return _album.isNotEmpty ? <AlbumPlateEntry>[_album.first] : <AlbumPlateEntry>[];
  }

  Map<String, dynamic> _buildExportPayload(List<AlbumPlateEntry> plates) {
    String ext = 'csv';
    String mimeType = 'text/csv';
    String content = '';

    if (_exportFormat == 'json') {
      ext = 'json';
      mimeType = 'application/json';
      final List<Map<String, dynamic>> payload = plates
          .map((p) => {
                'plate_id': p.id,
                'plate_title': p.title,
                'created_at': p.createdAt.toIso8601String(),
                'discs': p.discs.map((d) => d.toJson()).toList(),
              })
          .toList();
      content = const JsonEncoder.withIndent('  ').convert(payload);
    } else if (_exportFormat == 'tsv') {
      ext = 'xls';
      mimeType = 'text/tab-separated-values';
      final StringBuffer sb = StringBuffer('\uFEFF');
      sb.writeln([
        'Plate_Title',
        'Disc_Order',
        'Plate_Zone',
        'Center_X',
        'Center_Y',
        'Drug_Code',
        'Drug_Full_Name',
        'Diameter_mm',
        'CLSI_R_Max_mm',
        'CLSI_S_Min_mm',
        'SIR_Status',
      ].join('\t'));
      for (final p in plates) {
        for (final d in p.discs) {
          final bp = d.breakpoint;
          sb.writeln([
            p.title,
            '${d.discOrder}',
            d.plateZone,
            d.cx.toStringAsFixed(0),
            d.cy.toStringAsFixed(0),
            d.drugCode,
            bp.fullName,
            d.diameterMm.toStringAsFixed(1),
            bp.rMaxMm.toStringAsFixed(1),
            bp.sMinMm.toStringAsFixed(1),
            d.sirStatus,
          ].join('\t'));
        }
      }
      content = sb.toString();
    } else if (_exportFormat == 'md') {
      ext = 'md';
      mimeType = 'text/markdown';
      final StringBuffer sb = StringBuffer();
      sb.writeln(
        '# รายงานผลการวิเคราะห์ความไวต่อยาปฏิชีวนะ (${plates.length} จานเพาะเชื้อ)',
      );
      sb.writeln();
      sb.writeln([
        '| จานเพาะเชื้อ',
        'ลำดับ',
        'โซน',
        'พิกัด (X,Y)',
        'รหัสยา',
        'ชื่อยา',
        'ขนาดวง (mm)',
        'เกณฑ์ R/S (mm)',
        'ผลแปล |',
      ].join(' | '));
      sb.writeln(
        '| :--- | :---: | :---: | :---: | :---: | :--- | :---: | :---: | :---: |',
      );
      for (final p in plates) {
        for (final d in p.discs) {
          final bp = d.breakpoint;
          final String coordTxt =
              '(${d.cx.toStringAsFixed(0)}, ${d.cy.toStringAsFixed(0)})';
          final String bpRangeTxt =
              '<= ${bp.rMaxMm.toStringAsFixed(0)} / >= ${bp.sMinMm.toStringAsFixed(0)}';
          sb.writeln([
            '| ${p.title}',
            '#${d.discOrder}',
            d.plateZone,
            coordTxt,
            '**${d.drugCode}**',
            bp.fullName,
            d.diameterMm.toStringAsFixed(1),
            bpRangeTxt,
            '**${d.sirStatus}** |',
          ].join(' | '));
        }
      }
      content = sb.toString();
    } else {
      ext = 'csv';
      mimeType = 'text/csv';
      final StringBuffer sb = StringBuffer('\uFEFF');
      sb.writeln([
        'Plate_Title',
        'Disc_Order',
        'Plate_Zone',
        'Center_X',
        'Center_Y',
        'Drug_Code',
        'Drug_Full_Name',
        'Diameter_mm',
        'CLSI_R_Max_mm',
        'CLSI_S_Min_mm',
        'SIR_Status',
      ].join(','));
      for (final p in plates) {
        for (final d in p.discs) {
          final bp = d.breakpoint;
          sb.writeln([
            '"${p.title}"',
            '${d.discOrder}',
            '"${d.plateZone}"',
            d.cx.toStringAsFixed(0),
            d.cy.toStringAsFixed(0),
            '"${d.drugCode}"',
            '"${bp.fullName}"',
            d.diameterMm.toStringAsFixed(1),
            bp.rMaxMm.toStringAsFixed(1),
            bp.sMinMm.toStringAsFixed(1),
            d.sirStatus,
          ].join(','));
        }
      }
      content = sb.toString();
    }

    final DateTime now = DateTime.now();
    final String yStr = now.year.toString();
    final String mStr = now.month.toString().padLeft(2, '0');
    final String dStr = now.day.toString().padLeft(2, '0');
    final String hhStr = now.hour.toString().padLeft(2, '0');
    final String mmStr = now.minute.toString().padLeft(2, '0');
    final String stamp = '${yStr}${mStr}${dStr}_${hhStr}${mmStr}';
    final String defaultFileName = 'ast_export_${plates.length}plates_$stamp.$ext';
    final Uint8List bytes = Uint8List.fromList(utf8.encode(content));

    return {
      'ext': ext,
      'mimeType': mimeType,
      'content': content,
      'bytes': bytes,
      'defaultFileName': defaultFileName,
    };
  }

  Future<String?> _saveExportViaSystemPicker({
    required String fileName,
    required String mimeType,
    required Uint8List bytes,
  }) async {
    if (kIsWeb) return null;
    try {
      final String? savedUriOrPath = await AstSotaVisionEngine._yoloChannel
          .invokeMethod<String>('saveFileWithPicker', {
        'fileName': fileName,
        'mimeType': mimeType,
        'fileBytes': bytes,
      });
      return savedUriOrPath;
    } on MissingPluginException {
      return null;
    } catch (_) {
      return null;
    }
  }

  Future<String?> _saveExportToTargetDirectory({
    required String folderMode,
    required String customDirPath,
    required String fileName,
    required String mimeType,
    required Uint8List bytes,
  }) async {
    if (kIsWeb) return null;

    // 1. ลองบันทึกผ่าน Native Android MediaStore / Public Directory ก่อน (รองรับ Android 10-15 Scoped Storage)
    if (folderMode == 'downloads' || folderMode == 'documents' || folderMode == 'custom') {
      try {
        final String? nativeSavedPath = await AstSotaVisionEngine._yoloChannel
            .invokeMethod<String>('saveFileToPublicFolder', {
          'folderMode': folderMode,
          'customDirPath': customDirPath,
          'fileName': fileName,
          'mimeType': mimeType,
          'fileBytes': bytes,
        });
        if (nativeSavedPath != null && nativeSavedPath.isNotEmpty) {
          return nativeSavedPath;
        }
      } catch (_) {}
    }

    // 2. Fallback ด้วย dart:io สำหรับ Desktop (Linux/Windows/macOS) หรือโฟลเดอร์ที่เข้าถึงได้โดยตรง
    final List<String> candidateDirs = <String>[];
    if (folderMode == 'custom' && customDirPath.trim().isNotEmpty) {
      candidateDirs.add(customDirPath.trim());
    } else if (folderMode == 'downloads') {
      candidateDirs.add('/storage/emulated/0/Download');
      candidateDirs.add('/sdcard/Download');
      try {
        final Directory? dl = await getDownloadsDirectory();
        if (dl != null) candidateDirs.add(dl.path);
      } catch (_) {}
    } else if (folderMode == 'documents') {
      candidateDirs.add('/storage/emulated/0/Documents');
      candidateDirs.add('/sdcard/Documents');
      try {
        final Directory doc = await getApplicationDocumentsDirectory();
        candidateDirs.add(doc.path);
      } catch (_) {}
    }

    try {
      final Directory? extDir = await getExternalStorageDirectory();
      if (extDir != null) candidateDirs.add(extDir.path);
    } catch (_) {}
    try {
      final Directory appDoc = await getApplicationDocumentsDirectory();
      candidateDirs.add(appDoc.path);
    } catch (_) {}

    for (final String dirPath in candidateDirs) {
      try {
        final Directory d = Directory(dirPath);
        if (!await d.exists()) {
          await d.create(recursive: true);
        }
        final String cleanDir = dirPath.endsWith('/')
            ? dirPath.substring(0, dirPath.length - 1)
            : dirPath;
        final File out = File('$cleanDir/$fileName');
        await out.writeAsBytes(bytes, flush: true);
        return out.path;
      } catch (_) {
        continue;
      }
    }
    return null;
  }

  Future<void> _runCombinedExport() async {
    final List<AlbumPlateEntry> plates = _getPlatesForExport();
    if (plates.isEmpty) return;

    final Map<String, dynamic> bundle = _buildExportPayload(plates);
    final String ext = bundle['ext'] as String;
    final String mimeType = bundle['mimeType'] as String;
    final String content = bundle['content'] as String;
    final Uint8List bytes = bundle['bytes'] as Uint8List;
    final String defaultFileName = bundle['defaultFileName'] as String;

    final TextEditingController fileNameCtrl =
        TextEditingController(text: defaultFileName);
    final TextEditingController customDirCtrl =
        TextEditingController(text: '/storage/emulated/0/Download');
    String selectedFolderMode = 'downloads';
    final t = _t;

    if (!mounted) return;
    await showDialog<void>(
      context: context,
      builder: (ctx) {
        return StatefulBuilder(
          builder: (ctx, setDialogState) {
            String sanitizeFileName(String raw) {
              String name = raw.trim();
              if (name.isEmpty) name = defaultFileName;
              if (!name.toLowerCase().endsWith('.$ext')) {
                name = '$name.$ext';
              }
              return name;
            }

            Widget folderOptionTile({
              required String mode,
              required IconData icon,
              required String title,
              required String subtitle,
            }) {
              final bool isSel = selectedFolderMode == mode;
              return Padding(
                padding: const EdgeInsets.only(bottom: 6),
                child: InkWell(
                  borderRadius: BorderRadius.circular(9),
                  onTap: () => setDialogState(() => selectedFolderMode = mode),
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                    decoration: BoxDecoration(
                      color: isSel ? t.selectedNavBg : t.cardElevated,
                      borderRadius: BorderRadius.circular(9),
                      border: Border.all(
                        color: isSel ? t.primary : t.border,
                        width: isSel ? 1.5 : 1.0,
                      ),
                    ),
                    child: Row(
                      children: [
                        Icon(
                          isSel ? Icons.radio_button_checked : Icons.radio_button_off,
                          size: 18,
                          color: isSel ? t.accent : t.muted,
                        ),
                        const SizedBox(width: 8),
                        Icon(icon, size: 18, color: isSel ? t.accent : t.text),
                        const SizedBox(width: 8),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                title,
                                style: TextStyle(
                                  fontWeight: FontWeight.w700,
                                  fontSize: 12.5,
                                  color: t.text,
                                ),
                              ),
                              Text(
                                subtitle,
                                style: TextStyle(fontSize: 10.5, color: t.muted),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              );
            }

            return AlertDialog(
              backgroundColor: t.card,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(14),
                side: BorderSide(color: t.border),
              ),
              title: Row(
                children: [
                  Icon(Icons.save_alt_rounded, color: t.accent, size: 21),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'เลือกตำแหน่งบันทึกไฟล์ส่งออก (${plates.length} จานเพาะเชื้อ)',
                      style: TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w800,
                        color: t.text,
                      ),
                    ),
                  ),
                ],
              ),
              content: SizedBox(
                width: 480,
                child: SingleChildScrollView(
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      TextField(
                        controller: fileNameCtrl,
                        style: TextStyle(color: t.text, fontSize: 13, fontWeight: FontWeight.w600),
                        decoration: InputDecoration(
                          labelText: 'ชื่อไฟล์ที่ต้องการบันทึก (File Name)',
                          labelStyle: TextStyle(color: t.muted, fontSize: 12),
                          prefixIcon: Icon(Icons.insert_drive_file_outlined, size: 18, color: t.accent),
                          isDense: true,
                          filled: true,
                          fillColor: t.cardElevated,
                          border: OutlineInputBorder(borderRadius: BorderRadius.circular(9)),
                        ),
                      ),
                      const SizedBox(height: 12),
                      FilledButton.icon(
                        style: FilledButton.styleFrom(
                          backgroundColor: t.primary,
                          foregroundColor: const Color(0xFFF1F5F9),
                          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 11),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                        ),
                        onPressed: () async {
                          final String fName = sanitizeFileName(fileNameCtrl.text);
                          final String? pickedRes = await _saveExportViaSystemPicker(
                            fileName: fName,
                            mimeType: mimeType,
                            bytes: bytes,
                          );
                          if (pickedRes == 'CANCELED') {
                            return;
                          }
                          if (pickedRes != null && pickedRes.isNotEmpty) {
                            await Clipboard.setData(ClipboardData(text: content));
                            if (!ctx.mounted) return;
                            Navigator.of(ctx).pop();
                            if (!mounted) return;
                            ScaffoldMessenger.of(context).showSnackBar(
                              SnackBar(
                                duration: const Duration(seconds: 5),
                                content: Text('บันทึกไฟล์ "$fName" ไปยังตำแหน่งที่เลือกเรียบร้อยแล้ว ($pickedRes)'),
                              ),
                            );
                            return;
                          }
                          // หากเครื่องยังไม่รองรับ System Picker ให้บันทึกตามโฟลเดอร์ที่เลือกด้านล่างแทน
                          final String? fallbackPath = await _saveExportToTargetDirectory(
                            folderMode: selectedFolderMode,
                            customDirPath: customDirCtrl.text,
                            fileName: fName,
                            mimeType: mimeType,
                            bytes: bytes,
                          );
                          await Clipboard.setData(ClipboardData(text: content));
                          if (!ctx.mounted) return;
                          Navigator.of(ctx).pop();
                          if (!mounted) return;
                          ScaffoldMessenger.of(context).showSnackBar(
                            SnackBar(
                              duration: const Duration(seconds: 5),
                              content: Text(
                                fallbackPath != null
                                    ? 'บันทึกไฟล์ไว้ที่: $fallbackPath'
                                    : 'คัดลอกข้อมูลไฟล์ "$fName" ลงคลิปบอร์ดแล้ว',
                              ),
                            ),
                          );
                        },
                        icon: const Icon(Icons.folder_open_rounded, size: 18),
                        label: const Text(
                          'เปิดหน้าต่างเลือกโฟลเดอร์ในเครื่อง (Save As...)',
                          style: TextStyle(fontWeight: FontWeight.w700, fontSize: 12.5),
                        ),
                      ),
                      const SizedBox(height: 12),
                      Text(
                        'หรือเลือกโฟลเดอร์ปลายทางด่วน:',
                        style: TextStyle(
                          fontSize: 11.5,
                          fontWeight: FontWeight.w700,
                          color: t.muted,
                        ),
                      ),
                      const SizedBox(height: 6),
                      folderOptionTile(
                        mode: 'downloads',
                        icon: Icons.download_for_offline_outlined,
                        title: 'โฟลเดอร์ ดาวน์โหลด (Downloads)',
                        subtitle: '/storage/emulated/0/Download',
                      ),
                      folderOptionTile(
                        mode: 'documents',
                        icon: Icons.snippet_folder_outlined,
                        title: 'โฟลเดอร์ เอกสาร (Documents)',
                        subtitle: '/storage/emulated/0/Documents',
                      ),
                      folderOptionTile(
                        mode: 'app',
                        icon: Icons.sd_storage_outlined,
                        title: 'โฟลเดอร์ของแอปพลิเคชัน (App Storage)',
                        subtitle: 'Android/data/org.clinical.ast.ast_flutter_app/files',
                      ),
                      folderOptionTile(
                        mode: 'custom',
                        icon: Icons.create_new_folder_outlined,
                        title: 'ระบุพาธโฟลเดอร์เอง (Custom Folder Path)',
                        subtitle: 'พิมพ์ตำแหน่งโฟลเดอร์ที่ต้องการบันทึกด้านล่าง',
                      ),
                      if (selectedFolderMode == 'custom') ...[
                        const SizedBox(height: 4),
                        TextField(
                          controller: customDirCtrl,
                          style: TextStyle(color: t.text, fontSize: 12),
                          decoration: InputDecoration(
                            labelText: 'พาธโฟลเดอร์ปลายทาง',
                            hintText: '/storage/emulated/0/Download',
                            isDense: true,
                            filled: true,
                            fillColor: t.cardElevated,
                            border: OutlineInputBorder(borderRadius: BorderRadius.circular(8)),
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.of(ctx).pop(),
                  child: Text('ยกเลิก', style: TextStyle(color: t.muted)),
                ),
                OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                    foregroundColor: t.text,
                    side: BorderSide(color: t.border),
                  ),
                  onPressed: () async {
                    await Clipboard.setData(ClipboardData(text: content));
                    if (!ctx.mounted) return;
                    Navigator.of(ctx).pop();
                    if (!mounted) return;
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(content: Text('คัดลอกข้อมูลลงคลิปบอร์ดเรียบร้อยแล้ว')),
                    );
                  },
                  icon: const Icon(Icons.copy_rounded, size: 15),
                  label: const Text('คัดลอกลงคลิปบอร์ด', style: TextStyle(fontSize: 12)),
                ),
                FilledButton.icon(
                  style: FilledButton.styleFrom(
                    backgroundColor: t.primary,
                    foregroundColor: const Color(0xFFF1F5F9),
                  ),
                  onPressed: () async {
                    final String fName = sanitizeFileName(fileNameCtrl.text);
                    final String? savedPath = await _saveExportToTargetDirectory(
                      folderMode: selectedFolderMode,
                      customDirPath: customDirCtrl.text,
                      fileName: fName,
                      mimeType: mimeType,
                      bytes: bytes,
                    );
                    await Clipboard.setData(ClipboardData(text: content));
                    if (!ctx.mounted) return;
                    Navigator.of(ctx).pop();
                    if (!mounted) return;
                    ScaffoldMessenger.of(context).showSnackBar(
                      SnackBar(
                        duration: const Duration(seconds: 5),
                        content: Text(
                          savedPath != null
                              ? 'บันทึกไฟล์สำเร็จที่: $savedPath'
                              : 'คัดลอกข้อมูลไฟล์ "$fName" ลงคลิปบอร์ดแล้ว',
                        ),
                      ),
                    );
                  },
                  icon: const Icon(Icons.check_circle_outline, size: 16),
                  label: const Text('บันทึกตามโฟลเดอร์ที่เลือก', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 12)),
                ),
              ],
            );
          },
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final double screenW = MediaQuery.of(context).size.width;
    final bool isWide = screenW >= 920;
    final bool canDockSidebarInline = screenW >= 1260;
    final bool compactBar = screenW < 1280;
    final t = _t;

    return Scaffold(
      key: _scaffoldKey,
      backgroundColor: t.bg,
      drawer: (!canDockSidebarInline)
          ? Drawer(
              width: 284,
              backgroundColor: t.card,
              child: SafeArea(child: _buildAlbumSlideBar(isFullWidth: true)),
            )
          : null,
      appBar: AppBar(
        automaticallyImplyLeading: false,
        backgroundColor: t.bg,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        toolbarHeight: 50,
        titleSpacing: 12,
        shape: Border(bottom: BorderSide(color: t.border, width: 1.0)),
        title: Row(
          children: [
            OutlinedButton.icon(
              style: OutlinedButton.styleFrom(
                visualDensity: VisualDensity.compact,
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                backgroundColor: t.card,
                foregroundColor: t.text,
                side: BorderSide(color: t.border),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(9)),
              ),
              onPressed: () {
                if (canDockSidebarInline) {
                  setState(() => _showAlbumSlideBar = !_showAlbumSlideBar);
                } else {
                  _scaffoldKey.currentState?.openDrawer();
                }
              },
              icon: Icon(
                canDockSidebarInline && _showAlbumSlideBar
                    ? Icons.view_sidebar_outlined
                    : Icons.photo_library_outlined,
                size: 15,
                color: t.accent,
              ),
              label: Text(
                'อัลบั้ม (${_album.length})',
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                  color: t.text,
                ),
              ),
            ),
            const SizedBox(width: 10),
            Container(
              width: 26,
              height: 26,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                gradient: LinearGradient(
                  colors: [t.primary, t.accent],
                  begin: Alignment.topLeft,
                  end: Alignment.bottomRight,
                ),
              ),
              child: const Icon(Icons.biotech, color: Colors.white, size: 16),
            ),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                screenW < 760
                    ? 'AST Disk Diffusion'
                    : (screenW < 1180
                        ? 'ระบบวิเคราะห์ความไวต่อยาปฏิชีวนะ (AST)'
                        : 'ระบบวิเคราะห์ความไวต่อยาปฏิชีวนะ (AST Disk Diffusion System)'),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontWeight: FontWeight.w800,
                  fontSize: 14,
                  color: t.text,
                  letterSpacing: -0.2,
                ),
              ),
            ),
          ],
        ),
        actions: [
          OutlinedButton.icon(
            style: OutlinedButton.styleFrom(
              visualDensity: VisualDensity.compact,
              padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
              backgroundColor: t.card,
              side: BorderSide(
                color: _usePcServerMode ? t.warning.withOpacity(0.6) : t.border,
              ),
              foregroundColor: _usePcServerMode ? t.warning : t.muted,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(9)),
            ),
            onPressed: _showServerConfigDialog,
            icon: Icon(
              _usePcServerMode ? Icons.dns : Icons.memory,
              size: 14,
              color: _usePcServerMode ? t.warning : t.accent,
            ),
            label: Text(
              compactBar ? 'YOLO26n' : 'YOLO26n + AST-OCR',
              style: TextStyle(
                fontWeight: FontWeight.w600,
                fontSize: 11.5,
                color: t.text,
              ),
            ),
          ),
          const SizedBox(width: 6),
          OutlinedButton.icon(
            style: OutlinedButton.styleFrom(
              visualDensity: VisualDensity.compact,
              padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
              backgroundColor: t.card,
              side: BorderSide(color: t.border),
              foregroundColor: t.text,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(9)),
            ),
            onPressed: () => _pickSinglePlateFallback(ImageSource.camera),
            icon: Icon(Icons.photo_camera_outlined, size: 15, color: t.accent),
            label: Text(
              compactBar ? 'ถ่ายภาพ' : 'ถ่ายภาพจาน',
              style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 11.5),
            ),
          ),
          const SizedBox(width: 6),
          FilledButton.icon(
            style: FilledButton.styleFrom(
              visualDensity: VisualDensity.compact,
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              backgroundColor: t.primary,
              foregroundColor: const Color(0xFFF1F5F9),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(9)),
            ),
            onPressed: _pickAndAnalyzeMultiplePlates,
            icon: const Icon(Icons.add_photo_alternate_outlined, size: 15),
            label: Text(
              compactBar ? 'นำเข้าภาพ' : 'นำเข้าภาพจานเพาะเชื้อ',
              style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 11.5),
            ),
          ),
          const SizedBox(width: 6),
          OutlinedButton.icon(
            style: OutlinedButton.styleFrom(
              visualDensity: VisualDensity.compact,
              padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 6),
              backgroundColor: t.card,
              side: BorderSide(color: t.border),
              foregroundColor: t.text,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(9)),
            ),
            onPressed: _isSkeletonLoading
                ? null
                : () => _showCustomDrugEditDialog(targetDiscIndex: _selectedIndex),
            icon: Icon(Icons.tune_rounded, color: t.accent, size: 15),
            label: Text(
              'เกณฑ์ยา',
              style: TextStyle(
                color: t.text,
                fontWeight: FontWeight.w600,
                fontSize: 11.5,
              ),
            ),
          ),
          IconButton(
            visualDensity: VisualDensity.compact,
            tooltip: widget.isDarkMode ? 'สลับเป็นโหมดสว่าง (Light Mode)' : 'สลับเป็นโหมดมืด (Dark Mode)',
            onPressed: widget.onToggleTheme,
            icon: Icon(
              widget.isDarkMode ? Icons.dark_mode_outlined : Icons.light_mode_outlined,
              size: 18,
              color: t.text,
            ),
          ),
          const SizedBox(width: 4),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: isWide
                  ? Padding(
                      padding: const EdgeInsets.fromLTRB(10, 8, 10, 6),
                      child: Row(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          if (canDockSidebarInline && _showAlbumSlideBar) ...[
                            _buildAlbumSlideBar(),
                            const SizedBox(width: 10),
                          ],
                          Expanded(flex: 10, child: _buildFullSizePlateCanvasCard()),
                          const SizedBox(width: 10),
                          Expanded(flex: 11, child: _buildRightPanel(isMobile: false)),
                        ],
                      ),
                    )
                  : SingleChildScrollView(
                      padding: const EdgeInsets.fromLTRB(10, 8, 10, 10),
                      child: Column(
                        children: [
                          SizedBox(
                            height: math.min(420.0, screenW * 0.94),
                            child: _buildFullSizePlateCanvasCard(),
                          ),
                          const SizedBox(height: 10),
                          _buildRightPanel(isMobile: true),
                        ],
                      ),
                    ),
            ),
            _buildBottomExportBar(),
          ],
        ),
      ),
    );
  }

  Widget _buildAlbumSlideBar({bool isFullWidth = false}) {
    final t = _t;
    return Container(
      width: isFullWidth ? double.infinity : 236,
      decoration: BoxDecoration(
        color: t.card,
        borderRadius: isFullWidth ? BorderRadius.zero : BorderRadius.circular(12),
        border: isFullWidth ? null : Border.all(color: t.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(12, 12, 12, 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Row(
                      children: [
                        Icon(Icons.folder_copy_outlined, size: 15, color: t.accent),
                        const SizedBox(width: 7),
                        Text(
                          'รายการภาพ (${_album.length})',
                          style: TextStyle(
                            fontWeight: FontWeight.w700,
                            fontSize: 12.5,
                            color: t.text,
                          ),
                        ),
                      ],
                    ),
                    Text(
                      'เลือก ${_checkedAlbumIds.length}',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                        color: t.accent,
                      ),
                    ),
                  ],
                ),
                if (_pendingTasks.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Container(
                    padding: const EdgeInsets.all(8),
                    decoration: BoxDecoration(
                      color: t.primary.withOpacity(0.12),
                      borderRadius: BorderRadius.circular(8),
                      border: Border.all(color: t.primary.withOpacity(0.35)),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'กำลังประมวลผลขนาน ($_completedQueuedCount/$_totalQueuedCount)',
                          style: TextStyle(
                            fontSize: 10.5,
                            fontWeight: FontWeight.bold,
                            color: t.accent,
                          ),
                        ),
                        const SizedBox(height: 2),
                        Text(
                          'แก้ไขรูปปัจจุบันต่อได้ทันที',
                          style: TextStyle(fontSize: 9.5, color: t.muted),
                        ),
                      ],
                    ),
                  ),
                ],
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton(
                        style: OutlinedButton.styleFrom(
                          visualDensity: VisualDensity.compact,
                          padding: const EdgeInsets.symmetric(vertical: 4),
                          backgroundColor: t.cardElevated,
                          foregroundColor: t.text,
                          side: BorderSide(color: t.border),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(7)),
                          textStyle: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600),
                        ),
                        onPressed: () {
                          setState(() {
                            for (final item in _album) {
                              _checkedAlbumIds.add(item.id);
                            }
                            if (_album.isNotEmpty) _exportScope = 'checked';
                          });
                        },
                        child: const Text('เลือกทั้งหมด'),
                      ),
                    ),
                    const SizedBox(width: 6),
                    Expanded(
                      child: OutlinedButton(
                        style: OutlinedButton.styleFrom(
                          visualDensity: VisualDensity.compact,
                          padding: const EdgeInsets.symmetric(vertical: 4),
                          backgroundColor: t.cardElevated,
                          foregroundColor: t.muted,
                          side: BorderSide(color: t.border),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(7)),
                          textStyle: const TextStyle(fontSize: 11, fontWeight: FontWeight.w600),
                        ),
                        onPressed: () {
                          setState(() {
                            _checkedAlbumIds.clear();
                            _exportScope = 'current';
                          });
                        },
                        child: const Text('ล้างที่เลือก'),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 5),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton(
                        style: OutlinedButton.styleFrom(
                          visualDensity: VisualDensity.compact,
                          padding: const EdgeInsets.symmetric(vertical: 4),
                          foregroundColor: t.danger,
                          backgroundColor: t.danger.withOpacity(0.08),
                          side: BorderSide(color: t.danger.withOpacity(0.35)),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(7)),
                          textStyle: const TextStyle(fontSize: 10.5, fontWeight: FontWeight.w600),
                        ),
                        onPressed: _checkedAlbumIds.isEmpty ? null : _bulkDeleteSelectedEntries,
                        child: Text('ลบที่เลือก (${_checkedAlbumIds.length})'),
                      ),
                    ),
                    const SizedBox(width: 6),
                    Expanded(
                      child: OutlinedButton(
                        style: OutlinedButton.styleFrom(
                          visualDensity: VisualDensity.compact,
                          padding: const EdgeInsets.symmetric(vertical: 4),
                          foregroundColor: t.danger,
                          backgroundColor: t.danger.withOpacity(0.08),
                          side: BorderSide(color: t.danger.withOpacity(0.35)),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(7)),
                          textStyle: const TextStyle(fontSize: 10.5, fontWeight: FontWeight.w600),
                        ),
                        onPressed: _album.isEmpty ? null : _clearEntireAlbum,
                        child: const Text('ล้างอัลบั้ม'),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
          Divider(height: 1, color: t.border),
          Expanded(
            child: (_album.isEmpty && _pendingTasks.isEmpty)
                ? Center(
                    child: Padding(
                      padding: const EdgeInsets.all(14),
                      child: Text(
                        'ยังไม่มีภาพในอัลบั้ม\nกดปุ่ม "นำเข้าภาพ" ด้านบนเพื่อวิเคราะห์หลายภาพพร้อมกัน',
                        textAlign: TextAlign.center,
                        style: TextStyle(fontSize: 11.5, color: t.muted),
                      ),
                    ),
                  )
                : ListView(
                    padding: const EdgeInsets.all(8),
                    children: [
                      for (final pTask in _pendingTasks)
                        Container(
                          margin: const EdgeInsets.only(bottom: 6),
                          padding: const EdgeInsets.all(7),
                          decoration: BoxDecoration(
                            color: t.cardElevated,
                            borderRadius: BorderRadius.circular(9),
                            border: Border.all(color: t.accent.withOpacity(0.45)),
                          ),
                          child: Row(
                            children: [
                              const SizedBox(
                                width: 15,
                                height: 15,
                                child: CircularProgressIndicator(strokeWidth: 2),
                              ),
                              const SizedBox(width: 8),
                              if (pTask.previewBytes != null)
                                ClipRRect(
                                  borderRadius: BorderRadius.circular(6),
                                  child: Image.memory(
                                    pTask.previewBytes!,
                                    width: 38,
                                    height: 38,
                                    fit: BoxFit.cover,
                                    gaplessPlayback: true,
                                  ),
                                ),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Text(
                                      pTask.title,
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                      style: TextStyle(
                                        fontWeight: FontWeight.bold,
                                        fontSize: 11.5,
                                        color: t.text,
                                      ),
                                    ),
                                    Text(
                                      'กำลังวิเคราะห์ขนาน...',
                                      style: TextStyle(fontSize: 10, color: t.accent),
                                    ),
                                  ],
                                ),
                              ),
                            ],
                          ),
                        ),
                      for (final item in _album)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 6),
                          child: InkWell(
                            onTap: () {
                              _switchAlbumItemWithSkeleton(item);
                              if (isFullWidth) {
                                Navigator.of(context).maybePop();
                              }
                            },
                            borderRadius: BorderRadius.circular(9),
                            child: Container(
                              padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 6),
                              decoration: BoxDecoration(
                                color: item.id == _activeAlbumId
                                    ? t.selectedNavBg
                                    : t.cardElevated,
                                borderRadius: BorderRadius.circular(9),
                                border: Border.all(
                                  color: item.id == _activeAlbumId
                                      ? t.primary
                                      : t.border,
                                  width: item.id == _activeAlbumId ? 1.4 : 1.0,
                                ),
                              ),
                              child: Row(
                                children: [
                                  SizedBox(
                                    width: 22,
                                    height: 22,
                                    child: Checkbox(
                                      value: _checkedAlbumIds.contains(item.id),
                                      onChanged: (v) {
                                        setState(() {
                                          if (v == true) {
                                            _checkedAlbumIds.add(item.id);
                                            if (_exportScope == 'current') {
                                              _exportScope = 'checked';
                                            }
                                          } else {
                                            _checkedAlbumIds.remove(item.id);
                                          }
                                        });
                                      },
                                    ),
                                  ),
                                  const SizedBox(width: 5),
                                  if (item.imageBytes != null)
                                    ClipRRect(
                                      borderRadius: BorderRadius.circular(6),
                                      child: Image.memory(
                                        item.imageBytes!,
                                        width: 38,
                                        height: 38,
                                        fit: BoxFit.cover,
                                        gaplessPlayback: true,
                                      ),
                                    ),
                                  const SizedBox(width: 8),
                                  Expanded(
                                    child: Column(
                                      crossAxisAlignment: CrossAxisAlignment.start,
                                      children: [
                                        Text(
                                          item.title,
                                          maxLines: 1,
                                          overflow: TextOverflow.ellipsis,
                                          style: TextStyle(
                                            fontWeight: FontWeight.w700,
                                            fontSize: 11.5,
                                            color: t.text,
                                          ),
                                        ),
                                        Text(
                                          '${item.discs.length} แผ่นยา${item.id == _activeAlbumId ? " • กำลังดู" : ""}',
                                          style: TextStyle(
                                            fontSize: 10,
                                            color: item.id == _activeAlbumId
                                                ? t.accent
                                                : t.muted,
                                            fontWeight: item.id == _activeAlbumId
                                                ? FontWeight.w600
                                                : FontWeight.normal,
                                          ),
                                        ),
                                      ],
                                    ),
                                  ),
                                  IconButton(
                                    visualDensity: VisualDensity.compact,
                                    padding: EdgeInsets.zero,
                                    constraints: const BoxConstraints(minWidth: 24, minHeight: 24),
                                    icon: Icon(Icons.close, size: 14, color: t.danger),
                                    tooltip: 'ลบรูปนี้',
                                    onPressed: () => _deleteAlbumEntry(item.id),
                                  ),
                                ],
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
          ),
        ],
      ),
    );
  }

  Widget _buildFullSizePlateCanvasCard() {
    final t = _t;
    return Container(
      decoration: BoxDecoration(
        color: t.card,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: t.border),
      ),
      padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.radar_rounded, size: 16, color: t.accent),
              const SizedBox(width: 6),
              Expanded(
                child: Text(
                  'ภาพจานเพาะเชื้อและวงยับยั้งเชื้อ',
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontWeight: FontWeight.w700,
                    fontSize: 13,
                    color: t.text,
                  ),
                ),
              ),
              const SizedBox(width: 6),
              Flexible(
                flex: 0,
                child: SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      FilledButton.tonalIcon(
                        style: FilledButton.styleFrom(
                          visualDensity: VisualDensity.compact,
                          backgroundColor: _editCircleMode
                              ? t.primary.withOpacity(0.18)
                              : t.cardElevated,
                          foregroundColor: _editCircleMode ? t.text : t.muted,
                          side: BorderSide(
                            color: _editCircleMode ? t.primary : t.border,
                          ),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(7)),
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                        ),
                        onPressed: _isSkeletonLoading
                            ? null
                            : () {
                                setState(() => _editCircleMode = !_editCircleMode);
                              },
                        icon: Icon(
                          _editCircleMode ? Icons.open_with_rounded : Icons.lock_outline_rounded,
                          size: 13,
                          color: _editCircleMode ? t.accent : t.muted,
                        ),
                        label: Text(
                          _editCircleMode ? 'แก้ไขวง: เปิด' : 'แก้ไขวง: ล็อก',
                          style: const TextStyle(fontSize: 10.5, fontWeight: FontWeight.w600),
                        ),
                      ),
                      const SizedBox(width: 5),
                      FilledButton.tonalIcon(
                        style: FilledButton.styleFrom(
                          visualDensity: VisualDensity.compact,
                          backgroundColor: _soloSelectedZoneMode
                              ? t.accent.withOpacity(0.18)
                              : t.cardElevated,
                          foregroundColor: t.text,
                          side: BorderSide(
                            color: _soloSelectedZoneMode ? t.accent : t.border,
                          ),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(7)),
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                        ),
                        onPressed: _isSkeletonLoading
                            ? null
                            : () {
                                setState(() => _soloSelectedZoneMode = !_soloSelectedZoneMode);
                              },
                        icon: Icon(
                          _soloSelectedZoneMode
                              ? Icons.visibility_off_outlined
                              : Icons.center_focus_strong_rounded,
                          size: 13,
                          color: _soloSelectedZoneMode ? t.accent : t.muted,
                        ),
                        label: Text(
                          _soloSelectedZoneMode ? 'ซ่อนวงอื่น: เปิด' : 'ซ่อนวงอื่น',
                          style: const TextStyle(fontSize: 10.5, fontWeight: FontWeight.w600),
                        ),
                      ),
                      const SizedBox(width: 5),
                      FilledButton.icon(
                        style: FilledButton.styleFrom(
                          visualDensity: VisualDensity.compact,
                          backgroundColor: _addDiscTapMode ? t.accent : t.primary,
                          foregroundColor: const Color(0xFFF1F5F9),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(7)),
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                        ),
                        onPressed: _isSkeletonLoading
                            ? null
                            : () {
                                setState(() => _addDiscTapMode = !_addDiscTapMode);
                              },
                        icon: Icon(
                          _addDiscTapMode ? Icons.touch_app_rounded : Icons.add_circle_outline_rounded,
                          size: 13,
                        ),
                        label: Text(
                          _addDiscTapMode ? 'แตะวางบนจาน' : '+ เพิ่มยา',
                          style: const TextStyle(fontSize: 10.5, fontWeight: FontWeight.w700),
                        ),
                      ),
                      const SizedBox(width: 5),
                      OutlinedButton.icon(
                        style: OutlinedButton.styleFrom(
                          visualDensity: VisualDensity.compact,
                          backgroundColor: t.cardElevated,
                          foregroundColor: t.text,
                          side: BorderSide(color: t.border),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(7)),
                          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                        ),
                        onPressed: () {
                          setState(() => _fillPlateFrame = !_fillPlateFrame);
                        },
                        icon: Icon(
                          _fillPlateFrame ? Icons.fit_screen_outlined : Icons.fullscreen_rounded,
                          size: 14,
                          color: t.accent,
                        ),
                        label: Text(
                          _fillPlateFrame ? 'พอดีภาพ' : 'เต็มกรอบ',
                          style: const TextStyle(fontSize: 10.5, fontWeight: FontWeight.w600),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          Expanded(
            child: Container(
              width: double.infinity,
              decoration: BoxDecoration(
                color: const Color(0xFF13171E),
                borderRadius: BorderRadius.circular(10),
                border: Border.all(color: t.border),
              ),
              child: _isSkeletonLoading
                  ? _buildCanvasSkeletonLoader()
                  : (_decodedImage == null || _displayImageBytes == null
                      ? Center(
                          child: Text(
                            'ยังไม่มีรูปจานเพาะเชื้อ',
                            style: TextStyle(color: t.muted),
                          ),
                        )
                      : Center(
                          child: _fillPlateFrame
                              ? _buildInteractivePlateStack()
                              : AspectRatio(
                                  aspectRatio:
                                      _decodedImage!.width / _decodedImage!.height,
                                  child: _buildInteractivePlateStack(),
                                ),
                        )),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildInteractivePlateStack() {
    return LayoutBuilder(
      builder: (context, constraints) {
        final Size renderSize = Size(
          constraints.maxWidth,
          constraints.maxHeight,
        );
        return GestureDetector(
          onTapUp: (details) => _handleCanvasTap(details.localPosition, renderSize),
          onPanStart: (details) {
            if (!_editCircleMode || _decodedImage == null || _discs.isEmpty) return;
            final double scaleX = _decodedImage!.width / renderSize.width;
            final double scaleY = _decodedImage!.height / renderSize.height;
            final double imgX = details.localPosition.dx * scaleX;
            final double imgY = details.localPosition.dy * scaleY;

            int? hitIdx = _selectedIndex;
            double minDist = double.infinity;
            for (int i = 0; i < _discs.length; i++) {
              final double dist = math.sqrt(
                math.pow(imgX - _discs[i].cx, 2) + math.pow(imgY - _discs[i].cy, 2),
              );
              if (dist <= math.max(_discs[i].rZonePx * 1.25, 45.0) && dist < minDist) {
                minDist = dist;
                hitIdx = i;
              }
            }
            if (hitIdx != null) {
              setState(() {
                _selectedIndex = hitIdx;
                final d = _discs[hitIdx!];
                final double distFromCenter = math.sqrt(
                  math.pow(imgX - d.cx, 2) + math.pow(imgY - d.cy, 2),
                );
                _isDraggingCenter =
                    distFromCenter <= math.max(d.rDiscPx * 1.45, d.rZonePx * 0.65);
                // ยังไม่ทำให้วงอื่นจางตอนแตะเลือกเฉยๆ จะจางเฉพาะตอนเริ่มขยับนิ้วลากวง (onPanUpdate) เท่านั้น
                _isActivelyAdjustingZone = false;
                _refreshSelectedDiscZoomCrop();
              });
            }
          },
          onPanCancel: () {
            if (_isActivelyAdjustingZone) {
              setState(() => _isActivelyAdjustingZone = false);
            }
          },
          onPanUpdate: (details) {
            if (!_editCircleMode ||
                _decodedImage == null ||
                _selectedIndex == null ||
                _selectedIndex! >= _discs.length) {
              return;
            }
            final double scaleX = _decodedImage!.width / renderSize.width;
            final double scaleY = _decodedImage!.height / renderSize.height;
            final double imgX = details.localPosition.dx * scaleX;
            final double imgY = details.localPosition.dy * scaleY;
            final d = _discs[_selectedIndex!];

            if (_isDraggingCenter) {
              setState(() {
                _isActivelyAdjustingZone = true;
                d.cx = imgX.clamp(d.rDiscPx, _decodedImage!.width - d.rDiscPx);
                d.cy = imgY.clamp(d.rDiscPx, _decodedImage!.height - d.rDiscPx);
                _refreshSelectedDiscZoomCrop();
              });
            } else {
              _isActivelyAdjustingZone = true;
              final double distPx = math.sqrt(
                math.pow(imgX - d.cx, 2) + math.pow(imgY - d.cy, 2),
              );
              final double scaleMmPerPx = 6.0 / (2.0 * math.max(d.rDiscPx, 8.0));
              final double newMm = (2.0 * distPx * scaleMmPerPx).clamp(6.0, 42.0);
              _updateSelectedDiameter((newMm * 2.0).round() / 2.0);
            }
          },
          onPanEnd: (_) {
            if (!_editCircleMode || _decodedImage == null) return;
            setState(() {
              _isActivelyAdjustingZone = false;
              final DiscRecord? activeRef =
                  (_selectedIndex != null && _selectedIndex! < _discs.length)
                      ? _discs[_selectedIndex!]
                      : null;
              AstSotaVisionEngine.assignAutomaticSpatialOrder(
                _discs,
                _decodedImage!.width.toDouble(),
                _decodedImage!.height.toDouble(),
              );
              if (activeRef != null) {
                _selectedIndex = _discs.indexOf(activeRef);
              }
              _syncActiveAlbumState();
            });
          },
          child: Stack(
            fit: StackFit.expand,
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(9),
                child: Image.memory(
                  _displayImageBytes!,
                  fit: BoxFit.fill,
                  gaplessPlayback: true,
                ),
              ),
              CustomPaint(
                painter: _PlateOverlayPainter(
                  discs: _discs,
                  selectedIndex: _selectedIndex,
                  imageWidth: _decodedImage!.width.toDouble(),
                  imageHeight: _decodedImage!.height.toDouble(),
                  isActivelyAdjusting: _isActivelyAdjustingZone || _soloSelectedZoneMode,
                  hideOthersCompletely: _soloSelectedZoneMode,
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildCanvasSkeletonLoader() {
    final t = _t;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: t.cardElevated,
        borderRadius: BorderRadius.circular(10),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          const _SkeletonShimmerBox(width: 180, height: 180, borderRadius: 90),
          const SizedBox(height: 12),
          Text(
            _loadingStatusText,
            textAlign: TextAlign.center,
            style: TextStyle(fontSize: 12, color: t.accent),
          ),
        ],
      ),
    );
  }

  Widget _buildKpiSummaryRow() {
    final t = _t;
    int sCount = 0;
    int iCount = 0;
    int rCount = 0;
    double confSum = 0.0;
    for (final d in _discs) {
      if (d.sirStatus == 'S') {
        sCount++;
      } else if (d.sirStatus == 'I') {
        iCount++;
      } else {
        rCount++;
      }
      confSum += d.confidence;
    }
    final int avgConf =
        _discs.isNotEmpty ? ((confSum / _discs.length) * 100).round() : 0;

    Widget kpiCard(String label, String val, Color indicatorColor) {
      return Expanded(
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
          decoration: BoxDecoration(
            color: t.card,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(color: t.border),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  Container(
                    width: 6,
                    height: 6,
                    decoration: BoxDecoration(
                      color: indicatorColor,
                      shape: BoxShape.circle,
                    ),
                  ),
                  const SizedBox(width: 5),
                  Expanded(
                    child: Text(
                      label,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 10.5,
                        color: t.muted,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 3),
              Text(
                val,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(
                  fontSize: 15.5,
                  fontWeight: FontWeight.w800,
                  color: t.text,
                  letterSpacing: -0.3,
                ),
              ),
            ],
          ),
        ),
      );
    }

    return Row(
      children: [
        kpiCard('ทั้งหมด', '${_discs.length}', t.accent),
        const SizedBox(width: 6),
        kpiCard('ไว (S)', '$sCount', const Color(0xFF68B088)),
        const SizedBox(width: 6),
        kpiCard('ปานกลาง (I)', '$iCount', t.warning),
        const SizedBox(width: 6),
        kpiCard('ดื้อยา (R)', '$rCount', t.danger),
        const SizedBox(width: 6),
        kpiCard('ความแม่นยำ', '$avgConf%', t.primary),
      ],
    );
  }

  Widget _buildRightPanel({required bool isMobile}) {
    final t = _t;
    final DiscRecord? activeDisc =
        (_selectedIndex != null && _selectedIndex! < _discs.length)
            ? _discs[_selectedIndex!]
            : null;

    if (isMobile) {
      final Widget mobileTable = _isSkeletonLoading
          ? _buildTableSkeletonLoader()
          : _buildClinicalTable(shrinkWrap: true);
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          _buildKpiSummaryRow(),
          const SizedBox(height: 8),
          if (!_isSkeletonLoading && activeDisc != null) ...[
            _buildSelectedDiscInspector(activeDisc),
            const SizedBox(height: 8),
          ],
          Container(
            height: 340,
            decoration: BoxDecoration(
              color: t.card,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: t.border),
            ),
            padding: const EdgeInsets.all(10),
            child: mobileTable,
          ),
        ],
      );
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        // หากความสูงหน้าจอในแนวนอนค่อนข้างจำกัด (< 560px) ให้เลื่อนทั้งคอลัมน์ขวาได้ลื่นไหล
        // เพื่อไม่ให้ตารางผลลัพธ์ด้านล่างถูกบีบจนเหลือบรรทัดเดียว
        final bool tightVertical = constraints.maxHeight < 560;
        final Widget desktopTable = _isSkeletonLoading
            ? _buildTableSkeletonLoader()
            : _buildClinicalTable(shrinkWrap: false);

        if (tightVertical) {
          return SingleChildScrollView(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                _buildKpiSummaryRow(),
                const SizedBox(height: 8),
                if (!_isSkeletonLoading && activeDisc != null) ...[
                  _buildSelectedDiscInspector(activeDisc),
                  const SizedBox(height: 8),
                ],
                Container(
                  height: 270,
                  decoration: BoxDecoration(
                    color: t.card,
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: t.border),
                  ),
                  padding: const EdgeInsets.all(10),
                  child: desktopTable,
                ),
              ],
            ),
          );
        }

        return Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            _buildKpiSummaryRow(),
            const SizedBox(height: 8),
            if (!_isSkeletonLoading && activeDisc != null) ...[
              _buildSelectedDiscInspector(activeDisc),
              const SizedBox(height: 8),
            ],
            Expanded(
              child: Container(
                decoration: BoxDecoration(
                  color: t.card,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: t.border),
                ),
                padding: const EdgeInsets.all(10),
                child: desktopTable,
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _buildTableSkeletonLoader() {
    final t = _t;
    return ListView.separated(
      itemCount: 6,
      separatorBuilder: (_, __) => const SizedBox(height: 8),
      itemBuilder: (_, idx) => Container(
        padding: const EdgeInsets.all(10),
        decoration: BoxDecoration(
          color: t.cardElevated,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: t.border),
        ),
        child: const Row(
          children: [
            _SkeletonShimmerBox(width: 28, height: 28, borderRadius: 14),
            SizedBox(width: 10),
            Expanded(
              child: _SkeletonShimmerBox(width: 150, height: 13, borderRadius: 4),
            ),
            SizedBox(width: 10),
            _SkeletonShimmerBox(width: 60, height: 22, borderRadius: 6),
          ],
        ),
      ),
    );
  }

  Widget _buildSelectedDiscInspector(DiscRecord disc) {
    final t = _t;
    final Color badgeColor = _sirColor(disc.sirStatus);
    final int activeIdx = _selectedIndex ?? 0;
    final List<OcrCandidateScore> rankedCandidates =
        AstSotaVisionEngine.rankCandidatesForDisc(disc);

    return LayoutBuilder(
      builder: (context, constraints) {
        final bool stackVertically = constraints.maxWidth < 460;

        final Widget zoomCard = SizedBox(
          width: stackVertically ? 220 : 188,
          height: 174,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
            decoration: BoxDecoration(
              color: t.cardElevated,
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: t.border, width: 1.0),
            ),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                SizedBox(
                  height: 20,
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Expanded(
                        child: Text(
                          'เม็ดที่ #${disc.discOrder}/${_discs.length} (${disc.userRotDeg.toStringAsFixed(0)}°)',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            fontSize: 10.5,
                            fontWeight: FontWeight.w700,
                            color: t.text,
                          ),
                        ),
                      ),
                      InkWell(
                        onTap: () {
                          setState(() {
                            _zoomContrastBoost = !_zoomContrastBoost;
                            _refreshSelectedDiscZoomCrop();
                          });
                        },
                        borderRadius: BorderRadius.circular(5),
                        child: Container(
                          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 1.5),
                          decoration: BoxDecoration(
                            color: _zoomContrastBoost ? t.primary : t.card,
                            borderRadius: BorderRadius.circular(5),
                            border: Border.all(
                              color: _zoomContrastBoost ? t.primary : t.border,
                            ),
                          ),
                          child: Text(
                            'คอนทราสต์',
                            style: TextStyle(
                              fontSize: 9.5,
                              fontWeight: FontWeight.w600,
                              color: _zoomContrastBoost ? Colors.white : t.muted,
                            ),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    SizedBox(
                      width: 28,
                      height: 48,
                      child: OutlinedButton(
                        style: OutlinedButton.styleFrom(
                          padding: EdgeInsets.zero,
                          backgroundColor: t.card,
                          side: BorderSide(color: t.border, width: 1.0),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                        ),
                        onPressed: _discs.isEmpty
                            ? null
                            : () {
                                final int nextIdx =
                                    ((_selectedIndex ?? 0) - 1 + _discs.length) % _discs.length;
                                _selectDiscIndex(nextIdx);
                              },
                        child: Icon(Icons.chevron_left, color: t.text, size: 18),
                      ),
                    ),
                    Container(
                      width: 82,
                      height: 82,
                      padding: const EdgeInsets.all(2),
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        border: Border.all(color: t.accent.withOpacity(0.65), width: 1.6),
                      ),
                      child: ClipOval(
                        child: Container(
                          color: Colors.black,
                          child: _selectedDiscCropBytes != null
                              ? Transform.rotate(
                                  angle: disc.userRotDeg * math.pi / 180.0,
                                  child: Image.memory(
                                    _selectedDiscCropBytes!,
                                    fit: BoxFit.cover,
                                    gaplessPlayback: true,
                                  ),
                                )
                              : const Icon(Icons.lens_blur, size: 28, color: Colors.white38),
                        ),
                      ),
                    ),
                    SizedBox(
                      width: 28,
                      height: 48,
                      child: OutlinedButton(
                        style: OutlinedButton.styleFrom(
                          padding: EdgeInsets.zero,
                          backgroundColor: t.card,
                          side: BorderSide(color: t.border, width: 1.0),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                        ),
                        onPressed: _discs.isEmpty
                            ? null
                            : () {
                                final int nextIdx = ((_selectedIndex ?? 0) + 1) % _discs.length;
                                _selectDiscIndex(nextIdx);
                              },
                        child: Icon(Icons.chevron_right, color: t.text, size: 18),
                      ),
                    ),
                  ],
                ),
                SizedBox(
                  height: 22,
                  child: Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      for (final step in [
                        (label: '-45°', deg: -45.0),
                        (label: '-15°', deg: -15.0),
                        (label: '+15°', deg: 15.0),
                        (label: '+45°', deg: 45.0),
                        (label: '180°', deg: 180.0),
                      ])
                        Expanded(
                          child: Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 1.0),
                            child: OutlinedButton(
                              style: OutlinedButton.styleFrom(
                                visualDensity: VisualDensity.compact,
                                padding: EdgeInsets.zero,
                                side: BorderSide(color: t.border),
                                backgroundColor: t.card,
                                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(5)),
                              ),
                              onPressed: () => _rotateSelectedDiscZoom(step.deg),
                              child: Text(
                                step.label,
                                style: TextStyle(
                                  fontSize: 9.5,
                                  fontWeight: FontWeight.w600,
                                  color: t.text,
                                ),
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
                SizedBox(
                  width: double.infinity,
                  height: 25,
                  child: FilledButton.icon(
                    style: FilledButton.styleFrom(
                      visualDensity: VisualDensity.compact,
                      backgroundColor: t.primary,
                      foregroundColor: const Color(0xFFF1F5F9),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(7)),
                      padding: const EdgeInsets.symmetric(horizontal: 6),
                    ),
                    onPressed: _isReOcrBusy ? null : _reReadSelectedDiscOcr,
                    icon: const Icon(Icons.document_scanner_outlined, size: 12.5),
                    label: Text(
                      _isReOcrBusy ? 'กำลังอ่าน...' : 'อ่านรหัสยาซ้ำตามมุมหมุน',
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 10, fontWeight: FontWeight.w700),
                    ),
                  ),
                ),
              ],
            ),
          ),
        );

        final bool isKnownDrug =
            kClsiEucastDb.containsKey(disc.drugCode) && disc.drugCode != 'UNKNOWN';
        String rawReadText = disc.rawOcrText.trim().isNotEmpty
            ? disc.rawOcrText.trim()
            : (disc.drugCode != 'UNKNOWN' ? disc.drugCode : '');
        final RegExp revTokens = RegExp(r'^(\d+(?:/\d+)?)\s*([A-Z]{1,4})$');
        final Match? mRevDisp = revTokens.firstMatch(rawReadText);
        if (mRevDisp != null) {
          rawReadText = '${mRevDisp.group(2)!} ${mRevDisp.group(1)!}';
        }
        final String compactRawCode = rawReadText.replaceAll(' ', '');
        final List<OcrCandidateScore> topPossibleDrugs = rankedCandidates
            .where((c) => kClsiEucastDb.containsKey(c.code) && c.code != 'UNKNOWN')
            .take(5)
            .toList();

        final Widget controlsColumn = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    '#${disc.discOrder} (${disc.plateZone}) • ${disc.breakpoint.fullName}',
                    style: TextStyle(
                      fontWeight: FontWeight.w700,
                      fontSize: 12.5,
                      color: t.text,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                ),
                const SizedBox(width: 6),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2.5),
                  decoration: BoxDecoration(
                    color: isKnownDrug ? t.cardElevated : t.warning.withOpacity(0.14),
                    borderRadius: BorderRadius.circular(6),
                    border: Border.all(
                      color: isKnownDrug ? t.border : t.warning.withOpacity(0.5),
                    ),
                  ),
                  child: Text(
                    rawReadText.isNotEmpty ? 'OCR: "$rawReadText"' : 'OCR: รอระบุ',
                    style: TextStyle(
                      fontSize: 10.5,
                      fontWeight: FontWeight.w600,
                      color: isKnownDrug ? t.accent : t.warning,
                    ),
                  ),
                ),
                const SizedBox(width: 6),
                _buildSirBadge(disc.sirStatus),
              ],
            ),
            if (_reOcrStatus.isNotEmpty) ...[
              const SizedBox(height: 3),
              Text(
                _reOcrStatus,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: 10, fontWeight: FontWeight.w600, color: t.accent),
              ),
            ],
            const SizedBox(height: 7),
            Row(
              children: [
                Expanded(
                  child: DropdownButtonFormField<String>(
                    value: (isKnownDrug || disc.drugCode != 'UNKNOWN')
                        ? disc.drugCode
                        : 'UNKNOWN',
                    isExpanded: true,
                    decoration: InputDecoration(
                      labelText: 'รหัสยา / ชื่อยาที่เป็นไปได้ (เรียงตามความใกล้เคียง)',
                      labelStyle: TextStyle(color: t.muted, fontSize: 11),
                      isDense: true,
                      filled: true,
                      fillColor: t.cardElevated,
                      contentPadding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
                      enabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(8),
                        borderSide: BorderSide(color: t.border),
                      ),
                      focusedBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(8),
                        borderSide: BorderSide(color: t.primary, width: 1.4),
                      ),
                    ),
                    dropdownColor: t.cardElevated,
                    items: [
                      if (!isKnownDrug && disc.drugCode != 'UNKNOWN')
                        DropdownMenuItem<String>(
                          value: disc.drugCode,
                          child: Text(
                            '[อ่านได้] ${disc.drugCode} — ยานอกฐานข้อมูล',
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              fontSize: 11.5,
                              fontWeight: FontWeight.bold,
                              color: t.warning,
                            ),
                          ),
                        ),
                      const DropdownMenuItem<String>(
                        value: 'UNKNOWN',
                        child: Text(
                          '[รอระบุ] UNKNOWN — กรุณาเลือกรหัสยา',
                          style: TextStyle(fontSize: 11.5, fontWeight: FontWeight.bold),
                        ),
                      ),
                      ...rankedCandidates
                          .where((c) => kClsiEucastDb.containsKey(c.code) && c.code != 'UNKNOWN')
                          .map((cand) {
                        final int pct = (cand.confidence * 100).round();
                        final String fullName =
                            kClsiEucastDb[cand.code]?.fullName ?? cand.code;
                        return DropdownMenuItem<String>(
                          value: cand.code,
                          child: Text(
                            '[$pct%] ${cand.code} — $fullName',
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              fontWeight: FontWeight.w600,
                              fontSize: 11.5,
                              color: t.text,
                            ),
                          ),
                        );
                      }),
                    ],
                    onChanged: (newCode) {
                      if (newCode == null) return;
                      _applyTypedDrugCode(activeIdx, newCode);
                    },
                  ),
                ),
                const SizedBox(width: 4),
                IconButton(
                  visualDensity: VisualDensity.compact,
                  padding: const EdgeInsets.all(6),
                  constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
                  tooltip: 'พิมพ์แก้ไขชื่อยา/เกณฑ์เอง',
                  onPressed: () => _showCustomDrugEditDialog(targetDiscIndex: activeIdx),
                  icon: Icon(Icons.edit_note_rounded, size: 19, color: t.accent),
                ),
                IconButton(
                  visualDensity: VisualDensity.compact,
                  padding: const EdgeInsets.all(6),
                  constraints: const BoxConstraints(minWidth: 32, minHeight: 32),
                  tooltip: 'ลบเม็ดยานี้ออกจากจาน',
                  onPressed: () {
                    setState(() {
                      _discs.removeAt(activeIdx);
                      if (_decodedImage != null) {
                        AstSotaVisionEngine.assignAutomaticSpatialOrder(
                          _discs,
                          _decodedImage!.width.toDouble(),
                          _decodedImage!.height.toDouble(),
                        );
                      }
                      _selectedIndex = _discs.isNotEmpty
                          ? math.min(activeIdx, _discs.length - 1)
                          : null;
                      _refreshSelectedDiscZoomCrop();
                      _syncActiveAlbumState();
                    });
                  },
                  icon: Icon(Icons.delete_outline_rounded, size: 18, color: t.danger),
                ),
              ],
            ),
            const SizedBox(height: 5),
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: [
                  Text(
                    'ใกล้เคียง: ',
                    style: TextStyle(
                      fontSize: 10.5,
                      fontWeight: FontWeight.w600,
                      color: t.muted,
                    ),
                  ),
                  if (compactRawCode.isNotEmpty &&
                      !kClsiEucastDb.containsKey(compactRawCode))
                    Padding(
                      padding: const EdgeInsets.only(right: 5),
                      child: ActionChip(
                        visualDensity: VisualDensity.compact,
                        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 0),
                        backgroundColor: disc.drugCode == compactRawCode
                            ? t.warning.withOpacity(0.22)
                            : t.cardElevated,
                        side: BorderSide(
                          color: disc.drugCode == compactRawCode
                              ? t.warning
                              : t.border,
                        ),
                        label: Text(
                          'OCR: $compactRawCode',
                          style: TextStyle(
                            fontSize: 10.5,
                            fontWeight: FontWeight.bold,
                            color: t.text,
                          ),
                        ),
                        onPressed: () => _applyTypedDrugCode(
                          activeIdx,
                          compactRawCode,
                          isManual: false,
                          ocrConfidence: disc.confidence,
                        ),
                      ),
                    ),
                  for (final topCand in topPossibleDrugs)
                    Padding(
                      padding: const EdgeInsets.only(right: 5),
                      child: ActionChip(
                        visualDensity: VisualDensity.compact,
                        padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 0),
                        backgroundColor: topCand.code == disc.drugCode
                            ? t.primary
                            : t.cardElevated,
                        side: BorderSide(
                          color: topCand.code == disc.drugCode
                              ? t.primary
                              : t.border,
                        ),
                        label: Text(
                          '${topCand.code} (${(topCand.confidence * 100).round()}%)',
                          style: TextStyle(
                            fontSize: 10.5,
                            fontWeight: FontWeight.w700,
                            color: topCand.code == disc.drugCode
                                ? const Color(0xFFF1F5F9)
                                : t.text,
                          ),
                        ),
                        onPressed: () => _applyTypedDrugCode(
                          activeIdx,
                          topCand.code,
                          isManual: true,
                          ocrConfidence: topCand.confidence,
                        ),
                      ),
                    ),
                ],
              ),
            ),
            SizedBox(
              height: 32,
              child: Row(
                children: [
                  Text(
                    'ขนาดวง: ',
                    style: TextStyle(
                      fontSize: 11,
                      fontWeight: FontWeight.w600,
                      color: t.muted,
                    ),
                  ),
                  Expanded(
                    child: SliderTheme(
                      data: SliderTheme.of(context).copyWith(
                        trackHeight: 3.5,
                        thumbShape: const RoundSliderThumbShape(enabledThumbRadius: 7.0),
                        overlayShape: const RoundSliderOverlayShape(overlayRadius: 14.0),
                      ),
                      child: Slider(
                        value: disc.diameterMm.clamp(6.0, 42.0),
                        min: 6.0,
                        max: 42.0,
                        divisions: 72,
                        label: '${disc.diameterMm.toStringAsFixed(1)} mm',
                        onChangeStart: (_) {
                          setState(() => _isActivelyAdjustingZone = true);
                        },
                        onChanged: _updateSelectedDiameter,
                        onChangeEnd: (_) {
                          setState(() => _isActivelyAdjustingZone = false);
                        },
                      ),
                    ),
                  ),
                  Text(
                    '${disc.diameterMm.toStringAsFixed(1)} mm',
                    style: TextStyle(
                      fontWeight: FontWeight.w800,
                      fontSize: 12.5,
                      color: badgeColor,
                    ),
                  ),
                ],
              ),
            ),
          ],
        );

        return Container(
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: t.card,
            borderRadius: BorderRadius.circular(12),
            border: Border.all(color: t.border),
          ),
          child: stackVertically
              ? Column(
                  children: [
                    Center(child: zoomCard),
                    const SizedBox(height: 8),
                    controlsColumn,
                  ],
                )
              : Row(
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    zoomCard,
                    const SizedBox(width: 12),
                    Expanded(child: controlsColumn),
                  ],
                ),
        );
      },
    );
  }

  Widget _buildClinicalTable({bool shrinkWrap = false}) {
    final t = _t;
    if (_discs.isEmpty) {
      return Center(
        child: Text(
          'ไม่พบแผ่นยาบนจานเพาะเชื้อ',
          style: TextStyle(color: t.muted),
        ),
      );
    }
    return ListView.separated(
      shrinkWrap: shrinkWrap,
      itemCount: _discs.length,
      separatorBuilder: (_, __) => Divider(height: 1, color: t.border),
      itemBuilder: (context, idx) {
        final d = _discs[idx];
        final bool isSelected = idx == _selectedIndex;
        return ListTile(
          dense: true,
          visualDensity: const VisualDensity(horizontal: -2, vertical: -2),
          contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 1),
          selected: isSelected,
          selectedTileColor: t.selectedNavBg,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
          onTap: () => _selectDiscIndex(idx),
          leading: CircleAvatar(
            radius: 13,
            backgroundColor: isSelected ? t.primary : t.cardElevated,
            child: Text(
              '#${d.discOrder}',
              style: TextStyle(
                color: isSelected ? Colors.white : t.text,
                fontWeight: FontWeight.w700,
                fontSize: 10.5,
              ),
            ),
          ),
          title: Row(
            children: [
              Text(
                '${d.plateZone} • ',
                style: TextStyle(
                  fontWeight: FontWeight.w700,
                  fontSize: 12,
                  color: t.text,
                ),
              ),
              InkWell(
                onTap: () {
                  _selectDiscIndex(idx);
                  _showCustomDrugEditDialog(targetDiscIndex: idx);
                },
                borderRadius: BorderRadius.circular(5),
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
                  decoration: BoxDecoration(
                    color: d.needsReview
                        ? t.warning.withOpacity(0.15)
                        : t.cardElevated,
                    borderRadius: BorderRadius.circular(5),
                    border: Border.all(
                      color: d.needsReview ? t.warning : t.border,
                    ),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text(
                        d.drugCode,
                        style: TextStyle(
                          fontWeight: FontWeight.w700,
                          fontSize: 11.5,
                          color: d.needsReview ? t.warning : t.accent,
                        ),
                      ),
                      const SizedBox(width: 4),
                      Icon(Icons.edit, size: 11, color: t.muted),
                    ],
                  ),
                ),
              ),
            ],
          ),
          subtitle: Text(
            '${d.breakpoint.fullName} (R≤${d.breakpoint.rMaxMm.toStringAsFixed(0)} / S≥${d.breakpoint.sMinMm.toStringAsFixed(0)})',
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(fontSize: 10.5, color: t.muted),
          ),
          trailing: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                '${d.diameterMm.toStringAsFixed(1)} mm',
                style: TextStyle(
                  fontWeight: FontWeight.w700,
                  fontSize: 12.5,
                  color: t.text,
                ),
              ),
              const SizedBox(width: 8),
              _buildSirBadge(d.sirStatus),
            ],
          ),
        );
      },
    );
  }

  Widget _buildBottomExportBar() {
    final t = _t;
    final int exportPlateCount = _getPlatesForExport().length;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
      decoration: BoxDecoration(
        color: t.card,
        border: Border(top: BorderSide(color: t.border, width: 1.0)),
      ),
      child: Wrap(
        spacing: 12,
        runSpacing: 6,
        alignment: WrapAlignment.spaceBetween,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.inventory_2_outlined, size: 15, color: t.accent),
              const SizedBox(width: 6),
              Text(
                'ขอบเขตส่งออก:',
                style: TextStyle(
                  fontWeight: FontWeight.w600,
                  fontSize: 11.5,
                  color: t.muted,
                ),
              ),
              const SizedBox(width: 6),
              DropdownButton<String>(
                value: _exportScope,
                isDense: true,
                dropdownColor: t.cardElevated,
                style: TextStyle(color: t.text, fontSize: 11.5, fontWeight: FontWeight.w600),
                items: [
                  const DropdownMenuItem(
                    value: 'current',
                    child: Text('เฉพาะรูปปัจจุบัน (1 รูป)', style: TextStyle(fontSize: 11.5)),
                  ),
                  DropdownMenuItem(
                    value: 'checked',
                    child: Text(
                      'รูปที่เลือกในอัลบั้ม (${_checkedAlbumIds.length} รูป)',
                      style: const TextStyle(fontSize: 11.5),
                    ),
                  ),
                  DropdownMenuItem(
                    value: 'all',
                    child: Text(
                      'รวมทุกรูปทั้งหมด (${_album.length} รูป)',
                      style: const TextStyle(fontSize: 11.5),
                    ),
                  ),
                ],
                onChanged: (val) {
                  if (val != null) setState(() => _exportScope = val);
                },
              ),
            ],
          ),
          Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Text('รูปแบบ:', style: TextStyle(fontSize: 11.5, color: t.muted)),
              const SizedBox(width: 6),
              DropdownButton<String>(
                value: _exportFormat,
                isDense: true,
                dropdownColor: t.cardElevated,
                style: TextStyle(color: t.text, fontSize: 11.5, fontWeight: FontWeight.w600),
                items: const [
                  DropdownMenuItem(value: 'csv', child: Text('CSV (.csv)', style: TextStyle(fontSize: 11.5))),
                  DropdownMenuItem(value: 'tsv', child: Text('Excel TSV (.xls)', style: TextStyle(fontSize: 11.5))),
                  DropdownMenuItem(value: 'json', child: Text('JSON (.json)', style: TextStyle(fontSize: 11.5))),
                  DropdownMenuItem(value: 'md', child: Text('Markdown (.md)', style: TextStyle(fontSize: 11.5))),
                ],
                onChanged: (val) {
                  if (val != null) setState(() => _exportFormat = val);
                },
              ),
              const SizedBox(width: 10),
              FilledButton.icon(
                style: FilledButton.styleFrom(
                  visualDensity: VisualDensity.compact,
                  backgroundColor: t.primary,
                  foregroundColor: const Color(0xFFF1F5F9),
                  padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
                  textStyle: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.w700),
                ),
                onPressed: _isSkeletonLoading ? null : _runCombinedExport,
                icon: const Icon(Icons.download_rounded, size: 15),
                label: Text('ส่งออกไฟล์ ($exportPlateCount รายการ)'),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildSirBadge(String sir) {
    final Color c = _sirColor(sir);
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2.5),
      decoration: BoxDecoration(
        color: c.withOpacity(0.14),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: c.withOpacity(0.45), width: 1.0),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 5.5,
            height: 5.5,
            decoration: BoxDecoration(color: c, shape: BoxShape.circle),
          ),
          const SizedBox(width: 4),
          Text(
            sir,
            style: TextStyle(color: c, fontWeight: FontWeight.w700, fontSize: 10.5),
          ),
        ],
      ),
    );
  }

  static Color _sirColor(String sir) {
    switch (sir) {
      case 'S':
        return const Color(0xFF68B088);
      case 'I':
        return const Color(0xFFD9A754);
      default:
        return const Color(0xFFD96C6C);
    }
  }
}

// ============================================================================
// 6. CustomPainter สำหรับวาดวงใสและป้ายบอกตำแหน่ง #1..#N แบบหลบการทับซ้อนอัตโนมัติ
// ============================================================================
class _BadgePlacementItem {
  final int discIndex;
  final bool isSelected;
  final Offset discCenter;
  final double rxDisc;
  final double ryDisc;
  final double rZone;
  final Color strokeColor;
  final TextPainter tp;
  Rect rect;

  _BadgePlacementItem({
    required this.discIndex,
    required this.isSelected,
    required this.discCenter,
    required this.rxDisc,
    required this.ryDisc,
    required this.rZone,
    required this.strokeColor,
    required this.tp,
    required this.rect,
  });
}

class _PlateOverlayPainter extends CustomPainter {
  final List<DiscRecord> discs;
  final int? selectedIndex;
  final double imageWidth;
  final double imageHeight;
  final bool isActivelyAdjusting;
  final bool hideOthersCompletely;

  const _PlateOverlayPainter({
    required this.discs,
    required this.selectedIndex,
    required this.imageWidth,
    required this.imageHeight,
    this.isActivelyAdjusting = false,
    this.hideOthersCompletely = false,
  });

  @override
  void paint(Canvas canvas, Size size) {
    if (discs.isEmpty || imageWidth <= 0 || imageHeight <= 0) return;
    final double sx = size.width / imageWidth;
    final double sy = size.height / imageHeight;
    final double sAvg = 0.5 * (sx + sy);
    final double minCanvasDim = math.min(size.width, size.height);

    // คำนวณจุดศูนย์กลางรวมของแผ่นยาบนจาน เพื่อดันป้ายชื่อออกแนวรัศมีไม่ให้ชนกัน
    double sumX = 0.0;
    double sumY = 0.0;
    for (final d in discs) {
      sumX += d.cx * sx;
      sumY += d.cy * sy;
    }
    final double centroidX = sumX / discs.length;
    final double centroidY = sumY / discs.length;

    // เรียงลำดับการวาดวงให้วงที่ไม่ได้เลือกถูกวาดก่อน และวงที่กำลังเลือกถูกวาดทับบนสุดเสมอ
    final List<int> drawOrder = <int>[];
    for (int i = 0; i < discs.length; i++) {
      if (i != selectedIndex) drawOrder.add(i);
    }
    if (selectedIndex != null &&
        selectedIndex! >= 0 &&
        selectedIndex! < discs.length) {
      drawOrder.add(selectedIndex!);
    }

    final List<_BadgePlacementItem> badgeItems = <_BadgePlacementItem>[];

    // Pass 1: วาดวงยับยั้งเชื้อและขอบแผ่นยา
    for (final int i in drawOrder) {
      final d = discs[i];
      final bool isSelected = i == selectedIndex;
      final Offset center = Offset(d.cx * sx, d.cy * sy);
      final double rxDisc = d.rxDiscPx * sx;
      final double ryDisc = d.ryDiscPx * sy;
      final double zoneRatio = d.rZonePx / math.max(8.0, d.rDiscPx);
      final double rxZone = rxDisc * zoneRatio;
      final double ryZone = ryDisc * zoneRatio;
      final double rZone = d.rZonePx * sAvg;

      final Color sirColor = d.sirStatus == 'S'
          ? const Color(0xFF34D399)
          : (d.sirStatus == 'I' ? const Color(0xFFFBBF24) : const Color(0xFFF87171));
      const Color activeRingColor = Color(0xFF38BDF8);

      // เฉพาะตอนที่กำลังขยับ/ปรับขนาดวง (isActivelyAdjusting == true) เท่านั้น จึงจะทำให้วงอื่นจางลงชั่วคราว
      // หากอยู่ในสถานะดูปกติ (ไม่ได้กำลังขยับวง) ทุกวงจะแสดงคมชัด 100% เต็ม
      if (!isSelected && isActivelyAdjusting) {
        if (!hideOthersCompletely) {
          if (d.diameterMm > 6.4) {
            final Rect ghostZoneOval = Rect.fromCenter(
              center: center,
              width: rxZone * 2.0,
              height: ryZone * 2.0,
            );
            final Paint ghostZoneStroke = Paint()
              ..color = sirColor.withOpacity(0.18)
              ..strokeWidth = 1.2
              ..style = PaintingStyle.stroke;
            canvas.drawOval(ghostZoneOval, ghostZoneStroke);
          }
          final Rect ghostDiscOval = Rect.fromCenter(
            center: center,
            width: rxDisc * 2.0,
            height: ryDisc * 2.0,
          );
          final Paint ghostDiscStroke = Paint()
            ..color = const Color(0xFFE2E8F0).withOpacity(0.18)
            ..strokeWidth = 1.0
            ..style = PaintingStyle.stroke;
          canvas.drawOval(ghostDiscOval, ghostDiscStroke);
        }
        continue;
      }

      if (d.diameterMm > 6.4) {
        final Rect zoneOval = Rect.fromCenter(
          center: center,
          width: rxZone * 2.0,
          height: ryZone * 2.0,
        );

        if (!(isSelected && isActivelyAdjusting)) {
          final Paint fillPaint = Paint()
            ..color = (isSelected ? activeRingColor : sirColor)
                .withOpacity(isSelected ? 0.13 : 0.08)
            ..style = PaintingStyle.fill;
          canvas.drawOval(zoneOval, fillPaint);
        }

        final Paint darkHalo = Paint()
          ..color = const Color(0xB80F172A)
          ..strokeWidth = isSelected ? 3.8 : 2.8
          ..style = PaintingStyle.stroke;
        canvas.drawOval(zoneOval, darkHalo);

        final Paint zoneStroke = Paint()
          ..color = isSelected ? activeRingColor : sirColor
          ..strokeWidth = isSelected ? 2.4 : 1.8
          ..style = PaintingStyle.stroke;
        canvas.drawOval(zoneOval, zoneStroke);

        if (isSelected && isActivelyAdjusting) {
          final Paint tickPaint = Paint()
            ..color = const Color(0xFFF8FAFC)
            ..strokeWidth = 1.8
            ..style = PaintingStyle.stroke;
          for (final double ang in <double>[0, math.pi / 2, math.pi, 3 * math.pi / 2]) {
            final Offset p1 = Offset(
              center.dx + (rxZone + 2.0) * math.cos(ang),
              center.dy + (ryZone + 2.0) * math.sin(ang),
            );
            final Offset p2 = Offset(
              center.dx + (rxZone + 9.0) * math.cos(ang),
              center.dy + (ryZone + 9.0) * math.sin(ang),
            );
            canvas.drawLine(p1, p2, tickPaint);
          }
        }
      }

      final Rect discOval = Rect.fromCenter(
        center: center,
        width: rxDisc * 2.0,
        height: ryDisc * 2.0,
      );
      final Paint discHalo = Paint()
        ..color = const Color(0xA60F172A)
        ..strokeWidth = isSelected ? 3.0 : 2.2
        ..style = PaintingStyle.stroke;
      canvas.drawOval(discOval, discHalo);

      final Paint discStroke = Paint()
        ..color = isSelected
            ? activeRingColor
            : (d.needsReview ? const Color(0xFFFBBF24) : const Color(0xFFF8FAFC))
        ..strokeWidth = isSelected ? 2.0 : 1.4
        ..style = PaintingStyle.stroke;
      canvas.drawOval(discOval, discStroke);

      // ป้ายชื่อแบบกระชับสำหรับเม็ดที่ไม่ได้เลือก และแสดงข้อมูลครบเต็มสำหรับเม็ดที่เลือก
      final String label = isSelected
          ? '#${d.discOrder} ${d.drugCode} (${d.diameterMm.toStringAsFixed(1)}mm [${d.sirStatus}])'
          : (d.diameterMm > 6.2
              ? '#${d.discOrder} ${d.drugCode} • ${d.diameterMm.toStringAsFixed(1)}'
              : '#${d.discOrder} ${d.drugCode}');

      final TextPainter tp = TextPainter(
        text: TextSpan(
          text: label,
          style: TextStyle(
            color: isSelected ? const Color(0xFFF8FAFC) : const Color(0xFFE2E8F0),
            fontSize: isSelected ? 10.5 : 9.2,
            fontWeight: FontWeight.w700,
            letterSpacing: -0.15,
          ),
        ),
        textDirection: TextDirection.ltr,
      )..layout();

      final double boxW = tp.width + (isSelected ? 10.0 : 8.0);
      final double boxH = tp.height + (isSelected ? 4.0 : 3.0);
      final double dx = center.dx - centroidX;
      final double dy = center.dy - centroidY;
      final double lift = (isSelected && isActivelyAdjusting) ? 16.0 : 8.0;

      // จัดวางป้ายตามแนวรัศมีจากจุดศูนย์กลางจาน เพื่อลดการชนกันตั้งแต่เริ่มต้น
      final bool isCenterDisc =
          dx.abs() < minCanvasDim * 0.13 && dy.abs() < minCanvasDim * 0.13;
      final bool placeBelow = isCenterDisc || (dy > minCanvasDim * 0.08);

      double initX = center.dx + (isCenterDisc ? 0.0 : dx * 0.16);
      double initY = placeBelow
          ? (center.dy + rZone + lift + boxH * 0.5)
          : (center.dy - rZone - lift - boxH * 0.5);

      if (initY - boxH / 2 < 4.0) {
        initY = center.dy + rZone + lift + boxH * 0.5;
      } else if (initY + boxH / 2 > size.height - 4.0) {
        initY = center.dy - rZone - lift - boxH * 0.5;
      }

      initX = initX.clamp(boxW / 2 + 4.0, math.max(boxW / 2 + 4.0, size.width - boxW / 2 - 4.0));
      initY = initY.clamp(boxH / 2 + 4.0, math.max(boxH / 2 + 4.0, size.height - boxH / 2 - 4.0));

      badgeItems.add(
        _BadgePlacementItem(
          discIndex: i,
          isSelected: isSelected,
          discCenter: center,
          rxDisc: rxDisc,
          ryDisc: ryDisc,
          rZone: rZone,
          strokeColor: isSelected ? activeRingColor : sirColor,
          tp: tp,
          rect: Rect.fromCenter(center: Offset(initX, initY), width: boxW, height: boxH),
        ),
      );
    }

    // Pass 2: ระบบคลี่คลายการทับซ้อนของป้าย (2D Iterative Collision Resolution)
    const double padX = 5.0;
    const double padY = 3.5;
    for (int iter = 0; iter < 16; iter++) {
      bool anyMoved = false;

      // 2.1 ผลักป้ายไม่ให้ทับซ้อนกันเอง
      for (int a = 0; a < badgeItems.length; a++) {
        for (int b = a + 1; b < badgeItems.length; b++) {
          final Rect ra = badgeItems[a].rect.inflate(padX * 0.5);
          final Rect rb = badgeItems[b].rect.inflate(padX * 0.5);
          if (!ra.overlaps(rb)) continue;

          final double overlapX =
              math.min(ra.right, rb.right) - math.max(ra.left, rb.left);
          final double overlapY =
              math.min(ra.bottom, rb.bottom) - math.max(ra.top, rb.top);
          if (overlapX <= 0 || overlapY <= 0) continue;

          anyMoved = true;
          if (overlapX < overlapY * 1.35) {
            final double dir = (ra.center.dx <= rb.center.dx) ? -1.0 : 1.0;
            final double shift = (overlapX * 0.55) + 0.5;
            badgeItems[a].rect = badgeItems[a].rect.translate(dir * shift, 0);
            badgeItems[b].rect = badgeItems[b].rect.translate(-dir * shift, 0);
          } else {
            final double dir = (ra.center.dy <= rb.center.dy) ? -1.0 : 1.0;
            final double shift = (overlapY * 0.55) + 0.5;
            badgeItems[a].rect = badgeItems[a].rect.translate(0, dir * shift);
            badgeItems[b].rect = badgeItems[b].rect.translate(0, -dir * shift);
          }
        }
      }

      // 2.2 ป้องกันไม่ให้ป้ายไปบังทับตัวอักษรบนเม็ดยาใดๆ
      for (int a = 0; a < badgeItems.length; a++) {
        for (int j = 0; j < discs.length; j++) {
          final Offset dc = Offset(discs[j].cx * sx, discs[j].cy * sy);
          final double dr = math.max(discs[j].rxDiscPx * sx, discs[j].ryDiscPx * sy) + 3.0;
          final Rect discBox = Rect.fromCircle(center: dc, radius: dr);
          if (!badgeItems[a].rect.overlaps(discBox)) continue;

          anyMoved = true;
          final double dy = badgeItems[a].rect.center.dy - dc.dy;
          final double pushY = (dy >= 0 ? 1.0 : -1.0) * 3.5;
          badgeItems[a].rect = badgeItems[a].rect.translate(0, pushY);
        }

        // บังคับให้อยู่ในขอบเขตจานภาพเสมอ
        final Rect r = badgeItems[a].rect;
        final double clampedCx = r.center.dx.clamp(
          r.width / 2 + 4.0,
          math.max(r.width / 2 + 4.0, size.width - r.width / 2 - 4.0),
        );
        final double clampedCy = r.center.dy.clamp(
          r.height / 2 + 4.0,
          math.max(r.height / 2 + 4.0, size.height - r.height / 2 - 4.0),
        );
        badgeItems[a].rect = Rect.fromCenter(
          center: Offset(clampedCx, clampedCy),
          width: r.width,
          height: r.height,
        );
      }

      if (!anyMoved) break;
    }

    // Pass 3: วาดเส้นเชื่อมบางๆ (Leader Line) และวาดกล่องป้ายชื่อ โดยให้ป้ายที่เลือกอยู่บนสุดเสมอ
    for (final item in badgeItems) {
      final Rect bgRect = item.rect;
      final Offset badgeCenter = bgRect.center;
      final double distToDisc = (badgeCenter - item.discCenter).distance;
      if (distToDisc > item.rZone + 12.0) {
        final double ang = math.atan2(
          badgeCenter.dy - item.discCenter.dy,
          badgeCenter.dx - item.discCenter.dx,
        );
        final Offset anchorOnRing = Offset(
          item.discCenter.dx + math.max(item.rxDisc, item.rZone) * math.cos(ang),
          item.discCenter.dy + math.max(item.ryDisc, item.rZone) * math.sin(ang),
        );
        final Paint leaderPaint = Paint()
          ..color = item.strokeColor.withOpacity(0.55)
          ..strokeWidth = 1.0
          ..style = PaintingStyle.stroke;
        canvas.drawLine(anchorOnRing, badgeCenter, leaderPaint);
      }

      final RRect rrect = RRect.fromRectAndRadius(bgRect, const Radius.circular(5));
      canvas.drawRRect(
        rrect,
        Paint()
          ..color = item.isSelected
              ? const Color(0xF2161B22)
              : const Color(0xD9161B22),
      );
      canvas.drawRRect(
        rrect,
        Paint()
          ..color = item.strokeColor.withOpacity(item.isSelected ? 1.0 : 0.82)
          ..style = PaintingStyle.stroke
          ..strokeWidth = item.isSelected ? 1.4 : 1.0,
      );
      item.tp.paint(
        canvas,
        Offset(
          bgRect.left + (bgRect.width - item.tp.width) * 0.5,
          bgRect.top + (bgRect.height - item.tp.height) * 0.5,
        ),
      );
    }
  }

  @override
  bool shouldRepaint(covariant _PlateOverlayPainter oldDelegate) => true;
}