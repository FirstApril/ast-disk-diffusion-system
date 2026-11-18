## TL;DR

การพัฒนาระบบวิเคราะห์ภาพการทดสอบ Kirby-Bauer โดยใช้เทคโนโลยีปัญญาประดิษฐ์และคอมพิวเตอร์วิทัศน์ช่วยเพิ่มความแม่นยำและลดภาระงาน โดยแบ่งเป็นโมดูลตรวจจับแผ่นยา วัดขนาดวงใส และอ่านชื่อยา เพื่อให้ได้ผลลัพธ์การทดสอบความไวต่อยาที่รวดเร็วและน่าเชื่อถือ

----

## สถาปัตยกรรมระบบ

สถาปัตยกรรมของระบบควรแบ่งออกเป็น 3 โมดูลหลักเพื่อจัดการงานเฉพาะทาง โดยใช้แนวทาง Hybrid Model ที่รวมเทคนิค Deep Learning และ Image Processing เข้าด้วยกัน [1]:

1.  **โมดูลตรวจจับและนับแผ่นยา (Disk Detection Module):** ใช้สถาปัตยกรรม Convolutional Neural Networks (CNN) ตระกูล YOLO (เช่น YOLov9) เพื่อระบุตำแหน่งของแผ่นยาบนจานเพาะเชื้อ [1] [2] โดยสามารถใช้ Hough Transform เป็นทางเลือกเสริมในการตรวจจับรูปทรงวงกลมของแผ่นยาได้อย่างแม่นยำ [3]
2.  **โมดูลวัดขนาดวงใสและการปรับเทียบ (Zone Measurement & Calibration Module):** ใช้เทคนิคการแบ่งส่วนภาพ (Segmentation) เพื่อแยกขอบเขตของวงใส [4] [2] การปรับเทียบสเกลทำได้โดยอ้างอิงขนาดของแผ่นยาที่เป็นค่ามาตรฐาน หรือวัตถุอ้างอิงในภาพ เพื่อแปลงค่าพิกเซลเป็นมิลลิเมตร [5] [6]
3.  **โมดูลอ่านชื่อยา (OCR Module):** ใช้เทคนิค Optical Character Recognition (OCR) เช่น EasyOCR เพื่ออ่านตัวอักษรบนแผ่นยา [7] หรือใช้โมเดล YOLO ในการจำแนกประเภทข้อความและชื่อยาโดยตรง [1]

----

## ขั้นตอนการประมวลผล

กระบวนการประมวลผลภาพแบบลำดับ (Pipeline) มีขั้นตอนดังนี้:

*   **การรับภาพและการตรวจสอบคุณภาพ:** รับภาพจากกล้องมือถือและทำการประมวลผลเบื้องต้นเพื่อกำจัดสัญญาณรบกวน (Noise) [3] และปรับปรุงคุณภาพภาพ
*   **การจัดการภาพ:** ทำการปรับเทียบสเกลภาพ (Calibration) โดยใช้ขนาดแผ่นยาเป็นตัวอ้างอิง [6] และแยกพื้นหลัง (Background) ออกจากวัตถุที่สนใจ
*   **การตรวจจับและแบ่งส่วน:** ใช้โมเดลตรวจจับวัตถุระบุตำแหน่งจานเพาะเชื้อ แผ่นยา และวงใส [2] จากนั้นใช้เทคนิค Gradient Method หรือการวาด Contour เพื่อกำหนดขอบเขตของวงใส [3] [5]
*   **การวัดและวิเคราะห์:** วัดเส้นผ่านศูนย์กลางของวงใสที่ตรวจพบ [5] [2] แล้วนำไปเปรียบเทียบกับเกณฑ์มาตรฐาน (เช่น EUCAST) เพื่อจำแนกความไวต่อยา [1] [8]
*   **การจับคู่และตรวจสอบ:** จับคู่ชื่อยาที่อ่านได้จาก OCR กับตำแหน่งแผ่นยาที่วัดค่าได้ [1] โดยระบบควรมีกลไกตรวจสอบความน่าเชื่อถือ หากภาพมีความซับซ้อนเกินไปควรแจ้งเตือนให้ผู้เชี่ยวชาญตรวจสอบซ้ำ [8]
*   **การส่งออกผลลัพธ์:** สร้างรายงานสรุปผลการทดสอบความไวของเชื้อต่อยาแต่ละชนิด [7] [6]

