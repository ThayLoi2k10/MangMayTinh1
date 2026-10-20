# Role 4 — Client UI & Testing

## Phạm vi và baseline

- Repository: `https://github.com/ThayLoi2k10/MangMayTinh1`.
- Baseline: `ab63e31926b1809734edeecec2b213672660575d` (`origin/main`).
- Audit ngày 2026-10-20: clone mới vào workspace chưa có Git; `git fetch --all --prune`; remote chỉ có `main`; GitHub REST `pulls?state=all` trả danh sách rỗng.
- Nhánh: `feat/role4-client-ui-testing`.
- Đóng góp có sẵn: `9b42c95` handshake/auth/registry; `bbdc5d5` routing; `84af35b`, `10f7e59`, `ab63e31` transfer/security/client bridge.
- Không cherry-pick, không sửa history, không merge/push vào main.

Các file Role 4:

| File | Trách nhiệm |
| --- | --- |
| `static/index.html` | HTML/CSS/JavaScript tự chứa, được `UIHandler` có sẵn phục vụ tại `/` |
| `tests/role4_harness.py` | Khởi chạy/dọn server, client, HTTP bridge và trình duyệt trong test; không dùng trong runtime sản phẩm |
| `tests/test_role4_integration.py` | HTTP/network thật, chat, file/hash, concurrency, crash/restart và chạy test cũ |
| `tests/test_role4_network.py` | Fault injection chỉ trong test, dùng callback sẵn có và UDP thật |
| `tests/test_role4_ui.py` | Browser tests cho schema/lỗi/security/layout và tích hợp browser với server thật |
| `docs/role4_ui_testing.md` | Hướng dẫn, hợp đồng tích hợp, bằng chứng, giới hạn và đề xuất cho đồng đội |

Giữ nguyên `client.py`, `server.py`, `protocol.py`, `config.py`, `file_client.py`, `file_transfer.py`, `client_handshake.py`, mọi test cũ, `README.md`, `requirements.txt` và `docs/protocol.md`.

## Runtime và hợp đồng đã xác minh từ code

```text
Browser (static/index.html)
  → UIHandler / ThreadingHTTPServer (client.py, loopback)
  → CollaborationClient
  → TCP chat/control + FileTransferHandler/UDP + protocol.py
  → CollaborationServer / peer nhận file
```

Không thêm framework, route, transport, ACK, retry hay mã hóa. Không có dependency frontend, CDN hoặc dịch vụ bên ngoài. Login vẫn do `CollaborationClient.__init__` thực hiện trước khi HTTP server mở. UI không tạo màn hình xác thực giả.

| API | Hợp đồng thực tế |
| --- | --- |
| `GET /` | Chỉ phục vụ `static/index.html`; vì vậy CSS/JS nhúng trong HTML |
| `GET /api/state` | `{username, users, messages, transfers}`; không có trạng thái server, timestamp heartbeat hay lỗi gửi chat |
| `POST /api/send` | JSON `{to: "*" hoặc username, text}`; khởi chạy thread rồi trả `{ok:true}` |
| `POST /api/file` | JSON `{to: username, name: filename, data: base64}`; ghi `.upload_temp`, khởi chạy thread rồi trả `{ok:true}`; từ chối `to:"*"` |

`users` chứa `{username, ip, udp_port}`. Message chứa `{from,to,text,time}`; snapshot tối đa 100 message, không có ID ổn định. UI thay thế snapshot khi nội dung thay đổi, không nối lại mỗi lần poll và không loại nhầm hai tin giống nhau.

Transfer chứa `{filename,direction,peer,status,progress,file_id,total_chunks}`. `progress` là **0–100**, không phải 0–1. Handler trả tối đa 40 record. UI chỉ hiển thị trạng thái backend:

- `sending` / `receiving`: đang truyền.
- `done`: **bên gửi báo xong**, chưa có bằng chứng SHA-256 phía nhận trong API người gửi.
- `completed`: bên nhận đã ghép/kiểm tra/lưu file.
- `failed: …` / `timeout`: hiển thị nguyên văn an toàn khi API có record đó.
- 100% với `sending` vẫn là đang gửi; POST `ok` không tạo transfer giả.

