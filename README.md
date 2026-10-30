# JPG 轉 PDF

以 Python（tkinter＋Pillow）寫成的 JPG 轉 PDF 桌面小工具，有頁面預覽與拖曳排序，JPEG 原始資料直接放進 PDF，不重新壓縮、畫質不變。

> 只要 Python 3 與 Pillow，一個檔案，雙擊就能用。

## 功能

- **頁面預覽**：每張圖片以實際輸出的 PDF 頁面呈現，切換頁面大小、方向、邊界時預覽立即更新。
- **拖曳排序**：直接拖動縮圖調整頁序，拖到視窗上下邊緣會自動捲動；也可一鍵依檔名排序（2 排在 10 前面）。
- **拖檔加入**：從檔案總管把圖片或整個資料夾拖進視窗即可加入，非 JPG 檔案會略過並提示。
- **單頁旋轉與移除**：游標移到縮圖上出現旋轉（順時針 90°）與移除按鈕。
- **頁面設定**：頁面大小 A4／原圖大小；A4 可選方向（自動、直式、橫式）與邊界（無、10 mm、20 mm）。
- **畫質不變**：JPEG 資料原封不動嵌入 PDF；手機照片的 EXIF 方向自動轉正；只有鏡像方向或副檔名是 .jpg 的其他格式才以品質 95 重新壓縮。
- **指令批次轉檔**：加上 `--out` 就不開視窗，直接輸出 PDF。

## 執行指令

```bash
pip install -r requirements.txt                       # 安裝 Pillow

python jpg_to_pdf.pyw                                 # 開視窗（也可直接雙擊 jpg_to_pdf.pyw）
python jpg_to_pdf.pyw a.jpg b.jpg 照片資料夾           # 開視窗並先加入圖片；把圖片拖到 jpg_to_pdf.pyw 圖示上也一樣

python jpg_to_pdf.pyw 照片資料夾 --out 輸出.pdf        # 不開視窗，直接輸出；資料夾內依檔名排序
python jpg_to_pdf.pyw a.jpg b.jpg --out 輸出.pdf --page original     # 頁面用原圖大小（依圖片 DPI，沒有就用 96 DPI）
python jpg_to_pdf.pyw 照片資料夾 --out 輸出.pdf --orient landscape   # A4 方向：auto（預設，依圖片直橫）、portrait、landscape
python jpg_to_pdf.pyw 照片資料夾 --out 輸出.pdf --margin small       # A4 邊界：none（預設）、small（10 mm）、large（20 mm）
```

## 專案結構

```
jpg_to_pdf/
├── jpg_to_pdf.pyw      主程式：PDF 輸出（直接嵌入 JPEG）、視窗介面、指令列參數都在這個檔案
├── requirements.txt    相依套件清單（Pillow）
├── README.md           本說明文件
└── .gitignore          排除 Python 快取與轉檔中的暫存檔（*.part）
```