----

## ข้อแนะนำและการใช้งานบนมือถือ

สำหรับการพัฒนาบนอุปกรณ์มือถือ ควรพิจารณาแนวทางและข้อควรระวังดังนี้:

*   **ทางเลือกโมเดล:** แนะนำให้ใช้ YOLO รุ่นที่มีขนาดเล็ก (Tiny versions) เพื่อให้สามารถประมวลผลบนอุปกรณ์มือถือได้รวดเร็วและมีประสิทธิภาพ [2]
*   **เครื่องมือพัฒนา:** สามารถใช้ไลบรารีอย่าง OpenCV สำหรับงานประมวลผลภาพพื้นฐาน และใช้โมเดลที่ผ่านการ Train มาแล้วเพื่อความแม่นยำในการตรวจจับ [7] [2]
*   **ข้อควรระวังด้านความถูกต้อง:** 
    *   ความแม่นยำขึ้นอยู่กับคุณภาพภาพถ่าย ดังนั้นควรออกแบบ UI ให้ช่วยผู้ใช้งานจัดวางมุมกล้องให้ขนานกับจานเพาะเชื้อ
    *   การวัดค่าวงใสอาจเกิดความคลาดเคลื่อนได้หากแสงเงาไม่สม่ำเสมอ จึงควรใช้เทคนิคการปรับ Threshold ที่เหมาะสม [5]
    *   ควรเปรียบเทียบผลลัพธ์กับวิธีมาตรฐาน (Gold standard) เสมอ โดยเฉพาะในกรณีที่มีการตีความยาก [7] [8]

## References

[1]M. Karayiğit, O. Erdem, and H. Güdücüoğlu, “Artificial Intelligence Based Antibiotic Zone Measurement For Disk Diffusion,” pp. 48–53, Sept. 2024, doi: 10.23919/spa61993.2024.10715633.

[2]H. Li, H. Han, U. A. Bhatti, and Z. Wang, “Bacterial Inhibition Zone Recognition Method Based on YOLO,” pp. 216–221, Aug. 2024, doi: 10.1109/prai62207.2024.10826919.

[3]R. Ferreira, J. S. Amaral, G. Igrejas, and P. J. Rodrigues, “An antibiogram classification system based on an hybrid hough transform and gradient approach,” Jan. 2010.

[4]B. K. Priya, D. A. Reddy, A. D. Rani, N. Kalahasthi, W. G. Soliman, and D. V. R. K. Reddy, “Automatic Inhibition Zone Diameter Measurement for Disc Diffusion Test Using Image Segmentation,” Iete Journal of Research, pp. 1–18, Oct. 2021, doi: 10.1080/03772063.2021.1969293.

[5]H. S. Bhargav, S. D. Shastri, S. P. Poornav, K. M. Darshan, and M. M. Nayak, “Measurement of the Zone of Inhibition of an Antibiotic,” pp. 409–414, Aug. 2016, doi: 10.1109/IACC.2016.82.

[6]E. Gullu, S. Bora, and B. Beynek, “Exploiting Image Processing and Artificial Intelligence Techniques for the Determination of Antimicrobial Susceptibility,” Applied Sciences, May 2024, doi: 10.3390/app14093950.

[7]“Ab.ai – A Novel Automated AI Tool for Reporting Antibiograms,” Studies in health technology and informatics, Nov. 2022, doi: 10.3233/shti220984.

[8]G. Hejblum, V. Jarlier, J. Grosset, and A. Aurengo, “Automated interpretation of disk diffusion antibiotic susceptibility tests with the radial profile analysis algorithm.,” Journal of Clinical Microbiology, vol. 31, no. 9, pp. 2396–2401, Sept. 1993, doi: 10.1128/JCM.31.9.2396-2401.1993.
