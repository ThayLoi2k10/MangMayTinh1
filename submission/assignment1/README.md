# Assignment 1 - source, technical report và demo

Gói này do Role 4 chuẩn bị từ integrated baseline `3c4174791a7e796a18e6d57c98c03111359cc1a5`. Báo cáo ghi rõ phần đã kiểm chứng và blocker. **Không phải chứng nhận toàn bộ assignment đã đạt.** Source Roles 1-3 giữ nguyên; README này là hướng dẫn đóng gói mới, không thay README repository.

## Cài đặt

Yêu cầu Python3, pip, trình duyệt và cổng TCP9000/UDP9001 chưa được dùng. Đã kiểm trên Windows/Python3.14.4. Chạy tại thư mục root của source sau giải nén:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Chỉ runtime cần cryptography. UI dùng thư viện chuẩn http.server + vanilla JavaScript, không CDN/Flask/WebSocket. `--password` không phải tài khoản/password database: login hiện là đăng ký username duy nhất trong phiên online.

## Chạy thủ công trong ba terminal

```powershell
# Terminal server
.\.venv\Scripts\python.exe server.py
# Terminal Alice
.\.venv\Scripts\python.exe client.py --username alice --host 127.0.0.1 --ui-port 8000
# Terminal Bob
.\.venv\Scripts\python.exe client.py --username bob --host 127.0.0.1 --ui-port 8001
```

Mở http://127.0.0.1:8000 và http://127.0.0.1:8001. CLI vẫn hỗ trợ thêm `--cli`. LAN: thay127.0.0.1 bằng IP server và cho phép TCP9000, UDP9001 và các cổng UDP peer động trong mạng lab; cấu hình firewall do người vận hành thực hiện. Chưa chứng minh LAN hai máy trong đợt kiểm này.

1. Kiểm tra username và online list ở hai cửa sổ.
2. Alice chọn Mọi người, gửi broadcast; Bob nhắn riêng Alice.
3. Gửi file tên mới, quan sát progress ở hai đầu. HTTP accepted không phải delivered.
4. So SHA256 nguồn và `downloads_bob/<filename>` bằng `Get-FileHash -Algorithm SHA256`.
5. Đóng một client, kiểm tra peer còn lại; tắt server rồi tạo lại server/client để phục hồi. Chưa có automatic reconnect.

## Demo tự dọn / smoke verification

```powershell
.\.venv\Scripts\python.exe submission/assignment1/demo.py
.\.venv\Scripts\python.exe submission/assignment1/demo.py --smoke --output demo-result.json
```

Script dùng server thật và hai `client.main()` thật; dữ liệu/download nằm trong temporary directory. Nhấn Enter để đóng demo, chỉ các process do nó tạo. Copy file muốn giữ trước khi thoát. Script từ chối nếu9000/9001 đã bị dùng. Không chạy cùng demo thủ công hoặc network test khác trên cùng ports.

## Automated tests

Cài dependency test riêng, không cần cho người chỉ chạy ứng dụng:

```powershell
.\.venv\Scripts\python.exe -m pip install playwright==1.55.0
$env:ROLE4_BROWSER_CHANNEL = "msedge"
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_role4_*.py" -v
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest test_file_client.py test_file_transfer.py -q -p no:cacheprovider
```

Nếu không dùng Edge, cài browser qua `python -m playwright install chromium`; trên Windows đặt `ROLE4_BROWSER_CHANNEL=chromium`. Role 4 dùng unittest; test file của đồng đội có cả pytest và cần chạy bằng pytest. Linux dùng `.venv/bin/python` và Chromium đã cài. Báo cáo cuối có lệnh/metric thực tế và những test FAIL phải bàn giao upstream; không thêm expectedFailure để có màu xanh.

## Giới hạn cần trình bày khi demo

- HTTP state chỉ có username/users/messages/transfers, không verified server connectivity hoặc operation errors. UI thể hiện server chưa xác minh; lỗi worker có thể chỉ xuất hiện terminal.
- HTTP upload110MiB JSON cho khoảng82.5MiB data sau Base64; file layer100MiB. File lớn gầnlimit chưa được kiểm chứng trên môi trường thiếu dung lượng.
- Staging `.upload_temp/<basename>` còn collision khi nhiều request cùng tên. Dùng tên riêng trong demo không được coi là sửa bug; test phản ví dụ được giữ.
- UDP streamer độc lập chưa được nối vào client/server runtime; BBR/CUBIC và async stream semantics cần thống nhất/hoàn thiện với owner và giảng viên.
- Key Fernet chung nằm trong config là cơ chế demo, không đảm bảo bảo mật trước người biết key. Source headers/identity không phải đều encrypted.

Đọc báo cáo kỹ thuật PDF, readiness và upstream handoffs kèm gói trước khi nộp. Phần reflection là tổng hợp engineering evidence, nhóm cần duyệt và bổ sung trải nghiệm/tên thành viên thật; không tự gán công lao hay việc chưa làm.
