# Assignment 1 — Distributed Collaboration Application

Ứng dụng cộng tác cho localhost/LAN: server quản lý phiên và định tuyến chat, client gửi file trực tiếp qua UDP, trình duyệt hiển thị trạng thái qua HTTP cục bộ. Networking dùng `socket` của Python; UI dùng HTML/CSS/JavaScript thuần và `http.server`, không Flask, Django, WebSocket hoặc CDN.

Bản release closure bổ sung kiểm chứng và sửa lỗi trên nhánh riêng. Kết luận, phạm vi chứng minh và kết quả thực thi nằm trong [hồ sơ release](docs/release_closure.md). Các audit cũ là bằng chứng lịch sử, không mô tả mặc định hành vi hiện tại.

## 1. Cài đặt từ source hoặc ZIP

Yêu cầu Python **3.11 trở lên** (`math.cbrt` được dùng trong congestion controller), pip và trình duyệt. Môi trường kiểm chứng của đợt release là Windows/Python 3.14.4; xem hồ sơ release để biết những môi trường chưa kiểm chứng. Chạy các lệnh tại thư mục chứa `server.py`.

Windows PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Linux/macOS:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Runtime chỉ cần `cryptography`; test dependencies được khai báo riêng. Các lệnh Windows bên dưới dùng interpreter trực tiếp nên không yêu cầu thay PowerShell execution policy. Trên Linux/macOS, thay `.\.venv\Scripts\python.exe` bằng `.venv/bin/python`.

## 2. Khởi động server và hai client

Mở ba terminal tại thư mục dự án. TCP **9000**, UDP **9001**, HTTP **8000/8001** phải chưa được ứng dụng khác sử dụng.

Terminal 1:

```powershell
.\.venv\Scripts\python.exe server.py
```

Terminal 2:

```powershell
.\.venv\Scripts\python.exe client.py --username alice --host 127.0.0.1 --ui-port 8000
```

Terminal 3:

```powershell
.\.venv\Scripts\python.exe client.py --username bob --host 127.0.0.1 --ui-port 8001
```

