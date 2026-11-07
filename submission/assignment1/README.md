# Assignment 1 release tools

Hướng dẫn cài đặt và chạy nằm trong `README.md` tại gốc ZIP/repository.
Báo cáo hiện hành: `output/pdf/Assignment1_Release_Report.pdf`.
Kết quả, giới hạn và ma trận yêu cầu: `docs/release_closure.md`.
Các báo cáo mang ngày trước 07/11/2026 là lịch sử, không thay thế kết quả release.

```powershell
python submission/assignment1/demo.py
python submission/assignment1/demo.py --smoke --output test-results/demo.json
python scripts/verify_release.py --label repeat
python -m pip install -r requirements-report.txt
python scripts/build_release_report.py
python submission/assignment1/build_package.py --output ../Assignment1_Release.zip
python submission/assignment1/verify_package.py ../Assignment1_Release.zip --output test-results/package.json
```

Demo mở hai browser bằng hai `client.main()` thật, giữ dữ liệu trong thư mục
tạm và chỉ dừng những process do chính demo tạo. Sao chép file cần giữ trước
khi nhấn Enter để thoát. Chạy các phép thử nối tiếp; cổng 9000/9001 phải trống.

`build_report.py` tại thư mục này là builder lịch sử 05/11, được giữ để truy vết.
Builder release hiện tại là `scripts/build_release_report.py`.
Gói ZIP có `MANIFEST.json` chứa SHA-256 từng file, commit nguồn và trạng thái
working tree khi đóng gói. Verifier kiểm hash toàn bộ, giải nén cách ly rồi
chạy chat broadcast/private và file SHA-256 qua HTTP/TCP/UDP thật.
