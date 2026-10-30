# 格式轉換

以 Python（tkinter＋Pillow＋PyMuPDF）寫成的桌面轉檔小工具：圖片格式互轉、圖片與 PDF 合併成 PDF、PDF 轉圖片，附輸出預覽與拖曳排序。

> 只要 Python 3 與兩個套件（`pip install -r requirements.txt`），一個檔案，雙擊就能用。

## 功能

- **八種輸出格式**：PDF、JPG、PNG、WebP、BMP、TIFF、GIF、AVIF；輸入可混放上述圖片格式與 PDF。
- **合併成 PDF**：圖片與 PDF 依畫面順序合併成一份；PDF 頁面原樣複製，頁面大小（A4／原圖大小）、方向（自動、直式、橫式）、邊界（無、10 mm、20 mm）只套用在圖片。
- **畫質不變**：JPG 轉 PDF 時 JPEG 資料原封不動嵌入；其他格式以無損壓縮放進 PDF；透明部分鋪白底。
- **PDF 轉圖片**：每頁存成一張，檔名為「原檔名_第N頁」，解析度可選 72／150／300 DPI。
- **圖片互轉**：EXIF 方向寫進像素後轉正，保留 EXIF 與色彩描述檔；JPG、WebP、AVIF 可選品質（高 95、中 85、低 70）；不支援透明的格式自動鋪白底；不覆蓋既有檔案，重名時加 (2)、(3)。
- **輸出預覽**：轉 PDF 時每張縮圖畫成實際輸出的頁面，設定一改立即更新；PDF 檔案標出頁數。
- **拖曳排序**：直接拖動縮圖調整順序，拖到上下邊緣會自動捲動；也可一鍵依檔名排序（2 排在 10 前面）。
- **拖檔加入**：從檔案總管把檔案或整個資料夾拖進視窗即可加入，不支援的檔案會略過並提示。
- **單張旋轉與移除**：游標移到縮圖上出現旋轉（順時針 90°）與移除按鈕；旋轉 PDF 會轉整份的每一頁。
- **指令批次轉檔**：加上 `--out` 就不開視窗，直接輸出。

## 執行指令

```bash
pip install -r requirements.txt                          # 安裝 Pillow 與 PyMuPDF

python file_convert.pyw                                  # 開視窗（也可直接雙擊 file_convert.pyw）
python file_convert.pyw a.jpg b.png 報告.pdf 資料夾       # 開視窗並先加入檔案；把檔案拖到 file_convert.pyw 圖示上也一樣

python file_convert.pyw 照片資料夾 --out 輸出.pdf         # 合併成 PDF；--out 是 .pdf 時可省略 --to
python file_convert.pyw a.jpg 報告.pdf --out 輸出.pdf --page original   # 圖片頁面用原圖大小（依圖片 DPI，沒有就用 96 DPI）
python file_convert.pyw 照片資料夾 --out 輸出.pdf --orient landscape    # A4 方向：auto（預設，依圖片直橫）、portrait、landscape
python file_convert.pyw 照片資料夾 --out 輸出.pdf --margin small        # A4 邊界：none（預設）、small（10 mm）、large（20 mm）

python file_convert.pyw 照片資料夾 --to webp --out 輸出資料夾           # 轉成其他圖片格式：jpg、png、webp、bmp、tiff、gif、avif
python file_convert.pyw 照片資料夾 --to jpg --out 輸出資料夾 --quality medium   # JPG／WebP／AVIF 品質：high（預設 95）、medium（85）、low（70）
python file_convert.pyw 報告.pdf --to png --out 輸出資料夾 --dpi 300            # PDF 每頁轉成圖片，解析度預設 150 DPI
```

## 專案結構

```
file_convert/
├── file_convert.pyw    主程式：轉檔功能（PDF 輸出、圖片互轉、PDF 轉圖片）、視窗介面、指令列參數都在這個檔案
├── requirements.txt    相依套件清單（Pillow、PyMuPDF）
├── README.md           本說明文件
└── .gitignore          排除 Python 快取與轉檔中的暫存檔（*.part）
```