File layer giới hạn 100 MiB; `UIHandler.read_json` giới hạn **110 MiB toàn request**. UI tính trước:

```text
body_bytes = UTF8(JSON.stringify({to, name, data:""})).length
             + 4 * ceil(file.size / 3)
body_bytes <= 110 * 1024 * 1024
file.size <= 100 * 1024 * 1024
```

Vì Base64, ngưỡng file thực tế qua HTTP gần **82,5 MiB**, trừ metadata. Tên file được kiểm tra theo `safe_filename`: tối đa 255 code point, không slash/backslash/ký tự điều khiển hoặc `<>:"|?*`. File rỗng, khoảng trắng và Unicode hợp lệ được hỗ trợ.

UI giới hạn tin nhắn 5.000 UTF-16 unit (giới hạn UI bảo thủ cho payload JSON/protocol 65.535 byte với tên người dùng thông thường). Không thay đổi giới hạn protocol.

## Sử dụng và demo hai client

Từ thư mục repository, PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Mở ba terminal tại cùng thư mục:

```powershell
# Terminal 1
.\.venv\Scripts\python.exe -X utf8 server.py

# Terminal 2
.\.venv\Scripts\python.exe -X utf8 client.py --username alice --host 127.0.0.1 --ui-port 8000

# Terminal 3
.\.venv\Scripts\python.exe -X utf8 client.py --username bob --host 127.0.0.1 --ui-port 8001
```

Mở `http://127.0.0.1:8000` và `http://127.0.0.1:8001` nếu browser không tự mở.

`-X utf8` cần thiết khi output Windows bị redirect/capture bằng code page không hỗ trợ tiếng Việt. Lượt kiểm thử đầu đã gặp `UnicodeEncodeError` trong `print` của receive loop, làm dừng thread trước khi xử lý tiếp. Harness chỉ cấu hình UTF-8 cho output test; không sửa print của backend.

1. Kiểm tra danh tính và danh sách user/UDP address. Nhãn HTTP hoạt động **không** xác nhận server đang sống.
2. Alice chọn Mọi người, gửi bằng Enter; Bob nhận. Bob chọn Alice, gửi tin riêng bằng nút.
3. Chọn Bob trong form file của Alice, chọn file có tên chưa tồn tại ở đích, gửi. Theo dõi % và trạng thái ở cả hai tab.
4. File nhận nằm tại `downloads_bob/<filename>`, tương đối với cwd của tiến trình Bob.
5. So sánh SHA-256:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath 'C:\duong-dan\sample.bin'
Get-FileHash -Algorithm SHA256 -LiteralPath '.\downloads_bob\sample.bin'
```

6. Ctrl+C terminal server: HTTP của client còn hoạt động và UI vẫn ghi server chưa xác minh; không suy diễn từ danh sách user cũ. Khởi động lại server rồi khởi động lại các client để phục hồi.
7. Ctrl+C một client: tab tương ứng sẽ báo lỗi HTTP và giữ dữ liệu cũ có chú thích.

Trên LAN: chạy server trên một máy; thay `--host` bằng IP LAN server. Mỗi máy client mở URL loopback của chính nó. Theo cấu hình có sẵn cần TCP 9000, UDP 9001 đến server và UDP peer-to-peer đến cổng trong danh sách user. HTTP vẫn bind `127.0.0.1`; không đổi server/client để public HTTP.

CLI cũ giữ nguyên: thêm `--cli`. Tham số `--password` vẫn do client cũ xử lý; Role 4 không thêm/chỉnh logic xác thực.

## Chạy test tái lập

Đóng demo trước: tests cần TCP 9000 và UDP 9001 trống. Harness **từ chối** khi port bận, không kill tiến trình lạ. Không chạy song song các suite: server dùng port cố định, client dùng cwd để lưu file.

Dependency kiểm thử browser là tùy chọn, chỉ cài vào venv; không sửa dependency chung:

```powershell
.\.venv\Scripts\python.exe -m pip install "playwright==1.55.0"
# Windows có Edge: harness dùng Edge headless đã cài.
# Nếu dùng Chromium của Playwright:
.\.venv\Scripts\python.exe -m playwright install chromium
$env:ROLE4_BROWSER_CHANNEL = "chromium"
```

Trên Linux/macOS dùng `.venv/bin/python`; mặc định harness dùng Chromium của Playwright, cần cài browser qua lệnh trên. Có thể chọn `ROLE4_BROWSER_CHANNEL=chrome` hoặc `msedge` nếu đã cài.

```powershell
# Tất cả, chạy tuần tự:
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_role4_*.py' -v

