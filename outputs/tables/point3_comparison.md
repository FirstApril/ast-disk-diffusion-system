# รายงานประเมินประสิทธิภาพโมเดลอ่านชื่อยา (Point 3: Disc Recognition & OCR Evaluation)

## 1. ตารางเปรียบเทียบประสิทธิภาพรวม (img65 - img120, n = 280 เม็ดยา)

| Model                                                            | Architecture                                     |   Tested Discs |   Open-Set Accuracy (%) |   Plate-Matched Accuracy (%) |   Macro Precision (%) |   Macro Recall (%) |   Macro F1-Score (%) |   Latency (ms/disc) |
|:-----------------------------------------------------------------|:-------------------------------------------------|---------------:|------------------------:|-----------------------------:|----------------------:|-------------------:|---------------------:|--------------------:|
| 1. EasyOCR Baseline (0° Single-Pass)                             | CRAFT + BiLSTM (No Rotation Sweep)               |            280 |                    33.9 |                         33.9 |                  98   |               33.9 |                 47.4 |               86.77 |
| 2. EasyOCR Standard (4-Angle Ab.ai 2022)                         | 4-Way Rotation CRAFT + ResNet-BiLSTM             |            280 |                    76.1 |                         76.1 |                  87.5 |               76.1 |                 80.6 |              157.94 |
| 3. EasyOCR Super-Res (Underline + 8-Angle)                       | Underline Alignment + 8-Way CRAFT-BiLSTM         |            280 |                    55   |                         63.9 |                  74.3 |               63.9 |                 65.3 |              299.52 |
| 4. Proposed Hybrid AST-OCR (Underline + Fingerprint + Hungarian) | Underline Bar + Clinical Fingerprint + Hungarian |            280 |                    55   |                        100   |                 100   |              100   |                100   |              304.24 |

## 2. ความแม่นยำแยกตามชนิดยาปฏิชีวนะ 5 ชนิด (% Recall per Class)

| Model                                                            |   AMC30 |   AMP10 |   CAZ30 |   SXT25 |   TE30 |
|:-----------------------------------------------------------------|--------:|--------:|--------:|--------:|-------:|
| 1. EasyOCR Baseline (0° Single-Pass)                             |    28.6 |    35.7 |    32.1 |    64.3 |    8.9 |
| 2. EasyOCR Standard (4-Angle Ab.ai 2022)                         |    78.6 |    76.8 |    80.4 |    92.9 |   51.8 |
| 3. EasyOCR Super-Res (Underline + 8-Angle)                       |    33.9 |    80.4 |    53.6 |    80.4 |   71.4 |
| 4. Proposed Hybrid AST-OCR (Underline + Fingerprint + Hungarian) |   100   |   100   |   100   |   100   |  100   |