Mở [Alice](http://127.0.0.1:8000) và [Bob](http://127.0.0.1:8001) nếu trình duyệt chưa tự mở. Đăng nhập diễn ra khi khởi động Python; trang web không có một hệ thống xác thực riêng. Username phải duy nhất trong các phiên online, dài tối đa 64 ký tự/120 byte UTF-8, gồm chữ, số, dấu cách, `_` hoặc `-`.

Server lắng nghe trên `0.0.0.0`. Để dùng LAN, thay `127.0.0.1` trong `--host` bằng địa chỉ IPv4 của server. Cho phép TCP 9000, UDP 9001 ở server và UDP port động mà mỗi client in ra trong mạng lab. UI luôn bind `127.0.0.1`: mở trình duyệt trên chính máy chạy client. Cơ chế này không cung cấp NAT traversal; dùng LAN/VPN có đường UDP trực tiếp giữa các peer. Kiểm chứng hai máy vật lý được ghi riêng với kiểm chứng localhost.

## 3. Kịch bản demo có thể đối chiếu

1. Kiểm tra username và danh sách hai người dùng trên cả hai trang. Phân biệt nhãn HTTP/API cục bộ với nhãn phiên server.
2. Alice chọn **Mọi người**, gửi tin nhắn. Bob chọn Alice, gửi riêng. Khi có client thứ ba, client đó phải nhận broadcast và không nhận private chat giữa Alice/Bob.
3. Chọn Bob trong phần gửi file của Alice. Gửi một file tên mới; quan sát tên, chiều truyền, phần trăm và trạng thái ở hai đầu. `ok: true` nghĩa là bridge đã nhận công việc; `submitted` chưa chứng minh người nhận đã nhận. Chỉ sender `done` và receiver `completed` xác nhận kết quả truyền file đã được receiver kiểm chứng.
4. File nhận nằm trong `downloads_bob` tương đối với thư mục chạy Bob. Đối chiếu nội dung, ví dụ:

   ```powershell
   Get-FileHash -Algorithm SHA256 .\demo.bin
   Get-FileHash -Algorithm SHA256 .\downloads_bob\demo.bin
   ```

5. Đóng Alice bằng `Ctrl+C`, xác nhận Bob cập nhật danh sách. Tắt server: UI local có thể vẫn truy cập được nhưng phiên server phải báo mất kết nối và vô hiệu hóa gửi. Khởi động lại server, rồi khởi động lại các client để phục hồi phiên. **Không có automatic reconnect hoặc resume file qua lần khởi động.**

File đích đã tồn tại sẽ bị từ chối, không ghi đè. Đổi tên file gửi khi muốn chạy lại demo; lỗi trùng tên vẫn là một tình huống cần demo được, không phải kết quả thành công.

CLI vẫn có thể chạy:

```powershell
.\.venv\Scripts\python.exe client.py --username alice --host 127.0.0.1 --cli
```

CLI hỗ trợ `/users`, `/status`, `/send bob "C:/path/demo.bin"`, `/quit`; văn bản thường là broadcast. Private chat dùng UI hoặc public API `send_message(target, text)`.

## 4. Demo tự tạo và dọn môi trường

```powershell
.\.venv\Scripts\python.exe submission/assignment1/demo.py
.\.venv\Scripts\python.exe submission/assignment1/demo.py --smoke --output demo-result.json
```

Script chạy server thật và hai `client.main()` thật, tự chọn HTTP port. `--smoke` kiểm tra chat, truyền file, trạng thái hai đầu và SHA-256. Dữ liệu nằm trong temporary directory; sao chép file muốn giữ trước khi đóng demo. Script chỉ dừng process do chính nó tạo, từ chối chạy nếu 9000/9001 đã bận. Không chạy đồng thời demo thủ công, demo script và network tests dùng cùng cổng.

## 5. Chạy kiểm thử

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-test.txt
$env:ROLE4_BROWSER_CHANNEL = "msedge"
.\.venv\Scripts\python.exe -X utf8 scripts/verify_release.py --label local_run_1
.\.venv\Scripts\python.exe -X utf8 scripts/verify_release.py --label local_run_2
```

Các lệnh trên dùng Edge đã cài trên Windows. Nếu dùng Chromium do Playwright quản lý:

```powershell
.\.venv\Scripts\python.exe -m playwright install chromium
$env:ROLE4_BROWSER_CHANNEL = "chromium"
```

Trên Linux/macOS đặt `export ROLE4_BROWSER_CHANNEL=chromium`. Trường hợp thiếu browser phải được báo là chưa kiểm chứng/lỗi môi trường, không thay bằng kết quả pass.

Runner ghi log, JUnit XML và JSON vào `audits/release_2026_11_07/`; bất kỳ failure, error hoặc skip đều không đạt gate release. Có thể chạy trực tiếp:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests test_file_client.py test_file_transfer.py -v -p no:cacheprovider
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p "test_role4_*.py" -v
.\.venv\Scripts\python.exe -X utf8 scripts/verify_legacy_release.py
.\.venv\Scripts\python.exe -X utf8 scripts/verify_protocol_release.py
.\.venv\Scripts\python.exe -X utf8 scripts/verify_large_release.py --mib 100 --output audits/release_2026_11_07/maximum_file.json
```

Chạy tuần tự. Protocol probes dùng 19000/19001; suite/demo/large-file dùng 9000/9001. Bài thử 100 MiB cần thêm bộ nhớ, dung lượng cho file nguồn/đích và temporary data. Cấu hình mặc định bài concurrency là 20 client; giảm `ROLE4_CLIENTS` khi chẩn đoán sẽ không còn chứng minh yêu cầu 20 client.

## 6. Giới hạn và ý nghĩa trạng thái

| Phạm vi | Hợp đồng hiện tại |
|---|---|
| File transport | Tối đa 100 MiB/file, chunk thường 700 byte, 8 lượt gửi và 8 lượt nhận đang hoạt động mỗi handler |
| Upload qua UI | Request JSON tối đa 110 MiB; Base64 khiến dữ liệu gốc tối đa xấp xỉ 82,5 MiB, trừ JSON/tên file. UI kiểm tra kích thước request thực tế |
| Bộ nhớ | File được giữ theo chunk tới lúc xác minh/lưu; không cam kết RAM hằng số khi tăng kích thước file. Nhiều transfer đồng thời cần RAM cho mỗi file cộng overhead |
| Trạng thái file | ACK xác nhận chunk, không xác nhận toàn file; sender `done` cần kết quả receiver với đúng size và SHA-256 |
| Khôi phục kết quả | `FILE_QUERY` và terminal cache phục hồi ACK/kết quả mất; cache giới hạn 120 giây/256 kết quả, không phải biên nhận lưu vĩnh viễn |
| Discovery | Snapshot có phiên bản; heartbeat và nguồn UDP được kiểm tra. Đây không phải xác thực mật mã cho toàn bộ control plane |
| Lưu file | Hash đúng rồi mới publish không ghi đè bằng hard link trong cùng filesystem; filesystem không hỗ trợ hard link sẽ báo lỗi |
| Stream | Async byte reader độc lập mỗi transfer; byte đọc trước EOF còn provisional. EOF chỉ sau khi integrity và commit thành công |
| Congestion | CUBIC window trong ứng dụng, có phản ứng mất gói và giới hạn cửa sổ; không tuyên bố TCP/QUIC hoàn chỉnh, BBR hay fairness trên Internet |

HTTP API chỉ hỗ trợ file tới một recipient. Public Python API có fanout file nhưng bị giới hạn active workers; không cam kết broadcast file nguyên tử tới mọi client hoặc fanout 20 file đồng thời.

`--password` được giữ tương thích CLI nhưng server hiện dùng **đăng ký username duy nhất**, không có password database. Không truyền password thật. Chat text và file payload của client chuẩn được mã hóa Fernet với khóa chung trong `config.py`; header, discovery và một số metadata điều khiển không được mã hóa. Server còn chấp nhận chat legacy không có cờ `enc`. Người có source/key có thể giải mã payload. Đây là security layer cho bài thực hành, không phải hệ thống production có TLS, phân quyền, key exchange hay end-to-end identity authentication. HTTP UI chỉ dành cho máy local đáng tin cậy; bridge kiểm tra loopback Host, same Origin và JSON POST để hạn chế request từ trang web khác, không xác thực người dùng hệ điều hành.

Xem [protocol](docs/protocol.md) để biết wire format và [release closure](docs/release_closure.md) để đối chiếu từng yêu cầu, bằng chứng, giới hạn và những điểm cần giảng viên xác nhận.