# Không cần Playwright:
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_role4_integration.py' -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_role4_network.py' -v

# Browser và tích hợp browser thật:
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_role4_ui.py' -v
```

Mặc định 20 client và file lớn 2 MiB. Mỗi client là instance `CollaborationClient` độc lập, socket/thread riêng trong cùng tiến trình test; thêm một client subprocess bị kill để kiểm tra crash thật. Đây không phải benchmark 20 máy hoặc 20 browser.

```powershell
$env:ROLE4_CLIENTS = "20"
$env:ROLE4_LARGE_BYTES = "10485760"  # 10 MiB, tùy chọn; có thể mất nhiều thời gian
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_role4_integration.py' -v
Remove-Item Env:ROLE4_CLIENTS, Env:ROLE4_LARGE_BYTES
```

File test và download nằm trong thư mục tạm, dọn sau mỗi test. Screenshot của browser thật được ghi dưới `test-results/role4-desktop.png` và `role4-mobile.png` (đã được `.gitignore` có sẵn bỏ qua); có thể đổi bằng `ROLE4_SCREENSHOTS`. Test không ghi dữ liệu demo vào repository.

### Ma trận coverage

| Ca yêu cầu | Test / cách kiểm tra |
| --- | --- |
| 1–4: hai client, users thật, broadcast/private | `test_http_chat_files_and_sha256`; `test_two_browser_clients_chat_file_progress_hash_and_disconnect`; `test_existing_client_entrypoint_serves_ui_and_routes_chat` chạy `client.main` thật, chỉ chặn tự mở browser hệ thống |
| 5–7: file, SHA-256, progress thật trong browser | Hai test trên; file browser 1 MiB, API 2 MiB + 4 file nhỏ; assert có % trung gian |
| 8–11: 20 client, crash isolation, login/logout lặp, stale/duplicate | `test_twenty_clients_crash_isolation_and_repeated_login`; browser selection/snapshot tests |
| 12–14: kill client, tắt server, timeout/recovery | Crash subprocess; `test_server_shutdown_state_limitation_and_manual_recovery`; `test_actual_heartbeat_timeout_removes_user_and_other_client_survives` làm mất heartbeat thật, chờ watchdog mặc định và login lại; chạy nguyên `test_heartbeat.py` riêng |
| 15: loss/delay/duplicate/reorder | `test_loss_delay_duplicate_reorder_recover`: mất copy đầu chunk 2, delay chunk 3 80 ms, lặp chunk 4, đảo chunk 5/6, UDP thật |
| 16–17: interruption, lỗi network, UI responsive | `test_interrupted_transfer_sender_fails_and_chat_survives`; browser timeout/API-down tests |
| 18–22: rỗng/text/binary/large/Unicode | API fixtures và browser-originated file; tất cả kiểm SHA-256 |
| 23: unavailable recipient/failed transfer | `test_unavailable_recipient_rejected_by_existing_client`; sender retry exhaustion; UI mất người nhận |
| 24: nhiều transfer | API submits 5 file trước khi đợi hoàn thành |
| 25–28: schema/malformed/XSS/API failure-timeout | `Role4BrowserTests`, fixture rõ ràng; không gọi fixture là kiểm thử mạng thật |
| 29–30: validation/status/progress | Browser tests file 83 MiB sparse bị chặn; tên sai, file rỗng, request lỗi; `31% → failed → done → completed` |

`test_existing_team_scripts_unchanged` chạy **nguyên file** `test_proto.py`, `test_handshake.py`, `test_auth.py` (nhánh username trùng), `test_logout.py` bằng subprocess, timeout 45 s, kiểm exit code và marker SUCCESS/REJECTED. `test_existing_heartbeat_script` chạy nguyên `test_heartbeat.py` riêng; trên Windows đánh dấu `expectedFailure` vì script không bắt TCP reset từ watchdog (xem dưới). Đăng nhập thành công được kiểm chứng qua các client thật của suite. Test cũ có nhiều kiểm tra bằng print thay vì assertion; kết quả này không được coi là bao phủ toàn bộ protocol.

## Giới hạn tích hợp và đề xuất cho Roles 1–3

Không áp dụng bất kỳ thay đổi nào dưới đây vào file được bảo vệ.

1. **Không có trạng thái server trong HTTP state (Role 1/client owner).** `_tcp_receive_loop` set `stop_event` khi TCP đóng; `state()` chỉ trả bốn trường và còn giữ user cũ. HTTP vẫn sống sau khi server chết. UI luôn ghi “Server: chưa xác minh”. Đề xuất tối thiểu ở `CollaborationClient.state()`: thêm `connection: {closed: self.stop_event.is_set(), server_host: self.server_host}`. `closed:false` chỉ có nghĩa chưa phát hiện đóng, không chứng minh liveness. Muốn nhãn “đã xác minh” cần timestamp/signal liveness có định nghĩa từ Role 1.
2. **Lỗi worker không đến UI (client owner/Role 2–3).** `UIHandler.do_POST` trả ok ngay sau `Thread.start`; lỗi `send_message`, `send_file` trước khi tạo transfer record chỉ đi vào terminal. Lỗi unicast từ server cũng chỉ được print. Đề xuất wrapper worker tại hai POST: ghi `{request_id, operation, status, error}` vào một collection giới hạn kích thước, expose qua `state()`, trả `request_id` trong HTTP response. Không gọi HTTP accepted là delivery. Không thay đổi routing/retry.
3. **Mất ACK cuối (Role 3).** Receiver đã hoàn tất xóa `incoming[file_id]`. `FileReceiver.accept_chunk` trả `ignored:true` với chunk retransmit; `FileTransferHandler._on_chunk` return trước `_reply_ack`. Receiver đã có file nhưng sender hết retry và báo failed. Test `test_upstream_final_ack_loss_should_recover` đặt kỳ vọng mong muốn `done`, đánh dấu `expectedFailure`. Đề xuất Role 3 giữ completion tombstone có TTL và thông tin peer/file/chunk để ACK an toàn retransmission của transfer đã xác minh; không ACK mù mọi packet unknown.
4. **Receive timeout/failure không tới `get_progress()` của handler (Role 3).** `receiver.progress` đổi thành timeout/hash-error/destination-exists nhưng `file_handler.transfers` giữ `receiving`. Test `test_upstream_receiver_timeout_should_reach_state` gọi cleanup có sẵn với `max_age=0` để tái lập nhanh, xác minh receiver là timeout rồi kỳ vọng state cũng timeout (`expectedFailure`). Đề xuất đồng bộ record nhận từ `receiver.get_progress(file_id)` trong `FileTransferHandler.get_progress()` dưới cơ chế khóa phù hợp, hoặc cập nhật tại cleanup/error path.
5. **Giới hạn upload và staging (client owner/Role 3).** 100 MiB file không vừa JSON 110 MiB sau Base64. UI chặn theo giới hạn thực tế. `.upload_temp/<name>` được chia sẻ giữa client có cùng cwd, không được xóa và có thể bị ghi đè khi gửi đồng thời cùng tên. Test dùng tên riêng biệt. Đề xuất staging path riêng cho từng request, giữ basename gốc trong metadata, cleanup sau khi worker đọc xong; thống nhất/document lại giới hạn JSON với file layer.
6. **Không tự reconnect.** Backend dừng receive/heartbeat khi TCP chết; khởi động lại client là phương thức recovery hiện có. UI chỉ tự thử lại HTTP GET, không giả vờ phục hồi phiên mạng.
7. **Test heartbeat cũ không tương thích TCP reset Windows (Role 1).** `test_heartbeat.py:76` chỉ xử lý `recv()` trả bytes rỗng; trên môi trường này watchdog gây `ConnectionResetError [WinError 10054]`, script exit 1. Đã giữ nguyên test và đánh dấu riêng `expectedFailure` chỉ trên Windows. Đề xuất chủ sở hữu test bắt `ConnectionResetError` như một kiểu đóng kết nối và xác minh peer đã rời registry. Test Role 4 bổ sung kiểm tra trực tiếp việc user bị gỡ, `stop_event` set, client còn lại sống và đăng nhập lại được.

Hai `expectedFailure` của transfer là **lỗi đã biết ở backend**; một `expectedFailure` nữa trên Windows là lỗi tương thích của test heartbeat cũ. Chúng không phải kiểm thử đã pass và không được che bằng sửa code đồng đội. Nếu đồng đội sửa xong, unittest sẽ báo `unexpected success`, yêu cầu bỏ marker và kiểm tra lại. Không tuyên bố toàn bộ yêu cầu xử lý lỗi/độ tin cậy của assignment đã hoàn tất khi các hợp đồng này chưa được sửa.

## Những kiểm tra cần thêm ngoài localhost

Chưa coi test callback là mô phỏng packet loss toàn mạng. Nó chỉ gây lỗi tại đường gửi file UDP và không mô phỏng mất heartbeat/user-list, congestion, MTU, NAT hay LAN firewall.

Reproduction trên hai Linux VM/network namespace riêng, chỉ áp dụng cho interface lab:

```bash
# Trong VM Alice, thay eth0 bằng interface lab thực tế.
sudo tc qdisc add dev eth0 root netem delay 80ms 20ms loss 5% duplicate 2% reorder 25% 50%
# Chạy demo với --host <IP_VM_SERVER>, gửi file và kiểm hash ở Bob.
sudo tc -s qdisc show dev eth0
# Khôi phục chính interface lab sau kiểm thử.
sudo tc qdisc del dev eth0 root
```

Không chạy lệnh netem trên interface đang dùng để quản trị máy. Dùng tên file mới cho mỗi lần gửi; ghi trạng thái cả hai phía, hash, thời gian, packet capture nếu có. Tỷ lệ loss có thể lộ lỗi ACK cuối nêu trên; không đánh dấu pass nếu sender failed dù receiver có file.

Chưa kiểm toàn bộ file gần ngưỡng 82,5 MiB / 100 MiB, 20 tiến trình UI hoặc 20 máy thật, LAN/NAT, trình duyệt Firefox/Safari, screen reader thực. Để test 80 MiB qua API:

```powershell
$env:ROLE4_LARGE_BYTES = "83886080"
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_role4_integration.py' -v
Remove-Item Env:ROLE4_LARGE_BYTES
```

Test có timeout file 180 s; file lớn có thể vượt timeout do chi phí backend, không tự sửa retry/window/chunk settings. Dùng demo thủ công và ghi thời gian nếu cần khảo sát dài hơn. Giới hạn hiển thị phía browser không sửa việc backend còn tích lũy lịch sử trong bộ nhớ.

## Kết quả chạy và kiểm tra phạm vi

Ngày 2026-10-20, Windows, Python **3.14.4**, cryptography **50.0.2**, Playwright **1.55.0**, Edge headless **155.0.4283.62**:

| Lệnh / lượt chạy | Kết quả thực tế |
| --- | --- |
| `python -m unittest discover -s tests -p 'test_role4_*.py' -v` — lượt đầu | 17 tests: 4 failures, 1 error, 2 expected failures. Nguyên nhân: output CP1252 làm hỏng receive loop; fixture timeout abort một route đã được xử lý; test heartbeat cũ không bắt Windows reset. Không sửa code đội bạn. |
| `python -m unittest discover -s tests -p 'test_role4_ui.py' -k Role4BrowserTests -v` — trong lúc chẩn đoán | 7 tests: 6 pass, 1 lỗi cleanup fixture timeout. Sau đó thay fixture bằng HTTP chờ Event thật, tránh route bị treo trong Playwright. |
| `python -m unittest discover -s tests -p 'test_role4_ui.py' -k test_request_timeouts -v` — sau sửa fixture | 1 pass, 22,081 s; không còn lỗi cleanup bất đồng bộ. |
| `python -m unittest discover -s tests -p 'test_role4_*.py' -v` — sau sửa harness | **19 tests: 16 pass, 3 expected failures**, 135,838 s, exit 0. Log lưu cục bộ `test-results/role4-tests.log`. |
| `python -m unittest discover -s tests -p 'test_role4_integration.py' -k test_existing_client_entrypoint -v` — ca bổ sung cuối | **1 pass**, 1,976 s, exit 0. Xác minh `client.main()` phục vụ UI và route tin nhắn thật. |

Các lệnh trên dùng interpreter `.\.venv\Scripts\python.exe`. Tổng cộng phiên bản cuối có **20 tests đã được thực thi: 17 pass và 3 expected failures**, theo lượt suite 19 + ca entrypoint 1; không khẳng định đã chạy lại cả 20 trong một lệnh sau khi thêm ca cuối.

Bằng chứng quan sát:

- 20 client đồng thời, mỗi client nhận đúng 20 bản ghi của 20 broadcast (gồm bản ghi gửi local); không trùng nội dung; client bị kill không làm các client còn lại ngừng hoạt động; 3 vòng login/logout cùng tên thành công.
- 5 transfer cùng lúc: 0 byte, 17 byte text, 4.096 byte binary, 19 byte Unicode, 2.097.152 byte file lớn; **5 SHA-256 khớp**. Có progress giữa 0 và 100 qua HTTP.
- Hai browser trao đổi broadcast/private thật, gửi file Unicode 1.048.576 byte, thấy progress trung gian, sender `done`, receiver `completed`, **SHA-256 khớp**.
- Loss/delay/duplicate/reordering có kiểm soát phục hồi file 32.768 byte nguyên vẹn. Mất gói vĩnh viễn dẫn đến sender `failed`, chat vẫn hoạt động.
- Watchdog gỡ user không gửi heartbeat; client còn lại sống; đăng nhập lại và gửi tin thành công. Tắt/restart server và khởi động client mới cũng phục hồi.
- XSS payload không tạo element thực thi, không set `window.pwned`; snapshot không nhân đôi khi poll; lịch sử bị giới hạn; malformed state, request timeout/error, mất người nhận, file quá giới hạn và draft preservation đã được kiểm.
- Đã xem screenshot desktop 1280 px và mobile 390 px. Không phát hiện tràn ngang/cắt nội dung trong các ảnh. Test bàn phím kiểm tra focus và accessible label cơ bản.

Ba thất bại mong đợi, vẫn cần đồng đội giải quyết:

1. Mất ACK cuối: receiver hoàn tất nhưng sender thực tế `failed: Timeout chunks [0]`.
2. Cleanup receive: `receiver.progress.status = timeout` nhưng HTTP transfer vẫn `receiving`.
3. Script heartbeat cũ exit 1 với `ConnectionResetError [WinError 10054]`.

Cài đặt dependency bằng pip thông thường đã bị treo khi tải wheel trong môi trường này; đã tải wheel từ PyPI, xác minh SHA-256 theo metadata PyPI và cài offline vào `.venv`. Không thay `requirements.txt`.

`git diff --check` và kiểm tra diff các file bảo vệ đều sạch. Bàn giao nhánh local sẵn sàng review; không tạo/push PR và không merge.

Kiểm tra ownership trước khi commit:

```powershell
git diff --check
git diff --name-status ab63e31926b1809734edeecec2b213672660575d
git diff ab63e31926b1809734edeecec2b213672660575d -- client.py server.py protocol.py config.py file_client.py file_transfer.py client_handshake.py README.md requirements.txt docs/protocol.md test_auth.py test_handshake.py test_heartbeat.py test_logout.py test_proto.py
```

Lệnh cuối phải không có diff. Chỉ commit sáu file Role 4 liệt kê đầu tài liệu. Không commit venv, cache, download hay screenshot generated.
